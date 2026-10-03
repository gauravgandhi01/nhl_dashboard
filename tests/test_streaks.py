import asyncio
from copy import deepcopy

import pytest

from backend.cache import Feed, Store
from backend.streaks import Streaks, metric, normalize, entries_for, top_ten


def row(i, year=2025, points=1, goals=1, **kwargs):
    return {'gameId': year * 1000000 + 20000 + i, 'gameDate': f'{year}-11-{i:02}',
            'toi': '20:00', 'points': points, 'goals': goals, 'shots': 3, **kwargs}


def player(kind='skater'):
    return {'id': 1, 'kind': kind, 'name': 'Test Player', 'team': 'CAR', 'position': 'C'}


def test_last10_current_season_dedup_and_cutoff():
    rows = normalize([row(i) for i in range(1,9)] + [row(1,2026), row(2,2026), row(2,2026), row(3,2026)], '2026-11-03')
    assert len(rows) == 2
    result = entries_for(player(), rows, True)['points10']
    assert result['value'] == 2 and result['sample_size'] == 2
    assert result['seasons'] == ['2026-27']
    assert result['end_date'] == '2026-11-02'


def test_active_streak_not_longest_historical_streak_or_limited_to_ten():
    rows = normalize([row(i) for i in range(1,16)], '2026-01-01')
    assert metric(rows, 'point_streak', True)['value'] == 15
    assert metric(rows, 'point_streak', False)['open']
    rows[0]['points'] = 0
    assert metric(rows, 'point_streak', True)['value'] == 0
    rows[0]['points'] = 1; rows[2]['points'] = 0
    assert metric(rows, 'point_streak', False)['value'] == 2
    assert not metric(rows, 'point_streak', False)['open']


def test_regular_only_zero_toi_and_conflicting_duplicates():
    rows = [row(1), {**row(2), 'gameId': 2025030002}, {**row(3), 'gameId': 2025010003}, row(4,toi='00:00')]
    assert len(normalize(rows,'2026-01-01')) == 1
    with pytest.raises(ValueError):normalize([row(1),row(1,points=9)],'2026-01-01')


def test_win_streak_uses_decisions_and_stops_on_ot_loss():
    rows = [row(6,decision='W'), row(5,decision=''), row(4,decision='W'), row(3,decision='O'), row(2,decision='W')]
    result = metric(rows,'win_streak',False)
    assert result['value']==2 and len(result['sample'])==2 and not result['open']
    rows[0]['decision']='L'
    assert metric(rows,'win_streak',True)['value']==0


def test_low_ga_starts_only_and_less_than_two_not_less_or_equal():
    rows = [row(5,gamesStarted=1,goalsAgainst=1,shutouts=0),row(4,gamesStarted=0,goalsAgainst=0,shutouts=0),
            row(3,gamesStarted=1,goalsAgainst=2,shutouts=0),row(2,gamesStarted=1,goalsAgainst=0,shutouts=1)]
    result=metric(rows,'low_ga10',True)
    assert result['value']==2 and len(result['sample'])==3
    assert metric(rows,'shutouts10',True)['value']==1


def test_incomplete_stats_not_zero_and_small_samples_explicit():
    rows = [row(2),row(1)]
    assert entries_for(player(),rows,True)['points10']['sample_size']==2
    rows[0]['points']=None
    assert metric(rows,'points10',True) is None
    assert metric(rows,'point_streak',True) is None
    assert 'points10' not in entries_for(player(),rows,False)


def test_top_ten_caps_ties_and_uses_latest_date_and_name():
    entries=[{'id':i,'name':f'Player {i:02}','value':10,'sample_size':10,'latest_game':'2026-01-01'} for i in range(15)]
    ranked=top_ten(entries)
    assert len(ranked)==10 and all(p['rank']==1 for p in ranked)
    assert ranked[0]['id']==0
    entries[14]['value']=11
    assert top_ten(entries)[1]['rank']==2


def test_history_stops_at_season_boundary_and_missing_feed_excludes(tmp_path):
    async def scenario():
        store=Store(tmp_path/'history.sqlite3')
        class Fake:
            missing=False
            async def nhl(self,path,*args):
                s=int(path.split('/')[-2])
                data={'seasonId':s,'gameTypeId':2,'playerStatsSeasons':[{'season':20252026,'gameTypes':[2]},{'season':20242025,'gameTypes':[2]}],
                      'gameLog':[row(i,2025 if s==20252026 else 2024) for i in range(1,7)]}
                if self.missing:data=None
                return Feed(data,'NHL',path)
        fake=Fake();fake.store=store;service=Streaks(fake)
        try:
            result,feeds=await service.history(player(),20252026,'2026-01-01')
            assert result['point_streak']['value']==6 and not result['point_streak']['lower_bound']
            assert len(feeds)==1 and result['points10']['sample_size']==6
            fake.missing=True
            assert (await service.history(player(),20252026,'2026-01-01'))[0] is None
        finally:await service.close();await store.close()
    asyncio.run(scenario())


def test_snapshot_build_dedup_slate_scope_failures_and_no_games(tmp_path,monkeypatch):
    monkeypatch.setattr('backend.streaks.TEAM_NAMES',{'CAR':'Carolina Hurricanes','BOS':'Boston Bruins'})
    async def scenario():
        store=Store(tmp_path/'service.sqlite3')
        class Fake:
            failed=False
            async def stats(self,report,season,*args,**kwargs):
                assert season == 20262027
                return Feed(None if self.failed else [{'playerId':1,'gamesPlayed':10}], 'NHL',report)
            async def nhl(self,path,*args):
                if path.startswith('score'):
                    data={'games':[{'id':2026010001,'awayTeam':{'abbrev':'CAR'},'homeTeam':{'abbrev':'BOS'}}]}
                elif path.startswith('roster'):
                    data={'forwards':[{'id':1,'firstName':{'default':'A'},'lastName':{'default':'Player'},'positionCode':'C'}]} if 'CAR' in path else {'forwards':[]}
                else:
                    season=int(path.split('/')[-2])
                    data={'seasonId':season,'gameTypeId':2,'playerStatsSeasons':[{'season':season,'gameTypes':[2]}],'gameLog':[{**row(i, 2026), 'gameDate': f'2026-09-{i:02}'} for i in range(1,12)]}
                return Feed(data,'NHL',path)
        fake=Fake();fake.store=store;service=Streaks(fake)
        try:
            import json, time
            store.db.execute('INSERT INTO streak_snapshots VALUES(?,?,?,?,NULL)',
                             ('2026-09-28', json.dumps({'entries': {'points10': [{'name': 'Old season'}]}}), time.time(), time.time()))
            store.db.commit()
            assert service.cached('2026-09-28') is None
            first=await service.view('2026-09-28')
            assert not first['ready']
            key=first['as_of'];task=service.tasks[key]
            service.ensure_build(key);assert service.tasks[key] is task
            await task
            view=await service.view('2026-09-28','tonight')
            assert view['ready'] and view['boards'][0]['entries'][0]['matchups'][0]['opponent']=='BOS'
            store.db.execute('UPDATE streak_snapshots SET fetched=0,attempted=0');store.db.commit()
            fake.failed=True;service.ensure_build(key);await service.tasks[key]
            view=await service.view('2026-09-28')
            assert view['ready'] and view['stale'] and view['error']
        finally:await service.close();await store.close()
    asyncio.run(scenario())


def test_toi_averages_by_span_and_position_not_total_minutes():
    rows = normalize([row(i, toi='30:00' if i > 5 else '10:00') for i in range(1, 13)], '2026-01-01')
    forward = entries_for(player(), rows, True)
    assert forward['toi_forward_last5']['value'] == 1800
    assert forward['toi_forward_last10']['value'] == 1440
    assert forward['toi_forward_season']['value'] == 1300
    assert forward['toi_forward_last5']['sample_size'] == 5
    assert forward['toi_forward_season']['sample_size'] == 12
    assert not any(key.startswith('toi_defense') for key in forward)
    defense = entries_for({**player(), 'position': 'D'}, rows, True)
    assert defense['toi_defense_last10']['value'] == 1440
    assert not any(key.startswith('toi_forward') for key in defense)
    unknown = entries_for({**player(), 'position': None}, rows, True)
    assert not any(key.startswith('toi_') for key in unknown)
    roster_group = entries_for({**player(), 'position': None, 'position_group': 'defense'}, rows, True)
    assert 'toi_defense_last10' in roster_group
    short = entries_for({**player(), 'id': 2}, rows[:2], True)['toi_forward_last10']
    assert short['sample_size'] == 2
    assert top_ten([forward['toi_forward_last10'], short])[0]['id'] == 2
    assert short['recent'][0]['value'] == '30:00'


def test_toi_excludes_bad_times_and_retains_small_current_season_samples():
    rows = normalize([row(1, 2026, toi='20:30'), row(2, 2026, toi='21:31'),
                      row(3, 2026, toi='00:00'), row(4, 2026, toi='20:99'),
                      row(5, 2026, toi='-1:30'), row(6, 2026, toi=None), row(1, 2025)], '2026-11-07')
    entry = entries_for(player(), rows, True)['toi_forward_last10']
    assert entry['sample_size'] == 2
    assert entry['value'] == 1260.5
    assert entry['seasons'] == ['2026-27']
    assert metric([row(1, toi='bad')], 'toi_forward_last5', True) is None


def test_toi_scope_window_and_snapshot_reuse(tmp_path):
    async def scenario():
        import json, time
        from backend.streaks import SNAPSHOT_VERSION
        store = Store(tmp_path / 'toi.sqlite3')
        class Fake:
            async def nhl(self, path, *args):
                assert path.startswith('score/')  # Changing spans must reuse player history.
                return Feed({'games': [{'id': 2025020001, 'awayTeam': {'abbrev': 'CAR'},
                                         'homeTeam': {'abbrev': 'BOS'}}]}, 'NHL', path)
        p = Fake(); p.store = store
        service = Streaks(p)
        all_entries = {}
        for identity, team, position, toi in [(1, 'CAR', 'C', '20:00'), (2, 'NYR', 'R', '25:00'), (3, 'BOS', 'D', '30:00')]:
            entries = entries_for({**player(), 'id': identity, 'team': team, 'position': position}, [row(1, toi=toi)], True)
            for key, entry in entries.items():
                all_entries.setdefault(key, []).append(entry)
        body = {'version': SNAPSHOT_VERSION, 'entries': all_entries}
        store.db.execute('INSERT INTO streak_snapshots VALUES(?,?,?,?,NULL)',
                         ('2026-01-01', json.dumps(body), time.time(), time.time()))
        store.db.commit()
        try:
            league = await service.view('2026-01-01', 'league', 'last5')
            toi = [b for b in league['boards'] if b['unit'] == 'seconds']
            assert len(toi) == 2 and all(b['id'].endswith('last5') for b in toi)
            assert toi[0]['entries'][0]['id'] == 2
            slate = await service.view('2026-01-01', 'tonight', 'season')
            toi = [b for b in slate['boards'] if b['unit'] == 'seconds']
            assert all(b['id'].endswith('season') for b in toi)
            assert toi[0]['entries'][0]['id'] == 1
            assert toi[1]['entries'][0]['id'] == 3
            assert not service.tasks
        finally:
            await service.close(); await store.close()
    asyncio.run(scenario())
