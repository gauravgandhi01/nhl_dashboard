from __future__ import annotations

import math
import unicodedata
from datetime import date


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def total(rows, key):
    values = [number(r.get(key)) for r in rows]
    return sum(values) if values and all(v is not None for v in values) else None


def ratio(a, b, scale=1):
    return a / b * scale if a is not None and b is not None and b > 0 else None


def recent(rows, window):
    ordered = sorted(rows, key=lambda r: (str(r.get('gameDate', '')), str(r.get('gameId', ''))), reverse=True)
    return ordered[:10] if window == 'last10' else ordered


def normalized_name(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value or '').lower() if c.isalnum())


def match_player(name, players):
    matches = [p for p in players if normalized_name(p['name']) == normalized_name(name)]
    return matches[0]['id'] if len(matches) == 1 else None


def team_summary(rows):
    n = len(rows)
    return {
        'games': n,
        'wins': total(rows, 'wins'), 'losses': total(rows, 'losses'), 'ot_losses': total(rows, 'otLosses'),
        'gf': ratio(total(rows, 'goalsFor'), n), 'ga': ratio(total(rows, 'goalsAgainst'), n),
        'sf': ratio(total(rows, 'shotsForPerGame'), n), 'sa': ratio(total(rows, 'shotsAgainstPerGame'), n),
        'pp': ratio(total(rows, 'powerPlayGoalsFor'), total(rows, 'ppOpportunities'), 100),
        'pk': None if ratio(total(rows, 'ppGoalsAgainst'), total(rows, 'timesShorthanded')) is None
              else (1 - ratio(total(rows, 'ppGoalsAgainst'), total(rows, 'timesShorthanded'))) * 100,
    }


def advanced_summary(rows):
    return {'games': len(rows),
            'xgf60': ratio(total(rows, 'xGoalsFor'), total(rows, 'iceTime'), 3600),
            'xga60': ratio(total(rows, 'xGoalsAgainst'), total(rows, 'iceTime'), 3600),
            'xgf_pct': share(rows, 'xGoalsFor', 'xGoalsAgainst'),
            'cf_pct': share(rows, 'shotAttemptsFor', 'shotAttemptsAgainst')}


def share(rows, a, b):
    x, y = total(rows, a), total(rows, b)
    return ratio(x, x + y, 100) if x is not None and y is not None else None


def goalie_summary(rows, advanced):
    xg, goals = total(advanced, 'xGoals'), total(advanced, 'goals')
    return {'games': len(rows), 'sv': ratio(total(rows, 'saves'), total(rows, 'shotsAgainst')),
            'gaa': ratio(total(rows, 'goalsAgainst'), total(rows, 'timeOnIce'), 3600),
            'gsax': xg - goals if xg is not None and goals is not None else None,
            'advanced_games': len(advanced)}


def season_label(season):
    return f'{str(season)[:4]}-{str(season)[6:]}'


def card_team_stats(row):
    row = row or {}
    return {'games': number(row.get('gamesPlayed')), 'gf': number(row.get('goalsForPerGame')),
            'ga': number(row.get('goalsAgainstPerGame')), 'sf': number(row.get('shotsForPerGame')),
            'pp': number(row['powerPlayPct']) * 100 if number(row.get('powerPlayPct')) is not None else None}


def last_five(games, team_id):
    completed = [g for g in games if g.get('gameType') == 2 and g.get('gameState') in ['OFF', 'FINAL']]
    completed.sort(key=lambda g: (g.get('gameDate', ''), g['id']), reverse=True)
    form = []
    for game in completed[:5]:
        ours = 'homeTeam' if game['homeTeam']['id'] == team_id else 'awayTeam'
        theirs = 'awayTeam' if ours == 'homeTeam' else 'homeTeam'
        gf, ga = game[ours].get('score'), game[theirs].get('score')
        if gf is None or ga is None:
            continue
        result = 'W' if gf > ga else 'OTL' if game.get('gameOutcome', {}).get('lastPeriodType') in ['OT', 'SO'] else 'L'
        form.append({'result': result, 'date': game['gameDate'], 'opponent': game[theirs]['abbrev'], 'home': ours == 'homeTeam'})
    return list(reversed(form))


def card_goalie(starter, roster, rows, advanced):
    players = [{'id': p['id'], 'name': f"{p.get('firstName', {}).get('default', '')} {p.get('lastName', {}).get('default', '')}"}
               for p in roster]
    matched = match_player(starter.get('name'), players) if starter.get('name') else None
    by_id = {r['playerId']: r for r in rows}
    candidates = [p for p in players if p['id'] in by_id and (number(by_id[p['id']].get('gamesPlayed')) or 0) > 0]
    chosen = next((p for p in players if p['id'] == matched), None)
    if starter.get('name') and chosen is None:
        return {'name': starter['name'], 'basis': starter['status'], 'stats': {}, 'advanced_games': 0}
    if chosen is None:
        chosen = max(candidates, key=lambda p: number(by_id[p['id']].get('gamesPlayed')) or 0, default=None)
    if chosen is None:
        return {'name': None, 'basis': 'Not announced', 'stats': {}, 'advanced_games': 0}
    row = by_id.get(chosen['id'], {})
    samples = [r for r in advanced if str(r['playerId']) == str(chosen['id'])]
    xg, goals = total(samples, 'xGoals'), total(samples, 'goals')
    return {'name': chosen['name'], 'basis': starter['status'] if matched else 'Roster leader',
            'stats': {'games': number(row.get('gamesPlayed')), 'sv': number(row.get('savePct')),
                      'gaa': number(row.get('goalsAgainstAverage')), 'gsax': xg - goals if xg is not None and goals is not None else None},
            'advanced_games': len(samples)}


def season_for_date(value):
    year = int(value[:4]) - (int(value[5:7]) < 7)
    return year * 10000 + year + 1


def in_season(game_id, season):
    return str(game_id)[:4] == str(season)[:4]


def rest_context(games, selected):
    # Scheduled intervening games count for future rest, even if not played yet.
    prior = [g for g in games if g.get('gameDate', '') < selected and g.get('gameScheduleState') != 'PPD']
    if not prior:
        return {'days': None, 'back_to_back': False}
    previous = max(g['gameDate'] for g in prior)
    days = max(0, (date.fromisoformat(selected) - date.fromisoformat(previous)).days - 1)
    return {'days': days, 'back_to_back': days == 0}
