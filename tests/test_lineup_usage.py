import asyncio

from backend.cache import Feed
from backend.player_identity import resolve_player
from backend.service import Dashboard, lineup_usage_windows


def test_perreault_alias_requires_verified_roster_id():
    gabe = {'id': 8484210, 'name': 'Gabe Perreault', 'position': 'R'}
    assert resolve_player('Gabriel Perreault', [gabe]) == gabe
    assert resolve_player('Gabriel Perreault', []) is None
    assert resolve_player('Gabriel Perreault', [gabe, {**gabe, 'id': 123, 'name': 'Gabriel Perreault'}]) is None


def test_usage_distinguishes_empty_logs_failed_logs_and_missing_5v5():
    game = {'gameId': 2025020001, 'gameDate': '2025-10-01', 'toi': '16:20'}
    absent = lineup_usage_windows(None, None, '2025-10-02')
    empty = lineup_usage_windows([game], [], '2025-10-01')
    uncovered = lineup_usage_windows([game], [], '2025-10-02')
    unavailable = lineup_usage_windows([game], None, '2025-10-02')
    for window in ['season', 'l10', 'l5']:
        assert absent[window + '_games'] is None
        assert empty[window + '_games'] == 0
        assert empty[window] is None
        assert uncovered[window] == 980
        assert uncovered[window + '_5v5_games'] == 0
        assert unavailable[window + '_5v5_games'] is None


def test_team_usage_uses_nhl_ids_for_provider_aliases():
    class Fake:
        class Store:
            def save_games(self, *args):
                pass
        store = Store()

        async def nhl(self, path, *args):
            if path.startswith('roster/'):
                data = {'forwards': [{'id': 8484210, 'firstName': {'default': 'Gabe'},
                                      'lastName': {'default': 'Perreault'}, 'positionCode': 'R'}]}
            elif path.startswith('player/'):
                data = {'gameLog': [{'gameId': 2025020001, 'gameDate': '2025-10-01', 'toi': '16:20'}]}
            else:
                data = {'games': []}
            return Feed(data, 'NHL', path)

        async def stats(self, *args, **kwargs):
            return Feed([], 'NHL', 'stats')

        async def lineup(self, *args):
            return Feed({'sections': {'Forward Line 1': ['Gabriel Perreault', 'Unknown Skater']}}, 'DFO', 'lines')

    async def run():
        empty = Feed([], 'MoneyPuck', 'mp')
        team, _ = await Dashboard(Fake()).team(
            {'season': 20252026, 'gameDate': '2025-10-02', 'awayTeam': {'id': 3, 'abbrev': 'NYR'}},
            'away', 20252026, 'season', empty, empty,
            Feed([{'playerId': '8484210', 'gameId': '2025020001', 'situation': '5on5', 'icetime': 800}], 'MP', 'skaters'),
            empty, Feed({}, 'ESPN', 'injuries'), {'name': None})
        assert team['lineup_player_ids'] == {'Gabriel Perreault': 8484210, 'Unknown Skater': None}
        assert set(team['lineup_usage']) == {'8484210'}
        assert team['lineup_usage']['8484210']['season'] == 980
        assert team['lineup_usage']['8484210']['l5_5v5'] == 800
    asyncio.run(run())


def test_matchup_routes_nhl_scoring_and_moneypuck_usage_to_correct_fields():
    from unittest.mock import Mock

    class Fake:
        store = Mock()

        async def nhl(self, path, *args):
            if path.startswith('gamecenter/'):
                data = {'id': 2026020002, 'season': 20262027, 'gameDate': '2026-10-02',
                        'awayTeam': {'id': 3, 'abbrev': 'NYR'}, 'homeTeam': {'id': 6, 'abbrev': 'BOS'}}
            elif path.startswith('roster/'):
                data = {'forwards': [{'id': 8484210, 'firstName': {'default': 'Gabe'},
                                      'lastName': {'default': 'Perreault'}, 'positionCode': 'R'}]}
            elif path.startswith('player/'):
                data = {'gameLog': [{'gameId': 2026020001, 'gameDate': '2026-10-01', 'toi': '16:20'}]}
            else:
                data = {'games': []}
            return Feed(data, 'NHL', path)

        async def stats(self, report, *args, **kwargs):
            rows = [{'playerId': 8484210, 'gamesPlayed': 1, 'goals': 0, 'assists': 2,
                     'points': 2, 'shots': 3, 'timeOnIcePerGame': 980}] if report == 'skater/summary' else []
            return Feed(rows, 'NHL Stats', report)

        async def mp(self, kind, season):
            rows = [{'playerId': '8484210', 'gameId': '2026020001', 'situation': '5on5',
                     'icetime': 800, 'I_F_goals': 0, 'I_F_points': 1}] if kind == 'skaters' else []
            return Feed(rows, 'MoneyPuck', kind)

        async def goalies(self, *args):
            return Feed([], 'DFO', 'goalies')

        async def injuries(self):
            return Feed({}, 'ESPN', 'injuries')

        async def lineup(self, *args):
            return Feed({'sections': {'Forward Line 1': ['Gabriel Perreault']}}, 'DFO', 'lines')

    async def run():
        for window in ['season', 'last10']:
            result = await Dashboard(Fake()).matchup(2026020002, window)
            for side in ['away', 'home']:
                player = result[side]['roster'][0]
                assert player['stats']['goals'] == 0
                assert player['stats']['assists'] == 2
                assert player['stats']['points'] == 2
                assert result[side]['lineup_player_ids']['Gabriel Perreault'] == player['id']
                assert result[side]['lineup_usage'][str(player['id'])]['l5_5v5'] == 800
    asyncio.run(run())
