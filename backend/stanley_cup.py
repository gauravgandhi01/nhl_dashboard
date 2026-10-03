from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import httpx

from .odds_client import OddsError, odds_api_keys
from .providers import ALIASES, Providers, TEAM_NAMES
from .service import display_name, latest_sources
from .stats import advanced_summary, card_team_stats, normalized_name, number

ODDS_URL = 'https://api.the-odds-api.com/v4/sports/icehockey_nhl_championship_winner/odds/'
BOOKMAKER = 'fanduel'
CACHE_TTL = 3600


def american(value):
    if value is None:
        return None
    try:
        price = int(value)
    except (TypeError, ValueError):
        return None
    return f'+{price}' if price > 0 else str(price)


class StanleyCup:
    def __init__(self, providers: Providers):
        self.p = providers
        self.p.store.db.execute("""
            CREATE TABLE IF NOT EXISTS stanley_cup_odds (
                id TEXT PRIMARY KEY, body TEXT, fetched REAL, attempted REAL
            )
        """)
        self.p.store.db.commit()

    def cached_odds(self):
        row = self.p.store.db.execute(
            'SELECT body,fetched FROM stanley_cup_odds WHERE id=?', ('fanduel',)
        ).fetchone()
        if not row:
            return {}, None, 'empty'
        try:
            body = json.loads(row[0])
        except (TypeError, ValueError):
            return {}, None, 'empty'
        fetched = datetime.fromtimestamp(row[1], timezone.utc).isoformat() if row[1] else None
        status = 'fresh' if row[1] and time.time() - row[1] < CACHE_TTL else 'stale'
        return body if isinstance(body, dict) else {}, fetched, status

    async def fetch_odds(self):
        keys = odds_api_keys()
        if not keys:
            raise OddsError('Odds key not configured in keys.json or /etc/secrets/keys.json')
        last_reason = 'Odds provider returned no usable Stanley Cup prices'
        for key in keys:
            try:
                async with self.p.store.limit:
                    response = await self.p.store.client.get(ODDS_URL, params={
                        'apiKey': key,
                        'markets': 'outrights',
                        'bookmakers': BOOKMAKER,
                        'oddsFormat': 'american',
                    })
            except (httpx.TimeoutException, httpx.HTTPError):
                last_reason = 'Odds provider connection failed'
                continue
            if response.status_code != 200:
                try:
                    payload = response.json()
                    code = payload.get('error_code') if isinstance(payload, dict) else None
                except ValueError:
                    code = None
                if code == 'OUT_OF_USAGE_CREDITS':
                    last_reason = 'Odds quota insufficient for this request; check remaining credits'
                    continue
                if code in ['INVALID_KEY', 'MISSING_KEY'] or response.status_code == 401:
                    last_reason = 'Odds API key rejected; check configured keys file'
                    continue
                last_reason = f'Odds provider returned HTTP {response.status_code}'
                continue
            try:
                data = response.json()
            except ValueError:
                raise OddsError('Odds provider returned invalid JSON') from None
            prices = {}
            for event in data if isinstance(data, list) else []:
                for book in event.get('bookmakers', []):
                    if book.get('key') != BOOKMAKER:
                        continue
                    for market in book.get('markets', []):
                        if market.get('key') != 'outrights':
                            continue
                        for outcome in market.get('outcomes', []):
                            name = outcome.get('name')
                            price = american(outcome.get('price'))
                            if name and price:
                                prices[normalized_name(name)] = {
                                    'team': name,
                                    'odds': price,
                                    'price': outcome.get('price'),
                                    'updated_at': market.get('last_update') or book.get('last_update'),
                                }
            if prices:
                now = time.time()
                self.p.store.db.execute(
                    'INSERT OR REPLACE INTO stanley_cup_odds VALUES(?,?,?,?)',
                    ('fanduel', json.dumps(prices), now, now),
                )
                self.p.store.db.commit()
                return prices, datetime.fromtimestamp(now, timezone.utc).isoformat(), 'fresh'
        raise OddsError(last_reason)

    async def view(self, refresh=False):
        standings = await self.p.nhl('standings/now', 600)
        season = None
        if isinstance(standings.data, dict):
            seasons = [row.get('seasonId') for row in standings.data.get('standings', []) if row.get('seasonId')]
            season = int(seasons[0]) if seasons else None
        summary = await self.p.stats('team/summary', season, is_game=False) if season else None
        mp_teams = await self.p.mp('teams', season) if season else None
        by_team = {
            normalized_name(row.get('teamFullName')): row
            for row in (summary.data if summary else []) or []
            if row.get('teamFullName')
        }
        advanced_rows = {}
        for row in (mp_teams.data if mp_teams else []) or []:
            abbrev = ALIASES.get(row.get('team'), row.get('team'))
            if abbrev in TEAM_NAMES:
                advanced_rows.setdefault(abbrev, []).append(row)
        odds, fetched, status = self.cached_odds()
        error = None
        if refresh or status == 'empty':
            try:
                odds, fetched, status = await self.fetch_odds()
            except OddsError as exc:
                error = str(exc)
        rows = []
        for row in (standings.data or {}).get('standings', []) if isinstance(standings.data, dict) else []:
            abbrev = display_name(row.get('teamAbbrev'))
            name = TEAM_NAMES.get(abbrev, display_name(row.get('teamName')) or abbrev)
            price = odds.get(normalized_name(name), {})
            summary_row = by_team.get(normalized_name(name), {}) if by_team else {}
            summary_stats = card_team_stats(summary_row) if summary_row else {}
            advanced = advanced_summary(advanced_rows.get(abbrev, []))
            rows.append({
                'abbrev': abbrev,
                'name': name,
                'logo': row.get('teamLogoDark') or row.get('teamLogo'),
                'wins': row.get('wins'),
                'losses': row.get('losses'),
                'ot_losses': row.get('otLosses'),
                'points': row.get('points'),
                'games_played': row.get('gamesPlayed'),
                'gf_per_game': summary_stats.get('gf'),
                'ga_per_game': summary_stats.get('ga'),
                'sf_per_game': summary_stats.get('sf'),
                'sa_per_game': number(summary_row.get('shotsAgainstPerGame')),
                'power_play_pct': summary_stats.get('pp'),
                'penalty_kill_pct': (
                    number(summary_row.get('penaltyKillPct')) * 100
                    if number(summary_row.get('penaltyKillPct')) is not None else None
                ),
                'xgf_pct': advanced.get('xgf_pct'),
                'odds': price.get('odds'),
                'odds_price': price.get('price'),
                'odds_updated_at': price.get('updated_at'),
            })
        rows.sort(key=lambda r: (-(r['points'] or 0), -(r['wins'] or 0), r['name']))
        return {
            'teams': rows,
            'odds_status': status,
            'odds_fetched_at': fetched,
            'bookmaker': 'FanDuel',
            'error': error,
            'sources': latest_sources([feed for feed in [standings, summary, mp_teams] if feed is not None]),
        }
