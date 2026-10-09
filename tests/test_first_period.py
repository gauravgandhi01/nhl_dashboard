import asyncio
import hashlib
import time
from copy import deepcopy
from pathlib import Path

import pytest

from backend.cache import Feed, Store
from backend.first_period import FirstPeriod
from backend.first_period_stats import team_games, extract_goalies, windows, goalie_ranks


def pair(gid=2025020001, date='2025-10-07', a=1, h=2):
    return [dict(gameId=gid, gameDate=date, teamId=16, teamFullName='Chicago Blackhawks', homeRoad='R',
                 opponentTeamAbbrev='FLA', period1GoalsFor=a, period1GoalsAgainst=h, wins=0, losses=1, otLosses=0),
            dict(gameId=gid, gameDate=date, teamId=13, teamFullName='Florida Panthers', homeRoad='H',
                 opponentTeamAbbrev='CHI', period1GoalsFor=h, period1GoalsAgainst=a, wins=1, losses=0, otLosses=0)]


def game():
    return team_games(pair(), '2026-01-01')[0][0]


def goalie_rows():
    return [dict(gameId=2025020001, playerId=1, teamAbbrev='CHI', gamesStarted=1, goalieFullName='Away Goalie'),
            dict(gameId=2025020001, playerId=2, teamAbbrev='FLA', gamesStarted=1, goalieFullName='Home Goalie')]


def event(team, goalie=None, kind='goal', situation='1551'):
    return {'periodDescriptor': {'number': 1}, 'typeDescKey': kind, 'situationCode': situation,
            'details': {'eventOwnerTeamId': team, **({'goalieInNetId': goalie} if goalie else {})}}


def pbp():
    return {'id': 2025020001, 'gameState': 'OFF', 'homeTeam': {'id': 13}, 'awayTeam': {'id': 16},
            'plays': [event(16, 2), event(13, 1), event(13, 1), event(16, 2, 'shot-on-goal'),
                      event(13, 1, 'shot-on-goal'), event(13, kind='period-end')]}


def test_team_pair_validation_and_cutoff():
    games, rejected = team_games(pair() + pair(2025020002, '2026-01-01'), '2026-01-01')
    assert len(games) == 1 and not rejected
    assert games[0]['away']['abbrev'] == 'CHI'
    for bad in [pair()[:1], pair() + pair(), [{**pair()[0], 'period1GoalsFor': None}, pair()[1]],
                [{**pair()[0], 'period1GoalsFor': 9}, pair()[1]],
                [{**pair()[0], 'losses': 0}, pair()[1]]]:
        assert team_games(bad, '2026-01-01')[0] == []


def test_team_windows_small_samples_and_counts():
    rows = [{'gameId': i, 'date': f'2025-11-{i:02}', 'gf': 1, 'ga': i % 2} for i in range(1,13)]
    w = windows(rows)
    assert w['season']['games'] == 12 and w['season']['hits'] == 6
    assert w['last5']['games'] == 5 and w['last10']['games'] == 10
    assert windows(rows[:2])['last10']['games'] == 2
    assert windows([])['season']['hit_pct'] is None


def window_row(games, ga_pg, sv, allow_pct):
    played = {'games': games, 'ga_pg': ga_pg, 'sv': sv, 'allow_pct': allow_pct}
    return {'season': played, 'last5': played, 'last10': played}


def test_goalie_ranks_use_one_appearance_not_the_opponent():
    rows = {
        1: window_row(1, 2.0, .9, 80),
        2: window_row(6, 1.0, .8, 50),
        3: window_row(1, 1.0, None, 50),
        4: window_row(0, None, None, None),
    }
    rows[1]['last5'] = {'games': 1, 'ga_pg': 0.0, 'sv': .5, 'allow_pct': 0}
    ranks = goalie_ranks(rows)
    assert ranks[1]['season']['ga_pg'] == {'rank': 3, 'eligible': 3}
    assert ranks[2]['season']['ga_pg'] == {'rank': 1, 'eligible': 3}
    assert ranks[3]['season']['ga_pg'] == {'rank': 1, 'eligible': 3}
    assert ranks[4]['season']['ga_pg'] == {'rank': None, 'eligible': 3}
    assert ranks[1]['season']['sv'] == {'rank': 1, 'eligible': 2}
    assert ranks[2]['season']['sv'] == {'rank': 2, 'eligible': 2}
    assert ranks[3]['season']['sv'] == {'rank': None, 'eligible': 2}
    assert ranks[1]['season']['allow_pct']['rank'] == 3
    assert ranks[2]['season']['allow_pct']['rank'] == 1
    assert ranks[4]['last5']['sv']['rank'] is None
    assert ranks[1]['last5']['ga_pg'] == {'rank': 1, 'eligible': 3}
    assert ranks[1]['last5']['sv'] == {'rank': 2, 'eligible': 2}


def test_exact_goalie_totals_and_weighted_percentages():
    result = extract_goalies(game(), pbp(), goalie_rows())
    p = next(p for p in result['goalies'] if p['playerId'] == 1)
    assert (p['ga'], p['sa'], p['saves']) == (2,3,1)
    w = windows([p, {**p, 'gameId': 2025020002, 'date': '2025-10-08', 'ga': 0, 'sa': 7, 'saves': 7, 'teamId': 99}], True)
    assert w['season']['sv'] == .8
    assert w['season']['allow_pct'] == 50
    assert w['season']['games'] == 2  # Player identity survives a trade.


def test_empty_net_and_zero_shot_starter():
    g = team_games(pair(a=0,h=1), '2026-01-01')[0][0]
    data = pbp()
    data['plays'] = [event(13, situation='0551'), event(13, kind='period-end')]
    result = extract_goalies(g,data,goalie_rows())
    assert len(result['goalies']) == 2
    assert all(p['sa'] == p['ga'] == 0 for p in result['goalies'])
    w = windows(result['goalies'][:1], True)['season']
    assert w['games'] == 1 and w['allow_pct'] == 0 and w['sv'] is None


def test_goalie_changes_and_unresolved_relief():
    rows = goalie_rows()+[dict(gameId=2025020001,playerId=3,teamAbbrev='CHI',gamesStarted=0,goalieFullName='Relief')]
    data = pbp()
    data['plays'][2]['details']['goalieInNetId'] = 3
    result = extract_goalies(game(),data,rows)
    assert {p['playerId'] for p in result['goalies'] if p['partial']} == {1,3}
    assert not result['warnings']
    unresolved = extract_goalies(game(),pbp(),rows)
    assert unresolved['warnings'] and len(unresolved['goalies']) == 2


def test_unknown_goalie_events_are_not_zero_filled():
    data = pbp()
    del data['plays'][0]['details']['goalieInNetId']
    result = extract_goalies(game(),data,goalie_rows())
    assert not result['complete']
    assert [p['playerId'] for p in result['goalies']] == [1]


@pytest.mark.parametrize('change', ['unfinished','identity','goals','starter','period'])
def test_invalid_sources_rejected(change):
    data, rows = pbp(), goalie_rows()
    if change == 'unfinished': data['gameState'] = 'LIVE'
    if change == 'identity': data['id'] = 2
    if change == 'goals': data['plays'].pop(0)
    if change == 'starter': rows.pop()
    if change == 'period': data['plays'].pop()
    with pytest.raises(ValueError): extract_goalies(game(),data,rows)


class Fake:
    def __init__(self, store):
        self.store, self.calls, self.failure = store, [], False
        self.season = 20262027
        self.pbp_store_body = True
    async def stats(self, report, season, *args, **kwargs):
        self.calls.append((report,season))
        rows = [] if season == 20262027 else goalie_rows() if report == 'goalie/summary' else pair()
        return Feed(None if self.failure else rows, 'NHL', report)
    async def goalies(self,*args): return Feed([], 'DFO', 'goalies')
    async def nhl(self, path, *args, **kwargs):
        self.calls.append(path)
        if 'play-by-play' in path:
            self.pbp_store_body = kwargs.get('store_body', True)
        if path.startswith('score'):
            data={'games':[{'id':2026010001,'season':self.season,'gameDate':'2026-09-27','startTimeUTC':'2026-09-27T23:00:00Z',
                'awayTeam':{'id':16,'abbrev':'CHI'},'homeTeam':{'id':13,'abbrev':'FLA'}}]}
        elif path.startswith('roster'):
            data={'goalies':[{'id':1 if 'CHI' in path else 2,'firstName':{'default':'Test'},'lastName':{'default':'Goalie'}}]}
        else: data=pbp()
        return Feed(data,'NHL',path)


def test_build_dedup_current_season_persistence_and_failure(tmp_path):
    async def scenario():
        store = Store(tmp_path/'first.sqlite3'); fake=Fake(store); service=FirstPeriod(fake)
        try:
            url = 'gamecenter/2025020001/play-by-play'
            store.db.execute('INSERT INTO responses VALUES(?,?,?,?,?,0,NULL)', (
                hashlib.sha256(url.encode()).hexdigest(), url, 'NHL', b'raw-play-by-play', time.time()))
            store.db.commit()
            fake.season = 20252026
            first = await service.view('2026-09-27')
            assert not first['previous_season'] and first['season_label']=='2025-26'
            assert first['rankings'][0]['windows']['season']['hits']==1
            task = service.tasks[20252026]
            service.ensure_build(20252026,[game()])
            assert service.tasks[20252026] is task
            await task
            result = await service.view('2026-09-27')
            assert result['coverage']['goalie_games']==1
            assert result['matchups'][0]['away']['goalies'][0]['windows']['season']['ga_total']==2
            away_rank = result['matchups'][0]['away']['goalies'][0]['rank']['season']
            home_rank = result['matchups'][0]['home']['goalies'][0]['rank']['season']
            assert away_rank['ga_pg'] == {'rank': 2, 'eligible': 2}
            assert home_rank['ga_pg'] == {'rank': 1, 'eligible': 2}
            assert away_rank['sv'] == {'rank': 2, 'eligible': 2}
            assert home_rank['sv'] == {'rank': 1, 'eligible': 2}
            assert away_rank['allow_pct']['rank'] == 1 and home_rank['allow_pct']['rank'] == 1
            by_id = {goalie['id']: goalie for goalie in result['goalie_rankings']}
            assert set(by_id) == {1, 2}
            assert by_id[1]['abbrev'] == 'CHI' and by_id[1]['playing'] is True
            assert by_id[2]['abbrev'] == 'FLA' and by_id[2]['windows']['season']['games'] == 1
            assert [goalie['id'] for goalie in result['goalie_rankings']] == [2, 1]
            assert fake.calls.count('gamecenter/2025020001/play-by-play')==1
            assert fake.pbp_store_body is False
            assert store.db.execute('SELECT body FROM responses WHERE url=?', (url,)).fetchone() is None
            assert service.saved(20252026)[2025020001]['body']['goalies']
            held = fake.calls.count('gamecenter/2025020001/play-by-play')
            service.ensure_build(20252026, [game()])
            assert fake.calls.count('gamecenter/2025020001/play-by-play') == held
            store.db.execute('UPDATE first_period_games SET fetched=0,attempted=0');store.db.commit()
            fake.failure=True
            service.ensure_build(20252026,[game()]);await service.tasks[20252026]
            assert service.saved(20252026)[2025020001]['body'] is not None
            assert service.saved(20252026)[2025020001]['error']
        finally: await service.close();await store.close()
    asyncio.run(scenario())


def test_empty_current_season_never_loads_previous_season(tmp_path):
    async def scenario():
        store = Store(tmp_path / 'empty.sqlite3'); fake = Fake(store); service = FirstPeriod(fake)
        try:
            result = await service.view('2026-09-27')
            assert result['season'] == 20262027 and not result['previous_season']
            assert result['coverage']['games'] == 0
            assert not service.tasks
            assert all(call[1] == 20262027 for call in fake.calls if isinstance(call, tuple))
            assert not any(isinstance(call, str) and 'play-by-play' in call for call in fake.calls)
            assert result['matchups'][0]['away']['windows']['season']['games'] == 0
            assert result['goalie_rankings'] == []
        finally:
            await service.close(); await store.close()
    asyncio.run(scenario())
