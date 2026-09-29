"""On-demand, paired two-way NHL moneylines. Navigation is cache-only."""
import asyncio
import json
import math
import os
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .first_period_odds import event_game, NAMES, SOURCE
from .odds_client import odds_client
from .odds_config import market_params, odds_scope
from .stats import normalized_name, number


def moneyline_prices(event, game):
    best = {}
    for book in event.get('bookmakers', []):
        key = book.get('key')
        title = book.get('title') or key
        if not key or not title:
            continue
        markets = [m for m in book.get('markets', []) if m.get('key') == 'h2h']
        if len(markets) != 1 or len(markets[0].get('outcomes', [])) != 2:
            continue
        market = markets[0]
        sides = {}
        for outcome in market['outcomes']:
            team = NAMES.get(normalized_name(outcome.get('name', '')))
            price = number(outcome.get('price'))
            if price is None or not math.isfinite(price) or abs(price) < 100 or not float(price).is_integer():
                continue
            for side in ['away', 'home']:
                if team == game[side + 'Team']['abbrev']:
                    sides[side] = int(price)
        if set(sides) == {'away', 'home'}:
            updated = market.get('last_update') or book.get('last_update')
            for side, price in sides.items():
                current = best.get(side)
                if current is None or price > current['price']:
                    best[side] = {'price': price, 'bookmaker': key, 'name': title, 'updated_at': updated}
    if set(best) != {'away', 'home'}:
        return []
    return [{'bookmaker': 'best', 'name': 'Best available',
             'away': best['away']['price'], 'home': best['home']['price'],
             'away_bookmaker': best['away']['bookmaker'], 'away_name': best['away']['name'],
             'away_updated_at': best['away']['updated_at'],
             'home_bookmaker': best['home']['bookmaker'], 'home_name': best['home']['name'],
             'home_updated_at': best['home']['updated_at'],
             'updated_at': max(t for t in [best['away']['updated_at'], best['home']['updated_at']] if t) if any([best['away']['updated_at'], best['home']['updated_at']]) else None}]


class Moneylines:
    def __init__(self, providers):
        self.p = providers
        self.client = odds_client(providers.store)
        self.lock = asyncio.Lock()
        self.p.store.db.execute('''CREATE TABLE IF NOT EXISTS moneyline_odds (
            date TEXT PRIMARY KEY, body TEXT, fetched REAL, attempted REAL, error TEXT)''')
        self.p.store.db.commit()

    def cached(self, date):
        row = self.p.store.db.execute('SELECT body,fetched,attempted,error FROM moneyline_odds WHERE date=?', (date,)).fetchone()
        configured = bool(os.environ.get('THE_ODDS_API_KEY', '').strip())
        data = json.loads(row[0]) if row and row[0] else {'prices': {}}
        fresh = bool(row and row[0] and time.time() - row[1] < 1800)
        return {**data, 'date': date, 'configured': configured, 'source': SOURCE,
                'retrieved_at': datetime.fromtimestamp(row[1], timezone.utc).isoformat() if row and row[1] else None,
                'status': ('stale' if row[3] or not fresh else 'available') if row and row[0]
                          else 'not_configured' if not configured else 'unavailable' if row and row[3] else 'not_loaded',
                'error': row[3] if row else None}

    async def refresh(self, date):
        async with self.lock:
            cached = self.cached(date)
            if not cached['configured'] or cached['status'] == 'available':
                return cached
            row = self.p.store.db.execute('SELECT attempted FROM moneyline_odds WHERE date=?', (date,)).fetchone()
            now = time.time()
            if row and now - row[0] < 600:
                return cached
            try:
                schedule = await self.p.nhl(f'score/{date}', 600)
                if schedule.data is None or schedule.stale:
                    raise ValueError('Schedule unavailable')
                games = [g for g in schedule.data.get('games', [])
                         if g.get('gameState') in ['FUT', 'PRE'] and g.get('gameScheduleState') not in ['PPD', 'CNCL']
                         and datetime.fromisoformat(g['startTimeUTC'].replace('Z', '+00:00')).timestamp() > now]
                prices, usage = {}, None
                if games:
                    start = datetime.fromisoformat(date).replace(tzinfo=ZoneInfo('America/New_York'))
                    iso = lambda d: d.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                    events = await self.client.request('/odds', market_params({
                        'markets': 'h2h', 'oddsFormat': 'american', 'commenceTimeFrom': iso(start),
                        'commenceTimeTo': iso(start + timedelta(days=1) - timedelta(seconds=1))}))
                    usage = dict(self.client.usage)
                    if not isinstance(events, list):
                        raise ValueError('Invalid odds response')
                    matched = {}
                    for event in events:
                        game = event_game(event, games)
                        if game and datetime.fromisoformat(event['commence_time'].replace('Z', '+00:00')).timestamp() > time.time():
                            matched.setdefault(game['id'], []).append((event, game))
                    for gid, candidates in matched.items():
                        if len(candidates) == 1:
                            values = moneyline_prices(*candidates[0])
                            if values:
                                prices[str(gid)] = values
                body = {'prices': prices, 'usage': usage, 'eligible_games': len(games),
                        'odds_scope': odds_scope()}
                self.p.store.db.execute('INSERT OR REPLACE INTO moneyline_odds VALUES(?,?,?,?,NULL)',
                                       (date, json.dumps(body), now, now))
            except (ValueError, KeyError, TypeError):
                error = 'Odds quota exhausted' if time.time() < self.client.exhausted_until else 'Moneylines unavailable; check configuration or provider availability'
                self.p.store.db.execute('''INSERT INTO moneyline_odds VALUES(?,NULL,0,?,?)
                    ON CONFLICT(date) DO UPDATE SET attempted=excluded.attempted,error=excluded.error''', (date, now, error))
            self.p.store.db.commit()
            return self.cached(date)
