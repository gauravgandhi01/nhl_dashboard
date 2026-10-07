"""Current-roster goalie windows for the goalies tab."""
from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from datetime import datetime, timezone

from .players import PLAYERS_TTL, team_logo
from .providers import TEAM_NAMES, starter_for
from .service import display_name, game_info, latest_sources, today_et
from .stats import goalie_summary, in_season, normalized_name, number, season_for_date, season_label, total

SNAPSHOT_VERSION = 2


def goalie_windows(rows, advanced, cutoff):
    """Last 5, last 10, and season appearances with time on ice, before cutoff."""
    season = season_for_date(cutoff)
    grouped = {}
    for row in rows or []:
        gid = row.get('gameId')
        if (not in_season(gid, season) or str(gid)[4:6] != '02' or row.get('gameDate', '9999') >= cutoff
                or (number(row.get('timeOnIce')) or 0) <= 0):
            continue
        if gid in grouped and grouped[gid] != row:
            grouped[gid] = None
        else:
            grouped.setdefault(gid, row)
    appearances = sorted((row for row in grouped.values() if row),
                         key=lambda row: (row['gameDate'], row['gameId']), reverse=True)
    matched_by_game = defaultdict(list)
    for row in advanced or []:
        matched_by_game[str(row.get('gameId'))].append(row)
    known = advanced is not None
    result = {}
    for window, count in [('last5', 5), ('last10', 10), ('season', len(appearances))]:
        sample = appearances[:count]
        matched = []
        for game in sample:
            options = matched_by_game.get(str(game['gameId']), [])
            if len(options) == 1:
                matched.append(options[0])
        summary = goalie_summary(sample, matched if known else [])
        if not known:
            summary['gsax'] = None
            summary['advanced_games'] = None
        result[window] = {
            **summary,
            'starts': total(sample, 'gamesStarted'),
            'wins': total(sample, 'wins'),
            'losses': total(sample, 'losses'),
            'ot_losses': total(sample, 'otLosses'),
            'shutouts': total(sample, 'shutouts'),
            'saves': total(sample, 'saves'),
            'shots_against': total(sample, 'shotsAgainst'),
            'goals_against': total(sample, 'goalsAgainst'),
        }
    return result


def _ensure(db):
    db.execute('''CREATE TABLE IF NOT EXISTS goalie_dashboards (
        date TEXT PRIMARY KEY, body TEXT, fetched REAL, error TEXT)''')
    db.commit()


async def goalies_dashboard(p, date):
    cache_enabled = True
    now = time.time()
    try:
        _ensure(p.store.db)
        row = p.store.db.execute('SELECT body, fetched FROM goalie_dashboards WHERE date=?', (date,)).fetchone()
        if row and row[0] and now - row[1] < PLAYERS_TTL and json.loads(row[0]).get('version') == SNAPSHOT_VERSION:
            body = json.loads(row[0])
            body['retrieved_at'] = datetime.fromtimestamp(row[1], timezone.utc).isoformat()
            body['cache_status'] = 'cached'
            return body
    except (AttributeError, TypeError):
        cache_enabled = False
    cutoff = min(date, today_et())
    season = season_for_date(cutoff)
    scores, advanced, per_game, starting = await asyncio.gather(
        p.nhl(f'score/{date}', 600),
        p.mp('goalies', season),
        p.stats('goalie/summary', season),
        p.goalies(date))
    sources = [scores, advanced, per_game, starting]
    schedule_available = isinstance(scores.data, dict) and isinstance(scores.data.get('games'), list)
    games = []
    if schedule_available:
        games = sorted(
            [g for g in scores.data['games'] if g.get('gameScheduleState') not in ['PPD', 'CNCL']],
            key=lambda g: g.get('startTimeUTC', ''))
    result = {
        'version': SNAPSHOT_VERSION, 'date': date, 'as_of': cutoff, 'goalies': [],
        'games': [game_info(game, starting.data if isinstance(starting.data, list) else []) for game in games],
        'periods': [{'season_label': season_label(season), 'previous_season': False}],
        'sources': [], 'error': None, 'schedule_available': schedule_available,
        'schedule_stale': bool(scores.stale) and schedule_available, 'partial': False,
    }
    if per_game.data is None:
        result['error'] = 'Goalie statistics are unavailable.'
        result['sources'] = latest_sources(sources)
        return result
    by_player = defaultdict(list)
    for row in per_game.data:
        try:
            by_player[int(row['playerId'])].append(row)
        except (KeyError, TypeError, ValueError):
            continue
    mp_by_player = defaultdict(list)
    if advanced.data is not None:
        for row in advanced.data:
            try:
                mp_by_player[int(row['playerId'])].append(row)
            except (KeyError, TypeError, ValueError):
                continue
    teams = sorted(TEAM_NAMES)
    roster_feeds = await asyncio.gather(*(p.nhl(f'roster/{abbrev}/current', 3600) for abbrev in teams))
    sources.extend(roster_feeds)
    identities = {}
    for abbrev, feed in zip(teams, roster_feeds):
        for player in (feed.data or {}).get('goalies', []):
            identities.setdefault(player['id'], []).append((abbrev, player, feed))
    by_team = defaultdict(list)
    starters = {}
    dfo_rows = starting.data if isinstance(starting.data, list) else []
    for game in games:
        starters[game['id']] = starter_for(game, dfo_rows)
        for side, other in [('away', 'home'), ('home', 'away')]:
            team, opp = game[side + 'Team'], game[other + 'Team']
            by_team[team['abbrev']].append({
                'game_id': game['id'], 'opponent': opp['abbrev'], 'home': side == 'home',
                'logo': team_logo(team['abbrev'], team),
                'opponent_logo': opp.get('darkLogo') or opp.get('logo'),
                'starter': starters[game['id']][side],
            })
    ambiguous = 0
    for pid, candidates in identities.items():
        if len(candidates) != 1:
            ambiguous += 1
            continue
        abbrev, player, roster = candidates[0]
        name = f"{display_name(player.get('firstName'))} {display_name(player.get('lastName'))}".strip()
        windows = goalie_windows(
            by_player.get(pid, []),
            mp_by_player.get(pid) if advanced.data is not None else None,
            cutoff)
        if (windows['season']['games'] or 0) < 1:
            continue
        slots = by_team.get(abbrev) or [None]
        for slot in slots:
            status = None
            if slot and slot['starter'].get('name') and slot['starter'].get('status') in ['Confirmed', 'Likely']:
                if normalized_name(slot['starter']['name']) == normalized_name(name):
                    status = slot['starter']['status']
            result['goalies'].append({
                'id': pid, 'name': name, 'team': abbrev,
                'logo': slot['logo'] if slot else team_logo(abbrev),
                'game_id': slot['game_id'] if slot else None,
                'opponent': slot['opponent'] if slot else None,
                'home': slot['home'] if slot else None,
                'opponent_logo': slot['opponent_logo'] if slot else None,
                'starter_status': status, 'season_label': season_label(season), 'windows': windows,
                'stats_source': per_game.meta(), 'advanced_source': advanced.meta(),
                'roster_source': roster.meta(),
            })
    result['partial'] = ambiguous > 0 or any(feed.data is None for feed in roster_feeds) or advanced.data is None
    result['ambiguous_goalies'] = ambiguous
    result['roster_coverage'] = sum(feed.data is not None for feed in roster_feeds)
    result['roster_total'] = len(teams)
    result['sources'] = latest_sources(sources)
    result['retrieved_at'] = datetime.fromtimestamp(now, timezone.utc).isoformat()
    result['cache_status'] = 'fresh'
    if cache_enabled:
        p.store.db.execute(
            'INSERT OR REPLACE INTO goalie_dashboards (date, body, fetched, error) VALUES (?, ?, ?, NULL)',
            (date, json.dumps(result), now))
        p.store.db.commit()
        from .retention import compact
        compact(p.store)
    return result
