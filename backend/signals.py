"""Pregame flags, independent of the statistical baseline displayed on cards."""
from datetime import date, timedelta

from .stats import number


def career_nhl_games(player):
    if not isinstance(player, dict) or not isinstance(player.get('careerTotals'), dict):
        return None
    totals = player['careerTotals']
    games = 0
    observed = False
    for kind in ('regularSeason', 'playoffs'):
        row = totals.get(kind)
        if row is None or row == {}:
            continue
        if not isinstance(row, dict):
            return None
        count = number(row.get('gamesPlayed'))
        if count is None or count < 0 or not count.is_integer():
            return None
        games += int(count)
        observed = True
    if observed:
        return games
    # A complete rookie profile can have minor-league rows but no NHL career totals.
    seasons = player.get('seasonTotals')
    if isinstance(seasons, list) and all(isinstance(r, dict) and r.get('leagueAbbrev')
                                       and r['leagueAbbrev'] != 'NHL' for r in seasons):
        return 0
    return None


def matchup_signals(game, team_id, schedule, starter, career_gp=None):
    if game.get('gameScheduleState') in ('PPD', 'CNCL', 'CANCELLED', 'CANCELED'):
        return []
    selected = date.fromisoformat(game['gameDate'])
    yesterday = (selected - timedelta(days=1)).isoformat()
    flags = []
    team_games = [g for g in schedule or [] if team_id in (g.get('awayTeam', {}).get('id'), g.get('homeTeam', {}).get('id'))]
    previous_night = [g for g in team_games if g.get('gameDate') == yesterday
                      and g.get('id') != game['id']
                      and g.get('gameScheduleState') not in ('PPD', 'CNCL', 'CANCELLED', 'CANCELED')
                      and g.get('gameState') in ('OFF', 'FINAL', 'LIVE', 'CRIT', 'PRE', 'FUT')]
    if previous_night:
        flags.append({'id': 'back_to_back', 'label': 'B2B',
                      'detail': f'Second night of a back-to-back: games on {yesterday} and {selected.isoformat()}. Based on the current schedule.'})
    if starter.get('status') == 'Confirmed' and starter.get('name') and career_gp is not None and 0 <= career_gp < 5:
        flags.append({'id': 'inexperienced_goalie', 'label': f'Goalie {career_gp} NHL GP',
                      'detail': f"Confirmed starter {starter['name']} has {career_gp} NHL career appearances (regular season plus playoffs; preseason excluded)."})

    completed = sorted([g for g in team_games if g.get('season') == game.get('season')
                        and g.get('gameType') == 2 and g.get('gameState') in ('OFF', 'FINAL')
                        and g.get('gameDate', '') < game['gameDate']],
                       key=lambda g: (g['gameDate'], g['id']), reverse=True)
    outcomes = []
    for prior in completed:
        ours, theirs = ('homeTeam', 'awayTeam') if prior['homeTeam']['id'] == team_id else ('awayTeam', 'homeTeam')
        gf, ga = number(prior[ours].get('score')), number(prior[theirs].get('score'))
        if gf is None or ga is None or gf == ga:
            # Do not infer a winning record or a continuous streak across unknown results.
            return flags
        outcomes.append('W' if gf > ga else 'OTL' if prior.get('gameOutcome', {}).get('lastPeriodType') in ('OT', 'SO') else 'L')
    wins = outcomes.count('W')
    losses = outcomes.count('L')
    ot_losses = outcomes.count('OTL')
    streak = 0
    for outcome in outcomes:
        if outcome == 'W':
            break
        streak += 1
    if wins > losses + ot_losses and streak > 2:
        flags.append({'id': 'losing_streak', 'label': f'Winning team / L{streak}',
                      'detail': f'Current-season regular-season record {wins}-{losses}-{ot_losses}; {streak} consecutive losses. Wins exceed all losses, including OT/SO. Results before this matchup only.'})
    return flags
