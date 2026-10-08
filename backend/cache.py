from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx


@dataclass
class Feed:
    data: Any
    source: str
    url: str
    retrieved_at: str | None = None
    stale: bool = False
    error: str | None = None

    def meta(self):
        return {"source": self.source, "url": self.url, "retrieved_at": self.retrieved_at,
                "status": "unavailable" if self.data is None else "stale" if self.stale else "available",
                "error": self.error}


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS responses (
                key TEXT PRIMARY KEY, url TEXT, source TEXT, body BLOB,
                fetched REAL, failed_until REAL DEFAULT 0, error TEXT);
        """)
        self.db.commit()
        self.path = path
        self.locks: dict[str, asyncio.Lock] = {}
        self.limit = asyncio.Semaphore(4)
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(45, connect=10), follow_redirects=True,
                                       headers={"User-Agent": "NHLMatchupDashboard/1.0 (personal research)"})

    async def close(self):
        await self.client.aclose()
        self.db.close()

    async def last_good(self, url: str, source: str, parser: Callable, error: str) -> Feed:
        """Read an existing response without attempting network access."""
        key = hashlib.sha256(url.encode()).hexdigest()
        row = self.db.execute('SELECT body,fetched FROM responses WHERE key=?', (key,)).fetchone()
        data = None
        try:
            if row and row[0] is not None:
                data = await asyncio.to_thread(parser, row[0])
        except (ValueError, KeyError, TypeError):
            pass
        stamp = datetime.fromtimestamp(row[1], timezone.utc).isoformat() if row and row[1] else None
        return Feed(data, source, url, stamp, data is not None, error)

    async def fetch(self, url: str, source: str, ttl: int, parser: Callable = json.loads,
                    params: dict | None = None, store_body: bool = True,
                    failure_ttl: int = 600, headers: dict | None = None) -> Feed:
        request_url = str(httpx.URL(url, params=params)) if params else url
        key = hashlib.sha256(request_url.encode()).hexdigest()
        async with self.locks.setdefault(key, asyncio.Lock()):
            row = self.db.execute("SELECT body,fetched,failed_until,error FROM responses WHERE key=?", (key,)).fetchone()
            now = time.time()

            async def cached(stale=False, error=None):
                try:
                    data = await asyncio.to_thread(parser, row[0]) if row and row[0] is not None else None
                except (ValueError, KeyError, TypeError):
                    data = None
                stamp = datetime.fromtimestamp(row[1], timezone.utc).isoformat() if row and row[1] else None
                return Feed(data, source, request_url, stamp, stale, error)

            if row and row[0] is not None and now - row[1] < ttl:
                return await cached()
            if row and row[2] > now:
                return await cached(True, row[3])
            error = "Source unavailable"
            for attempt in range(2):
                try:
                    async with self.limit:
                        response = await self.client.get(request_url, headers=headers)
                    response.raise_for_status()
                    data = await asyncio.to_thread(parser, response.content)
                    body = response.content if store_body else None
                    self.db.execute("INSERT OR REPLACE INTO responses VALUES(?,?,?,?,?,0,NULL)",
                                    (key, request_url, source, body, now))
                    self.db.commit()
                    return Feed(data, source, request_url, datetime.fromtimestamp(now, timezone.utc).isoformat())
                except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                    error = f"HTTP {exc.response.status_code}" if isinstance(exc, httpx.HTTPStatusError) else "Source response unavailable or changed"
                    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500 and exc.response.status_code != 429:
                        break
                    if attempt == 0:
                        await asyncio.sleep(1)
            self.db.execute("INSERT INTO responses(key,url,source,body,fetched,failed_until,error) VALUES(?,?,?,NULL,0,?,?) "
                            "ON CONFLICT(key) DO UPDATE SET failed_until=excluded.failed_until,error=excluded.error",
                            (key, request_url, source, now + failure_ttl, error))
            self.db.commit()
            return await cached(True, error)

    async def stream_parse(self, url: str, source: str, parser: Callable, failure_ttl: int = 600,
                           headers: dict | None = None):
        """Download to a temp file and parse it there.

        MoneyPuck's team history is a single career file. Holding that body in
        memory, then decoding a second copy, is what pushes a 512 MB instance over.
        """
        key = hashlib.sha256(url.encode()).hexdigest()
        async with self.locks.setdefault(key, asyncio.Lock()):
            row = self.db.execute(
                "SELECT failed_until, error FROM responses WHERE key=?", (key,)).fetchone()
            now = time.time()
            if row and row[0] and row[0] > now:
                return None, row[1]
            error = "Source unavailable"
            for attempt in range(2):
                path = None
                try:
                    async with self.limit:
                        async with self.client.stream('GET', url, headers=headers) as response:
                            response.raise_for_status()
                            fd, path = tempfile.mkstemp(prefix='moneypuck-')
                            os.close(fd)
                            with open(path, 'wb') as out:
                                async for chunk in response.aiter_bytes(65536):
                                    out.write(chunk)
                    data = await asyncio.to_thread(parser, path)
                    self.db.execute(
                        "INSERT OR REPLACE INTO responses VALUES(?,?,?,?,?,0,NULL)",
                        (key, url, source, None, now))
                    self.db.commit()
                    return data, None
                except (httpx.HTTPError, ValueError, KeyError, TypeError, OSError) as exc:
                    error = (f"HTTP {exc.response.status_code}" if isinstance(exc, httpx.HTTPStatusError)
                             else "Source response unavailable or changed")
                    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500 and exc.response.status_code != 429:
                        break
                    if attempt == 0:
                        await asyncio.sleep(1)
                finally:
                    if path and os.path.exists(path):
                        os.unlink(path)
            self.db.execute(
                "INSERT INTO responses(key,url,source,body,fetched,failed_until,error) VALUES(?,?,?,NULL,0,?,?) "
                "ON CONFLICT(key) DO UPDATE SET failed_until=excluded.failed_until,error=excluded.error",
                (key, url, source, now + failure_ttl, error))
            self.db.commit()
            return None, error

    def delete_response(self, url: str | None):
        if not url:
            return
        key = hashlib.sha256(url.encode()).hexdigest()
        self.db.execute('DELETE FROM responses WHERE key=?', (key,))
        self.db.commit()

    def save_moneypuck(self, kind: str, season: int, rows: list[dict], entity_key: str):
        now = time.time()
        self.db.execute("""CREATE TABLE IF NOT EXISTS moneypuck_rows (
            kind TEXT, season INTEGER, entity TEXT, game_id TEXT, situation TEXT,
            body TEXT, fetched REAL,
            PRIMARY KEY(kind, season, entity, game_id, situation)
        )""")
        self.db.executemany("INSERT OR REPLACE INTO moneypuck_rows VALUES(?,?,?,?,?,?,?)", [
            (kind, season, str(r[entity_key]), str(r['gameId']), str(r.get('situation') or ''), json.dumps(r), now)
            for r in rows if r.get(entity_key) is not None and r.get('gameId') is not None])
        self.db.commit()
        self.note_moneypuck_fetch(kind, season, now)

    def note_moneypuck_fetch(self, kind: str, season: int, fetched: float | None = None):
        """Remember a successful read even when the season filter kept zero rows."""
        self.db.execute("""CREATE TABLE IF NOT EXISTS moneypuck_fetches (
            kind TEXT, season INTEGER, fetched REAL, PRIMARY KEY(kind, season))""")
        self.db.execute(
            "INSERT OR REPLACE INTO moneypuck_fetches VALUES(?,?,?)",
            (kind, season, time.time() if fetched is None else fetched))
        self.db.commit()

    def moneypuck_fetched_at(self, kind: str, season: int) -> float | None:
        stamps = []
        if self._table('moneypuck_rows'):
            row = self.db.execute(
                "SELECT MAX(fetched) FROM moneypuck_rows WHERE kind=? AND season=?",
                (kind, season)).fetchone()
            if row and row[0] is not None:
                stamps.append(row[0])
        if self._table('moneypuck_fetches'):
            row = self.db.execute(
                "SELECT fetched FROM moneypuck_fetches WHERE kind=? AND season=?",
                (kind, season)).fetchone()
            if row and row[0] is not None:
                stamps.append(row[0])
        return max(stamps) if stamps else None

    def _table(self, name: str) -> bool:
        return self.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone() is not None

    def load_moneypuck(self, kind: str, season: int, entities: list | None = None) -> tuple[list[dict], float | None]:
        if not self._table('moneypuck_rows'):
            return [], None
        if entities is not None and not entities:
            return [], self.moneypuck_fetched_at(kind, season)
        rows = []
        if entities is None:
            rows = self.db.execute(
                "SELECT body,fetched FROM moneypuck_rows WHERE kind=? AND season=?",
                (kind, season),
            ).fetchall()
        else:
            ids = [str(entity) for entity in entities]
            for start in range(0, len(ids), 400):
                chunk = ids[start:start + 400]
                marks = ','.join('?' for _ in chunk)
                rows.extend(self.db.execute(
                    f"SELECT body,fetched FROM moneypuck_rows WHERE kind=? AND season=? AND entity IN ({marks})",
                    (kind, season, *chunk),
                ).fetchall())
        return [json.loads(row[0]) for row in rows], max((row[1] for row in rows), default=None)
