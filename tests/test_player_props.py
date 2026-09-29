import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from backend.cache import Feed, Store
from backend.player_identity import resolve_player
from backend.player_props import BOOKS, MARKETS, PlayerProps, normalize_props


def test_player_identity_requires_unique_game_roster_member():
    players = [{'id': 1, 'name': 'Tim Stutzle', 'team': 'OTT'}, {'id': 2, 'name': 'John Smith', 'team': 'NYR'}]
    assert resolve_player('Tim Stützle', players, {})['id'] == 1
    assert resolve_player('J. Smith', players, {}) is None
    assert resolve_player('Johnny Smith', players, {'Johnny Smith': 2})['id'] == 2
    assert resolve_player('Johnny Smith', players, {'Johnny Smith': 3}) is None
    assert resolve_player('John Smith', players, {'John Smith': 1}) is None
    assert resolve_player('John Smith', players + [{'id': 3, 'name': 'John Smith'}], {}) is None
    assert resolve_player('John Smith', players + [{'id': 2, 'name': 'John Smith', 'team': 'CAR'}], {}) is None


def event():
    start = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    return {'id': 'abc123', 'commence_time': start, 'away_team': 'Florida Panthers', 'home_team': 'Carolina Hurricanes',
        'bookmakers': [{'key': 'fanduel', 'title': 'FanDuel', 'last_update': start, 'markets': [
            {'key': 'player_points', 'outcomes': [{'description': 'Sam Reinhart', 'name': 'Over', 'point': 0.5, 'price': -120},
                {'description': 'Sam Reinhart', 'name': 'Under', 'point': 0.5, 'price': 100},
                {'description': 'Wrong Player', 'name': 'Over', 'point': 0.5, 'price': 110}]},
            {'key': 'player_points_alternate', 'outcomes': [{'description': 'Sam Reinhart', 'name': 'Over', 'point': 1.5, 'price': 200}]},
            {'key': 'player_goal_scorer_anytime', 'outcomes': [{'description': 'Sam Reinhart', 'name': 'Yes', 'price': 160}]},
        ]}]}


def test_normalization_filters_books_invalid_prices_and_preserves_market_sides():
    body = event()
    body['bookmakers'].append({**body['bookmakers'][0], 'key': 'hardrockbet'})
    body['bookmakers'][0]['markets'][0]['outcomes'].extend([
        {'description': 'Sam Reinhart', 'name': 'Over', 'point': 2.5, 'price': float('inf')},
        {'description': 'Sam Reinhart', 'name': 'Over', 'price': 120},
    ])
    result = normalize_props(body, [{'id': 13, 'name': 'Sam Reinhart', 'team': 'FLA'}], {})
    p = result['players']['13']
    assert result['unmatched_names'] == ['Wrong Player']
    assert len(p['markets']['points']) == 2
    assert p['markets']['points'][1]['alternate']
    assert {q['side'] for q in p['markets']['points'][0]['quotes']} == {'over', 'under'}
    assert {q['bookmaker'] for line in p['markets']['points'] for q in line['quotes']} == {'fanduel'}
    assert p['markets']['anytime'][0]['point'] is None
    assert p['markets']['anytime'][0]['quotes'][0]['side'] == 'yes'


@pytest.mark.parametrize('mode', ['success', 'no_key', 'started', 'postponed', 'schedule_failure', 'roster_failure', 'mismatch', 'ambiguous', 'quota', 'empty'])
def test_explicit_fetch_cache_rosters_identity_and_provider_failures(tmp_path, monkeypatch, mode):
    monkeypatch.setenv('THE_ODDS_API_KEY', 'SECRET')
    if mode == 'no_key': monkeypatch.delenv('THE_ODDS_API_KEY')
    async def run():
        store = Store(tmp_path / 'test.sqlite3')
        e = event()
        game = {'id': 2026020001, 'startTimeUTC': e['commence_time'], 'awayTeam': {'abbrev': 'FLA'},
                'homeTeam': {'abbrev': 'CAR'}, 'gameState': 'LIVE' if mode == 'started' else 'FUT',
                'gameScheduleState': 'PPD' if mode == 'postponed' else 'OK'}
        class Providers:
            async def nhl(self, path, ttl):
                if path.startswith('score'):
                    return Feed(None if mode == 'schedule_failure' else {'games': [game]}, 'NHL', 'safe')
                name = ('Sam', 'Reinhart') if '/FLA/' in path else ('Sebastian', 'Aho')
                return Feed(None if mode == 'roster_failure' else {'forwards': [
                    {'id': 13 if '/FLA/' in path else 20, 'firstName': {'default': name[0]}, 'lastName': {'default': name[1]}}]}, 'NHL', 'safe-roster')
        p = Providers(); p.store = store
        calls = []
        def respond(request):
            calls.append(request)
            if mode == 'quota': return httpx.Response(429)
            if request.url.path.endswith('/events'):
                return httpx.Response(200, json=[e, e] if mode == 'ambiguous' else [e])
            assert request.url.params['bookmakers'].split(',') == list(BOOKS)
            assert 'regions' not in request.url.params
            assert request.url.params['markets'].split(',') == list(MARKETS)
            payload = {**e, 'home_team': 'Boston Bruins'} if mode == 'mismatch' else e
            if mode == 'empty': payload = {**e, 'bookmakers': []}
            return httpx.Response(200, json=payload, headers={'x-requests-remaining': '100'})
        await store.client.aclose(); store.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        service = PlayerProps(p)
        initial = await service.view('2026-09-29')
        assert not calls
        a, b = await asyncio.gather(service.view('2026-09-29', refresh=True), service.view('2026-09-29', refresh=True))
        if mode == 'success':
            assert set(a['games']['2026020001']['players']) == {'13'}
            assert len(calls) == 2
            store.db.execute('UPDATE player_prop_odds SET fetched=0,attempted=0'); store.db.commit()
            def fail(request): return httpx.Response(403)
            await store.client.aclose(); store.client = httpx.AsyncClient(transport=httpx.MockTransport(fail))
            stale = await service.view('2026-09-29', refresh=True)
            assert stale['games']['2026020001']['status'] == 'stale'
            assert stale['games']['2026020001']['players']
            game['gameScheduleState'] = 'PPD'
            assert not (await service.view('2026-09-29'))['games']['2026020001']['players']
        elif mode != 'schedule_failure':
            assert not a['games']['2026020001']['players']
        if mode in ['no_key', 'started', 'postponed', 'schedule_failure']: assert not calls
        if mode in ['quota', 'roster_failure', 'ambiguous']: assert len(calls) == 1
        assert 'SECRET' not in json.dumps([initial, a, b])
        assert 'SECRET' not in '\n'.join(store.db.iterdump())
        await store.close()
    asyncio.run(run())
