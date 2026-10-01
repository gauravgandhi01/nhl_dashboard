"""Shared event/player-ID prop cache. Paid requests refresh hourly as needed."""
import asyncio
import json
import logging
import math
import time
from datetime import datetime, timezone

from .first_period_odds import event_game, SOURCE
from .odds_client import OddsError, odds_client, odds_configured
from .player_identity import resolve_player
from .service import display_name
from .stats import number

BOOKS = ('ballybet', 'betonlineag', 'draftkings', 'fanatics', 'fanduel',
         'kalshi', 'novig', 'prophetx', 'williamhill_us')
MARKETS = {
    'player_assists': ('assists', False), 'player_assists_alternate': ('assists', True),
    'player_points': ('points', False), 'player_points_alternate': ('points', True),
    'player_shots_on_goal': ('shots', False), 'player_shots_on_goal_alternate': ('shots', True),
    'player_goals': ('goals', False), 'player_goals_alternate': ('goals', True),
    'player_goal_scorer_anytime': ('anytime', False),
    'player_goal_scorer_first': ('first_goal', False),
}
VERSION = '1:' + ','.join(BOOKS)
logger = logging.getLogger(__name__)


class PropUnavailable(ValueError):
    pass


def timestamp(value):
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError, AttributeError):
        return None


def eligible(game):
    return (game.get('gameState') in ['FUT', 'PRE']
            and game.get('gameScheduleState') not in ['PPD', 'CNCL']
            and (timestamp(game.get('startTimeUTC')) or 0) > time.time())


def normalize_props(event, roster, aliases=None):
    players, unresolved, seen = {}, set(), set()
    for book in event.get('bookmakers', []):
        if book.get('key') not in BOOKS:
            continue
        for market in book.get('markets', []):
            key = market.get('key')
            if key not in MARKETS:
                continue
            family, alternate = MARKETS[key]
            for outcome in market.get('outcomes', []):
                name = outcome.get('description', '')
                player = resolve_player(name, roster, aliases)
                if not player:
                    if name:
                        unresolved.add(name)
                    continue
                price = number(outcome.get('price'))
                side = str(outcome.get('name', '')).lower()
                point = number(outcome.get('point'))
                binary = family in ['anytime', 'first_goal']
                if (price is None or not math.isfinite(price) or abs(price) < 100
                    or not float(price).is_integer() or side not in (['yes', 'no'] if binary else ['over', 'under'])
                    or (not binary and (point is None or not math.isfinite(point) or point < 0))):
                    continue
                if binary:
                    point = None
                identity = (player['id'], book['key'], key, point, side)
                if identity in seen:
                    continue
                seen.add(identity)
                pid = str(player['id'])
                item = players.setdefault(pid, {**player, 'markets': {}})
                lines = item['markets'].setdefault(family, [])
                line_id = f'{key}:{point}'
                line = next((line for line in lines if line['id'] == line_id), None)
                if line is None:
                    line = {'id': line_id, 'market': key, 'point': point, 'alternate': alternate, 'quotes': []}
                    lines.append(line)
                line['quotes'].append({'side': side, 'price': int(price), 'bookmaker': book['key'], 'market': key,
                    'book': book.get('title') or book['key'], 'updated_at': market.get('last_update') or book.get('last_update')})
    return {'players': players, 'unmatched_names': sorted(unresolved), 'matched_players': len(players)}


class PlayerProps:
    def __init__(self, providers):
        self.p = providers
        self.client = odds_client(providers.store)
        self.lock = asyncio.Lock()
        self.p.store.db.execute('''CREATE TABLE IF NOT EXISTS player_prop_odds (
            game_id INTEGER PRIMARY KEY, version TEXT, body TEXT, fetched REAL, attempted REAL, error TEXT)''')
        self.p.store.db.commit()

    def cached(self, game):
        row = self.p.store.db.execute('SELECT body,fetched,attempted,error FROM player_prop_odds WHERE game_id=? AND version=?',
                                      (game['id'], VERSION)).fetchone()
        body = json.loads(row[0]) if row and row[0] else {'players': {}, 'unmatched_names': []}
        stale = bool(row and row[0] and (row[3] or time.time() - row[1] >= 3600))
        return {**body, 'game_id': game['id'], 'eligible': eligible(game),
                **({'players': {}} if game.get('gameScheduleState') in ['PPD', 'CNCL'] else {}),
                'status': ('stale' if stale else 'available') if row and row[0] else 'unavailable' if row and row[3] else 'not_loaded',
                'retrieved_at': datetime.fromtimestamp(row[1], timezone.utc).isoformat() if row and row[1] else None,
                'error': row[3] if row else None}

    def failure(self, game, error):
        logger.warning('Player props unavailable game_id=%s reason=%s', game['id'], error)
        self.p.store.db.execute('''INSERT INTO player_prop_odds VALUES(?,?,NULL,0,?,?)
            ON CONFLICT(game_id) DO UPDATE SET attempted=excluded.attempted,error=excluded.error''',
            (game['id'], VERSION, time.time(), error))
        self.p.store.db.commit()

    async def refresh_game(self, game, events):
        now = time.time()
        try:
            matches = [e for e in events if (event_game(e, [game]) or {}).get('id') == game['id']]
            if len(matches) != 1:
                raise PropUnavailable('No unique odds event matches this NHL matchup')
            event = matches[0]
            eid = event.get('id', '')
            if not isinstance(eid, str) or not eid.isalnum() or (timestamp(event.get('commence_time')) or 0) <= now:
                raise PropUnavailable('Odds event has started or has an invalid identifier')
            roster, sources = [], []
            for side in ['awayTeam', 'homeTeam']:
                team = game[side]['abbrev']
                feed = await self.p.nhl(f'roster/{team}/current', 3600)
                if feed.data is None or feed.stale:
                    raise PropUnavailable(f'Current NHL roster unavailable or stale for {team}; prices not requested')
                sources.append(feed.meta())
                for group in ['forwards', 'defensemen']:
                    for p in feed.data.get(group, []):
                        roster.append({'id': p['id'], 'name': f"{display_name(p.get('firstName'))} {display_name(p.get('lastName'))}", 'team': team})
                if not any(p['team'] == team for p in roster):
                    raise PropUnavailable(f'Current NHL roster is empty for {team}; prices not requested')
            if not eligible(game):
                raise PropUnavailable('Game already started; pregame prices not requested')
            body = await self.client.request(f'/events/{eid}/odds', {
                'bookmakers': ','.join(BOOKS), 'markets': ','.join(MARKETS), 'oddsFormat': 'american'})
            if body.get('id') != eid or (event_game(body, [game]) or {}).get('id') != game['id']:
                raise PropUnavailable('Odds response does not match the requested NHL matchup')
            result = {**normalize_props(body, roster), 'event_id': eid, 'roster_sources': sources,
                      'usage': dict(self.client.usage)}
            self.p.store.db.execute('INSERT OR REPLACE INTO player_prop_odds VALUES(?,?,?,?,?,NULL)',
                (game['id'], VERSION, json.dumps(result), now, now))
            self.p.store.db.commit()
        except (PropUnavailable, OddsError) as exc:
            self.failure(game, str(exc))
        except (ValueError, KeyError, TypeError, AttributeError):
            self.failure(game, 'Props response schema invalid; cached prices retained when available')

    async def view(self, date, game_id=None, refresh=False):
        schedule = await self.p.nhl(f'score/{date}', 600)
        configured = odds_configured()
        result = {'date': date, 'configured': configured, 'games': {}, 'books': list(BOOKS),
                  'source': SOURCE, 'max_credits_per_game': len(MARKETS), 'error': None}
        if schedule.data is None or not isinstance(schedule.data.get('games'), list):
            result['error'] = 'Schedule unavailable; props not requested'
            return result
        games = [g for g in schedule.data['games'] if game_id is None or g['id'] == game_id]
        should_refresh = refresh
        if should_refresh and schedule.stale:
            result['error'] = 'Schedule is stale; props not requested'
        elif should_refresh and configured:
            async with self.lock:
                pending = []
                for game in games:
                    row = self.p.store.db.execute('SELECT attempted FROM player_prop_odds WHERE game_id=? AND version=?', (game['id'], VERSION)).fetchone()
                    if eligible(game) and (refresh or self.cached(game)['status'] != 'available') and (refresh or not row or time.time() - row[0] >= 600):
                        pending.append(game)
                if pending:
                    try:
                        events = await self.client.request('/events')
                        if not isinstance(events, list):
                            raise ValueError('Invalid events')
                        events = [e for e in events if event_game(e, schedule.data['games']) is not None]
                        for game in pending:
                            await self.refresh_game(game, events)
                    except OddsError as exc:
                        for game in pending:
                            self.failure(game, str(exc))
                    except (ValueError, KeyError, TypeError):
                        for game in pending:
                            self.failure(game, 'Odds event discovery returned an invalid response')
        result['games'] = {str(g['id']): self.cached(g) for g in games}
        return result
