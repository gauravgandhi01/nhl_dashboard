"""Credential-safe transport and shared quota guard for optional odds feeds."""
import asyncio
import calendar
import hashlib
import math
from datetime import datetime, timezone
import json
import os
import time
from pathlib import Path

import httpx

API_ROOT = 'https://api.the-odds-api.com/v4'
BASE = API_ROOT + '/sports/icehockey_nhl'
KEYS_PATH = Path(__file__).resolve().parents[2] / 'keys.json'
RENDER_KEYS_PATH = Path('/etc/secrets/keys.json')


class OddsError(ValueError):
    """A fixed, credential-free diagnosis safe to surface in logs and responses."""


def _clean_key(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def key_paths(path=None):
    if path is not None:
        return [Path(path)]
    paths = []
    env_path = os.environ.get('NHL_ODDS_KEYS_PATH')
    if env_path:
        paths.append(Path(env_path))
    paths.extend([KEYS_PATH, RENDER_KEYS_PATH])
    unique = []
    for item in paths:
        if item not in unique:
            unique.append(item)
    return unique


def odds_api_keys(path=None):
    payload = None
    for candidate in key_paths(path):
        try:
            payload = json.loads(candidate.read_text(encoding='utf-8'))
            break
        except (OSError, ValueError, TypeError):
            continue
    if payload is None:
        return []
    if not isinstance(payload, dict):
        return []
    values = payload.get('api_keys')
    if not isinstance(values, list):
        values = []
    keys = []
    seen = set()
    for value in values:
        key = _clean_key(value)
        if key and key not in seen:
            keys.append(key)
            seen.add(key)
    return keys


def odds_configured():
    return bool(odds_api_keys())


def request_cost(path, params):
    if path in ['/events', '/sports']:
        return 0
    markets = len(set(params.get('markets', 'h2h').split(',')))
    groups = math.ceil(len(set(params['bookmakers'].split(','))) / 10) if params.get('bookmakers') else len(set(params.get('regions', 'us').split(',')))
    return markets * groups


def key_id(key):
    return hashlib.sha256(key.encode()).hexdigest()


def merge_odds(parts):
    """Combine disjoint markets/books bought with small remaining key balances."""
    events = {}
    is_list = isinstance(parts[0], list)
    for part in parts:
        for event in part if isinstance(part, list) else [part]:
            target = events.setdefault(event['id'], {**event, 'bookmakers': []})
            for book in event.get('bookmakers', []):
                existing = next((b for b in target['bookmakers'] if b['key'] == book['key']), None)
                if existing is None:
                    target['bookmakers'].append({**book, 'markets': list(book.get('markets', []))})
                else:
                    existing['markets'].extend(book.get('markets', []))
    return list(events.values()) if is_list else next(iter(events.values()))


class OddsClient:
    def __init__(self, store):
        self.store = store
        self.lock = asyncio.Lock()
        self.exhausted_until = 0
        self.usage = {}
        self.key_index = 0
        self.store.db.executescript("""
            CREATE TABLE IF NOT EXISTS odds_key_budgets (
                key_id TEXT, month TEXT, remaining INTEGER, used INTEGER,
                checked REAL, blocked_until REAL DEFAULT 0, invalid INTEGER DEFAULT 0,
                PRIMARY KEY(key_id, month));
            CREATE TABLE IF NOT EXISTS odds_usage (
                id INTEGER PRIMARY KEY, key_id TEXT, requested REAL, month TEXT,
                feed TEXT, cost INTEGER, status INTEGER);
            CREATE INDEX IF NOT EXISTS odds_usage_requested ON odds_usage(requested);
        """)
        self.store.db.commit()

    def period(self):
        now = datetime.now(timezone.utc)
        end = now.replace(year=now.year + (now.month == 12), month=now.month % 12 + 1,
                          day=1, hour=0, minute=0, second=0, microsecond=0)
        return now.strftime('%Y-%m'), end.timestamp()

    def budgets(self, keys):
        month, _ = self.period()
        return {key: self.store.db.execute(
            'SELECT remaining,used,checked,blocked_until,invalid FROM odds_key_budgets WHERE key_id=? AND month=?',
            (key_id(key), month)).fetchone() for key in keys}

    def daily_budget(self, keys):
        now = datetime.now(timezone.utc)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        spent = self.store.db.execute('SELECT COALESCE(SUM(cost),0) FROM odds_usage WHERE requested>=?', (day_start,)).fetchone()[0]
        rows = self.budgets(keys)
        capacity = sum((r[0] + r[1]) if r and r[0] is not None and r[1] is not None else 500
                       for r in rows.values() if not r or not r[4])
        days = calendar.monthrange(now.year, now.month)[1]
        limit = int(capacity * .9 / days)
        if rows and all(r and r[0] is not None for r in rows.values()):
            remaining = sum(r[0] for r in rows.values() if not r[4])
            limit = min(limit, int((remaining + spent) * .9 / (days - now.day + 1)))
        override = os.environ.get('NHL_ODDS_DAILY_BUDGET')
        if override is not None:
            limit = max(0, int(override))
        return limit, spent

    def status(self):
        keys = odds_api_keys()
        month, _ = self.period()
        rows = self.budgets(keys)
        limit, spent = self.daily_budget(keys)
        return {'month': month, 'key_count': len(keys),
                'known_keys': sum(r is not None and r[0] is not None for r in rows.values()),
                'remaining': sum(r[0] for r in rows.values() if r and r[0] is not None and not r[4]),
                'daily_budget': limit, 'spent_today': spent,
                'keys': [{'id': key_id(k)[:12], 'remaining': r[0] if r else None,
                          'used': r[1] if r else None, 'checked': r[2] if r else None,
                          'invalid': bool(r and r[4])} for k, r in rows.items()]}

    def record(self, key, response, path, estimated):
        def header(name):
            try:
                return max(0, int(response.headers['x-requests-' + name]))
            except (KeyError, ValueError):
                return None
        remaining, used, cost = header('remaining'), header('used'), header('last')
        if cost is None:
            cost = estimated if response.status_code == 200 else 0
        self.usage = {n: response.headers.get('x-requests-' + n) for n in ['remaining', 'used', 'last']}
        month, reset = self.period()
        try:
            payload = response.json() if response.status_code != 200 else {}
            code = payload.get('error_code') if isinstance(payload, dict) else None
        except ValueError:
            code = None
        invalid = code in ['INVALID_KEY', 'MISSING_KEY'] or (response.status_code == 401 and code != 'OUT_OF_USAGE_CREDITS')
        # An insufficient balance for a large request is still usable for smaller markets.
        blocked = reset if remaining == 0 else time.time() + 60 if response.status_code == 429 else 0
        if code == 'OUT_OF_USAGE_CREDITS' and (remaining is None or estimated == 0):
            blocked = time.time() + 1800
        self.store.db.execute("""INSERT INTO odds_key_budgets VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(key_id,month) DO UPDATE SET
            remaining=COALESCE(excluded.remaining,odds_key_budgets.remaining),
            used=COALESCE(excluded.used,odds_key_budgets.used),checked=excluded.checked,
            blocked_until=excluded.blocked_until,invalid=excluded.invalid""",
            (key_id(key), month, remaining, used, time.time(), blocked, int(invalid)))
        self.store.db.execute('INSERT INTO odds_usage(key_id,requested,month,feed,cost,status) VALUES(?,?,?,?,?,?)',
                              (key_id(key), time.time(), month, path, cost, response.status_code))
        self.store.db.commit()
        return code

    async def sync_budgets(self):
        """Free /sports checks, at most once per key per day; no paid odds."""
        async with self.lock:
            keys = odds_api_keys()
            rows = self.budgets(keys)
            for key, row in rows.items():
                if row and row[2] and time.time() - row[2] < 86400:
                    continue
                try:
                    async with self.store.limit:
                        response = await self.store.client.get(API_ROOT + '/sports/', params={'apiKey': key})
                    self.record(key, response, '/sports', 0)
                except httpx.HTTPError:
                    month, _ = self.period()
                    self.store.db.execute("""INSERT INTO odds_key_budgets VALUES(?,?,NULL,NULL,?,0,0)
                        ON CONFLICT(key_id,month) DO UPDATE SET checked=excluded.checked""",
                        (key_id(key), month, time.time()))
                    self.store.db.commit()
                    continue
            return self.status()

    async def request(self, path, params=None, sport='icehockey_nhl'):
        async with self.lock:
            try:
                return await self._request(path, dict(params or {}), sport)
            except OddsError:
                raise
            except httpx.TimeoutException:
                raise OddsError('Odds provider request timed out') from None
            except httpx.HTTPError:
                raise OddsError('Odds provider connection failed') from None
            except (ValueError, KeyError, TypeError):
                raise OddsError('Odds provider returned invalid JSON or odds configuration') from None

    async def _request(self, path, params, sport, split=True):
        keys = odds_api_keys()
        if not keys:
            raise OddsError('Odds key not configured in keys.json or /etc/secrets/keys.json')
        cost = request_cost(path, params)
        if cost:
            limit, spent = self.daily_budget(keys)
            if spent + cost > limit:
                raise OddsError('Odds daily budget reached; cached prices retained')
        rows = self.budgets(keys)
        now = time.time()
        ordered = keys[self.key_index:] + keys[:self.key_index]
        candidates = [k for k in ordered if not rows[k] or
                      (not rows[k][4] and rows[k][3] <= now and
                       (not cost or rows[k][0] is None or rows[k][0] >= cost))]
        # Highest known balance first; rotate ties. Unknown keys are tried as well.
        candidates.sort(key=lambda k: rows[k][0] if rows[k] and rows[k][0] is not None else 501, reverse=True)
        last_reason = None
        for key in candidates:
            async with self.store.limit:
                response = await self.store.client.get(API_ROOT + '/sports/' + sport + path,
                                                        params={**params, 'apiKey': key})
            code = self.record(key, response, path, cost)
            if response.status_code == 200:
                self.key_index = (keys.index(key) + 1) % len(keys)
                self.exhausted_until = 0
                return response.json()
            if code == 'OUT_OF_USAGE_CREDITS':
                last_reason = 'Odds quota insufficient for this request; check remaining credits'
            elif code in ['INVALID_KEY', 'MISSING_KEY'] or response.status_code == 401:
                last_reason = 'Odds API key rejected; check configured keys file'
            elif response.status_code == 429:
                last_reason = 'Odds provider rate limited the request; retry after cooldown'
            elif code in ['INVALID_MARKET', 'INVALID_MARKETS', 'INVALID_BOOKMAKERS', 'INVALID_REGIONS']:
                raise OddsError('Odds provider rejected the requested markets or bookmakers')
            elif response.status_code == 404:
                raise OddsError('Odds event no longer available')
            else:
                raise OddsError(f'Odds provider returned HTTP {response.status_code}')
        rows = self.budgets(keys)
        if split and cost > 1 and all(r and r[0] is not None for r in rows.values()):
            available = sum(r[0] for r in rows.values() if not r[4] and r[3] <= time.time())
            if available >= cost:
                scope = 'bookmakers' if params.get('bookmakers') else 'regions'
                entries = params.get(scope, 'us').split(',')
                size = 10 if scope == 'bookmakers' else 1
                parts = []
                for market in params.get('markets', 'h2h').split(','):
                    for offset in range(0, len(entries), size):
                        parts.append(await self._request(path, {**params, 'markets': market,
                            scope: ','.join(entries[offset:offset + size])}, sport, split=False))
                return merge_odds(parts)
        if rows and all(r and r[4] for r in rows.values()):
            raise OddsError('Odds API key rejected; check configured keys file')
        blocked = [r[3] for r in rows.values() if r and r[3] > time.time()]
        self.exhausted_until = min(blocked) if blocked else time.time() + 600
        raise OddsError(last_reason or 'Odds quota exhausted or rate limited; retry after cooldown')


def odds_client(store):
    if not hasattr(store, '_odds_client'):
        store._odds_client = OddsClient(store)
    return store._odds_client
