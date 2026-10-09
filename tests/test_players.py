import asyncio
import io
import zipfile
from unittest.mock import Mock

import pytest

from backend.cache import Feed, Store
from backend.players import LeaguePlayers, appearance_log, ensure_player_table, player_windows, players_dashboard, recent_games
from backend.providers import parse_mp_skaters


def logs(n=12):
    return [{'gameId': 2025020000 + i, 'gameDate': f'2025-11-{i:02}', 'toi': '10:00',
             'goals': 1, 'assists': 1, 'points': 2, 'shots': 3, 'powerPlayPoints': 1}
            for i in range(1, n + 1)]


def advanced(rows):
    return [{'gameId': str(r['gameId']), 'icetime': 600, 'I_F_shotAttempts': 4,
             'I_F_points': 2, 'I_F_shotsOnGoal': 3, 'I_F_xGoals': .5, 'I_F_highDangerShots': 1}
            for r in rows]


EMPTY_LOG = {'goals': [], 'assists': [], 'points': [], 'shots': [], 'opponents': [], 'home': []}


def test_recent_games_order_limit_and_appearance_cutoff():
    rows = logs(12)
    rows += [dict(rows[0]), {**rows[-1], 'gameId': 2025030001},
             {**rows[-1], 'gameId': 2024020001},
             {**rows[-1], 'gameId': 2025020099, 'gameDate': '2025-11-11', 'toi': '0:00'}]
    result = recent_games(rows, None, '2025-11-12', 20252026)
    assert [g['game_id'] for g in result] == [2025020011, 2025020010, 2025020009, 2025020008, 2025020007]
    assert [g['date'] for g in result] == [f'2025-11-{i:02}' for i in range(11, 6, -1)]
    assert result[0]['toi'] == 600
    assert result[0]['shot_attempts'] is None
    assert result[0]['toi_5v5'] is None
    assert len(recent_games(logs(2), [], '2025-11-12')) == 2
    assert recent_games([], [], '2025-11-12') == []
    assert recent_games(None, [], '2025-11-12') is None


def test_recent_games_strength_matching_missing_and_zero_values():
    rows = logs(3)
    rows[2].update(goals=0, assists=0, points=0, shots=0, toi='12:34', opponentAbbrev='BOS', homeRoad='R')
    rows[1].update(shots=None, opponentAbbrev='MTL', homeRoad='H')
    mp = [
        {'gameId': str(rows[2]['gameId']), 'situation': 'all', 'icetime': 754, 'I_F_shotAttempts': 0},
        {'gameId': rows[2]['gameId'], 'situation': '5on5', 'icetime': 0, 'I_F_shotAttempts': 9},
        {'gameId': rows[1]['gameId'], 'situation': '5on5', 'icetime': 501},
        {'gameId': rows[0]['gameId'], 'situation': 'all', 'I_F_shotAttempts': 7},
        {'gameId': 2025020099, 'situation': 'all', 'I_F_shotAttempts': 100},
    ]
    result = recent_games(rows, mp, '2025-11-12')
    assert result[0] == {'game_id': 2025020003, 'date': '2025-11-03', 'opponent': 'BOS', 'home': False,
                         'goals': 0, 'assists': 0, 'points': 0, 'shots': 0, 'toi': 754,
                         'toi_5v5': 0, 'shot_attempts': 0}
    assert result[1]['home'] is True
    assert result[1]['shots'] is None
    assert result[1]['toi_5v5'] == 501
    assert result[1]['shot_attempts'] is None
    assert result[2]['shot_attempts'] == 7
    assert result[2]['opponent'] is None and result[2]['home'] is None
    duplicate = recent_games(rows, mp + mp[:2], '2025-11-12')
    assert len(duplicate) == 3
    assert duplicate[0]['toi_5v5'] is None and duplicate[0]['shot_attempts'] is None
    assert duplicate[1] == result[1]


def test_appearance_log_matches_windows_and_keeps_missing_values():
    rows = logs(3)
    rows[1]['shots'] = None
    rows[1]['opponentAbbrev'] = 'BOS'
    rows[1]['homeRoad'] = 'R'
    rows[2]['opponentAbbrev'] = 'MTL'
    rows[2]['homeRoad'] = 'H'
    rows.append({**rows[0], 'gameId': 2025030001, 'gameDate': '2025-11-20', 'shots': 9})
    rows.append({**rows[0], 'gameId': 2025020099, 'gameDate': '2025-11-12', 'shots': 8,
                 'opponentAbbrev': 'TOR', 'homeRoad': 'H'})
    series = appearance_log(rows, '2025-11-12')
    windows = player_windows(rows, None, '2025-11-12')
    assert series is not None
    assert len(series['points']) == windows['season']['games'] == 3
    assert series['points'] == [2, 2, 2]
    assert series['shots'] == [3, None, 3]
    assert series['opponents'] == ['MTL', 'BOS', None]
    assert series['home'] == [True, False, None]
    assert appearance_log(None, '2025-11-12') is None
    assert appearance_log([], '2025-11-12') == EMPTY_LOG


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

    async def mp(self, kind, season, entities=None):
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
    assert result['players'][0]['log'] == EMPTY_LOG
    assert result['players'][0]['recent_games'] == []


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


def test_scope_migration_keeps_tonight_rows(tmp_path):
    from backend.cache import Store
    store = Store(tmp_path / 'migrate.sqlite3')
    store.db.execute('DROP TABLE IF EXISTS player_dashboards')
    store.db.execute('''CREATE TABLE player_dashboards (
        date TEXT PRIMARY KEY, body TEXT, fetched REAL, error TEXT)''')
    store.db.execute(
        'INSERT INTO player_dashboards VALUES (?, ?, ?, NULL)',
        ('2026-09-26', '{"version":3}', 1))
    store.db.commit()
    ensure_player_table(store.db)
    assert store.db.execute('SELECT date, scope FROM player_dashboards').fetchall() == [('2026-09-26', 'tonight')]
    asyncio.run(store.close())


class LeagueFake:
    def __init__(self, store, schedule=True, duplicate=False):
        self.store = store
        self.schedule = schedule
        self.duplicate = duplicate
        self.log_ids = []
        self.score_calls = 0

    async def nhl(self, path, *args, **kwargs):
        if path.startswith('score'):
            self.score_calls += 1
            if not self.schedule:
                return Feed(None, 'NHL', path, error='down')
            return Feed({'games': [{
                'id': 2026010001, 'season': 20262027, 'gameDate': '2026-09-26',
                'startTimeUTC': '2026-09-26T23:00:00Z', 'gameScheduleState': 'OK',
                'awayTeam': {'id': 1, 'abbrev': 'NJD', 'darkLogo': 'njd.svg'},
                'homeTeam': {'id': 2, 'abbrev': 'NYI', 'darkLogo': 'nyi.svg'}}]}, 'NHL', path, '2026-09-26T00:00:00Z')
        if path.startswith('roster/'):
            team = path.split('/')[1]
            forwards = []
            if team == 'NJD':
                forwards = [{'id': 1, 'firstName': {'default': 'Slate'}, 'lastName': {'default': 'Skater'}, 'positionCode': 'C'}]
            elif team == 'BOS':
                forwards = [
                    {'id': 3, 'firstName': {'default': 'Idle'}, 'lastName': {'default': 'Skater'}, 'positionCode': 'D'},
                    {'id': 9, 'firstName': {'default': 'Zero'}, 'lastName': {'default': 'Games'}, 'positionCode': 'C'}]
            elif team == 'NYI' and self.duplicate:
                forwards = [{'id': 1, 'firstName': {'default': 'Slate'}, 'lastName': {'default': 'Skater'}, 'positionCode': 'C'}]
            return Feed({'forwards': forwards, 'defensemen': [], 'goalies': [{'id': 2, 'positionCode': 'G'}]},
                        'NHL', path, '2026-09-26T00:00:00Z')
        if path.startswith('player/'):
            pid = int(path.split('/')[1])
            self.log_ids.append(pid)
            assert '/20262027/2' in path
            played = [{'gameId': 2026020000 + i, 'gameDate': f'2026-09-{i:02}', 'toi': '10:00',
                       'goals': 1, 'assists': 0, 'points': 1, 'shots': 2, 'powerPlayPoints': 0} for i in range(1, 6)]
            return Feed({'gameLog': played}, 'NHL', path, '2026-09-26T00:00:00Z')
        raise AssertionError(path)

    async def stats(self, report, season, extra='', is_game=True):
        assert (report, season, is_game) == ('skater/summary', 20262027, False)
        return Feed([{'playerId': 1, 'gamesPlayed': 4}], 'NHL Stats', report, '2026-09-26T00:00:00Z')

    async def mp(self, kind, season, entities=None):
        assert (kind, season) == ('skaters', 20262027)
        return Feed(None, 'MoneyPuck', 'mp')


@pytest.mark.parametrize('scope', ['tonight', 'league'])
def test_recent_games_api_matches_player_and_game(tmp_path, scope):
    class GameLogFake(LeagueFake):
        async def mp(self, kind, season, entities=None):
            return Feed([
                {'playerId': pid, 'gameId': '2026020005', 'situation': situation,
                 'icetime': ice, 'I_F_shotAttempts': attempts}
                for pid, ice, attempts in [(1, 480, 4), (3, 900, 10)]
                for situation in ['all', '5on5']
            ], 'MoneyPuck', 'mp')

    async def scenario():
        store = Store(tmp_path / f'{scope}.sqlite3')
        fake = GameLogFake(store)
        directory = LeaguePlayers(fake)
        body = await (players_dashboard(fake, '2026-09-26') if scope == 'tonight'
                      else directory.build('2026-09-26'))
        player = next(p for p in body['players'] if p['id'] == 1)
        assert player['recent_games'][0]['toi_5v5'] == 480
        assert player['recent_games'][0]['shot_attempts'] == 4
        assert player['recent_games'][1]['toi_5v5'] is None
        assert len(player['log']['points']) == 5
        await directory.close()
        await store.close()

    asyncio.run(scenario())


def test_league_includes_idle_skaters_and_skips_goalies_and_idle_logs(tmp_path):
    from backend.cache import Store

    async def scenario():
        store = Store(tmp_path / 'league.sqlite3')
        fake = LeagueFake(store)
        directory = LeaguePlayers(fake)
        body = await directory.build('2026-09-26')
        ids = {player['id'] for player in body['players']}
        assert ids == {1, 3, 9}
        assert 2 not in ids
        slate = next(player for player in body['players'] if player['id'] == 1)
        idle = next(player for player in body['players'] if player['id'] == 3)
        zero = next(player for player in body['players'] if player['id'] == 9)
        assert slate['game_id'] == 2026010001 and slate['opponent'] == 'NYI' and slate['home'] is False
        assert slate['windows']['season']['games'] == 5
        assert len(slate['recent_games']) == 5
        assert slate['recent_games'][0]['game_id'] == 2026020005
        assert idle['game_id'] is None and idle['team'] == 'BOS'
        assert zero['windows']['season']['games'] == 0
        assert zero['recent_games'] == []
        assert fake.log_ids == [1]
        assert body['schedule_available'] is True
        await directory.close()
        await store.close()

    asyncio.run(scenario())


def test_league_survives_a_missing_schedule_and_skips_duplicate_roster_ids(tmp_path):
    from backend.cache import Store

    async def scenario():
        store = Store(tmp_path / 'league-gap.sqlite3')
        missing = LeagueFake(store, schedule=False)
        directory = LeaguePlayers(missing)
        body = await directory.build('2026-09-26')
        assert body['schedule_available'] is False
        assert {player['id'] for player in body['players']} == {1, 3, 9}
        assert all(player['game_id'] is None for player in body['players'])
        await directory.close()

        duplicate = LeagueFake(store, duplicate=True)
        directory = LeaguePlayers(duplicate)
        body = await directory.build('2026-09-27')
        assert 1 not in {player['id'] for player in body['players']}
        assert body['ambiguous_players'] == 1
        assert body['partial'] is True
        await directory.close()
        await store.close()

    asyncio.run(scenario())


def test_league_view_reuses_the_snapshot(tmp_path):
    from backend.cache import Store

    async def scenario():
        store = Store(tmp_path / 'league-cache.sqlite3')
        fake = LeagueFake(store)
        directory = LeaguePlayers(fake)
        first = await directory.view('2026-09-26')
        assert first['ready'] is False and first['build']['status'] == 'building'
        await directory.tasks['2026-09-26']
        second = await directory.view('2026-09-26')
        assert second['ready'] is True and second['cache_status'] == 'cached'
        assert fake.score_calls == 1
        assert len(second['players']) == 3
        await directory.close()
        await store.close()

    asyncio.run(scenario())
