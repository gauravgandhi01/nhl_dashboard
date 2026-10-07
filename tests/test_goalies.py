import asyncio
import time

from backend.cache import Feed, Store
from backend.goalies import goalie_windows, goalies_dashboard
from backend.retention import compact
from backend.service import today_et


def game(i, **kwargs):
    row = {'gameId': 2025020000 + i, 'gameDate': f'2025-11-{i:02}', 'timeOnIce': 3600,
           'saves': 30, 'shotsAgainst': 33, 'goalsAgainst': 3, 'gamesStarted': 1,
           'wins': 1, 'losses': 0, 'otLosses': 0, 'shutouts': 0, 'playerId': 10}
    row.update(kwargs)
    return row


def test_windows_weight_saves_time_and_expected_goals():
    rows = [game(1, saves=9, shotsAgainst=10, goalsAgainst=1, timeOnIce=1200),
            game(2, saves=38, shotsAgainst=40, goalsAgainst=2, timeOnIce=3600, wins=0, losses=1)]
    advanced = [{'playerId': '10', 'gameId': str(rows[0]['gameId']), 'xGoals': 1.5, 'goals': 1},
                {'playerId': '10', 'gameId': str(rows[1]['gameId']), 'xGoals': 2, 'goals': 1}]
    season = goalie_windows(rows, advanced, '2025-11-03')['season']
    assert season['games'] == 2
    assert season['sv'] == 47 / 50
    assert season['gaa'] == 3 / 4800 * 3600
    assert season['gsax'] == 1.5
    assert season['starts'] == 2
    assert season['wins'] == 1 and season['losses'] == 1 and season['ot_losses'] == 0
    assert season['shots_against'] == 50 and season['saves'] == 47
    assert season['advanced_games'] == 2


def test_cutoff_relief_and_missing_moneypuck_stay_blank():
    rows = [game(1, gamesStarted=1, shutouts=1), game(2, gamesStarted=0, shutouts=0),
            game(3, gameDate='2025-11-20', saves=10, shotsAgainst=10, goalsAgainst=0)]
    counted = goalie_windows(rows, None, '2025-11-03')['season']
    assert counted['games'] == 2
    assert counted['starts'] == 1
    assert counted['shutouts'] == 1
    assert counted['gsax'] is None
    assert counted['advanced_games'] is None
    assert counted['sv'] == 60 / 66
    missing = goalie_windows([game(1, saves=None)], [], '2025-11-03')['season']
    assert missing['sv'] is None
    assert missing['games'] == 1


def test_duplicate_moneypuck_game_is_not_guessed():
    rows = [game(1)]
    advanced = [{'gameId': str(rows[0]['gameId']), 'xGoals': 4, 'goals': 1},
                {'gameId': str(rows[0]['gameId']), 'xGoals': 1, 'goals': 3}]
    assert goalie_windows(rows, advanced, '2025-11-03')['season']['gsax'] is None
    assert goalie_windows(rows, advanced, '2025-11-03')['season']['advanced_games'] == 0


class GoalieFake:
    def __init__(self, store, schedule=True):
        self.store = store
        self.schedule = schedule

    async def nhl(self, path, *args, **kwargs):
        if path.startswith('score'):
            if not self.schedule:
                return Feed(None, 'NHL', path, error='down')
            return Feed({'games': [{
                'id': 2026010001, 'season': 20262027, 'gameDate': '2026-09-26',
                'startTimeUTC': '2026-09-26T23:00:00Z', 'gameScheduleState': 'OK',
                'awayTeam': {'id': 1, 'abbrev': 'ANA', 'darkLogo': 'ana.svg'},
                'homeTeam': {'id': 2, 'abbrev': 'NYI', 'darkLogo': 'nyi.svg'}}]}, 'NHL', path, '2026-09-26T00:00:00Z')
        if path.startswith('roster/'):
            team = path.split('/')[1]
            goalies = []
            if team == 'ANA':
                goalies = [{'id': 10, 'firstName': {'default': 'A'}, 'lastName': {'default': 'Goalie'}}]
            elif team == 'BOS':
                goalies = [{'id': 11, 'firstName': {'default': 'Idle'}, 'lastName': {'default': 'Goalie'}}]
            elif team == 'NYI':
                goalies = [{'id': 12, 'firstName': {'default': 'Fresh'}, 'lastName': {'default': 'Goalie'}}]
            return Feed({'goalies': goalies}, 'NHL', path, '2026-09-26T00:00:00Z')
        raise AssertionError(path)

    async def stats(self, report, season, extra='', is_game=True):
        assert report == 'goalie/summary' and is_game is True and season == 20262027
        return Feed([
            {'playerId': 10, 'gameId': 2026020001, 'gameDate': '2026-09-10', 'timeOnIce': 3600,
             'saves': 30, 'shotsAgainst': 32, 'goalsAgainst': 2, 'gamesStarted': 1,
             'wins': 1, 'losses': 0, 'otLosses': 0, 'shutouts': 0},
            {'playerId': 11, 'gameId': 2026020002, 'gameDate': '2026-09-11', 'timeOnIce': 3600,
             'saves': 20, 'shotsAgainst': 25, 'goalsAgainst': 5, 'gamesStarted': 1,
             'wins': 0, 'losses': 1, 'otLosses': 0, 'shutouts': 0},
        ], 'NHL Stats', report, '2026-09-26T00:00:00Z')

    async def mp(self, kind, season):
        assert kind == 'goalies'
        return Feed([{'playerId': '10', 'gameId': '2026020001', 'xGoals': 3, 'goals': 2}], 'MoneyPuck', kind)

    async def goalies(self, date):
        return Feed([{
            'awayTeamName': 'Anaheim Ducks', 'homeTeamName': 'New York Islanders',
            'dateGmt': '2026-09-26T23:00:00Z', 'awayGoalieName': 'A Goalie',
            'awayNewsStrengthName': 'Confirmed', 'homeGoalieName': 'Someone Else',
            'homeNewsStrengthName': 'Likely'}], 'Daily Faceoff', 'goalies')


def test_dashboard_lists_goalies_with_a_game_played_and_marks_a_confirmed_starter(tmp_path):
    async def scenario():
        store = Store(tmp_path / 'goalies.sqlite3')
        result = await goalies_dashboard(GoalieFake(store), '2026-09-26')
        by_id = {goalie['id']: goalie for goalie in result['goalies']}
        assert set(by_id) == {10, 11}
        assert by_id[10]['game_id'] == 2026010001
        assert by_id[10]['starter_status'] == 'Confirmed'
        assert by_id[10]['windows']['season']['gsax'] == 1
        assert by_id[10]['windows']['season']['sv'] == 30 / 32
        assert by_id[11]['game_id'] is None and by_id[11]['starter_status'] is None
        assert by_id[11]['team'] == 'BOS'
        missing = await goalies_dashboard(GoalieFake(store, schedule=False), '2026-09-27')
        assert missing['schedule_available'] is False
        assert {goalie['id'] for goalie in missing['goalies']} == {10, 11}
        assert all(goalie['game_id'] is None for goalie in missing['goalies'])
        await store.close()
    asyncio.run(scenario())


def test_goalie_dashboards_expire_with_the_player_snapshot(tmp_path):
    store = Store(tmp_path / 'goalie-retention.sqlite3')
    store.db.execute('''CREATE TABLE goalie_dashboards (
        date TEXT PRIMARY KEY, body TEXT, fetched REAL, error TEXT)''')
    now = time.time()
    store.db.execute('INSERT INTO goalie_dashboards VALUES (?, ?, ?, NULL)', ('2020-01-01', '{}', now - 7200))
    store.db.execute('INSERT INTO goalie_dashboards VALUES (?, ?, ?, NULL)', (today_et(), '{}', now))
    store.db.commit()
    compact(store)
    assert store.db.execute('SELECT date FROM goalie_dashboards').fetchall() == [(today_et(),)]
    asyncio.run(store.close())
