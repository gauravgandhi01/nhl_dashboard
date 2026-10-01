import asyncio
import json

import httpx
import pytest

from backend.cache import Store
from backend.providers import Providers, DFO
import backend.odds_client as odds_client_module
from backend.odds_client import OddsClient, OddsError, odds_api_keys


@pytest.mark.parametrize('cached,disallow', [(False, False), (True, False), (True, True)])
def test_robots_failure_preserves_cache_without_fetching_page(tmp_path, cached, disallow):
    async def run():
        store = Store(tmp_path / 'cache.sqlite3')
        calls = []
        def respond(request):
            calls.append(request.url.path)
            if request.url.path == '/robots.txt':
                return httpx.Response(200, text='User-agent: *\nDisallow: /') if disallow else httpx.Response(403)
            return httpx.Response(200, json={'sections': {'Forwards': ['Test Player']}})
        await store.client.aclose()
        store.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        path = '/teams/test/line-combinations'
        if cached:
            await store.fetch(DFO + path, 'Daily Faceoff', 120)
        calls.clear()
        feed = await Providers(store).dfo(path, json.loads)
        if disallow or cached:
            assert calls == ['/robots.txt']
        else:
            assert calls == ['/robots.txt', '/teams/test/line-combinations']
        if not disallow:
            assert feed.data['sections']['Forwards'] == ['Test Player']
            assert feed.retrieved_at
        else:
            assert feed.data is None
        assert feed.error == ('Automated access unavailable' if disallow else None)
        await store.close()
    asyncio.run(run())


@pytest.mark.parametrize('status,code,expected', [
    (401, 'OUT_OF_USAGE_CREDITS', 'quota insufficient'),
    (401, 'INVALID_KEY', 'key rejected'),
    (422, 'INVALID_MARKET', 'requested markets'),
    (429, None, 'rate limited'),
    (404, None, 'no longer available'),
])
def test_odds_diagnostics_are_specific_and_credential_safe(tmp_path, monkeypatch, status, code, expected):
    keys_path = tmp_path / 'keys.json'
    keys_path.write_text(json.dumps({'api_keys': ['SECRET_TEST_KEY']}))
    monkeypatch.setattr(odds_client_module, 'KEYS_PATH', keys_path)
    async def run():
        store = Store(tmp_path / 'cache.sqlite3')
        calls = []
        def respond(request):
            calls.append(request)
            return httpx.Response(status, json={'error_code': code, 'message': 'SECRET_TEST_KEY'},
                                  headers={'x-requests-remaining': '5'})
        await store.client.aclose()
        store.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        client = OddsClient(store)
        with pytest.raises(OddsError, match=expected) as error:
            await client.request('/events')
        assert 'SECRET_TEST_KEY' not in str(error.value)
        if code == 'OUT_OF_USAGE_CREDITS' or status == 429:
            with pytest.raises(OddsError, match='cooldown'):
                await client.request('/events')
            assert len(calls) == 1
        assert not store.db.execute('SELECT * FROM responses').fetchall()
        await store.close()
    asyncio.run(run())


def test_odds_keys_support_env_workspace_and_render_secret_paths(tmp_path, monkeypatch):
    workspace = tmp_path / 'workspace_keys.json'
    render = tmp_path / 'render_keys.json'
    env = tmp_path / 'env_keys.json'
    workspace.write_text(json.dumps({'api_keys': ['WORKSPACE']}))
    render.write_text(json.dumps({'api_keys': ['RENDER']}))
    env.write_text(json.dumps({'api_keys': ['ENV', 'ENV']}))
    monkeypatch.setattr(odds_client_module, 'KEYS_PATH', workspace)
    monkeypatch.setattr(odds_client_module, 'RENDER_KEYS_PATH', render)
    monkeypatch.delenv('NHL_ODDS_KEYS_PATH', raising=False)
    assert odds_api_keys() == ['WORKSPACE']
    workspace.unlink()
    assert odds_api_keys() == ['RENDER']
    monkeypatch.setenv('NHL_ODDS_KEYS_PATH', str(env))
    assert odds_api_keys() == ['ENV']
