import asyncio
import hashlib
import json
import time
from collections import namedtuple

from backend.cache import Store
from backend.players import player_windows
from backend.retention import _space_for_vacuum, compact
from backend.service import today_et
from backend.stats import season_for_date
from backend.streaks import entries_for, normalize


def put(store, url, body=b'{}', fetched=None):
    store.db.execute(
        'INSERT INTO responses VALUES(?,?,?,?,?,0,NULL)',
        (hashlib.sha256(url.encode()).hexdigest(), url, 'NHL', body, time.time() if fetched is None else fetched),
    )


def test_vacuum_runs_only_when_free_space_exceeds_the_file(tmp_path, monkeypatch):
    path = tmp_path / 'disk.sqlite3'
    path.write_bytes(b'x' * 64)
    usage = namedtuple('Usage', 'total used free')
    monkeypatch.setattr('backend.retention.shutil.disk_usage', lambda parent: usage(1, 1, 0))
    assert not _space_for_vacuum(path)
    monkeypatch.setattr('backend.retention.shutil.disk_usage', lambda parent: usage(1, 1, 10**12))
    assert _space_for_vacuum(path)


def test_compaction_keeps_current_season_stats_and_drops_the_rest(tmp_path, monkeypatch):
    monkeypatch.setattr('backend.retention._space_for_vacuum', lambda path: False)
    store = Store(tmp_path / 'retain.sqlite3')
    today = today_et()
    season = season_for_date(today)
    previous = season - 10001
    log = {'gameId': int(f'{season // 10000}020001'), 'gameDate': f'{season // 10000}-10-02', 'toi': '12:00',
           'goals': 1, 'assists': 1, 'points': 2, 'shots': 3, 'powerPlayPoints': 0}
    advanced = {'playerId': '1', 'gameId': str(log['gameId']), 'situation': 'all', 'icetime': 600,
                'I_F_shotAttempts': 4, 'I_F_points': 2, 'I_F_shotsOnGoal': 3, 'I_F_xGoals': 0.4,
                'I_F_highDangerShots': 1}
    current_log = f'https://api-web.nhle.com/v1/player/1/game-log/{season}/2'
    stat_cutoff = f'{season // 10000 + 1}-04-01'
    windows = player_windows([log], [advanced], stat_cutoff, season)
    player = {'id': 1, 'name': 'Current Skater', 'kind': 'skater', 'team': 'BOS',
              'position': 'C', 'position_group': 'forward'}
    streak = entries_for(player, normalize([log], stat_cutoff, season), True)

    put(store, current_log, json.dumps([log]).encode())
    put(store, f'https://api-web.nhle.com/v1/player/1/game-log/{previous}/2', b'old-log')
    put(store, f'https://api-web.nhle.com/v1/club-schedule-season/BOS/{season}', b'schedule')
    put(store, f'https://api-web.nhle.com/v1/club-schedule-season/BOS/{previous}', b'old-schedule')
    put(store, f'https://api.nhle.com/stats/rest/en/team/goalsbyperiod?cayenneExp=seasonId%3D{season}%20and%20gameTypeId%3D2', b'goals')
    put(store, f'https://api.nhle.com/stats/rest/en/skater/summary?cayenneExp=seasonId%3D{season}%20and%20gameDate%3C%27{today}%27', b'daily')
    put(store, f'https://api.nhle.com/stats/rest/en/team/summary?cayenneExp=seasonId%3D{previous}%20and%20gameTypeId%3D2', b'old-stats')
    put(store, 'https://api-web.nhle.com/v1/gamecenter/2025020001/play-by-play', b'old-pbp')
    put(store, 'https://api-web.nhle.com/v1/gamecenter/2026020001/play-by-play', b'new-pbp')
    put(store, f'https://api-web.nhle.com/v1/score/{today}', b'today')
    put(store, 'https://api-web.nhle.com/v1/score/2020-01-01', b'old-score')
    put(store, 'https://api-web.nhle.com/v1/roster/BOS/current', b'roster', fetched=time.time() - 10 * 24 * 3600)
    put(store, 'https://api-web.nhle.com/v1/gamecenter/2026020001/landing', b'landing', fetched=time.time() - 3 * 24 * 3600)
    put(store, 'https://www.dailyfaceoff.com/starting-goalies/2020-01-01', b'old-goalies', fetched=time.time())
    put(store, 'https://www.dailyfaceoff.com/teams/boston-bruins/line-combinations', b'lines')
    store.save_moneypuck('skaters', previous, [{'playerId': '9', 'gameId': '2025020001', 'situation': 'all'}], 'playerId')
    store.save_moneypuck('skaters', season, [advanced], 'playerId')
    store.db.executescript(f"""
        CREATE TABLE first_period_games (
            season INTEGER, game_id INTEGER, version INTEGER, body TEXT, fetched REAL,
            attempted REAL, error TEXT, PRIMARY KEY(season, game_id));
        CREATE TABLE player_dashboards (date TEXT PRIMARY KEY, body TEXT, fetched REAL, error TEXT);
        CREATE TABLE streak_snapshots (cutoff TEXT PRIMARY KEY, body TEXT, fetched REAL, attempted REAL, error TEXT);
        CREATE TABLE moneyline_odds (date TEXT PRIMARY KEY, body TEXT, fetched REAL, attempted REAL, error TEXT);
        CREATE TABLE first_period_odds (date TEXT PRIMARY KEY, body TEXT, fetched REAL, attempted REAL, error TEXT);
        CREATE TABLE player_prop_odds (
            game_id INTEGER PRIMARY KEY, version TEXT, body TEXT, fetched REAL, attempted REAL, error TEXT);
        CREATE TABLE stanley_cup_odds (id TEXT PRIMARY KEY, body TEXT, fetched REAL, attempted REAL);
        CREATE TABLE game_stats (
            provider TEXT, season INTEGER, entity TEXT, game_id TEXT, body TEXT,
            PRIMARY KEY(provider, season, entity, game_id));
        INSERT INTO first_period_games VALUES ({previous}, 2025020001, 1, '{{"goalies":[]}}', 1, 1, NULL);
        INSERT INTO first_period_games VALUES ({season}, {log['gameId']}, 1, '{{"goalies":[{{"sa":1}}]}}', 1, 1, NULL);
        INSERT INTO player_dashboards VALUES ('2020-01-01', '{{"version":2}}', {time.time() - 7200}, NULL);
        INSERT INTO player_dashboards VALUES ('{today}', '{{"version":2,"kept":true}}', {time.time()}, NULL);
        INSERT INTO streak_snapshots VALUES ('2020-01-01', '{{"entries":{{}}}}', {time.time()}, {time.time()}, NULL);
        INSERT INTO moneyline_odds VALUES ('2020-01-01', '{{}}', 1, 1, NULL);
        INSERT INTO moneyline_odds VALUES ('{today}', '{{"prices":{{"home":1}}}}', 1, 1, NULL);
        INSERT INTO first_period_odds VALUES ('2020-01-01', '{{}}', 1, 1, NULL);
        INSERT INTO first_period_odds VALUES ('{today}', '{{"prices":{{}}}}', 1, 1, NULL);
        INSERT INTO player_prop_odds VALUES (2025020001, '1', '{{}}', 1, 1, NULL);
        INSERT INTO player_prop_odds VALUES ({log['gameId']}, '1', '{{"players":{{}}}}', 1, 1, NULL);
        INSERT INTO stanley_cup_odds VALUES ('fanduel', '{{"odds":1}}', 1, 1);
        INSERT INTO game_stats VALUES ('nhl_skater', {season}, '1', '{log['gameId']}', '{{}}');
    """)
    store.db.execute(
        'INSERT INTO streak_snapshots VALUES (?,?,?,?,NULL)',
        (today, json.dumps({'entries': streak}), time.time(), time.time()))
    store.db.commit()

    deleted = compact(store, vacuum=True)
    urls = {row[0] for row in store.db.execute('SELECT url FROM responses')}
    assert current_log in urls
    assert f'https://api-web.nhle.com/v1/club-schedule-season/BOS/{season}' in urls
    assert f'https://api.nhle.com/stats/rest/en/team/goalsbyperiod?cayenneExp=seasonId%3D{season}%20and%20gameTypeId%3D2' in urls
    assert f'https://api-web.nhle.com/v1/score/{today}' in urls
    assert 'https://api-web.nhle.com/v1/roster/BOS/current' in urls
    assert 'https://www.dailyfaceoff.com/teams/boston-bruins/line-combinations' in urls
    assert all('play-by-play' not in url for url in urls)
    assert all(str(previous) not in url for url in urls)
    assert all('gameDate' not in url for url in urls)
    assert 'https://api-web.nhle.com/v1/score/2020-01-01' not in urls
    assert 'https://api-web.nhle.com/v1/gamecenter/2026020001/landing' not in urls
    assert 'https://www.dailyfaceoff.com/starting-goalies/2020-01-01' not in urls

    kept_log = json.loads(store.db.execute('SELECT body FROM responses WHERE url=?', (current_log,)).fetchone()[0])
    kept_mp = json.loads(store.db.execute(
        'SELECT body FROM moneypuck_rows WHERE season=?', (season,)).fetchone()[0])
    assert player_windows(kept_log, [kept_mp], stat_cutoff, season) == windows
    assert entries_for(player, normalize(kept_log, stat_cutoff, season), True) == streak
    assert store.db.execute('SELECT season FROM moneypuck_rows').fetchall() == [(season,)]
    assert store.db.execute('SELECT season, body FROM first_period_games').fetchall() == [
        (season, '{"goalies":[{"sa":1}]}')]
    assert store.db.execute('SELECT date FROM player_dashboards').fetchall() == [(today,)]
    assert json.loads(store.db.execute('SELECT body FROM streak_snapshots').fetchone()[0])['entries'] == streak
    assert store.db.execute('SELECT date FROM moneyline_odds').fetchall() == [(today,)]
    assert store.db.execute('SELECT date FROM first_period_odds').fetchall() == [(today,)]
    assert store.db.execute('SELECT game_id FROM player_prop_odds').fetchall() == [(log['gameId'],)]
    assert store.db.execute('SELECT id FROM stanley_cup_odds').fetchall() == [('fanduel',)]
    assert store.db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='game_stats'").fetchone() is None
    assert deleted['responses'] > 0
    assert deleted['game_stats'] == 1
    asyncio.run(store.close())
