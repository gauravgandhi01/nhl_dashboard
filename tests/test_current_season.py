import asyncio
from collections import Counter
from unittest.mock import Mock

import pytest

from backend.cache import Feed
from backend.service import Dashboard, lineup_usage_windows
from backend.players import player_windows


@pytest.mark.parametrize('unavailable', [False, True])
def test_matchup_and_slate_do_not_fall_back_or_fetch_career_history(unavailable):
    class Fake:
        store = Mock()

        def __init__(self):
            self.calls = []

        async def nhl(self, path, *args):
            self.calls.append(path)
            game = {'id': 2026020001, 'season': 20262027, 'gameDate': '2026-10-02',
                    'awayTeam': {'id': 12, 'abbrev': 'CAR'}, 'homeTeam': {'id': 6, 'abbrev': 'BOS'}}
            if path.startswith('score/'):
                data = {'games': [game]}
            elif path.startswith('gamecenter/'):
                data = game
            elif path.startswith('club-schedule-season/'):
                assert path.endswith('/20262027')
                data = {'games': []}
            elif path.startswith('roster/'):
                data = {}
            else:
                raise AssertionError(f'Unexpected historical request: {path}')
            return Feed(data, 'NHL', path)

        async def stats(self, report, season, *args, **kwargs):
            assert season == 20262027
            return Feed(None if unavailable else [], 'NHL', report)

        async def mp(self, kind, season, entities=None):
            assert season == 20262027
            return Feed(None if unavailable else [], 'MoneyPuck', kind)

        async def goalies(self, *args):
            return Feed([], 'DFO', 'goalies')

        async def injuries(self):
            return Feed({}, 'ESPN', 'injuries')

        async def lineup(self, *args):
            return Feed({}, 'DFO', 'lineup')

    async def scenario():
        fake = Fake()
        dashboard = Dashboard(fake)
        slate = await dashboard.slate('2026-10-02')
        card = slate['comparisons']['2026020001']
        assert card['season_label'] == '2026-27' and not card['previous_season']
        assert card['away']['form'] == []
        fake.calls.clear()
        detail = await dashboard.matchup(2026020001, 'last10')
        assert detail['season'] == 20262027 and not detail['previous_season']
        assert detail['away']['recent'] == []
        assert Counter(fake.calls)['club-schedule-season/CAR/20262027'] == 1
        assert Counter(fake.calls)['club-schedule-season/BOS/20262027'] == 1
    asyncio.run(scenario())


def test_player_and_lineup_windows_exclude_old_rows_and_keep_short_samples():
    old = {'gameId': 2025020001, 'gameDate': '2025-10-01', 'toi': '30:00',
           'goals': 9, 'assists': 9, 'points': 18, 'shots': 20, 'powerPlayPoints': 0}
    current = {**old, 'gameId': 2026020001, 'gameDate': '2026-10-01',
               'toi': '10:00', 'goals': 1, 'assists': 0, 'points': 1}
    result = player_windows([old, current], [], '2026-10-02')
    assert result['last10']['games'] == 1
    assert result['season']['points'] == 1
    usage = lineup_usage_windows([old, current], [], '2026-10-02')
    assert usage['l10_games'] == 1
    assert usage['season'] == 600
