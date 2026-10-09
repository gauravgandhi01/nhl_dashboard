import asyncio

import pytest

from backend.cache import Feed
from backend.service import Dashboard


@pytest.mark.parametrize('unavailable', [False, True])
def test_card_form_uses_actual_starters_by_game_and_team(unavailable):
    class Fake:
        def __init__(self):
            self.history_calls = []

        async def nhl(self, path, *args):
            game = {'id': 2026020010, 'season': 20262027, 'gameDate': '2026-10-09',
                    'gameType': 2, 'gameState': 'FUT',
                    'awayTeam': {'id': 1, 'abbrev': 'COL', 'score': 2},
                    'homeTeam': {'id': 2, 'abbrev': 'DAL', 'score': 3}}
            if path.startswith('score/'):
                return Feed({'games': [game]}, 'NHL', path)
            if path.startswith('club-schedule-season/'):
                return Feed({'games': [{**game, 'id': 2026020000 + i, 'gameDate': f'2026-10-0{i}',
                                        'gameState': 'OFF'} for i in range(1, 7)]}, 'NHL', path)
            return Feed({}, 'NHL', path)

        async def stats(self, report, season, extra='', is_game=True):
            if not is_game:
                return Feed([], 'NHL Stats', report)
            assert report == 'goalie/summary' and season == 20262027
            self.history_calls.append(extra)
            rows = [
                {'gameId': 2026020006, 'teamAbbrev': 'COL', 'gamesStarted': 0, 'goalieFullName': 'Away Relief'},
                {'gameId': 2026020006, 'teamAbbrev': 'COL', 'gamesStarted': 1, 'goalieFullName': 'Away Starter'},
                {'gameId': 2026020006, 'teamAbbrev': 'DAL', 'gamesStarted': 1, 'goalieFullName': 'Home Starter'},
                {'gameId': 2026020005, 'teamAbbrev': 'COL', 'gamesStarted': 0, 'goalieFullName': 'Only Relief'},
                {'gameId': 2026020004, 'teamAbbrev': 'COL', 'gamesStarted': 1, 'goalieFullName': 'Ambiguous One'},
                {'gameId': 2026020004, 'teamAbbrev': 'COL', 'gamesStarted': 1, 'goalieFullName': 'Ambiguous Two'},
                {'gameId': 2026020003, 'teamAbbrev': 'COL', 'gamesStarted': 1, 'goalieFullName': None},
                {'gameId': 2026020002, 'teamAbbrev': 'COL', 'gamesStarted': 1, 'goalieFullName': 'Earlier Starter'},
            ]
            return Feed(None if unavailable else rows, 'NHL Stats', 'historical-goalies')

        async def mp(self, *args):
            return Feed([], 'MoneyPuck', 'mp')

        async def goalies(self, *args):
            return Feed([], 'DFO', 'goalies')

    fake = Fake()
    result = asyncio.run(Dashboard(fake).slate('2026-10-09'))
    card = result['comparisons']['2026020010']
    away, home = card['away']['form'], card['home']['form']
    assert len(away) == len(home) == 5
    assert all((entry['goals_for'], entry['goals_against']) == (2, 3) for entry in away)
    assert all((entry['goals_for'], entry['goals_against']) == (3, 2) for entry in home)
    assert [entry['game_id'] for entry in away] == list(range(2026020002, 2026020007))
    assert len(fake.history_calls) == 1
    assert 'gameId=2026020001' not in fake.history_calls[0]
    assert all(fake.history_calls[0].count(f'gameId={gid}') == 1 for gid in range(2026020002, 2026020007))
    assert any(source['url'] == 'historical-goalies' for source in result['sources'])
    if unavailable:
        assert all(entry['starting_goalie'] is None for entry in away + home)
    else:
        assert [entry['starting_goalie'] for entry in away] == ['Earlier Starter', None, None, None, 'Away Starter']
        assert [entry['starting_goalie'] for entry in home] == [None, None, None, None, 'Home Starter']
