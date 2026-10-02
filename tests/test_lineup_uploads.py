import asyncio
import json
import time
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.cache import Feed, Store
from backend.collect_lineups import collect, initialize, read_config, remote_request, site_url
from backend.lineup_uploads import FRESH_SECONDS, MAX_AGE_SECONDS, MAX_BODY_BYTES
from backend.providers import Providers

TOKEN = 'test-only-' + 'x' * 32
HEADERS = {'Authorization': 'Bearer ' + TOKEN}


def batch(team='NYR', age=0, name='Test Player'):
    return {'version': 1, 'lineups': [{
        'team': team, 'retrieved_at': datetime.fromtimestamp(time.time() - age, timezone.utc).isoformat(),
        'data': {'sections': {'Forward line 1': [name]}, 'updated_at': '2026-10-02T12:00:00Z'},
    }]}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('NHL_DASHBOARD_DB', str(tmp_path / 'api.sqlite3'))
    monkeypatch.setenv('NHL_LINEUP_UPLOAD_TOKEN', TOKEN)
    monkeypatch.setenv('NHL_DFO_LINEUP_MODE', 'uploaded')
    with TestClient(app) as client:
        yield client


def lineup(team='NYR'):
    return asyncio.run(app.state.dashboard.p.lineup(team))


def test_upload_requires_configured_token_before_reading_body(client, monkeypatch):
    assert client.post('/api/admin/lineups', content=b'bad').status_code == 401
    assert client.get('/api/admin/lineups').status_code == 401
    assert client.post('/api/admin/lineups', headers={'Authorization': 'Bearer wrong'}, json=batch()).status_code == 401
    monkeypatch.delenv('NHL_LINEUP_UPLOAD_TOKEN')
    assert client.post('/api/admin/lineups', headers=HEADERS, json=batch()).status_code == 503


def test_uploaded_lineup_uses_original_timestamp_without_network(client, monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError('Uploaded mode must not access Daily Faceoff')
    monkeypatch.setattr(app.state.dashboard.p.store, 'fetch', forbidden)
    assert lineup().data is None
    payload = batch()
    response = client.post('/api/admin/lineups', headers=HEADERS, json=payload)
    assert response.json() == {'accepted': ['NYR'], 'ignored': []}
    feed = lineup()
    assert feed.data == payload['lineups'][0]['data']
    assert feed.retrieved_at == payload['lineups'][0]['retrieved_at']
    assert feed.meta()['status'] == 'available'
    assert feed.url == 'https://www.dailyfaceoff.com/teams/new-york-rangers/line-combinations'
    status = client.get('/api/admin/lineups', headers=HEADERS).json()
    assert status['mode'] == 'uploaded'
    assert status['teams'][0]['status'] == 'available'
    assert TOKEN not in json.dumps(status)


def test_replayed_and_older_uploads_do_not_replace_newer_data(client):
    payload = batch()
    client.post('/api/admin/lineups', headers=HEADERS, json=payload)
    before = client.get('/api/admin/lineups', headers=HEADERS).json()
    assert client.post('/api/admin/lineups', headers=HEADERS, json=payload).json()['ignored'] == ['NYR']
    assert client.post('/api/admin/lineups', headers=HEADERS, json=batch(age=60, name='Old Player')).json()['ignored'] == ['NYR']
    assert lineup().data['sections']['Forward line 1'] == ['Test Player']
    assert client.get('/api/admin/lineups', headers=HEADERS).json() == before


def test_partial_upload_keeps_other_teams_and_failed_batch_is_atomic(client):
    client.post('/api/admin/lineups', headers=HEADERS, json=batch('NYR'))
    client.post('/api/admin/lineups', headers=HEADERS, json=batch('TOR'))
    payload = batch('NYR', name='Changed Player')
    payload['lineups'].extend(batch('INVALID')['lineups'])
    assert client.post('/api/admin/lineups', headers=HEADERS, json=payload).status_code == 422
    assert lineup().data['sections']['Forward line 1'] == ['Test Player']
    assert lineup('TOR').data is not None


@pytest.mark.parametrize('case', ['future', 'old', 'naive', 'empty', 'unknown', 'duplicate', 'large_section', 'version'])
def test_invalid_uploads_are_rejected(client, case):
    payload = batch()
    if case == 'future':
        payload = batch(age=-120)
    elif case == 'old':
        payload = batch(age=MAX_AGE_SECONDS + 60)
    elif case == 'naive':
        payload['lineups'][0]['retrieved_at'] = '2026-10-02T12:00:00'
    elif case == 'empty':
        payload['lineups'][0]['data']['sections'] = {'Forward line 1': []}
    elif case == 'unknown':
        payload = batch('XXX')
    elif case == 'duplicate':
        payload['lineups'] *= 2
    elif case == 'large_section':
        payload['lineups'][0]['data']['sections']['Forward line 1'] *= 31
    else:
        payload['version'] = 2
    assert client.post('/api/admin/lineups', headers=HEADERS, json=payload).status_code == 422
    assert lineup().data is None


def test_oversized_and_malformed_uploads(client):
    assert client.post('/api/admin/lineups', headers=HEADERS, content=b'x' * (MAX_BODY_BYTES + 1)).status_code == 413
    assert client.post('/api/admin/lineups', headers=HEADERS, content=b'{').status_code == 422


def test_stale_expired_and_persistent_snapshots(client):
    client.post('/api/admin/lineups', headers=HEADERS, json=batch(age=FRESH_SECONDS + 1))
    assert lineup().meta()['status'] == 'stale'
    store = app.state.dashboard.p.store
    db_path = store.db.execute('PRAGMA database_list').fetchone()[2]
    async def reopened():
        other = Store(__import__('pathlib').Path(db_path))
        try:
            assert (await Providers(other).lineup('NYR')).data is not None
        finally:
            await other.close()
    asyncio.run(reopened())
    store.db.execute('UPDATE uploaded_lineups SET fetched=?', (time.time() - MAX_AGE_SECONDS - 1,))
    store.db.commit()
    assert lineup().data is None
    assert 'expired' in lineup().error
    assert client.get('/api/admin/lineups', headers=HEADERS).json()['teams'][0]['status'] == 'expired'


def test_direct_mode_keeps_existing_provider(client, monkeypatch):
    monkeypatch.delenv('NHL_DFO_LINEUP_MODE')
    calls = []
    async def direct(path, *args):
        calls.append(path)
        return Feed({'direct': True}, 'Daily Faceoff', path)
    monkeypatch.setattr(app.state.dashboard.p, 'dfo', direct)
    assert lineup().data == {'direct': True}
    assert calls == ['/teams/new-york-rangers/line-combinations']


def test_collector_does_not_relabel_stale_data_or_upload_failures(tmp_path, monkeypatch):
    stamp = datetime.now(timezone.utc).isoformat()
    async def fake(self, path, *args, **kwargs):
        data = {'sections': {'Forward line 1': ['Test Player']}, 'updated_at': None}
        stale = 'toronto' in path
        return Feed(data, 'Daily Faceoff', path, stamp, stale, 'HTTP 403' if stale else None)
    monkeypatch.setattr(Providers, 'dfo', fake)
    async def scenario():
        store = Store(tmp_path / 'collector.sqlite3')
        try:
            payload, failures = await collect(store, ['NYR', 'TOR'], pause=0)
            assert failures == ['TOR']
            assert [entry['team'] for entry in payload['lineups']] == ['NYR']
            assert payload['lineups'][0]['retrieved_at'] == stamp
        finally:
            await store.close()
    asyncio.run(scenario())


def test_private_config_and_origin_validation(tmp_path, capsys):
    path = tmp_path / 'config.json'
    initialize(path, 'https://example.com/')
    config = read_config(path)
    assert config['site'] == 'https://example.com'
    assert config['token'] not in capsys.readouterr().out
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        initialize(path, 'https://example.com')
    for value in ['http://example.com', 'https://name:password@example.com', 'https://example.com/api', 'https://example.com?token=secret']:
        with pytest.raises(ValueError):
            site_url(value)


def test_uploader_sends_auth_without_following_redirects():
    def respond(request):
        assert request.headers['authorization'] == 'Bearer ' + TOKEN
        assert request.url.path == '/api/admin/lineups'
        assert TOKEN not in str(request.url)
        return httpx.Response(302, headers={'Location': 'https://other.example.com'})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond), follow_redirects=False) as client:
            with pytest.raises(RuntimeError, match='HTTP 302'):
                await remote_request(client, {'site': 'https://example.com', 'token': TOKEN}, 'GET')
    asyncio.run(scenario())
