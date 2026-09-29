from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
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
            CREATE TABLE IF NOT EXISTS game_stats (
                provider TEXT, season INTEGER, entity TEXT, game_id TEXT, body TEXT,
                PRIMARY KEY(provider, season, entity, game_id));
        """)
        self.db.commit()
        self.locks: dict[str, asyncio.Lock] = {}
        self.limit = asyncio.Semaphore(4)
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(45, connect=10), follow_redirects=True,
                                       headers={"User-Agent": "NHLMatchupDashboard/1.0 (personal research)"})

    async def close(self):
        await self.client.aclose()
        self.db.close()

    async def fetch(self, url: str, source: str, ttl: int, parser: Callable = json.loads,
                    params: dict | None = None, store_body: bool = True) -> Feed:
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
                        response = await self.client.get(request_url)
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
                            (key, request_url, source, now + 600, error))
            self.db.commit()
            return await cached(True, error)

    def save_games(self, provider: str, season: int, rows: list[dict], entity_key: str):
        self.db.executemany("INSERT OR REPLACE INTO game_stats VALUES(?,?,?,?,?)", [
            (provider, season, str(r[entity_key]), str(r['gameId']), json.dumps(r)) for r in rows
            if r.get(entity_key) is not None and r.get('gameId') is not None])
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

    def load_moneypuck(self, kind: str, season: int) -> tuple[list[dict], float | None]:
        table = self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='moneypuck_rows'"
        ).fetchone()
        if not table:
            return [], None
        rows = self.db.execute(
            "SELECT body,fetched FROM moneypuck_rows WHERE kind=? AND season=?",
            (kind, season),
        ).fetchall()
        return [json.loads(r[0]) for r in rows], max((r[1] for r in rows), default=None)
