import asyncio
import json
import time
from datetime import datetime, timezone

import httpx
import pytest

from backend.cache import Store
from backend.odds_client import OddsClient, OddsError, key_id
from backend.odds_policy import expensive_refresh_after, refresh_due


@pytest.fixture
def pool(monkeypatch):
    keys = ['PRIVATE_A', 'PRIVATE_B', 'PRIVATE_C']
    monkeypatch.setattr('backend.odds_client.odds_api_keys', lambda: keys)
    monkeypatch.setenv('NHL_ODDS_DAILY_BUDGET', '1000')
    return keys


def seed(client, key, remaining, blocked=0, invalid=0):
    month, _ = client.period()
    client.store.db.execute('INSERT OR REPLACE INTO odds_key_budgets VALUES(?,?,?,?,?,?,?)',
        (key_id(key), month, remaining, 500 - remaining, time.time(), blocked, invalid))
    client.store.db.commit()


def test_free_balance_sync_checks_every_key_and_persists_without_credentials(tmp_path, pool):
    async def run():
        store = Store(tmp_path / 'cache.sqlite3')
        calls = []
        def respond(request):
            assert request.url.path == '/v4/sports/'
            key = request.url.params['apiKey']
            calls.append(key)
            remaining = {pool[0]: 0, pool[1]: 1, pool[2]: 500}[key]
            return httpx.Response(200, json=[], headers={'x-requests-remaining': str(remaining),
                'x-requests-used': str(500 - remaining), 'x-requests-last': '0'})
        await store.client.aclose()
        store.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        client = OddsClient(store)
        result = await client.sync_budgets()
        assert calls == pool
        assert result['remaining'] == 501 and result['known_keys'] == 3
        assert result['spent_today'] == 0
        await client.sync_budgets()
        assert calls == pool
        assert OddsClient(store).status()['remaining'] == 501
        dump = '\n'.join(store.db.iterdump()) + json.dumps(result)
        assert all(key not in dump for key in pool)
        await store.close()
    asyncio.run(run())


def test_budget_aware_selection_rotation_daily_cap_and_small_balance_reuse(tmp_path, pool, monkeypatch):
    async def run():
        store = Store(tmp_path / 'cache.sqlite3')
        client = OddsClient(store)
        for key in pool: seed(client, key, 20)
        calls = []
        remaining = dict.fromkeys(pool, 20)
        def respond(request):
            key = request.url.params['apiKey']; calls.append(key)
            cost = len(request.url.params['markets'].split(','))
            remaining[key] -= cost
            return httpx.Response(200, json=[], headers={'x-requests-remaining': str(remaining[key]),
                'x-requests-used': str(500 - remaining[key]), 'x-requests-last': str(cost)})
        await store.client.aclose()
        store.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        for _ in pool:
            await client.request('/odds', {'markets': 'h2h', 'bookmakers': 'fanduel'})
        assert calls == pool
        # A small balance cannot cover nine markets, so a different key is selected.
        seed(client, pool[0], 2); seed(client, pool[1], 20); seed(client, pool[2], 0)
        await client.request('/events/abc/odds', {'markets': ','.join('m'+str(i) for i in range(9)), 'bookmakers': 'fanduel'})
        assert calls[-1] == pool[1]
        seed(client, pool[1], 0)
        await client.request('/odds', {'markets': 'h2h', 'bookmakers': 'fanduel'})
        assert calls[-1] == pool[0]
        spent = client.status()['spent_today']
        monkeypatch.setenv('NHL_ODDS_DAILY_BUDGET', str(spent))
        before = len(calls)
        with pytest.raises(OddsError, match='daily budget'):
            await client.request('/odds', {'markets': 'h2h'})
        assert len(calls) == before
        await store.close()
    asyncio.run(run())


def test_split_request_uses_small_balances_and_merges_markets_and_books(tmp_path, pool):
    async def run():
        store = Store(tmp_path / 'cache.sqlite3')
        client = OddsClient(store)
        remaining = {pool[0]: 2, pool[1]: 2, pool[2]: 0}
        for key, value in remaining.items(): seed(client, key, value)
        calls = []
        def respond(request):
            key = request.url.params['apiKey']; remaining[key] -= 1
            calls.append(request)
            books = request.url.params['bookmakers'].split(',')
            market = request.url.params['markets']
            assert ',' not in market and len(books) <= 10
            body = [{'id': 'abc', 'bookmakers': [{'key': book, 'markets': [{'key': market, 'outcomes': []}]} for book in books]}]
            return httpx.Response(200, json=body, headers={'x-requests-remaining': str(remaining[key]),
                'x-requests-used': str(500 - remaining[key]), 'x-requests-last': '1'})
        await store.client.aclose()
        store.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        books = ['b'+str(i) for i in range(12)]
        result = await client.request('/odds', {'markets': 'h2h,totals', 'bookmakers': ','.join(books)})
        assert len(calls) == 4
        assert {b['key'] for b in result[0]['bookmakers']} == set(books)
        assert all({m['key'] for m in b['markets']} == {'h2h', 'totals'} for b in result[0]['bookmakers'])
        assert client.status()['remaining'] == 0 and client.status()['spent_today'] == 4
        await store.close()
    asyncio.run(run())


def test_month_rollover_reenables_exhausted_and_invalid_keys(tmp_path, pool, monkeypatch):
    async def run():
        store = Store(tmp_path / 'cache.sqlite3')
        client = OddsClient(store)
        monkeypatch.setattr(client, 'period', lambda: ('2026-10', time.time() + 999999))
        for key in pool: seed(client, key, 0, time.time() + 999999, invalid=1)
        monkeypatch.setattr(client, 'period', lambda: ('2026-11', time.time() + 999999))
        calls = []
        def respond(request):
            calls.append(request)
            return httpx.Response(200, json=[], headers={'x-requests-remaining': '499', 'x-requests-used': '1', 'x-requests-last': '1'})
        await store.client.aclose()
        store.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        await client.request('/odds', {'markets': 'h2h'})
        assert len(calls) == 1
        await store.close()
    asyncio.run(run())


def test_schedule_handles_eastern_slots_dst_restarts_and_force_cooldowns():
    from zoneinfo import ZoneInfo
    et = ZoneInfo('America/New_York')
    for day in ['2026-10-30', '2026-11-01']:
        assert expensive_refresh_after(datetime.fromisoformat(day+'T10:59').replace(tzinfo=et)) is None
        slot = expensive_refresh_after(datetime.fromisoformat(day+'T15:05').replace(tzinfo=et))
        assert datetime.fromtimestamp(slot, et).hour == 15
        assert not refresh_due(('{}', slot + 30, slot + 30, None), 3600, refresh_after=slot, now=slot+7200)
        assert refresh_due(('{}', slot - 3600, slot - 3600, None), 3600, refresh_after=slot, now=slot+300)
    assert not refresh_due(('{}', 1000, 1000, None), 1800, force=True, now=1100)
    assert refresh_due(('{}', 1000, 1000, None), 1800, force=True, now=1300)
    assert not refresh_due(('{}', 1000, 1000, 'failure'), 1800, force=True, now=1500)
    assert refresh_due(('{}', 1000, 1000, None), 1800, now=2800)


def test_default_daily_cap_paces_pool_and_tightens_when_balance_is_low(tmp_path, pool, monkeypatch):
    import calendar
    monkeypatch.delenv('NHL_ODDS_DAILY_BUDGET')
    async def run():
        store = Store(tmp_path / 'budget.sqlite3')
        client = OddsClient(store)
        for key in pool: seed(client, key, 500)
        now = datetime.now(timezone.utc)
        days = calendar.monthrange(now.year, now.month)[1]
        full_cap, spent = client.daily_budget(pool)
        assert full_cap == int(1500 * .9 / days) and spent == 0
        for key in pool: seed(client, key, 10)
        low_cap, _ = client.daily_budget(pool)
        assert low_cap == min(full_cap, int(30 * .9 / (days - now.day + 1)))
        await store.close()
    asyncio.run(run())
