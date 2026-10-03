import asyncio

from backend.cache import Feed
from backend.providers import TEAM_NAMES
from backend.service import Dashboard
from backend.stats import league_ranks


def test_ranks_share_ties_reverse_against_stats_and_exclude_missing_samples():
    teams = {
        'A': {'games': 2, 'gf': 4, 'ga': 2},
        'B': {'games': 2, 'gf': 4, 'ga': 3},
        'C': {'games': 2, 'gf': 2, 'ga': 1},
        'D': {'games': 0, 'gf': 99, 'ga': 0},
        'E': {'games': 2, 'gf': None, 'ga': float('nan')},
    }
    ranks = league_ranks(teams, ['gf', 'ga'], lower={'ga'})
    assert [ranks[t]['gf']['rank'] for t in teams] == [1, 1, 3, None, None]
    assert [ranks[t]['ga']['rank'] for t in teams] == [2, 3, 1, None, None]
    assert ranks['A']['gf']['eligible'] == 3


def test_slate_ranks_include_all_32_teams_not_only_the_two_playing():
    class Fake:
        async def nhl(self, path, *args):
            data = {'games': [{'id': 2026020017, 'season': 20262027, 'gameDate': '2026-10-02',
                              'awayTeam': {'id': 3, 'abbrev': 'NYR'},
                              'homeTeam': {'id': 17, 'abbrev': 'DET'}}]} if path.startswith('score/') else {'games': []}
            return Feed(data, 'NHL', path)

        async def goalies(self, *args):
            return Feed([], 'DFO', 'goalies')

        async def stats(self, report, season, **kwargs):
            assert season == 20262027
            assert kwargs['is_game'] is False
            rows = [{'teamId': i, 'gamesPlayed': 2, 'goalsForPerGame': i,
                     'goalsAgainstPerGame': i, 'shotsForPerGame': i, 'powerPlayPct': i / 100}
                    for i in range(1, 33)] if report == 'team/summary' else []
            return Feed(rows, 'NHL', report)

        async def mp(self, kind, season):
            rows = [{'team': team, 'gameId': '2026020001', 'xGoalsFor': i, 'xGoalsAgainst': 33 - i,
                     'iceTime': 3600, 'shotAttemptsFor': i, 'shotAttemptsAgainst': 33 - i}
                    for i, team in enumerate(TEAM_NAMES, 1)] if kind == 'teams' else []
            return Feed(rows, 'MoneyPuck', kind)

    result = asyncio.run(Dashboard(Fake()).slate('2026-10-02'))
    card = result['comparisons']['2026020017']
    assert card['away']['ranks']['sf'] == {'rank': 30, 'eligible': 32}
    assert card['home']['ranks']['sf'] == {'rank': 16, 'eligible': 32}
    assert card['away']['ranks']['ga']['rank'] == 3
    assert card['home']['ranks']['ga']['rank'] == 17
    assert card['away']['ranks']['xgf_pct']['eligible'] == 32
    assert card['away']['ranks']['xgf_pct']['rank'] == 32 - list(TEAM_NAMES).index('NYR')
