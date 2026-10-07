"""Drop caches the current season does not read, without removing the stats it shows."""
from __future__ import annotations

import logging
import re
import shutil
import sqlite3
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import unquote

from .service import today_et
from .stats import season_for_date

logger = logging.getLogger(__name__)
DAY = 24 * 60 * 60
GAME_LOG = re.compile(r'/game-log/(\d{8})/')
CLUB_SCHEDULE = re.compile(r'/club-schedule-season/[^/]+/(\d{8})')
SEASON_ID = re.compile(r'seasonId=(\d{8})')
MONEYPUCK_YEAR = re.compile(r'/seasonPlayersSummary/(?:skaters|goalies)/(\d{4})\.zip')
SCORE_DATE = re.compile(r'/score/(\d{4}-\d{2}-\d{2})')
GOALIE_DATE = re.compile(r'/starting-goalies/(\d{4}-\d{2}-\d{2})')


def compact(store, *, vacuum=False, keep_cutoff=None):
    """Delete prior-season rows and rebuildable snapshots. Vacuum only when asked and disk allows."""
    today = today_et()
    season = season_for_date(today)
    season_start = f'{season // 10000}-07-01'
    cutoff = (date.fromisoformat(today) - timedelta(days=2)).isoformat()
    now = time.time()
    deleted = {
        'responses': _delete_responses(store, season, cutoff, now),
        'moneypuck_rows': _delete_where(store, 'moneypuck_rows', 'season != ?', (season,)),
        'first_period_games': _delete_where(store, 'first_period_games', 'season != ?', (season,)),
        'player_dashboards': _delete_player_dashboards(store, now),
        'goalie_dashboards': _delete_goalie_dashboards(store, now),
        'streak_snapshots': _delete_where(
            store, 'streak_snapshots',
            'cutoff < ? AND cutoff != ?' if keep_cutoff else 'cutoff < ?',
            (today, keep_cutoff) if keep_cutoff else (today,)),
        'moneyline_odds': _delete_where(store, 'moneyline_odds', 'date < ?', (season_start,)),
        'first_period_odds': _delete_where(store, 'first_period_odds', 'date < ?', (season_start,)),
        'player_prop_odds': _delete_where(
            store, 'player_prop_odds', 'game_id < ? OR game_id >= ?',
            (season // 10000 * 1000000, (season // 10000 + 1) * 1000000)),
    }
    if _table(store, 'game_stats'):
        store.db.execute('DROP TABLE game_stats')
        deleted['game_stats'] = 1
    store.db.commit()
    if vacuum and _space_for_vacuum(store.path):
        try:
            store.db.execute('VACUUM')
        except sqlite3.DatabaseError:
            logger.warning('SQLite vacuum skipped after retention', exc_info=True)
    elif vacuum:
        logger.info('SQLite vacuum skipped; free disk is not larger than %s', store.path)
    logger.info('Retention kept season %s and removed %s', season, deleted)
    return deleted


def _table(store, name):
    return store.db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _delete_where(store, table, clause, params):
    if not _table(store, table):
        return 0
    cursor = store.db.execute(f'DELETE FROM {table} WHERE {clause}', params)
    return cursor.rowcount


def _delete_player_dashboards(store, now):
    from .players import PLAYERS_TTL
    return _delete_where(store, 'player_dashboards', 'fetched < ?', (now - PLAYERS_TTL,))


def _delete_goalie_dashboards(store, now):
    from .players import PLAYERS_TTL
    return _delete_where(store, 'goalie_dashboards', 'fetched < ?', (now - PLAYERS_TTL,))


def _delete_responses(store, season, cutoff, now):
    if not _table(store, 'responses'):
        return 0
    rows = store.db.execute('SELECT key, url, fetched FROM responses').fetchall()
    drop = [key for key, url, fetched in rows if _drop_response(url or '', fetched or 0, season, cutoff, now)]
    store.db.executemany('DELETE FROM responses WHERE key=?', [(key,) for key in drop])
    return len(drop)


def _drop_response(url, fetched, season, cutoff, now):
    text = unquote(url)
    if 'play-by-play' in text or 'gameDate<' in text:
        return True
    game_log = GAME_LOG.search(text)
    if game_log:
        return int(game_log.group(1)) != season
    schedule = CLUB_SCHEDULE.search(text)
    if schedule:
        return int(schedule.group(1)) != season
    if '/stats/rest/' in text:
        found = SEASON_ID.search(text)
        return bool(found and int(found.group(1)) != season)
    archive = MONEYPUCK_YEAR.search(text)
    if archive:
        return int(archive.group(1)) != season // 10000
    if '/v1/score/' in text:
        found = SCORE_DATE.search(text)
        if found and found.group(1) < cutoff:
            return True
        return bool(fetched and now - fetched > 2 * DAY)
    if '/landing' in text or 'dailyfaceoff.com' in text:
        found = GOALIE_DATE.search(text)
        if found and found.group(1) < cutoff:
            return True
        return bool(fetched and now - fetched > 2 * DAY)
    return False


def _space_for_vacuum(path: Path) -> bool:
    size = path.stat().st_size if path.exists() else 0
    wal = Path(str(path) + '-wal')
    if wal.exists():
        size += wal.stat().st_size
    return shutil.disk_usage(path.parent).free > size
