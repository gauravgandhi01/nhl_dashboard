import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from backend.cache import Store, Feed
import backend.first_period_odds as first_period_module
import backend.odds_client as odds_client_module
from backend.first_period_odds import FirstPeriodOdds, event_game, market_price
from backend.odds_config import configured_bookmakers


def event():
    return {'id':'abc123','commence_time':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),
            'away_team':'Chicago Blackhawks','home_team':'Florida Panthers'}


def game():
    e=event()
    return {'id':2026020001,'startTimeUTC':e['commence_time'],'awayTeam':{'abbrev':'CHI'},'homeTeam':{'abbrev':'FLA'},'gameState':'FUT','gameScheduleState':'OK'}


def market(point=1.5):
    return {'bookmakers':[{'key':'fanduel','last_update':'2026-09-27T12:00:00Z','markets':[{'key':'totals_p1',
        'outcomes':[{'name':'Over','point':point,'price':-110},{'name':'Under','point':point,'price':100}]}]}]}


def test_market_matching_and_actual_total():
    assert event_game(event(),[game()])['id']==2026020001
    assert event_game(event(),[game(),game()]) is None
    assert event_game({**event(),'away_team':'Unknown'},[game()]) is None
    assert event_game({**event(),'commence_time':'2020-01-01T00:00:00Z'},[game()]) is None
    assert market_price(market(2.5))['total']==2.5
    assert market_price({'bookmakers':[{**market()['bookmakers'][0],'key':'draftkings','title':'DraftKings'}]}, ['fanduel']) is None
    assert market_price({'bookmakers':[{**market()['bookmakers'][0],'key':'draftkings','title':'DraftKings'}]}, ['draftkings'])['name']=='DraftKings'
    assert market_price({'bookmakers':[]}) is None
    m=market();m['bookmakers'][0]['markets'][0]['outcomes'].pop()
    assert market_price(m) is None


@pytest.mark.parametrize('mode',['success','bookmaker_filter','no_key','quota','missing','mismatch','failure','started'])
def test_odds_opt_in_caching_quota_and_secret_redaction(tmp_path,monkeypatch,mode):
    keys_path = tmp_path / 'keys.json'
    keys_path.write_text(json.dumps({'api_keys': [] if mode == 'no_key' else ['SECRET_TEST_KEY']}))
    monkeypatch.setattr(odds_client_module, 'KEYS_PATH', keys_path)
    if mode=='bookmaker_filter':
        monkeypatch.setattr(first_period_module, 'market_params',
                            lambda extra=None: {**(extra or {}), 'bookmakers': 'fanduel,espnbet'})
        monkeypatch.setattr(first_period_module, 'configured_bookmakers',
                            lambda: ['fanduel', 'espnbet'])
        monkeypatch.setattr(first_period_module, 'odds_scope',
                            lambda: {'regions': 'us,us2,us_ex', 'bookmakers': ['fanduel', 'espnbet'], 'mode': 'bookmakers'})
    async def scenario():
        store=Store(tmp_path/'odds.sqlite3');calls=[]
        g=game()
        if mode=='started': g['gameState']='LIVE'
        class Fake:
            async def nhl(self,*args):return Feed({'games':[g]},'NHL','safe-schedule')
        fake=Fake();fake.store=store
        def respond(request):
            calls.append(request.url)
            if mode=='failure':return httpx.Response(403)
            if request.url.path.endswith('/events'):
                return httpx.Response(200,json=[event()],headers={'x-requests-remaining':'0' if mode=='quota' else '100'})
            if mode=='bookmaker_filter':
                assert request.url.params['bookmakers']=='fanduel,espnbet'
                assert 'regions' not in request.url.params
            else:
                assert request.url.params['bookmakers']==','.join(configured_bookmakers())
                assert 'regions' not in request.url.params
            body={**event(),**market()}
            if mode=='missing':body['bookmakers']=[]
            if mode=='mismatch':body['home_team']='Boston Bruins'
            return httpx.Response(200,json=body)
        await store.client.aclose();store.client=httpx.AsyncClient(transport=httpx.MockTransport(respond))
        odds=FirstPeriodOdds(fake)
        assert not odds.cached('2026-09-28')['prices'] and not calls
        results=await asyncio.gather(odds.refresh('2026-09-28'),odds.refresh('2026-09-28'))
        if mode in ['success','bookmaker_filter']:
            assert results[0]['prices']['2026020001']['total']==1.5
            assert results[0]['odds_scope']['mode']=='bookmakers'
            assert len(calls)==2
            forced=await odds.refresh('2026-09-28', force=True)
            assert forced['prices']['2026020001']['total']==1.5
            assert len(calls)==4
            store.db.execute('UPDATE first_period_odds SET fetched=0,attempted=0');store.db.commit()
            async def fail(request):return httpx.Response(403)
            await store.client.aclose();store.client=httpx.AsyncClient(transport=httpx.MockTransport(fail))
            stale=await odds.refresh('2026-09-28')
            assert stale['status']=='stale' and stale['prices']
        elif mode in ['no_key','started']:assert not calls
        elif mode=='quota':assert len(calls)==1 and not results[0]['prices']
        else:assert not results[0]['prices']
        assert 'SECRET_TEST_KEY' not in json.dumps(results)
        assert 'SECRET_TEST_KEY' not in '\n'.join(store.db.iterdump())
        await store.close()
    asyncio.run(scenario())
