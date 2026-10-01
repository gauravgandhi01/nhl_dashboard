"""Opt-in first-period prices. Credential-bearing requests never enter the HTTP cache."""
import asyncio
import json
import time
from datetime import datetime, timezone

import httpx

from .providers import TEAM_NAMES
from .stats import normalized_name, number
from .odds_client import odds_client, odds_configured
from .odds_config import configured_bookmakers, market_params, odds_scope

BASE = 'https://api.the-odds-api.com/v4/sports/icehockey_nhl'
SOURCE = 'https://the-odds-api.com/liveapi/guides/v4/'
# Explicit historical bookmaker naming; no fuzzy joins across identities.
NAMES = {normalized_name(name): abbrev for abbrev, name in TEAM_NAMES.items()}
NAMES.update({normalized_name('Utah Hockey Club'): 'UTA', normalized_name('St. Louis Blues'): 'STL'})


def event_game(event, games):
    try:
        start = datetime.fromisoformat(event['commence_time'].replace('Z', '+00:00'))
        candidates = [g for g in games
                      if NAMES.get(normalized_name(event['away_team'])) == g['awayTeam']['abbrev']
                      and NAMES.get(normalized_name(event['home_team'])) == g['homeTeam']['abbrev']
                      and abs((datetime.fromisoformat(g['startTimeUTC'].replace('Z', '+00:00')) - start).total_seconds()) <= 3600]
        return candidates[0] if len(candidates) == 1 else None
    except (KeyError, ValueError, TypeError):
        return None


def market_price(payload, allowed_books=None):
    allowed = set(allowed_books or [])
    candidates = []
    for book in payload.get('bookmakers', []):
        key = book.get('key')
        if allowed and key not in allowed:
            continue
        title = book.get('title') or key
        for market in book.get('markets', []):
            if market.get('key') != 'totals_p1':
                continue
            pairs = {}
            for outcome in market.get('outcomes', []):
                point, price = number(outcome.get('point')), number(outcome.get('price'))
                name = outcome.get('name', '').lower()
                if point is not None and point >= 0 and price is not None and abs(price) >= 100 and name in ['over', 'under']:
                    pairs.setdefault(point, {})[name] = price
            for point, prices in pairs.items():
                if set(prices) == {'over', 'under'}:
                    candidates.append({'total': point, **prices, 'bookmaker': key, 'name': title,
                                       'updated_at': market.get('last_update') or book.get('last_update')})
    return min(candidates, key=lambda r: (abs(r['total'] - 1.5), r['total'])) if candidates else None


class FirstPeriodOdds:
    def __init__(self, providers):
        self.p = providers
        self.client = odds_client(providers.store)
        self.lock = asyncio.Lock()
        self.exhausted_until = 0
        self.p.store.db.execute('''CREATE TABLE IF NOT EXISTS first_period_odds (
            date TEXT PRIMARY KEY, body TEXT, fetched REAL, attempted REAL, error TEXT)''')
        self.p.store.db.commit()

    def cached(self, date):
        row = self.p.store.db.execute('SELECT body,fetched,attempted,error FROM first_period_odds WHERE date=?', (date,)).fetchone()
        configured = odds_configured()
        data = json.loads(row[0]) if row and row[0] else {'prices': {}}
        fresh = bool(row and row[0] and time.time() - row[1] < 3600)
        return {**data, 'date': date, 'configured': configured, 'source': SOURCE,
                'retrieved_at': datetime.fromtimestamp(row[1], timezone.utc).isoformat() if row and row[1] else None,
                'status': ('stale' if row[3] or not fresh else 'available') if row and row[0]
                          else 'not_configured' if not configured else 'unavailable' if row and row[3] else 'not_loaded',
                'error': row[3] if row else None}

    async def refresh(self, date, force=False):
        async with self.lock:
            cached = self.cached(date)
            if not cached['configured'] or (cached['status'] == 'available' and not force):
                return cached
            row = self.p.store.db.execute('SELECT attempted FROM first_period_odds WHERE date=?', (date,)).fetchone()
            if row and time.time() - row[0] < 600 and not force:
                return cached
            now = time.time()
            try:
                if now < self.exhausted_until:
                    raise ValueError('Odds quota exhausted; retry after the cooldown')
                schedule = await self.p.nhl(f'score/{date}', 600)
                if schedule.data is None or schedule.stale:
                    raise ValueError('Current NHL schedule unavailable; no odds requested')
                games = [g for g in schedule.data.get('games', [])
                         if g.get('gameState') in ['FUT', 'PRE'] and g.get('gameScheduleState') not in ['PPD', 'CNCL']
                         and datetime.fromisoformat(g['startTimeUTC'].replace('Z', '+00:00')).timestamp() > now]
                prices = {}
                if games:
                    async def request(path, params=None):
                        try:
                            return await self.client.request(path, params)
                        finally:
                            self.exhausted_until = self.client.exhausted_until
                    events = await request('/events')
                    if not isinstance(events, list):
                        raise ValueError('Odds event response unavailable')
                    matched = {}
                    for e in events:
                        game = event_game(e, games)
                        if game:
                            matched.setdefault(game['id'], []).append(e)
                    for gid, events_for_game in matched.items():
                        if len(events_for_game) != 1:
                            continue
                        if time.time() < self.exhausted_until:
                            raise ValueError('Odds quota exhausted; retaining cached prices')
                        e = events_for_game[0]
                        if datetime.fromisoformat(e['commence_time'].replace('Z', '+00:00')).timestamp() <= time.time():
                            continue
                        # IDs must be a plain provider identifier, never a path or query.
                        eid = e.get('id', '')
                        if not isinstance(eid, str) or not eid.isalnum():
                            continue
                        body = await request(f'/events/{eid}/odds', market_params(
                            {'markets': 'totals_p1', 'oddsFormat': 'american'}))
                        if not isinstance(body, dict) or body.get('id') != eid or event_game(body, games) is None or event_game(body, games)['id'] != gid:
                            continue
                        price = market_price(body, configured_bookmakers())
                        if price:
                            prices[str(gid)] = price
                self.p.store.db.execute('INSERT OR REPLACE INTO first_period_odds VALUES(?,?,?,?,NULL)',
                                        (date, json.dumps({'prices': prices, 'odds_scope': odds_scope()}), now, now))
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                # Never stringify HTTP exceptions: their URLs contain the API key.
                error = 'Odds quota exhausted' if time.time() < self.exhausted_until else 'Odds unavailable; check configuration or provider availability'
                self.p.store.db.execute('''INSERT INTO first_period_odds VALUES(?,NULL,0,?,?)
                    ON CONFLICT(date) DO UPDATE SET attempted=excluded.attempted,error=excluded.error''', (date, now, error))
            self.p.store.db.commit()
            return self.cached(date)
