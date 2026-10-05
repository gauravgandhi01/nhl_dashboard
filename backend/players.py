from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from datetime import datetime, timezone

from .cache import Feed
from .service import appearance_series, display_name, game_info, latest_sources, skater_appearances, today_et
from .stats import number, season_label

PLAYERS_TTL = 3600
SNAPSHOT_VERSION = 3


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


def appearance_log(logs, cutoff, season=None):
    games = skater_appearances(logs, cutoff, season)
    if games is None:
        return None
    return appearance_series(games)


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
        p.store.db.execute('''CREATE TABLE IF NOT EXISTS player_dashboards (
            date TEXT PRIMARY KEY, body TEXT, fetched REAL, error TEXT
        )''')
        p.store.db.commit()
        row = p.store.db.execute('SELECT body,fetched,error FROM player_dashboards WHERE date=?', (date,)).fetchone()
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
        advanced = await p.mp('skaters', stats_season)
        sources.append(advanced)
        by_id = defaultdict(list)
        for row in advanced.data or []:
            by_id[int(row['playerId'])].append(row)
        teams = {g[side]['abbrev'] for g in games if int(g['season']) == season for side in ['awayTeam', 'homeTeam']}
        rosters = dict(zip(sorted(teams), await asyncio.gather(*(
            p.nhl(f'roster/{team}/current', 3600) for team in sorted(teams)))))
        sources.extend(rosters.values())
        identities = {r['id'] for feed in rosters.values() for group in ['forwards', 'defensemen']
                      for r in (feed.data or {}).get(group, [])}
        ids = sorted(identities)
        logs = dict(zip(ids, await asyncio.gather(*(
            p.nhl(f'player/{pid}/game-log/{stats_season}/2', 21600) for pid in ids))))
        for pid, feed in list(logs.items()):
            if feed.data is not None and not isinstance(feed.data.get('gameLog'), list):
                logs[pid] = Feed(None, feed.source, feed.url, feed.retrieved_at, feed.stale, 'Game log unavailable')
        sources.extend(logs.values())
        summaries, series = {}, {}
        for pid, feed in logs.items():
            rows = feed.data['gameLog'] if feed.data is not None else None
            summaries[pid] = player_windows(rows, by_id[pid] if advanced.data is not None else None, cutoff, season)
            series[pid] = appearance_log(rows, cutoff, season)
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
                            'logo': team.get('darkLogo') or team.get('logo'), 'game_id': game['id'],
                            'opponent': game[opponent + 'Team']['abbrev'], 'home': side == 'home',
                            'opponent_logo': game[opponent + 'Team'].get('darkLogo') or game[opponent + 'Team'].get('logo'),
                            'season_label': season_label(stats_season), 'windows': summaries[r['id']],
                            'log': series[r['id']],
                            'stats_source': logs[r['id']].meta(), 'advanced_source': advanced.meta(),
                            'roster_source': roster.meta(),
                        })
    result['as_of'] = cutoff
    result['sources'] = latest_sources(sources)
    result['retrieved_at'] = datetime.fromtimestamp(now, timezone.utc).isoformat()
    result['cache_status'] = 'fresh'
    if cache_enabled:
        p.store.db.execute('INSERT OR REPLACE INTO player_dashboards VALUES(?,?,?,NULL)',
                           (date, json.dumps(result), now))
        p.store.db.commit()
        from .retention import compact
        compact(p.store)
    return result
