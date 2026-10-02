"""Single-season regular-season form and streak leaderboards."""
import asyncio
import json
import time

from .providers import TEAM_NAMES
from .service import display_name, latest_sources, today_et
from .stats import number, season_label, season_for_date, in_season
from .players import seconds

SNAPSHOT_VERSION = 2

BOARDS = [
    ('points10', 'Points', 'Last 10 appearances', 'skater', 'points'),
    ('goals10', 'Goals', 'Last 10 appearances', 'skater', 'goals'),
    ('shots10', 'Shots on goal', 'Last 10 appearances', 'skater', 'shots'),
    ('point_streak', 'Active point streak', 'Consecutive appearances with a point', 'skater', 'points'),
    ('goal_streak', 'Active goal streak', 'Consecutive appearances with a goal', 'skater', 'goals'),
    ('win_streak', 'Active win streak', 'Consecutive decisions; no-decisions skipped', 'goalie', 'decision'),
    ('low_ga10', 'Starts with 0-1 GA', 'Last 10 starts; relief appearances excluded', 'goalie', 'goalsAgainst'),
    ('shutouts10', 'Shutouts', 'Last 10 starts; official NHL shutouts', 'goalie', 'shutouts'),
]


def normalize(rows, cutoff, season=None):
    season = season or season_for_date(cutoff)
    grouped = {}
    for r in rows:
        gid = r.get('gameId')
        if not in_season(gid, season) or str(gid)[4:6] != '02' or r.get('gameDate', '9999') >= cutoff or not seconds(r.get('toi')):
            continue
        if gid in grouped and grouped[gid] != r:
            raise ValueError('Conflicting player-game records')
        grouped[gid] = r
    return sorted(grouped.values(), key=lambda r: (r['gameDate'], r['gameId']), reverse=True)


def metric(rows, key, complete):
    field = next(b[4] for b in BOARDS if b[0] == key)
    sample = [r for r in rows if r.get('gamesStarted') == 1] if key in ['low_ga10', 'shutouts10'] else rows
    if key == 'win_streak':
        sample = [r for r in rows if r.get('decision') not in [None, '', 'N', 'ND']]
    if key.endswith('streak'):
        used = []
        for row in sample:
            v = row.get('decision') if key == 'win_streak' else number(row.get(field))
            if v is None or (key == 'win_streak' and v not in ['W', 'L', 'O', 'OT', 'OTL']):
                return None
            success = v == 'W' if key == 'win_streak' else v > 0
            if not success:
                return {'value': len(used), 'sample': used, 'open': False}
            used.append(row)
        return {'value': len(used), 'sample': used, 'open': not complete and bool(used)}
    sample = sample[:10]
    values = [number(r.get(field)) for r in sample]
    if not sample or any(v is None for v in values):
        return None
    return {'value': sum(v < 2 for v in values) if key == 'low_ga10' else sum(values),
            'sample': sample, 'open': False}


def entries_for(player, rows, complete):
    entries = {}
    for key, _, _, kind, field in BOARDS:
        if kind != player['kind']:
            continue
        result = metric(rows, key, complete)
        if result is None or result['value'] <= 0:
            continue
        sample = result['sample']
        seasons = sorted({int(str(r['gameId'])[:4]) for r in sample})
        entries[key] = {**player, 'value': result['value'], 'sample_size': len(sample),
                        'lower_bound': result['open'], 'latest_game': rows[0]['gameDate'],
                        'start_date': sample[-1]['gameDate'], 'end_date': sample[0]['gameDate'],
                        'seasons': [season_label(y * 10000 + y + 1) for y in seasons],
                        'recent': [{'date': r['gameDate'], 'value': r.get(field),
                                    'opponent': r.get('opponentAbbrev')} for r in sample[:5][::-1]]}
    return entries


def top_ten(entries):
    ordered = sorted(entries, key=lambda p: (-p['value'], -p['sample_size'],
                                            -int(p['latest_game'].replace('-', '')), p['name'], p['id']))
    return [{**p, 'rank': 1 + sum(other['value'] > p['value'] for other in ordered)} for p in ordered[:10]]


class Streaks:
    def __init__(self, providers):
        self.p = providers
        self.tasks, self.progress = {}, {}
        self.p.store.db.execute('''CREATE TABLE IF NOT EXISTS streak_snapshots (
            cutoff TEXT PRIMARY KEY, body TEXT, fetched REAL, attempted REAL, error TEXT)''')
        self.p.store.db.commit()

    async def close(self):
        for task in self.tasks.values():
            task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)

    def cached(self, cutoff):
        row = self.p.store.db.execute('SELECT body,fetched,attempted,error FROM streak_snapshots WHERE cutoff=?', (cutoff,)).fetchone()
        # Old snapshots may contain earlier seasons, including after a failed rebuild.
        if row and row[0] and json.loads(row[0]).get('version') != SNAPSHOT_VERSION:
            return (None, 0, row[2], row[3]) if row[3] else None
        return row

    def ensure_build(self, cutoff):
        if cutoff in self.tasks and not self.tasks[cutoff].done():
            return
        row = self.cached(cutoff)
        ttl = 600 if row and (row[3] or (row[0] and json.loads(row[0]).get('partial'))) else 21600
        if row and time.time() - max(row[1], row[2]) < ttl:
            return
        self.progress[cutoff] = {'status': 'building', 'done': 0, 'total': 0}
        self.tasks[cutoff] = asyncio.create_task(self.build(cutoff))

    async def history(self, player, season, cutoff):
        feed = await self.p.nhl(f"player/{player['id']}/game-log/{season}/2", 21600)
        data = feed.data
        if data is None or data.get('seasonId') != season or data.get('gameTypeId') != 2:
            return None, [feed]
        logs = data.get('gameLog')
        if logs is None and data.get('playerStatsSeasons') == []:
            logs = []
        if not isinstance(logs, list):
            return None, [feed]
        rows = normalize(logs, cutoff, season)
        self.p.store.save_games('nhl_streak_' + player['kind'], season,
                                [{**r, 'playerId': player['id']} for r in rows], 'playerId')
        # The season boundary ends the sample, even when the streak remains active.
        return entries_for(player, rows, True), [feed]

    async def build(self, cutoff):
        progress = self.progress[cutoff]
        now = time.time()
        try:
            season = season_for_date(cutoff)
            sources = []
            inventory = {}
            # Only roster players with activity in this season need game-log requests.
            for kind in ['skater', 'goalie']:
                feed = await self.p.stats(f'{kind}/summary', season,
                                         f" and gameDate<'{cutoff}'", is_game=False)
                sources.append(feed)
                if feed.data is None:
                    raise ValueError('Player inventory unavailable')
                for r in feed.data:
                    if (number(r.get('gamesPlayed')) or 0) > 0:
                        inventory[(kind, r['playerId'])] = season
            teams = sorted(TEAM_NAMES)
            roster_feeds = await asyncio.gather(*(self.p.nhl(f'roster/{a}/current', 3600) for a in teams))
            sources.extend(roster_feeds)
            identities = {}
            for team, feed in zip(teams, roster_feeds):
                for group in ['forwards', 'defensemen', 'goalies']:
                    for r in (feed.data or {}).get(group, []):
                        kind = 'goalie' if group == 'goalies' else 'skater'
                        if (kind, r['id']) not in inventory:
                            continue
                        identities.setdefault(r['id'], []).append({
                            'id': r['id'], 'name': f"{display_name(r.get('firstName'))} {display_name(r.get('lastName'))}",
                            'kind': kind, 'team': team, 'position': r.get('positionCode'),
                            'logo': f'https://assets.nhle.com/logos/nhl/svg/{team}_light.svg'})
            players = [candidates[0] for candidates in identities.values() if len(candidates) == 1]
            progress['total'] = len(players)
            results, skipped = {b[0]: [] for b in BOARDS}, 0
            limiter = asyncio.Semaphore(8)
            async def collect(player):
                nonlocal skipped
                async with limiter:
                    try:
                        entries, feeds = await self.history(player, inventory[(player['kind'], player['id'])], cutoff)
                        sources.extend(feeds)
                        if entries is None:
                            skipped += 1
                        else:
                            stale = any(f.stale for f in feeds)
                            for key, entry in entries.items():
                                results[key].append({**entry, 'stale': stale})
                    except (ValueError, KeyError, TypeError):
                        skipped += 1
                    progress['done'] += 1
            await asyncio.gather(*(collect(p) for p in players))
            partial = skipped > 0 or any(f.data is None or f.stale for f in sources) or any(len(v) != 1 for v in identities.values())
            body = {'version': SNAPSHOT_VERSION, 'season': season, 'entries': results, 'sources': latest_sources(sources), 'partial': partial,
                    'eligible_players': len(players), 'skipped_players': skipped,
                    'ambiguous_players': sum(len(v) != 1 for v in identities.values()),
                    'roster_coverage': sum(f.data is not None for f in roster_feeds), 'roster_total': len(teams)}
            self.p.store.db.execute('INSERT OR REPLACE INTO streak_snapshots VALUES(?,?,?,?,NULL)',
                                    (cutoff, json.dumps(body), time.time(), now))
            self.p.store.db.commit()
            progress['status'] = 'ready'
        except Exception:
            self.p.store.db.execute('''INSERT INTO streak_snapshots VALUES(?,NULL,0,?,?)
                ON CONFLICT(cutoff) DO UPDATE SET attempted=excluded.attempted,error=excluded.error''',
                (cutoff, now, 'Streak history unavailable; last verified snapshot retained'))
            self.p.store.db.commit()
            progress['status'] = 'unavailable'

    async def view(self, date, scope='league'):
        cutoff = min(date, today_et())
        self.ensure_build(cutoff)
        schedule = await self.p.nhl(f'score/{date}', 600)
        opponents = {}
        if schedule.data is not None:
            for game in schedule.data.get('games', []):
                if game.get('gameScheduleState') in ['PPD', 'CNCL']:
                    continue
                for side, other in [('awayTeam', 'homeTeam'), ('homeTeam', 'awayTeam')]:
                    opponents.setdefault(game[side]['abbrev'], []).append({
                        'game_id': game['id'], 'opponent': game[other]['abbrev'], 'home': side == 'homeTeam'})
        row = self.cached(cutoff)
        body = json.loads(row[0]) if row and row[0] else None
        boards = []
        for key, title, period, kind, _ in BOARDS:
            entries = (body or {}).get('entries', {}).get(key, [])
            eligible = [e for e in entries if scope == 'league' or e['team'] in opponents]
            boards.append({'id': key, 'title': title, 'period': period, 'kind': kind,
                           'entries': [{**e, 'matchups': opponents.get(e['team'], [])} for e in top_ten(eligible)]})
        from datetime import datetime, timezone
        return {'date': date, 'season_label': season_label(season_for_date(cutoff)), 'as_of': cutoff, 'scope': scope, 'boards': boards,
                'build': self.progress.get(cutoff, {'status': 'ready', 'done': 0, 'total': 0}),
                'retrieved_at': datetime.fromtimestamp(row[1], timezone.utc).isoformat() if row and row[1] else None,
                'stale': bool(row and row[0] and (row[3] or time.time() - row[1] >= 21600)),
                'error': row[3] if row else None, 'ready': body is not None,
                'schedule_available': schedule.data is not None, 'schedule_stale': schedule.stale,
                'coverage': {k: (body or {}).get(k) for k in ['partial', 'eligible_players', 'skipped_players', 'ambiguous_players', 'roster_coverage', 'roster_total']},
                'sources': [*(body or {}).get('sources', []), schedule.meta()]}
