import asyncio
import io
import zipfile
from unittest.mock import Mock

import pytest

from backend.cache import Feed, Store
from backend.players import appearance_log, player_windows, players_dashboard
from backend.providers import parse_mp_skaters


def logs(n=12):
    return [{'gameId': 2025020000 + i, 'gameDate': f'2025-11-{i:02}', 'toi': '10:00',
             'goals': 1, 'assists': 1, 'points': 2, 'shots': 3, 'powerPlayPoints': 1}
            for i in range(1, n + 1)]


def advanced(rows):
    return [{'gameId': str(r['gameId']), 'icetime': 600, 'I_F_shotAttempts': 4,
             'I_F_points': 2, 'I_F_shotsOnGoal': 3, 'I_F_xGoals': .5, 'I_F_highDangerShots': 1}
            for r in rows]


def test_appearance_log_matches_windows_and_keeps_missing_values():
    rows = logs(3)
    rows[1]['shots'] = None
    rows.append({**rows[0], 'gameId': 2025030001, 'gameDate': '2025-11-20', 'shots': 9})
    rows.append({**rows[0], 'gameId': 2025020099, 'gameDate': '2025-11-12', 'shots': 8})
    series = appearance_log(rows, '2025-11-12')
    windows = player_windows(rows, None, '2025-11-12')
    assert series is not None
    assert len(series['points']) == windows['season']['games'] == 3
    assert series['points'] == [2, 2, 2]
    assert series['shots'] == [3, None, 3]
    assert appearance_log(None, '2025-11-12') is None
    assert appearance_log([], '2025-11-12') == {'goals': [], 'assists': [], 'points': [], 'shots': []}


def test_windows_appearances_cutoff_and_partial_coverage():
    result = player_windows(logs(), advanced(logs(9)), '2025-11-12')
    assert result['season']['games'] == 11
    assert result['last5']['games'] == 5
    assert result['last10']['games'] == 10
    assert result['last5']['advanced_games'] == 3
    assert result['last5']['points'] == 10
    assert result['last5']['attempts'] == 12
    assert result['last5']['attempts_pg'] == 4
    assert result['last5']['attempts60'] == 24
    assert result['last5']['point_games_pct'] == 100


def test_rates_use_summed_ice_time_not_mean_rates():
    rows = logs(2)
    mp = advanced(rows)
    mp[1]['icetime'] = 1200
    result = player_windows(rows, mp, '2026-01-01')['season']
    assert result['points60'] == 8
    assert result['attempts'] == 8
    assert result['attempts_pg'] == 4
    assert result['attempts60'] == 16
    assert result['advanced_minutes'] == 30


def test_unavailable_is_not_zero_and_small_samples_are_explicit():
    result = player_windows(logs(2), None, '2026-01-01')['last10']
    assert result['games'] == 2
    assert result['advanced_games'] is None
    assert result['attempts_pg'] is None
    assert result['ixg60'] is None
    missing = player_windows(None, [], '2026-01-01')['season']
    assert missing['games'] is None and missing['points'] is None
    debut = player_windows([], [], '2026-01-01')['season']
    assert debut['games'] == 0 and debut['points_pg'] is None


def test_duplicate_mp_rows_unresolved_and_playoffs_excluded():
    rows = logs(2) + [{**logs(1)[0], 'gameId': 2025030001}]
    mp = advanced(rows)
    result = player_windows(rows, mp + [mp[0]], '2026-01-01')['season']
    assert result['games'] == 2
    assert result['advanced_games'] == 1
    assert result['attempts_pg'] == 4


def test_missing_field_does_not_become_zero():
    mp = advanced(logs(2))
    del mp[0]['I_F_xGoals']
    result = player_windows(logs(2), mp, '2026-01-01')['season']
    assert result['ixg60'] is None
    assert result['attempts_pg'] == 4
    assert result['attempts60'] == 24


def test_mp_parser_strength_and_game_type():
    body = 'playerId,gameId,icetime,I_F_shotAttempts,I_F_points,I_F_shotsOnGoal,I_F_xGoals,I_F_highDangerShots,situation\n'
    body += '1,2025020001,600,4,2,3,.5,1,all\n1,2025020001,400,3,1,2,.2,1,5on5\n1,2025030001,600,4,2,3,.5,1,all\n'
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, 'w') as z:
        z.writestr('2025.csv', body)
    assert len(parse_mp_skaters(raw.getvalue())) == 2
    with pytest.raises(ValueError):
        parse_mp_skaters(b'broken')


class Fake:
    store = Mock()
    no_games = False
    unavailable = False
    postponed = False
    league_missing = False

    async def nhl(self, path, *args):
        if path.startswith('score'):
            data = None if self.unavailable else {'games': [] if self.no_games else [{
                'id': 2026010001, 'season': 20262027, 'gameDate': '2026-09-26', 'startTimeUTC': '2026-09-26T23:00:00Z',
                'gameScheduleState': 'PPD' if self.postponed else 'OK',
                'awayTeam': {'id': 1, 'abbrev': 'NJD'}, 'homeTeam': {'id': 2, 'abbrev': 'NYI'}}]}
        elif path.startswith('roster'):
            data = {'forwards': [{'id': 1, 'firstName': {'default': 'Test'}, 'lastName': {'default': 'Skater'}, 'positionCode': 'C'}], 'goalies': [{'id': 2}]}
        else:
            assert '/20262027/2' in path
            data = {'gameLog': logs()}
        return Feed(data, 'NHL', path, '2026-09-26T00:00:00Z')

    async def stats(self, *args, **kwargs):
        raise AssertionError('No league-wide request needed to select a season')

    async def mp(self, kind, season):
        assert season == 20262027
        return Feed(None, 'MoneyPuck', 'mp')


def test_service_current_season_ids_and_isolated_provider_failure():
    result = asyncio.run(players_dashboard(Fake(), '2026-09-26'))
    assert result['periods'] == [{'season_label': '2026-27', 'previous_season': False}]
    assert len(result['players']) == 2
    assert result['players'][0]['id'] == 1
    assert result['players'][0]['windows']['season']['games'] == 0
    assert result['players'][0]['windows']['season']['attempts60'] is None
    assert result['players'][0]['opponent_logo'] is None
    assert result['players'][0]['advanced_source']['status'] == 'unavailable'
    assert result['players'][0]['log'] == {'goals': [], 'assists': [], 'points': [], 'shots': []}


@pytest.mark.parametrize('flag', ['no_games', 'postponed', 'unavailable'])
def test_empty_schedule_and_outage(flag):
    fake = Fake()
    setattr(fake, flag, True)
    result = asyncio.run(players_dashboard(fake, '2026-09-26'))
    assert result['players'] == []
    assert bool(result['error']) == (flag == 'unavailable')


def test_season_outage_does_not_assume_previous_season():
    fake = Fake()
    fake.league_missing = True
    result = asyncio.run(players_dashboard(fake, '2026-09-26'))
    assert not result['periods'][0]['previous_season']


def test_dashboard_snapshot_cache_reuses_built_payload(tmp_path):
    class CachedFake(Fake):
        def __init__(self):
            self.store = Store(tmp_path / 'players.sqlite3')
            self.score_calls = 0

        async def nhl(self, path, *args):
            if path.startswith('score'):
                self.score_calls += 1
            return await super().nhl(path, *args)

    async def scenario():
        fake = CachedFake()
        first = await players_dashboard(fake, '2026-09-26')
        second = await players_dashboard(fake, '2026-09-26')
        assert fake.score_calls == 1
        assert first['players'] == second['players']
        assert first['cache_status'] == 'fresh'
        assert second['cache_status'] == 'cached'
        import json
        legacy = {**first, 'version': 1, 'periods': [{'season_label': '2025-26', 'previous_season': True}]}
        fake.store.db.execute('UPDATE player_dashboards SET body=?', (json.dumps(legacy),))
        fake.store.db.commit()
        rebuilt = await players_dashboard(fake, '2026-09-26')
        assert fake.score_calls == 2
        assert rebuilt['periods'][0]['season_label'] == '2026-27'
        await fake.store.close()
    asyncio.run(scenario())
