import asyncio

import httpx
from fastapi.testclient import TestClient

from backend.app import app, manual_odds_refresh_enabled
from backend.cache import Feed, Store
from backend.service import Dashboard
from backend.providers import Providers


def test_cache_retains_last_good_response_and_backs_off(tmp_path):
    async def scenario():
        store = Store(tmp_path / 'cache.sqlite3')
        calls = []
        def respond(request):
            calls.append(request)
            return httpx.Response(200, json={'value': 7}) if len(calls) == 1 else httpx.Response(403)
        await store.client.aclose()
        store.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        first = await store.fetch('https://test.local/data', 'Test', 3600)
        assert first.data == {'value': 7}
        second = await store.fetch('https://test.local/data', 'Test', 3600)
        assert len(calls) == 1
        assert second.retrieved_at == first.retrieved_at
        stale = await store.fetch('https://test.local/data', 'Test', -1)
        assert stale.stale and stale.data == first.data
        assert stale.meta()['status'] == 'stale'
        await store.fetch('https://test.local/data', 'Test', -1)
        assert len(calls) == 2
        await store.close()
    asyncio.run(scenario())


def test_schema_failure_does_not_replace_good_cache(tmp_path):
    async def scenario():
        store = Store(tmp_path / 'cache.sqlite3')
        count = 0
        def respond(request):
            nonlocal count
            count += 1
            return httpx.Response(200, content=b'{"data":1}' if count == 1 else b'<html>broken</html>')
        await store.client.aclose()
        store.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        await store.fetch('https://test.local/data', 'Test', 0)
        stale = await store.fetch('https://test.local/data', 'Test', -1)
        assert stale.data == {'data': 1}
        assert stale.stale
        await store.close()
    asyncio.run(scenario())


def test_no_games_and_source_failure_are_distinct():
    class Fake:
        unavailable = False
        async def nhl(self, *args):
            return Feed(None if self.unavailable else {'games': []}, 'NHL', 'https://test.local')
        async def goalies(self, *args):
            return Feed(None, 'Daily Faceoff', 'https://test.local/goalies')
    async def scenario():
        p = Fake()
        service = Dashboard(p)
        assert (await service.slate('2026-09-27'))['error'] is None
        p.unavailable = True
        assert (await service.slate('2026-09-27'))['error'] is not None
    asyncio.run(scenario())


def test_slate_card_goalie_includes_normalized_gsax():
    class Fake:
        store = None

        async def nhl(self, path, *args):
            if path.startswith('score'):
                return Feed({'games': [{
                    'id': 2026020001, 'season': 20262027, 'gameDate': '2026-09-29',
                    'startTimeUTC': '2026-09-29T23:00:00Z', 'gameState': 'FUT',
                    'gameScheduleState': 'OK', 'gameType': 2, 'venue': {'default': 'Test'},
                    'awayTeam': {'id': 1, 'abbrev': 'MTL', 'name': {'default': 'Canadiens'}},
                    'homeTeam': {'id': 2, 'abbrev': 'TOR', 'name': {'default': 'Maple Leafs'}},
                }]}, 'NHL', path)
            if path.startswith('roster/MTL'):
                return Feed({'goalies': [{'id': 10, 'firstName': {'default': 'Jakub'}, 'lastName': {'default': 'Dobes'}}]}, 'NHL', path)
            if path.startswith('roster/TOR'):
                return Feed({'goalies': [{'id': 20, 'firstName': {'default': 'Sergei'}, 'lastName': {'default': 'Bobrovsky'}}]}, 'NHL', path)
            if path.startswith('club-schedule-season'):
                return Feed({'games': []}, 'NHL', path)
            if path.startswith('player/'):
                return Feed({'playerId': 10, 'featuredStats': {'regularSeason': {'career': {'gamesPlayed': 10}}}}, 'NHL', path)
            return Feed({}, 'NHL', path)

        async def goalies(self, *args):
            return Feed([{'awayTeamName': 'Montreal Canadiens', 'homeTeamName': 'Toronto Maple Leafs',
                          'dateGmt': '2026-09-29T23:00:00Z', 'awayGoalieName': 'Jakub Dobes',
                          'awayNewsStrengthName': 'Confirmed', 'homeGoalieName': 'Sergei Bobrovsky',
                          'homeNewsStrengthName': 'Likely'}], 'Daily Faceoff', 'goalies')

        async def stats(self, report, *args, **kwargs):
            if report == 'team/summary':
                return Feed([{'teamId': 1, 'gamesPlayed': 1}, {'teamId': 2, 'gamesPlayed': 1}], 'NHL Stats', report)
            if report == 'goalie/summary':
                return Feed([{'playerId': 10, 'gamesPlayed': 5, 'savePct': .91, 'goalsAgainstAverage': 2.5},
                             {'playerId': 20, 'gamesPlayed': 5, 'savePct': .9, 'goalsAgainstAverage': 2.8}], 'NHL Stats', report)
            return Feed([], 'NHL Stats', report)

        async def mp(self, kind, *args):
            data = [{'playerId': '10', 'gameId': '1', 'xGoals': 3, 'goals': 1},
                    {'playerId': '20', 'gameId': '1', 'xGoals': 2, 'goals': 3}] if kind == 'goalies' else []
            return Feed(data, 'MoneyPuck', kind)

    async def scenario():
        slate = await Dashboard(Fake()).slate('2026-09-29')
        card = slate['comparisons']['2026020001']
        assert card['away']['goalie']['stats']['gsax'] == 2
        assert card['away']['goalie']['advanced_games'] == 1
        assert card['home']['goalie']['stats']['gsax'] == -1
    asyncio.run(scenario())


def test_api_validation_and_spa_routes(tmp_path, monkeypatch):
    monkeypatch.setenv('NHL_DASHBOARD_DB', str(tmp_path / 'api.sqlite3'))
    with TestClient(app) as client:
        assert client.get('/api/health').json()['status'] == 'ok'
        assert client.get('/api/slate?date=not-a-date').status_code == 422
        assert client.get('/api/player-props?date=not-a-date').status_code == 422
        assert client.post('/api/player-props/refresh?game_id=invalid').status_code == 422
        assert client.get('/api/odds/moneyline?date=not-a-date').status_code == 422
        assert client.post('/api/odds/moneyline/refresh?date=not-a-date').status_code == 422
        assert client.get('/api/odds/moneyline?date=2026-09-28').json()['prices'] == {}
        assert client.get('/api/streaks?date=not-a-date').status_code == 422
        assert client.get('/api/streaks?scope=invalid').status_code == 422
        assert client.get('/api/first-period?date=not-a-date').status_code == 422
        assert client.get('/api/first-period?window=last20').status_code == 422
        assert client.get('/api/first-period/matchups/123').status_code == 404
        assert client.get('/api/first-period/odds?date=bad').status_code == 422
        assert client.post('/api/first-period/odds/refresh?date=bad').status_code == 422
        assert client.get('/api/matchups/123').status_code == 404
        assert client.get('/api/matchups/2026010001?window=invalid').status_code == 422
        assert client.get('/api/missing').status_code == 404


def test_manual_odds_refresh_gate_defaults_on_and_can_disable_posts(tmp_path, monkeypatch):
    monkeypatch.setenv('NHL_DASHBOARD_DB', str(tmp_path / 'api.sqlite3'))
    monkeypatch.delenv('NHL_MANUAL_ODDS_REFRESH_ENABLED', raising=False)
    assert manual_odds_refresh_enabled()
    with TestClient(app) as client:
        assert client.get('/api/odds/moneyline?date=2026-09-28').json()['manual_refresh_enabled'] is True
    monkeypatch.setenv('NHL_MANUAL_ODDS_REFRESH_ENABLED', 'false')
    assert not manual_odds_refresh_enabled()
    with TestClient(app) as client:
        assert client.post('/api/odds/moneyline/refresh?date=2026-09-28').status_code == 403
        assert client.post('/api/first-period/odds/refresh?date=2026-09-28').status_code == 403
        assert client.post('/api/player-props/refresh?date=2026-09-28').status_code == 403
        assert client.get('/api/odds/moneyline?date=2026-09-28').json()['manual_refresh_enabled'] is False
        assert client.get('/api/first-period/odds?date=2026-09-28').json()['manual_refresh_enabled'] is False


def test_pagination_advances_by_actual_page_size(tmp_path):
    async def scenario():
        store = Store(tmp_path / 'pagination.sqlite3')
        seen = []
        def respond(request):
            offset = int(request.url.params['start'])
            seen.append(offset)
            return httpx.Response(200, json={'data': [{'playerId': n} for n in range(offset, min(offset + 2, 5))], 'total': 5})
        await store.client.aclose()
        store.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        feed = await Providers(store).stats('skater/summary', 20252026, is_game=False)
        assert [r['playerId'] for r in feed.data] == [0, 1, 2, 3, 4]
        assert seen == [0, 2, 4]
        await store.close()
    asyncio.run(scenario())


def test_daily_faceoff_goalies_and_lineups_use_short_configurable_ttl(tmp_path, monkeypatch):
    async def scenario():
        monkeypatch.setenv('NHL_DFO_TTL', '1')
        store = Store(tmp_path / 'dfo.sqlite3')
        calls = []
        goalie_html = b'<script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"data":[]}}}</script>'
        lineup_html = b'<script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"combinations":{"updatedAt":"2026-09-29T12:00:00Z","players":[{"categoryIdentifier":"ev","groupIdentifier":"f1","name":"Player A"}]}}}}</script>'
        robots = b'User-agent: *\nAllow: /\n'
        def respond(request):
            url = str(request.url)
            calls.append(url)
            content = robots if url.endswith('/robots.txt') else lineup_html if 'line-combinations' in url else goalie_html
            return httpx.Response(200, content=content)
        await store.client.aclose()
        store.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        providers = Providers(store)
        await providers.goalies('2026-09-29')
        await providers.goalies('2026-09-29')
        await providers.lineup('TOR')
        await providers.lineup('TOR')
        assert sum('/starting-goalies/' in url for url in calls) == 1
        assert sum('/line-combinations' in url for url in calls) == 1
        store.db.execute("UPDATE responses SET fetched=0 WHERE url LIKE '%starting-goalies%' OR url LIKE '%line-combinations%'")
        store.db.commit()
        await providers.goalies('2026-09-29')
        await providers.lineup('TOR')
        assert sum('/starting-goalies/' in url for url in calls) == 2
        assert sum('/line-combinations' in url for url in calls) == 2
        await store.close()
    asyncio.run(scenario())


def test_moneypuck_rows_are_normalized_without_raw_blob(tmp_path):
    async def scenario():
        store = Store(tmp_path / 'mp.sqlite3')
        body = (
            'team,gameId,gameDate,season,situation,playoffGame,iceTime,xGoalsFor,xGoalsAgainst,shotAttemptsFor,shotAttemptsAgainst\n'
            'CAR,2025020001,2025-10-10,2025,5on5,0,3000,2.1,1.4,41,30\n'
            'CAR,2025030001,2025-05-10,2025,5on5,1,3000,2.1,1.4,41,30\n'
        ).encode()
        await store.client.aclose()
        store.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body)))
        providers = Providers(store)
        feed = await providers.mp('teams', 20252026)
        assert len(feed.data) == 1
        rows, fetched = store.load_moneypuck('teams', 20252026)
        assert len(rows) == 1
        assert fetched is not None
        raw = store.db.execute("SELECT body FROM responses WHERE source='MoneyPuck'").fetchone()
        assert raw is None or raw[0] is None
        await store.client.aclose()
        store.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(AssertionError('network should not be used'))))
        providers = Providers(store)
        cached = await providers.mp('teams', 20252026)
        assert cached.data == rows
        await store.close()
    asyncio.run(scenario())


def test_last_ten_excludes_live_game_and_preserves_advanced_coverage():
    from unittest.mock import Mock
    class Fake:
        store = Mock()
        async def stats(self, report, *args, **kwargs):
            rows = [{'gameId': i, 'gameDate': f'2025-12-{i:02}', 'teamId': 12, 'playerId': 5,
                     'wins': 1, 'losses': 0, 'otLosses': 0, 'goalsFor': 3, 'goalsAgainst': 1,
                     'shotsForPerGame': 30, 'shotsAgainstPerGame': 20, 'powerPlayGoalsFor': 1,
                     'ppOpportunities': 4, 'ppGoalsAgainst': 0, 'timesShorthanded': 2,
                     'timeOnIce': 3600, 'saves': 19, 'shotsAgainst': 20}
                    for i in range(1, 13)]
            return Feed(rows, 'NHL Stats', 'https://test.local/' + report)
        async def nhl(self, path, *args):
            data = {'goalies': [{'id': 5, 'firstName': {'default': 'Test'}, 'lastName': {'default': 'Goalie'}, 'positionCode': 'G'}]}
            if path.startswith('club-schedule-season'):
                data = {'games': [{'id': i, 'gameDate': f'2025-12-{i:02}', 'gameState': 'LIVE' if i == 12 else 'OFF'} for i in range(1, 13)]}
            return Feed(data, 'NHL', 'https://test.local/' + path)
        async def lineup(self, *args):
            return Feed(None, 'Daily Faceoff', 'https://test.local/lineup')
    async def scenario():
        advanced = [{'team': 'CAR', 'gameId': str(i), 'xGoalsFor': 2, 'xGoalsAgainst': 1,
                     'iceTime': 3000, 'shotAttemptsFor': 40, 'shotAttemptsAgainst': 30} for i in range(1, 10)]
        goalie_advanced = [{'playerId': '5', 'gameId': str(i), 'xGoals': 1.5, 'goals': 1} for i in range(1, 10)]
        result, _ = await Dashboard(Fake()).team(
            {'id': 12, 'season': 20252026, 'gameDate': '2025-12-12', 'gameState': 'LIVE', 'awayTeam': {'id': 12, 'abbrev': 'CAR'}},
            'away', 20252026, 'last10', Feed(advanced, 'MP', 'mp'), Feed(goalie_advanced, 'MP', 'mp-g'), Feed([], 'MP', 'mp-s'),
            Feed([], 'NHL', 'skaters'), Feed({}, 'ESPN', 'injuries'), {'name': None, 'status': 'Unknown'})
        assert result['summary']['games'] == 10
        assert result['recent'][0]['gameId'] == 11
        assert result['advanced']['games'] == 8
        assert result['goalies'][0]['summary']['games'] == 10
        assert result['goalies'][0]['summary']['advanced_games'] == 8
        assert result['goalies'][0]['summary']['gsax'] == 4
    asyncio.run(scenario())
