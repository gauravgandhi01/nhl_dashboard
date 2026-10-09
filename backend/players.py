from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone

from .cache import Feed
from .providers import TEAM_NAMES
from .service import appearance_series, display_name, game_info, latest_sources, skater_appearances, today_et
from .stats import number, season_for_date, season_label

logger = logging.getLogger(__name__)
PLAYERS_TTL = 3600
SNAPSHOT_VERSION = 6
ERROR_TTL = 600


def seconds(value):
    try:
        minutes, secs = str(value).split(':')
        return int(minutes) * 60 + int(secs)
    except (ValueError, TypeError):
        return None


def total(rows, key):
    values = [number(r.get(key)) for r in rows]
    return sum(values) if values and all(v is not None for v in values) else None


def divide(value, denominator, scale=1):
    return value * scale / denominator if value is not None and denominator else None


def team_logo(abbrev, team=None):
    if team:
        logo = team.get('darkLogo') or team.get('logo')
        if logo:
            return logo
    return f'https://assets.nhle.com/logos/nhl/svg/{abbrev}_light.svg'


def ensure_player_table(db):
    exists = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='player_dashboards'").fetchone()
    if not exists:
        db.execute('''CREATE TABLE player_dashboards (
            date TEXT NOT NULL, scope TEXT NOT NULL, body TEXT, fetched REAL, error TEXT,
            PRIMARY KEY (date, scope))''')
        db.commit()
        return
    cols = {row[1] for row in db.execute('PRAGMA table_info(player_dashboards)')}
    if 'scope' in cols:
        return
    db.execute('ALTER TABLE player_dashboards RENAME TO player_dashboards_v3')
    db.execute('''CREATE TABLE player_dashboards (
        date TEXT NOT NULL, scope TEXT NOT NULL, body TEXT, fetched REAL, error TEXT,
        PRIMARY KEY (date, scope))''')
    db.execute('''INSERT INTO player_dashboards (date, scope, body, fetched, error)
                  SELECT date, 'tonight', body, fetched, error FROM player_dashboards_v3''')
    db.execute('DROP TABLE player_dashboards_v3')
    db.commit()


def appearance_log(logs, cutoff, season=None):
    games = skater_appearances(logs, cutoff, season)
    if games is None:
        return None
    return appearance_series(games)


def recent_games(logs, advanced, cutoff, season=None):
    """Last five NHL appearances enriched with this player's MoneyPuck rows."""
    games = skater_appearances(logs, cutoff, season)
    if games is None:
        return None
    matched = defaultdict(list)
    for row in advanced or []:
        if row.get('situation') in ('all', '5on5'):
            matched[(str(row['gameId']), row['situation'])].append(row)

    def metric(game_id, situation, field):
        rows = matched[(str(game_id), situation)]
        value = number(rows[0].get(field)) if len(rows) == 1 else None
        return value if value is not None and value >= 0 else None

    return [{
        'game_id': game['gameId'], 'date': game['gameDate'],
        'opponent': game.get('opponentAbbrev') or None,
        'opponent_logo': team_logo(game.get('opponentAbbrev')) if game.get('opponentAbbrev') else None,
        'home': True if game.get('homeRoad') == 'H' else False if game.get('homeRoad') == 'R' else None,
        **{key: number(game.get(key)) for key in ('goals', 'assists', 'points', 'shots')},
        'toi': seconds(game.get('toi')),
        'toi_5v5': metric(game['gameId'], '5on5', 'icetime'),
        'shot_attempts': metric(game['gameId'], 'all', 'I_F_shotAttempts'),
    } for game in games[:5]]


def player_windows(logs, advanced, cutoff, season=None):
    # Match by NHL player/game IDs; window membership always comes from NHL appearances.
    games = skater_appearances(logs, cutoff, season)
    known = games is not None
    games = games or []
    mp = defaultdict(list)
    for row in advanced or []:
        if row.get('situation') in [None, 'all']:
            mp[str(row['gameId'])].append(row)
    result = {}
    for window, count in [('last5', 5), ('last10', 10), ('season', len(games))]:
        sample = games[:count]
        n = len(sample)
        values = {key: total(sample, key) for key in ['goals', 'assists', 'points', 'shots', 'powerPlayPoints']}
        matched = [mp[str(g['gameId'])][0] for g in sample if len(mp[str(g['gameId'])]) == 1
                   and (number(mp[str(g['gameId'])][0].get('icetime')) or 0) > 0]
        ice = total(matched, 'icetime')
        attempts = total(matched, 'I_F_shotAttempts')
        result[window] = {
            **values, 'games': n if known else None,
            'points_pg': divide(values['points'], n), 'shots_pg': divide(values['shots'], n),
            'toi_pg': divide(sum(seconds(g['toi']) for g in sample) if n else None, n),
            'point_games_pct': divide(sum((number(g.get('points')) or 0) > 0 for g in sample), n, 100)
                if values['points'] is not None else None,
            'advanced_games': len(matched) if advanced is not None and known else None,
            'advanced_minutes': divide(ice, 60),
            'attempts': attempts if advanced is not None and known else None,
            'attempts_pg': divide(attempts, len(matched)) if advanced is not None and known else None,
            **{key: divide(total(matched, field), ice, 3600) for key, field in {
                'attempts60': 'I_F_shotAttempts', 'points60': 'I_F_points', 'shots60': 'I_F_shotsOnGoal',
                'ixg60': 'I_F_xGoals', 'hd60': 'I_F_highDangerShots'}.items()},
        }
    return result


async def players_dashboard(p, date):
    cache_enabled = True
    now = time.time()
    try:
        ensure_player_table(p.store.db)
        row = p.store.db.execute(
            'SELECT body, fetched, error FROM player_dashboards WHERE date=? AND scope=?',
            (date, 'tonight')).fetchone()
        if row and row[0] and now - row[1] < PLAYERS_TTL and json.loads(row[0]).get('version') == SNAPSHOT_VERSION:
            body = json.loads(row[0])
            body['retrieved_at'] = datetime.fromtimestamp(row[1], timezone.utc).isoformat()
            body['cache_status'] = 'cached'
            return body
    except (AttributeError, TypeError):
        cache_enabled = False
    scores = await p.nhl(f'score/{date}', 600)
    sources = [scores]
    result = {'version': SNAPSHOT_VERSION, 'date': date, 'players': [], 'games': [], 'periods': [], 'sources': [], 'error': None}
    if scores.data is None or not isinstance(scores.data.get('games'), list):
        result['error'] = 'The NHL schedule is unavailable.'
        result['sources'] = latest_sources(sources)
        return result
    games = sorted([g for g in scores.data['games'] if g.get('gameScheduleState') not in ['PPD', 'CNCL']],
                   key=lambda g: g.get('startTimeUTC', ''))
    result['games'] = [game_info(g, []) for g in games]
    cutoff = min(date, today_et())
    for season in sorted({int(g['season']) for g in games}):
        stats_season = season
        result['periods'].append({'season_label': season_label(season), 'previous_season': False})
        teams = {g[side]['abbrev'] for g in games if int(g['season']) == season for side in ['awayTeam', 'homeTeam']}
        rosters = dict(zip(sorted(teams), await asyncio.gather(*(
            p.nhl(f'roster/{team}/current', 3600) for team in sorted(teams)))))
        sources.extend(rosters.values())
        identities = {r['id'] for feed in rosters.values() for group in ['forwards', 'defensemen']
                      for r in (feed.data or {}).get(group, [])}
        advanced = await p.mp('skaters', stats_season, entities=sorted(identities))
        sources.append(advanced)
        by_id = defaultdict(list)
        for row in advanced.data or []:
            by_id[int(row['playerId'])].append(row)
        ids = sorted(identities)
        logs = dict(zip(ids, await asyncio.gather(*(
            p.nhl(f'player/{pid}/game-log/{stats_season}/2', 21600) for pid in ids))))
        for pid, feed in list(logs.items()):
            if feed.data is not None and not isinstance(feed.data.get('gameLog'), list):
                logs[pid] = Feed(None, feed.source, feed.url, feed.retrieved_at, feed.stale, 'Game log unavailable')
        sources.extend(logs.values())
        summaries, series, recent = {}, {}, {}
        for pid, feed in logs.items():
            rows = feed.data['gameLog'] if feed.data is not None else None
            summaries[pid] = player_windows(rows, by_id[pid] if advanced.data is not None else None, cutoff, season)
            series[pid] = appearance_log(rows, cutoff, season)
            recent[pid] = recent_games(rows, by_id[pid] if advanced.data is not None else None, cutoff, season)
        for game in games:
            if int(game['season']) != season:
                continue
            for side, opponent in [('away', 'home'), ('home', 'away')]:
                team = game[side + 'Team']
                roster = rosters[team['abbrev']]
                for group in ['forwards', 'defensemen']:
                    for r in (roster.data or {}).get(group, []):
                        result['players'].append({
                            'id': r['id'], 'name': f"{display_name(r.get('firstName'))} {display_name(r.get('lastName'))}",
                            'position': r.get('positionCode'), 'team': team['abbrev'],
                            'logo': team_logo(team['abbrev'], team), 'game_id': game['id'],
                            'opponent': game[opponent + 'Team']['abbrev'], 'home': side == 'home',
                            'opponent_logo': game[opponent + 'Team'].get('darkLogo') or game[opponent + 'Team'].get('logo'),
                            'season_label': season_label(stats_season), 'windows': summaries[r['id']],
                            'log': series[r['id']],
                            'recent_games': recent[r['id']],
                            'stats_source': logs[r['id']].meta(), 'advanced_source': advanced.meta(),
                            'roster_source': roster.meta(),
                        })
    result['as_of'] = cutoff
    result['sources'] = latest_sources(sources)
    result['retrieved_at'] = datetime.fromtimestamp(now, timezone.utc).isoformat()
    result['cache_status'] = 'fresh'
    if cache_enabled:
        p.store.db.execute(
            '''INSERT OR REPLACE INTO player_dashboards (date, scope, body, fetched, error)
               VALUES (?, 'tonight', ?, ?, NULL)''',
            (date, json.dumps(result), now))
        p.store.db.commit()
        from .retention import compact
        compact(p.store)
    return result


def _log_rows(feed):
    if feed is None:
        return []
    data = feed.data if isinstance(feed.data, dict) else None
    if data is not None and isinstance(data.get('gameLog'), list):
        return data['gameLog']
    return None


def _save_league(db, date, body, error):
    now = time.time()
    if body is None:
        db.execute(
            '''INSERT INTO player_dashboards (date, scope, body, fetched, error)
               VALUES (?, 'league', NULL, ?, ?)
               ON CONFLICT(date, scope) DO UPDATE SET fetched=excluded.fetched, error=excluded.error''',
            (date, now, error))
    else:
        db.execute(
            '''INSERT INTO player_dashboards (date, scope, body, fetched, error)
               VALUES (?, 'league', ?, ?, NULL)
               ON CONFLICT(date, scope) DO UPDATE SET
                 body=excluded.body, fetched=excluded.fetched, error=NULL''',
            (date, json.dumps(body), now))
    db.commit()


class LeaguePlayers:
    """Current-roster skaters for every team. Game logs build in the background."""

    def __init__(self, providers):
        self.p = providers
        self.tasks, self.progress = {}, {}
        try:
            ensure_player_table(self.p.store.db)
        except (AttributeError, TypeError):
            pass

    async def close(self):
        for task in self.tasks.values():
            task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)

    def cached(self, date):
        try:
            row = self.p.store.db.execute(
                'SELECT body, fetched, error FROM player_dashboards WHERE date=? AND scope=?',
                (date, 'league')).fetchone()
        except (AttributeError, TypeError):
            return None
        if not row or not row[0]:
            return row
        try:
            body = json.loads(row[0])
        except (TypeError, json.JSONDecodeError):
            return None
        if body.get('version') != SNAPSHOT_VERSION or body.get('scope') != 'league':
            return None
        return row

    def _fresh(self, row):
        if not row:
            return False
        if row[0]:
            return time.time() - row[1] < PLAYERS_TTL
        return bool(row[2]) and time.time() - row[1] < ERROR_TTL

    def ensure_build(self, date):
        if date in self.tasks and not self.tasks[date].done():
            return
        row = self.cached(date)
        if self._fresh(row):
            return
        self.progress[date] = {'status': 'building', 'done': 0, 'total': 0}
        self.tasks[date] = asyncio.create_task(self.build(date))

    async def view(self, date):
        self.ensure_build(date)
        row = self.cached(date)
        body = json.loads(row[0]) if row and row[0] else None
        if date in self.progress:
            progress = self.progress[date]
        elif body:
            progress = {'status': 'ready', 'done': body.get('log_total', 0), 'total': body.get('log_total', 0)}
        else:
            progress = {'status': 'building', 'done': 0, 'total': 0}
        retrieved = datetime.fromtimestamp(row[1], timezone.utc).isoformat() if row and row[1] else None
        base = body or {
            'version': SNAPSHOT_VERSION, 'date': date, 'as_of': min(date, today_et()), 'scope': 'league',
            'players': [], 'games': [], 'periods': [], 'sources': [], 'error': None,
            'schedule_available': True, 'partial': False,
        }
        return {**base, 'date': date, 'scope': 'league', 'ready': body is not None, 'build': progress,
                'retrieved_at': retrieved, 'cache_status': 'cached' if body else 'building',
                'error': None if body else (row[2] if row else None)}

    async def build(self, date):
        progress = self.progress.setdefault(date, {'status': 'building', 'done': 0, 'total': 0})
        try:
            body = await self._build(date, progress)
            progress['status'] = 'ready'
            return body
        except Exception:
            logger.exception('League skater list failed for %s', date)
            progress['status'] = 'unavailable'
            progress['done'] = progress.get('done', 0)
            try:
                _save_league(self.p.store.db, date, None, 'Skater list unavailable.')
            except (AttributeError, TypeError):
                pass
            return None

    async def _build(self, date, progress):
        cutoff = min(date, today_et())
        season = season_for_date(cutoff)
        sources = []
        scores = await self.p.nhl(f'score/{date}', 600)
        sources.append(scores)
        schedule_available = isinstance(scores.data, dict) and isinstance(scores.data.get('games'), list)
        games = []
        if schedule_available:
            games = sorted(
                [g for g in scores.data['games'] if g.get('gameScheduleState') not in ['PPD', 'CNCL']],
                key=lambda g: g.get('startTimeUTC', ''))
        inventory = await self.p.stats('skater/summary', season, is_game=False)
        sources.append(inventory)
        if inventory.data is None:
            raise ValueError('Player inventory unavailable')
        played = {int(r['playerId']) for r in inventory.data if (number(r.get('gamesPlayed')) or 0) > 0}
        teams = sorted(TEAM_NAMES)
        roster_feeds = await asyncio.gather(*(self.p.nhl(f'roster/{abbrev}/current', 3600) for abbrev in teams))
        sources.extend(roster_feeds)
        identities = {}
        for abbrev, feed in zip(teams, roster_feeds):
            for group in ['forwards', 'defensemen']:
                for player in (feed.data or {}).get(group, []):
                    identities.setdefault(player['id'], []).append((abbrev, player, feed))
        chosen = []
        ambiguous = 0
        for pid, candidates in identities.items():
            if len(candidates) != 1:
                ambiguous += 1
                continue
            chosen.append((*candidates[0], pid in played))
        advanced = await self.p.mp(
            'skaters', season, entities=[player['id'] for _abbrev, player, _feed, _needs in chosen])
        sources.append(advanced)
        by_id = defaultdict(list)
        if advanced.data is not None:
            for row in advanced.data:
                by_id[int(row['playerId'])].append(row)
        log_ids = [player['id'] for _abbrev, player, _feed, needs_log in chosen if needs_log]
        progress['total'] = len(log_ids)
        logs = {}
        limiter = asyncio.Semaphore(8)

        async def collect(pid):
            async with limiter:
                try:
                    feed = await self.p.nhl(f'player/{pid}/game-log/{season}/2', 21600)
                    if feed.data is not None and not isinstance(feed.data.get('gameLog'), list):
                        feed = Feed(None, feed.source, feed.url, feed.retrieved_at, feed.stale, 'Game log unavailable')
                    logs[pid] = feed
                except (ValueError, KeyError, TypeError):
                    logs[pid] = Feed(None, 'NHL', f'player/{pid}/game-log/{season}/2', error='Game log unavailable')
                progress['done'] += 1

        await asyncio.gather(*(collect(pid) for pid in log_ids))
        sources.extend(logs.values())
        by_team = defaultdict(list)
        for game in games:
            for side, other in [('away', 'home'), ('home', 'away')]:
                team, opp = game[side + 'Team'], game[other + 'Team']
                by_team[team['abbrev']].append({
                    'game_id': game['id'], 'opponent': opp['abbrev'], 'home': side == 'home',
                    'logo': team_logo(team['abbrev'], team),
                    'opponent_logo': opp.get('darkLogo') or opp.get('logo'),
                })
        rows = []
        for abbrev, player, roster, needs_log in chosen:
            feed = logs.get(player['id']) if needs_log else None
            log_rows = _log_rows(feed)
            windows = player_windows(
                log_rows, by_id[player['id']] if advanced.data is not None else None, cutoff, season)
            series = appearance_log(log_rows, cutoff, season)
            recent = recent_games(log_rows, by_id[player['id']] if advanced.data is not None else None, cutoff, season)
            slots = by_team.get(abbrev) or [None]
            for slot in slots:
                rows.append({
                    'id': player['id'],
                    'name': f"{display_name(player.get('firstName'))} {display_name(player.get('lastName'))}",
                    'position': player.get('positionCode'), 'team': abbrev,
                    'logo': slot['logo'] if slot else team_logo(abbrev),
                    'game_id': slot['game_id'] if slot else None,
                    'opponent': slot['opponent'] if slot else None,
                    'home': slot['home'] if slot else None,
                    'opponent_logo': slot['opponent_logo'] if slot else None,
                    'season_label': season_label(season), 'windows': windows, 'log': series,
                    'recent_games': recent,
                    'stats_source': (feed or inventory).meta(),
                    'advanced_source': advanced.meta(), 'roster_source': roster.meta(),
                })
        partial = (ambiguous > 0 or any(feed.data is None for feed in roster_feeds)
                   or any(feed.data is None or feed.stale for feed in logs.values()))
        body = {
            'version': SNAPSHOT_VERSION, 'date': date, 'as_of': cutoff, 'scope': 'league',
            'players': rows, 'games': [game_info(game, []) for game in games],
            'periods': [{'season_label': season_label(season), 'previous_season': False}],
            'sources': latest_sources(sources), 'error': None,
            'schedule_available': schedule_available, 'schedule_stale': bool(scores.stale) and schedule_available,
            'partial': partial, 'ambiguous_players': ambiguous,
            'roster_coverage': sum(feed.data is not None for feed in roster_feeds),
            'roster_total': len(teams), 'log_total': len(log_ids),
        }
        try:
            _save_league(self.p.store.db, date, body, None)
            from .retention import compact
            compact(self.p.store)
        except (AttributeError, TypeError):
            pass
        return body
