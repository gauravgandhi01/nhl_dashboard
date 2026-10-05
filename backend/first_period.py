from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from datetime import date as Date, timedelta

from .first_period_stats import VERSION, team_games, extract_goalies, windows, summarize, WINDOWS
from .service import today_et, game_info, display_name, latest_sources
from .stats import season_label, match_player, in_season


class FirstPeriod:
    def __init__(self, providers):
        self.p = providers
        self.tasks, self.progress, self.memo, self.locks = {}, {}, {}, {}
        self.p.store.db.execute('''CREATE TABLE IF NOT EXISTS first_period_games (
            season INTEGER, game_id INTEGER, version INTEGER, body TEXT, fetched REAL,
            attempted REAL, error TEXT, PRIMARY KEY(season, game_id))''')
        self.p.store.db.commit()

    async def close(self):
        for task in self.tasks.values():
            task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)

    async def dataset(self, season):
        async with self.locks.setdefault(season, asyncio.Lock()):
            memo = self.memo.get(season)
            if memo and time.monotonic() - memo[0] < 600:
                return memo[1]
            feed = await self.p.stats('team/goalsbyperiod', season)
            rows = [r for r in feed.data or [] if in_season(r.get('gameId'), season)]
            games, rejected = team_games(rows, today_et())
            data = (feed, games, rejected)
            self.memo[season] = (time.monotonic(), data)
            return data

    def saved(self, season):
        return {r[0]: {'body': json.loads(r[1]) if r[1] else None, 'fetched': r[2], 'attempted': r[3], 'error': r[4]}
                for r in self.p.store.db.execute(
                    'SELECT game_id,body,fetched,attempted,error FROM first_period_games WHERE season=? AND version=?', (season, VERSION))}

    def ttl(self, game):
        return 21600 if game['date'] >= (Date.fromisoformat(today_et()) - timedelta(days=7)).isoformat() else 604800

    def ensure_build(self, season, games):
        current = self.tasks.get(season)
        if current and not current.done():
            return
        saved = self.saved(season)
        now = time.time()
        missing = [g for g in games if g['gameId'] not in saved or (
            now - saved[g['gameId']]['fetched'] >= self.ttl(g)
            and now - saved[g['gameId']]['attempted'] >= 600)]
        if missing:
            self.progress[season] = {'status': 'building', 'done': 0, 'total': len(missing), 'error': None}
            self.tasks[season] = asyncio.create_task(self.build(season, missing))

    async def build(self, season, games):
        progress = self.progress[season]
        try:
            goalies = await self.p.stats('goalie/summary', season)
            if goalies.data is None:
                raise ValueError('NHL goalie starter records unavailable')
            by_game = defaultdict(list)
            for r in goalies.data:
                by_game[r['gameId']].append(r)
            semaphore = asyncio.Semaphore(4)
            async def process(game):
                async with semaphore:
                    gid, now = game['gameId'], time.time()
                    try:
                        pbp = await self.p.nhl(f'gamecenter/{gid}/play-by-play', self.ttl(game), store_body=False)
                        normalized = extract_goalies(game, pbp.data, by_game[gid])
                        body = {**normalized, 'sources': latest_sources([pbp, goalies])}
                        if pbp.stale or goalies.stale:
                            raise ValueError('Source is stale; retaining last verified period records')
                        self.p.store.db.execute('INSERT OR REPLACE INTO first_period_games VALUES(?,?,?,?,?,?,NULL)',
                                                (season, gid, VERSION, json.dumps(body), now, now))
                        self.p.store.db.commit()
                        self.p.store.delete_response(pbp.url)
                    except (ValueError, TypeError, KeyError):
                        self.p.store.db.execute('''INSERT INTO first_period_games VALUES(?,?,?,NULL,0,?,?)
                            ON CONFLICT(season,game_id) DO UPDATE SET attempted=excluded.attempted,error=excluded.error''',
                            (season, gid, VERSION, now, 'First-period goalie data unavailable or inconsistent'))
                    self.p.store.db.commit()
                    progress['done'] += 1
            await asyncio.gather(*(process(g) for g in games))
            progress['status'] = 'ready'
        except Exception:
            progress.update(status='unavailable', error='Goalie history build unavailable')
            # Back off a failed season-wide source without suppressing team statistics.
            now = time.time()
            for g in games:
                self.p.store.db.execute('''INSERT INTO first_period_games VALUES(?,?,?,NULL,0,?,?)
                    ON CONFLICT(season,game_id) DO UPDATE SET attempted=excluded.attempted,error=excluded.error''',
                    (season, g['gameId'], VERSION, now, progress['error']))
            self.p.store.db.commit()

    async def view(self, date, window='season', game_id=None):
        sources = []
        if game_id is not None:
            landing = await self.p.nhl(f'gamecenter/{game_id}/landing', 600)
            sources.append(landing)
            if not landing.data or not all(k in landing.data for k in ['id', 'season', 'gameDate', 'awayTeam', 'homeTeam']):
                return {'error': 'Matchup unavailable', 'sources': latest_sources(sources)}
            date = landing.data['gameDate']
            raw_games = [landing.data]
            season = int(landing.data['season'])
        else:
            scores = await self.p.nhl(f'score/{date}', 600)
            sources.append(scores)
            if scores.data is None or not isinstance(scores.data.get('games'), list):
                return {'error': 'The NHL schedule is unavailable.', 'sources': latest_sources(sources)}
            raw_games = sorted(scores.data['games'], key=lambda g: g.get('startTimeUTC', ''))
            year = int(date[:4]) - (int(date[5:7]) < 7)
            season = int(raw_games[0]['season']) if raw_games else year * 10000 + year + 1
        cutoff = min(date, today_et())
        feed, season_games, rejected = await self.dataset(season)
        sources.append(feed)
        stats_season = season
        self.ensure_build(stats_season, season_games)
        games = [g for g in season_games if g['date'] < cutoff]
        saved = self.saved(stats_season)
        team_rows, goalie_rows = defaultdict(list), defaultdict(list)
        teams, names, roster_map = {}, {}, {}
        covered, incomplete, stale = 0, 0, 0
        period_sources = {}
        for g in games:
            for side in ['away', 'home']:
                t = g[side]
                teams[t['id']] = {k: t[k] for k in ['id', 'abbrev', 'name']}
                team_rows[t['id']].append({'gameId': g['gameId'], 'date': g['date'], 'gf': t['gf'], 'ga': t['ga']})
            row = saved.get(g['gameId'])
            if not row or not row['body']:
                continue
            covered += 1
            incomplete += bool(row['body']['warnings'])
            stale += bool(row['error']) or time.time() - row['fetched'] >= self.ttl(g)
            for meta in row['body']['sources']:
                period_sources[meta['url']] = meta
            for p in row['body']['goalies']:
                goalie_rows[p['playerId']].append(p)
                names[p['playerId']] = p['name']
        goalie_windows = {pid: windows(rows, True) for pid, rows in goalie_rows.items()}
        qualified = [pid for pid, w in goalie_windows.items() if w['season']['games'] >= 5]
        ranks = {}
        for pid in qualified:
            s = goalie_windows[pid]['season']
            ranks[pid] = {'ga': 1 + sum(goalie_windows[q]['season']['ga_pg'] < s['ga_pg'] for q in qualified),
                          'sv': None if s['sv'] is None else 1 + sum((goalie_windows[q]['season']['sv'] or 0) > s['sv'] for q in qualified),
                          'qualified': len(qualified)}
        league_goalies = {key: summarize([p for rows in goalie_rows.values()
                                          for p in sorted(rows, key=lambda r: (r['date'], r['gameId']), reverse=True)[:count]], True)
                          for key, count in WINDOWS.items()}
        team_windows = {tid: windows(rows) for tid, rows in team_rows.items()}
        starters = await self.p.goalies(date)
        sources.append(starters)
        abbreviations = sorted({g[side]['abbrev'] for g in raw_games for side in ['awayTeam', 'homeTeam']})
        rosters = await asyncio.gather(*(self.p.nhl(f'roster/{a}/current', 3600) for a in abbreviations))
        sources.extend(rosters)
        for abbrev, roster in zip(abbreviations, rosters):
            roster_map[abbrev] = [{'id': r['id'], 'name': f"{display_name(r.get('firstName'))} {display_name(r.get('lastName'))}"}
                                  for r in (roster.data or {}).get('goalies', [])]
        comparisons = []
        for raw in raw_games:
            game = game_info(raw, starters.data)
            sides = {}
            for side in ['away', 'home']:
                t = game[side]
                roster = roster_map.get(t['abbrev'], [])
                starter_id = match_player(t['starter']['name'], roster)
                choices = [{**p, 'windows': goalie_windows.get(p['id'], windows([], True)),
                            'rank': ranks.get(p['id'])} for p in roster]
                choices.sort(key=lambda p: (-p['windows']['season']['games'], p['name']))
                selected = starter_id or (choices[0]['id'] if choices else None)
                sides[side] = {'team': t, 'windows': team_windows.get(t['id'], windows([])),
                               'starter': {**t['starter'], 'player_id': starter_id}, 'goalies': choices,
                               'selected_goalie': selected, 'goalie_basis': 'Reported starter' if starter_id else 'Roster leader' if selected else 'Unavailable'}
            pair = {game['away']['id'], game['home']['id']}
            h2h = [g for g in games if {g['away']['id'], g['home']['id']} == pair]
            comparisons.append({'game': game, **sides, 'h2h': {'recent': h2h[:5],
                                'summary': summarize([{'gf': g['away']['gf'], 'ga': g['home']['gf']} for g in h2h])}})
        ranked = sorted(teams.values(), key=lambda t: (-(team_windows[t['id']]['season']['hits'] or 0), t['abbrev']))
        rankings = [{**t, 'rank': 1 + sum((team_windows[o['id']]['season']['hits'] or 0) > (team_windows[t['id']]['season']['hits'] or 0) for o in ranked),
                     'windows': team_windows[t['id']], 'playing': t['abbrev'] in abbreviations} for t in ranked]
        progress = self.progress.get(stats_season, {'status': 'ready', 'done': 0, 'total': 0, 'error': None})
        return {'date': date, 'window': window, 'season': stats_season, 'season_label': season_label(stats_season),
                'previous_season': False, 'as_of': cutoff, 'matchups': comparisons,
                'rankings': rankings, 'league_goalies': league_goalies, 'build': dict(progress),
                'coverage': {'games': len(games), 'goalie_games': covered, 'incomplete_games': incomplete,
                             'stale_games': stale, 'rejected_team_games': rejected},
                'sources': [*latest_sources(sources), *period_sources.values()],
                'error': None, 'stats_error': None if feed.data is not None else 'First-period team statistics unavailable'}
