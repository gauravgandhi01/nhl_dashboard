"""Pregame flags, independent of the statistical baseline displayed on cards."""
from datetime import date, timedelta

from .stats import number


def team_label(team):
    name = team.get('abbrev') or team.get('placeName') or team.get('name') or team.get('id')
    return name.get('default', '') if isinstance(name, dict) else str(name or '')


def previous_game_detail(prior, team_id):
    ours, theirs = ('homeTeam', 'awayTeam') if prior.get('homeTeam', {}).get('id') == team_id else ('awayTeam', 'homeTeam')
    marker = 'vs' if ours == 'homeTeam' else '@'
    opponent = team_label(prior.get(theirs, {}))
    gf, ga = number(prior.get(ours, {}).get('score')), number(prior.get(theirs, {}).get('score'))
    if gf is None or ga is None:
        return f'{marker} {opponent}: scheduled'
    return f'{marker} {opponent}: {int(gf)}-{int(ga)}'


def matchup_signals(game, team_id, schedule):
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
        prior = sorted(previous_night, key=lambda g: g.get('startTimeUTC', ''))[-1]
        flags.append({'id': 'back_to_back', 'label': 'B2B',
                      'detail': previous_game_detail(prior, team_id)})
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
