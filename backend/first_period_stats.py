"""First-period normalization and aggregation, independent of provider I/O."""
from collections import defaultdict

from .providers import TEAM_NAMES, ALIASES
from .stats import number, normalized_name

WINDOWS = {'season': None, 'last5': 5, 'last10': 10}
VERSION = 1


def integer(value):
    n = number(value)
    return int(n) if n is not None and n >= 0 and n.is_integer() else None


def team_games(rows, cutoff):
    grouped = defaultdict(list)
    for row in rows:
        if row.get('gameDate', '9999') < cutoff and str(row.get('gameId', ''))[4:6] == '02':
            grouped[row['gameId']].append(row)
    games, rejected = [], 0
    names = {normalized_name(name): abbrev for abbrev, name in TEAM_NAMES.items()}
    for gid, pair in grouped.items():
        if len(pair) != 2 or {r.get('homeRoad') for r in pair} != {'H', 'R'}:
            rejected += 1
            continue
        away = next(r for r in pair if r['homeRoad'] == 'R')
        home = next(r for r in pair if r['homeRoad'] == 'H')
        fields = [integer(r.get(k)) for r in pair for k in ['period1GoalsFor', 'period1GoalsAgainst']]
        if (None in fields or away.get('teamId') == home.get('teamId')
                or away.get('gameDate') != home.get('gameDate')
                or away['period1GoalsFor'] != home['period1GoalsAgainst']
                or home['period1GoalsFor'] != away['period1GoalsAgainst']
                or any(sum(number(r.get(k)) or 0 for k in ['wins', 'losses', 'otLosses']) != 1 for r in pair)):
            rejected += 1
            continue
        game = {'gameId': gid, 'date': away['gameDate']}
        for side, row, opponent in [('away', away, home), ('home', home, away)]:
            abbrev = ALIASES.get(opponent.get('opponentTeamAbbrev'), opponent.get('opponentTeamAbbrev'))
            abbrev = abbrev or names.get(normalized_name(row.get('teamFullName')))
            game[side] = {'id': row['teamId'], 'abbrev': abbrev or str(row['teamId']),
                          'name': row.get('teamFullName'), 'gf': integer(row['period1GoalsFor']),
                          'ga': integer(row['period1GoalsAgainst'])}
        games.append(game)
    return sorted(games, key=lambda g: (g['date'], g['gameId']), reverse=True), rejected


def extract_goalies(game, pbp, official):
    if (not isinstance(pbp, dict) or pbp.get('id') != game['gameId']
            or pbp.get('gameState') not in ['OFF', 'FINAL'] or not isinstance(pbp.get('plays'), list)):
        raise ValueError('Completed play-by-play unavailable')
    team_ids = {game[s]['id'] for s in ['away', 'home']}
    if {pbp.get(s + 'Team', {}).get('id') for s in ['away', 'home']} != team_ids:
        raise ValueError('Play-by-play identity mismatch')
    abbrevs = {game[s]['abbrev']: game[s]['id'] for s in ['away', 'home']}
    entries, starters, full_game_players = {}, {}, defaultdict(set)
    for r in official:
        tid = abbrevs.get(ALIASES.get(r.get('teamAbbrev'), r.get('teamAbbrev')))
        pid = r.get('playerId')
        if tid is None or pid is None:
            continue
        full_game_players[tid].add(pid)
        if r.get('gamesStarted') == 1:
            if tid in starters:
                raise ValueError('Ambiguous starter records')
            starters[tid] = pid
        entries[pid] = {'playerId': pid, 'teamId': tid, 'name': r.get('goalieFullName', str(pid)),
                        'gameId': game['gameId'], 'date': game['date'], 'sa': 0, 'ga': 0, 'saves': 0,
                        'starter': r.get('gamesStarted') == 1, 'partial': False}
    if set(starters) != team_ids:
        raise ValueError('Starter records unavailable')
    seen = set(starters.values())
    counted_goals = defaultdict(int)
    bad_teams = set()
    first_period = [p for p in pbp['plays'] if p.get('periodDescriptor', {}).get('number') == 1]
    if not any(p.get('typeDescKey') == 'period-end' for p in first_period):
        raise ValueError('First period is incomplete')
    for play in first_period:
        event = play.get('typeDescKey')
        if event not in ['shot-on-goal', 'goal']:
            continue
        d = play.get('details', {})
        shooting = d.get('eventOwnerTeamId')
        if shooting not in team_ids:
            raise ValueError('Unknown shooting team')
        defending = next(t for t in team_ids if t != shooting)
        if event == 'goal':
            counted_goals[shooting] += 1
        pid = d.get('goalieInNetId')
        situation = str(play.get('situationCode', ''))
        defending_home = defending == pbp['homeTeam']['id']
        empty_net = d.get('emptyNet') is True or (len(situation) == 4 and situation[3 if defending_home else 0] == '0')
        if pid is None:
            if not (event == 'goal' and empty_net):
                bad_teams.add(defending)
            continue
        if pid not in entries or entries[pid]['teamId'] != defending or empty_net:
            bad_teams.add(defending)
            continue
        seen.add(pid)
        entries[pid]['sa'] += 1
        entries[pid]['ga' if event == 'goal' else 'saves'] += 1
    for side in ['away', 'home']:
        if counted_goals[game[side]['id']] != game[side]['gf']:
            raise ValueError('First-period goals disagree with NHL period totals')
    warnings = []
    for tid in team_ids:
        participants = [pid for pid in seen if entries[pid]['teamId'] == tid]
        if len(participants) > 1:
            for pid in participants:
                entries[pid]['partial'] = True
        if full_game_players[tid] - seen:
            warnings.append('Relief participation without a first-period shot cannot be verified')
        if tid in bad_teams:
            warnings.append('Unattributed first-period shot events; affected goalie data excluded')
    return {'goalies': [entries[pid] for pid in seen if entries[pid]['teamId'] not in bad_teams],
            'warnings': sorted(set(warnings)), 'complete': not bad_teams}


def ratio(n, d, scale=1):
    return n / d * scale if d else None


def summarize(rows, goalie=False):
    n = len(rows)
    if goalie:
        sa, ga, saves = (sum(r[k] for r in rows) for k in ['sa', 'ga', 'saves'])
        allow = sum(r['ga'] >= 1 for r in rows)
        return {'games': n, 'ga_total': ga if n else None, 'ga_pg': ratio(ga, n),
                'sa': sa if n else None, 'saves': saves if n else None, 'sv': ratio(saves, sa),
                'allow_count': allow if n else None, 'allow_pct': ratio(allow, n, 100),
                'partial_games': sum(r['partial'] for r in rows)}
    gf, ga = (sum(r[k] for r in rows) for k in ['gf', 'ga'])
    hits = sum(r['gf'] + r['ga'] >= 2 for r in rows)
    return {'games': n, 'gf_pg': ratio(gf, n), 'ga_pg': ratio(ga, n),
            'combined_pg': ratio(gf + ga, n), 'hits': hits if n else None, 'hit_pct': ratio(hits, n, 100)}


def windows(rows, goalie=False):
    ordered = sorted(rows, key=lambda r: (r['date'], r['gameId']), reverse=True)
    return {key: summarize(ordered[:count] if count else ordered, goalie) for key, count in WINDOWS.items()}
