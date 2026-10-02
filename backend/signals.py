"""Pregame flags, independent of the statistical baseline displayed on cards."""
from datetime import date, timedelta

from .stats import number


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
        flags.append({'id': 'back_to_back', 'label': 'B2B',
                      'detail': f'Second night of a back-to-back: games on {yesterday} and {selected.isoformat()}. Based on the current schedule.'})
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
