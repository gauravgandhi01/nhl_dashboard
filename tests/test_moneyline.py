import asyncio
import json
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from backend.cache import Store, Feed
import backend.moneyline as moneyline_module
import backend.odds_client as odds_client_module
from backend.moneyline import Moneylines, moneyline_prices
from backend.odds_config import configured_bookmakers
from backend.odds_client import odds_client


def fixture():
    start = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    game = {'id': 2026020001, 'startTimeUTC': start, 'awayTeam': {'abbrev': 'CHI'},
            'homeTeam': {'abbrev': 'FLA'}, 'gameState': 'FUT', 'gameScheduleState': 'OK'}
    event = {'id': 'abcd123', 'commence_time': start, 'away_team': 'Chicago Blackhawks', 'home_team': 'Florida Panthers',
             'bookmakers': [{'key': 'fanduel', 'title': 'FanDuel', 'last_update': start, 'markets': [{'key': 'h2h',
                'outcomes': [{'name': 'Florida Panthers', 'price': -140}, {'name': 'Chicago Blackhawks', 'price': 120}]},
                {'key': 'totals', 'outcomes': [{'name': 'Over', 'point': 6.5, 'price': -110},
                                             {'name': 'Under', 'point': 6.5, 'price': -110}]}]}]}
    return game, event


def test_paired_moneylines_and_reject_ambiguous_markets():
    game, event = fixture()
    assert moneyline_prices(event, game)[0]['away'] == 120
    assert moneyline_prices(event, game)[0]['home'] == -140
    event['bookmakers'].append({'key': 'pinnacle', 'title': 'Pinnacle', 'last_update': event['commence_time'], 'markets': [{'key': 'h2h',
        'outcomes': [{'name': 'Florida Panthers', 'price': -130}, {'name': 'Chicago Blackhawks', 'price': 115}]}]})
    best = moneyline_prices(event, game)[0]
    assert best['away'] == 120 and best['away_name'] == 'FanDuel'
    assert best['home'] == -130 and best['home_name'] == 'Pinnacle'
    event['bookmakers'].append({'key': 'prophetx', 'title': 'ProphetX', 'last_update': event['commence_time'], 'markets': [{'key': 'h2h',
        'outcomes': [{'name': 'Florida Panthers', 'price': -128}, {'name': 'Chicago Blackhawks', 'price': 122}]}]})
    best = moneyline_prices(event, game)[0]
    assert best['away'] == 120 and best['away_name'] == 'FanDuel'
    assert best['home'] == -130 and best['home_name'] == 'Pinnacle'
    event['bookmakers'] = event['bookmakers'][:1]
    market = event['bookmakers'][0]['markets'][0]
    market['outcomes'].append({'name': 'Draw', 'price': 250})
    assert moneyline_prices(event, game) == []
    market['outcomes'].pop()
    for invalid in [0, None, 99, float('inf'), -100.5]:
        market['outcomes'][0]['price'] = invalid
        assert moneyline_prices(event, game) == []
    market['outcomes'][0]['price'] = -140
    market['outcomes'][0]['name'] = 'Chicago Blackhawks'
    assert moneyline_prices(event, game) == []


@pytest.mark.parametrize('mode', ['success', 'bookmaker_filter', 'totals_only', 'no_totals', 'missing', 'duplicate', 'started', 'postponed', 'empty', 'schedule_failure', 'no_key', 'quota', 'failure'])
def test_cache_and_failure_isolation(tmp_path, monkeypatch, mode):
    keys_path = tmp_path / 'keys.json'
    keys_path.write_text(json.dumps({'api_keys': [] if mode == 'no_key' else ['TEST_SECRET']}))
    monkeypatch.setattr(odds_client_module, 'KEYS_PATH', keys_path)
    if mode == 'bookmaker_filter':
        monkeypatch.setattr(moneyline_module, 'market_params',
                            lambda extra=None: {**(extra or {}), 'bookmakers': 'fanduel,espnbet'})
        monkeypatch.setattr(moneyline_module, 'odds_scope',
                            lambda: {'regions': 'us,us2,us_ex', 'bookmakers': ['fanduel', 'espnbet'], 'mode': 'bookmakers'})
    async def run():
        store = Store(tmp_path / 'test.sqlite3')
        game, event = fixture()
        if mode == 'started': game['gameState'] = 'LIVE'
        if mode == 'postponed': game['gameScheduleState'] = 'PPD'
        if mode == 'missing': event['bookmakers'] = []
        if mode == 'totals_only': event['bookmakers'][0]['markets'] = event['bookmakers'][0]['markets'][1:]
        if mode == 'no_totals': event['bookmakers'][0]['markets'] = event['bookmakers'][0]['markets'][:1]
        calls = []
        class Providers:
            async def nhl(self, *args):
                return Feed(None if mode == 'schedule_failure' else {'games': [] if mode == 'empty' else [game]}, 'NHL', 'safe')
        p = Providers(); p.store = store
        def respond(request):
            calls.append(request)
            assert request.url.params['markets'] == 'h2h,totals'
            assert request.url.params['oddsFormat'] == 'american'
            if mode == 'bookmaker_filter':
                assert request.url.params['bookmakers'] == 'fanduel,espnbet'
                assert 'regions' not in request.url.params
            else:
                assert request.url.params['bookmakers'] == ','.join(configured_bookmakers())
                assert 'regions' not in request.url.params
            assert request.url.params['commenceTimeFrom'] == '2026-11-01T04:00:00Z'
            assert request.url.params['commenceTimeTo'] == '2026-11-02T04:59:59Z'
            if mode in ['quota', 'failure']:
                return httpx.Response(429 if mode == 'quota' else 403)
            return httpx.Response(200, json=[event, event] if mode == 'duplicate' else [event], headers={'x-requests-remaining': '100'})
        await store.client.aclose()
        store.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        service = Moneylines(p)
        assert not service.cached('2026-11-01')['prices'] and not calls
        results = await asyncio.gather(service.refresh('2026-11-01'), service.refresh('2026-11-01'))
        if mode in ['success', 'bookmaker_filter']:
            assert results[0]['prices']['2026020001'][0]['away'] == 120
            assert results[0]['prices']['2026020001'][0]['name'] == 'Best available'
            assert results[0]['odds_scope']['mode'] == 'bookmakers'
            assert results[0]['totals']['2026020001']['total'] == 6.5
            assert results[0]['totals_loaded'] is True
            assert len(calls) == 1
            forced = await service.refresh('2026-11-01', force=True)
            assert forced['prices']['2026020001'][0]['away'] == 120
            assert len(calls) == 2
            store.db.execute('UPDATE moneyline_odds SET fetched=0,attempted=0'); store.db.commit()
            async def fail(request): raise httpx.ConnectError('Secret-bearing URL must not escape', request=request)
            await store.client.aclose()
            store.client = httpx.AsyncClient(transport=httpx.MockTransport(fail))
            stale = await service.refresh('2026-11-01')
            assert stale['status'] == 'stale' and stale['prices']
            assert stale['totals']['2026020001']['over'] == -110
        elif mode == 'totals_only':
            assert not results[0]['prices']
            assert results[0]['totals']['2026020001']['total'] == 6.5
            assert len(calls) == 1
        elif mode == 'no_totals':
            assert results[0]['prices'] and not results[0]['totals']
            assert results[0]['totals_loaded'] is True
            assert len(calls) == 1
        else:
            assert not results[0]['prices']
            assert not results[0]['totals']
        if mode in ['no_key', 'started', 'postponed', 'empty', 'schedule_failure']:
            assert not calls
        if mode == 'quota':
            assert odds_client(store) is service.client
            assert service.client.exhausted_until > time.time()
            with pytest.raises(ValueError): await service.client.request('/events')
            assert len(calls) == 1
        assert 'TEST_SECRET' not in json.dumps(results)
        assert 'TEST_SECRET' not in '\n'.join(store.db.iterdump())
        await store.close()
    asyncio.run(run())
