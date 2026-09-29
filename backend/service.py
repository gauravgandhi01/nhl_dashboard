from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from .cache import Feed
from .signals import career_nhl_games, matchup_signals
from .providers import ALIASES, TEAM_NAMES, Providers, starter_for
from .stats import (advanced_summary, choose_season, goalie_summary, match_player, normalized_name,
                    number, recent, rest_context, season_label, team_summary, card_team_stats, last_five, card_goalie)


def today_et():
    return datetime.now(ZoneInfo('America/New_York')).date().isoformat()


def display_name(value):
    return value.get('default', '') if isinstance(value, dict) else value or ''


def team_info(team):
    abbrev = team['abbrev']
    return {'id': team['id'], 'abbrev': abbrev, 'name': TEAM_NAMES.get(abbrev, display_name(team.get('name')) or abbrev),
            'logo': team.get('darkLogo') or team.get('logo'), 'record': team.get('record'), 'score': team.get('score')}


def game_info(game, goalies):
    starters = starter_for(game, goalies)
    return {'id': game['id'], 'date': game.get('gameDate'), 'season': game.get('season'),
            'start': game.get('startTimeUTC'), 'state': game.get('gameState'),
            'schedule_state': game.get('gameScheduleState'), 'game_type': game.get('gameType'),
            'venue': display_name(game.get('venue')), 'period': game.get('periodDescriptor', {}).get('number'),
            'clock': game.get('clock'), 'away': {**team_info(game['awayTeam']), 'starter': starters['away']},
            'home': {**team_info(game['homeTeam']), 'starter': starters['home']}}


def clock_seconds(value):
    try:
        minutes, seconds = str(value).split(':')
        return int(minutes) * 60 + int(seconds)
    except (TypeError, ValueError):
        return None


def average(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def lineup_usage_windows(logs, advanced, cutoff):
    games = sorted({r['gameId']: r for r in logs or []
                    if r.get('gameDate', '9999') < cutoff and clock_seconds(r.get('toi'))
                    and str(r.get('gameId', ''))[4:6] == '02'}.values(),
                   key=lambda r: (r['gameDate'], r['gameId']), reverse=True)
    mp_5v5 = {}
    for row in advanced or []:
        if row.get('situation') == '5on5' and (number(row.get('icetime')) or 0) > 0:
            mp_5v5.setdefault(str(row['gameId']), []).append(row)
    result = {}
    for key, count in [('l5', 5), ('l10', 10), ('season', len(games))]:
        sample = games[:count]
        matched = [mp_5v5[str(g['gameId'])][0] for g in sample if len(mp_5v5.get(str(g['gameId']), [])) == 1]
        result[key] = average([clock_seconds(g.get('toi')) for g in sample])
        result[key + '_games'] = len(sample) if logs is not None else None
        result[key + '_5v5'] = average([number(r.get('icetime')) for r in matched]) if advanced is not None else None
        result[key + '_5v5_games'] = len(matched) if advanced is not None and logs is not None else None
    return result


def latest_sources(feeds):
    unique = {f.url: f.meta() for f in feeds}
    return list(unique.values())


class Dashboard:
    def __init__(self, providers: Providers):
        self.p = providers

    async def slate(self, date):
        scores, goalies = await asyncio.gather(self.p.nhl(f'score/{date}', 600), self.p.goalies(date))
        if scores.data is None or not isinstance(scores.data.get('games'), list):
            return {'date': date, 'games': [], 'error': 'The NHL schedule is unavailable.', 'sources': latest_sources([scores, goalies])}
        games = sorted(scores.data['games'], key=lambda g: g.get('startTimeUTC', ''))
        sources = [scores, goalies]
        comparisons = {}
        for season in sorted({int(g['season']) for g in games}):
            league = await self.p.stats('team/summary', season, is_game=False)
            sources.append(league)
            completed = [r for r in league.data or [] if (number(r.get('gamesPlayed')) or 0) > 0]
            stats_season = choose_season(season, completed) if league.data is not None else season
            if stats_season != season:
                league = await self.p.stats('team/summary', stats_season, is_game=False)
                sources.append(league)
            goalie_stats, mp_goalies, mp_teams = await asyncio.gather(self.p.stats('goalie/summary', stats_season, is_game=False),
                                                                      self.p.mp('goalies', stats_season),
                                                                      self.p.mp('teams', stats_season))
            sources.extend([goalie_stats, mp_goalies, mp_teams])
            teams = {g[side]['id']: g[side] for g in games if int(g['season']) == season for side in ['awayTeam', 'homeTeam']}
            async def team_context(team):
                roster, schedule, signal_schedule = await asyncio.gather(self.p.nhl(f"roster/{team['abbrev']}/current", 3600),
                                                        self.p.nhl(f"club-schedule-season/{team['abbrev']}/{stats_season}", 21600),
                                                        self.p.nhl(f"club-schedule-season/{team['abbrev']}/{season}", 600))
                return roster, schedule, signal_schedule
            contexts = dict(zip(teams, await asyncio.gather(*(team_context(t) for t in teams.values()))))
            for roster, schedule, signal_schedule in contexts.values():
                sources.extend([roster, schedule, signal_schedule])
            confirmed_ids = {}
            if not goalies.stale:
                for game in games:
                    if int(game['season']) != season:
                        continue
                    for side, starter in starter_for(game, goalies.data).items():
                        if starter.get('status') != 'Confirmed':
                            continue
                        roster = contexts[game[side + 'Team']['id']][0]
                        if roster.stale:
                            continue
                        candidates = [{'id': p['id'], 'name': f"{display_name(p.get('firstName'))} {display_name(p.get('lastName'))}"}
                                      for p in (roster.data or {}).get('goalies', [])]
                        player_id = match_player(starter.get('name'), candidates)
                        if player_id is not None:
                            confirmed_ids[(game['id'], side)] = player_id
            player_ids = sorted(set(confirmed_ids.values()))
            career_feeds = dict(zip(player_ids, await asyncio.gather(*(
                self.p.nhl(f'player/{pid}/landing', 3600) for pid in player_ids))))
            sources.extend(career_feeds.values())
            by_team = {r['teamId']: r for r in league.data or []}
            for game in games:
                if int(game['season']) != season:
                    continue
                starters = starter_for(game, goalies.data)
                comparison = {'season_label': season_label(stats_season), 'previous_season': stats_season != season}
                for side in ['away', 'home']:
                    tid = game[side + 'Team']['id']
                    roster, schedule, signal_schedule = contexts[tid]
                    player_id = confirmed_ids.get((game['id'], side))
                    career = career_feeds.get(player_id)
                    career_gp = career_nhl_games(career.data) if career and not career.stale and career.data and career.data.get('playerId') == player_id else None
                    advanced = [r for r in mp_teams.data or [] if ALIASES.get(r['team'], r['team']) == game[side + 'Team']['abbrev']]
                    comparison[side] = {'summary': card_team_stats(by_team.get(tid)),
                                        'advanced': advanced_summary(advanced),
                                        'form': last_five((schedule.data or {}).get('games', []), tid),
                                        'goalie': card_goalie(starters[side], (roster.data or {}).get('goalies', []),
                                                              goalie_stats.data or [], mp_goalies.data or []),
                                        'signals': matchup_signals(game, tid, (signal_schedule.data or {}).get('games', []) if not signal_schedule.stale else [],
                                                                   starters[side], career_gp)}
                comparisons[str(game['id'])] = comparison
        return {'date': date, 'games': [game_info(g, goalies.data) for g in games],
                'comparisons': comparisons, 'sources': latest_sources(sources), 'error': None}

    async def matchup(self, game_id, window):
        landing = await self.p.nhl(f'gamecenter/{game_id}/landing', 600)
        if not landing.data or not all(k in landing.data for k in ['awayTeam', 'homeTeam', 'season', 'gameDate']):
            return None
        game = landing.data
        season = int(game['season'])
        league, goalies, injuries = await asyncio.gather(self.p.stats('team/summary', season, is_game=False),
                                                       self.p.goalies(game['gameDate']), self.p.injuries())
        completed = [r for r in (league.data or []) if (number(r.get('gamesPlayed')) or 0) > 0]
        stats_season = choose_season(season, completed) if league.data is not None else season
        mp_teams, mp_goalies, skater_totals, mp_skaters = await asyncio.gather(
            self.p.mp('teams', stats_season), self.p.mp('goalies', stats_season),
            self.p.mp('skaters', stats_season),
            self.p.stats('skater/summary', stats_season, is_game=False))
        # Roster totals are always season totals; the comparison window applies to teams and goalies.
        info = game_info(game, goalies.data)
        sides = await asyncio.gather(*[self.team(game, side, stats_season, window, mp_teams, mp_goalies, mp_skaters,
                                                skater_totals, injuries, info[side]['starter']) for side in ['away', 'home']])
        return {'game': info, 'season': stats_season, 'season_label': season_label(stats_season),
                'previous_season': stats_season != season, 'window': window, 'as_of': today_et(),
                'away': sides[0][0], 'home': sides[1][0],
                'sources': latest_sources([landing, league, goalies, mp_teams, mp_goalies, mp_skaters, skater_totals, injuries,
                                            *sides[0][1], *sides[1][1]])}

    async def team(self, game, side, season, window, mp_teams, mp_goalies, mp_skaters, skaters, injuries, starter):
        raw_team = game[side + 'Team']
        abbrev, tid = raw_team['abbrev'], raw_team['id']
        summary, pp, pk, roster, schedule, lineup, stat_schedule = await asyncio.gather(
            self.p.stats('team/summary', season, f' and teamId={tid}'),
            self.p.stats('team/powerplay', season, f' and teamId={tid}'),
            self.p.stats('team/penaltykill', season, f' and teamId={tid}'),
            self.p.nhl(f'roster/{abbrev}/current', 3600),
            self.p.nhl(f'club-schedule-season/{abbrev}/{game["season"]}', 600), self.p.lineup(abbrev),
            self.p.nhl(f'club-schedule-season/{abbrev}/{season}', 600))
        sources = [summary, pp, pk, roster, schedule, lineup, stat_schedule]
        game_map = {r['id']: r for r in (stat_schedule.data or {}).get('games', [])}
        pp_map = {r['gameId']: r for r in pp.data or []}
        pk_map = {r['gameId']: r for r in pk.data or []}
        rows = [{**r, **{k: pp_map.get(r['gameId'], {}).get(k) for k in ['powerPlayGoalsFor', 'ppOpportunities']},
                 **{k: pk_map.get(r['gameId'], {}).get(k) for k in ['ppGoalsAgainst', 'timesShorthanded']}}
                for r in summary.data or [] if r.get('gameDate', '') <= today_et()
                and (stat_schedule.data is None or game_map.get(r['gameId'], {}).get('gameState') in ['OFF', 'FINAL'])]
        self.p.store.save_games('nhl_team', season, rows, 'teamId')
        selected = recent(rows, window)
        ids = {str(r['gameId']) for r in selected}
        advanced = [r for r in mp_teams.data or [] if ALIASES.get(r['team'], r['team']) == abbrev and r['gameId'] in ids]
        players = []
        for group in ['forwards', 'defensemen', 'goalies']:
            for r in (roster.data or {}).get(group, []):
                players.append({'id': r['id'], 'name': f"{display_name(r.get('firstName'))} {display_name(r.get('lastName'))}",
                                'position': r.get('positionCode'), 'number': r.get('sweaterNumber'), 'headshot': r.get('headshot')})
        by_player = {}
        for row in skaters.data or []:
            by_player.setdefault(row['playerId'], []).append(row)
        for player in players:
            candidates = by_player.get(player['id'], [])
            # Summary normally aggregates traded players; use only unambiguous rows.
            s = candidates[0] if len(candidates) == 1 else {}
            player['stats'] = {k: s.get(k) for k in ['gamesPlayed', 'goals', 'assists', 'points', 'shots', 'timeOnIcePerGame']}
        skater_players = [p for p in players if p['position'] != 'G']
        usage = {}
        log_ids = [p['id'] for p in skater_players]
        log_results = await asyncio.gather(*(
            self.p.nhl(f'player/{pid}/game-log/{season}/2', 21600) for pid in log_ids))
        log_feeds = dict(zip(log_ids, log_results))
        sources.extend(log_feeds.values())
        mp_by_player = {}
        for row in mp_skaters.data or []:
            mp_by_player.setdefault(int(row['playerId']), []).append(row)
        cutoff = min(game['gameDate'], today_et())
        for player in skater_players:
            feed = log_feeds[player['id']]
            log_rows = feed.data.get('gameLog') if isinstance(feed.data, dict) and isinstance(feed.data.get('gameLog'), list) else None
            usage[normalized_name(player['name'])] = lineup_usage_windows(
                log_rows, mp_by_player.get(player['id']) if mp_skaters.data is not None else None, cutoff)
        goalie_players = [p for p in players if p['position'] == 'G']
        goalie_feed = Feed(None, 'NHL Stats', 'https://api.nhle.com/stats/rest/en/goalie/summary', error='Goalie roster unavailable')
        if goalie_players:
            clause = ' and (' + ' or '.join(f"playerId={p['id']}" for p in goalie_players) + ')'
            goalie_feed = await self.p.stats('goalie/summary', season, clause)
        sources.append(goalie_feed)
        self.p.store.save_games('nhl_goalie', season, goalie_feed.data or [], 'playerId')
        for goalie in goalie_players:
            samples = recent([r for r in goalie_feed.data or [] if r['playerId'] == goalie['id']
                              and r.get('gameDate', '') <= today_et() and (number(r.get('timeOnIce')) or 0) > 0
                              and (r['gameId'] != game['id'] or game.get('gameState') in ['OFF', 'FINAL'])], window)
            gids = {str(r['gameId']) for r in samples}
            advanced_samples = [r for r in mp_goalies.data or [] if r['playerId'] == str(goalie['id']) and r['gameId'] in gids]
            goalie['summary'] = goalie_summary(samples, advanced_samples)
        starter = {**starter, 'player_id': match_player(starter['name'], goalie_players)}
        team_injuries = []
        for group in (injuries.data or {}).get('injuries', []):
            if normalized_name(group.get('displayName')) != normalized_name(TEAM_NAMES.get(abbrev)):
                continue
            for injury in group.get('injuries', []):
                athlete = injury.get('athlete', {})
                name = athlete.get('displayName', '')
                team_injuries.append({'name': name, 'player_id': match_player(name, players), 'status': injury.get('status'),
                                      'note': injury.get('shortComment'), 'updated_at': injury.get('date')})
        logs = []
        for row in recent(rows, 'last10'):
            actual = game_map.get(row['gameId'], {})
            our_side = 'homeTeam' if row.get('homeRoad') == 'H' else 'awayTeam'
            other_side = 'awayTeam' if our_side == 'homeTeam' else 'homeTeam'
            logs.append({**row, 'result': 'W' if row.get('wins') else 'OTL' if row.get('otLosses') else 'L',
                         'scoreFor': actual.get(our_side, {}).get('score'), 'scoreAgainst': actual.get(other_side, {}).get('score')})
        return ({'team': team_info(raw_team), 'summary': team_summary(selected), 'advanced': advanced_summary(advanced),
                 'recent': logs, 'rest': rest_context((schedule.data or {}).get('games', []), game['gameDate']),
                 'starter': starter, 'goalies': goalie_players, 'roster': players, 'roster_source': roster.meta(),
                 'lineup': lineup.data, 'lineup_usage': usage, 'lineup_source': lineup.meta(), 'injuries': team_injuries,
                 'injury_source': injuries.meta(), 'stats_source': summary.meta()}, sources)
