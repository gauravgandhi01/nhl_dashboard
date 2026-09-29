from __future__ import annotations

import asyncio
from collections import defaultdict

from .cache import Feed
from .service import display_name, game_info, latest_sources, today_et
from .stats import number, season_label


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


def player_windows(logs, advanced, cutoff):
    # Match by NHL player/game IDs; window membership always comes from NHL appearances.
    games = sorted({r['gameId']: r for r in logs or []
                    if r.get('gameDate', '9999') < cutoff and seconds(r.get('toi'))
                    and str(r.get('gameId', ''))[4:6] == '02'}.values(),
                   key=lambda r: (r['gameDate'], r['gameId']), reverse=True)
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
            **values, 'games': n if logs is not None else None,
            'points_pg': divide(values['points'], n), 'shots_pg': divide(values['shots'], n),
            'toi_pg': divide(sum(seconds(g['toi']) for g in sample) if n else None, n),
            'point_games_pct': divide(sum((number(g.get('points')) or 0) > 0 for g in sample), n, 100)
                if values['points'] is not None else None,
            'advanced_games': len(matched) if advanced is not None and logs is not None else None,
            'advanced_minutes': divide(ice, 60),
            'attempts': attempts if advanced is not None and logs is not None else None,
            'attempts_pg': divide(attempts, len(matched)) if advanced is not None and logs is not None else None,
            **{key: divide(total(matched, field), ice, 3600) for key, field in {
                'attempts60': 'I_F_shotAttempts', 'points60': 'I_F_points', 'shots60': 'I_F_shotsOnGoal',
                'ixg60': 'I_F_xGoals', 'hd60': 'I_F_highDangerShots'}.items()},
        }
    return result


async def players_dashboard(p, date):
    scores = await p.nhl(f'score/{date}', 600)
    sources = [scores]
    result = {'date': date, 'players': [], 'games': [], 'periods': [], 'sources': [], 'error': None}
    if scores.data is None or not isinstance(scores.data.get('games'), list):
        result['error'] = 'The NHL schedule is unavailable.'
        result['sources'] = latest_sources(sources)
        return result
    games = sorted([g for g in scores.data['games'] if g.get('gameScheduleState') not in ['PPD', 'CNCL']],
                   key=lambda g: g.get('startTimeUTC', ''))
    result['games'] = [game_info(g, []) for g in games]
    cutoff = min(date, today_et())
    for season in sorted({int(g['season']) for g in games}):
        league = await p.stats('team/summary', season, f" and gameDate<'{cutoff}'", is_game=False)
        sources.append(league)
        no_games = league.data is not None and not any((number(r.get('gamesPlayed')) or 0) > 0 for r in league.data)
        stats_season = season - 10001 if no_games else season
        result['periods'].append({'season_label': season_label(stats_season), 'previous_season': season != stats_season})
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
        summaries = {}
        for pid, feed in logs.items():
            rows = feed.data['gameLog'] if feed.data is not None else None
            summaries[pid] = player_windows(rows, by_id[pid] if advanced.data is not None else None, cutoff)
            p.store.save_games('nhl_skater', stats_season, [{**r, 'playerId': pid} for r in rows or []], 'playerId')
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
                            'stats_source': logs[r['id']].meta(), 'advanced_source': advanced.meta(),
                            'roster_source': roster.meta(),
                        })
    result['as_of'] = cutoff
    result['sources'] = latest_sources(sources)
    return result
