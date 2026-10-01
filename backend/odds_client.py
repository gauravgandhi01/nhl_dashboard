"""Credential-safe transport and shared quota guard for optional odds feeds."""
import asyncio
import json
import time
from pathlib import Path

import httpx

BASE = 'https://api.the-odds-api.com/v4/sports/icehockey_nhl'
KEYS_PATH = Path(__file__).resolve().parents[2] / 'keys.json'


class OddsError(ValueError):
    """A fixed, credential-free diagnosis safe to surface in logs and responses."""


def _clean_key(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def odds_api_keys(path=None):
    path = KEYS_PATH if path is None else path
    try:
        payload = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
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


class OddsClient:
    def __init__(self, store):
        self.store = store
        self.lock = asyncio.Lock()
        self.exhausted_until = 0
        self.usage = {}
        self.key_index = 0
        self.key_cooldowns = {}
        self.invalid_keys = set()

    async def request(self, path, params=None):
        async with self.lock:
            try:
                keys = odds_api_keys()
                if not keys:
                    raise OddsError('Odds key not configured in keys.json')
                if time.time() < self.exhausted_until:
                    raise OddsError('Odds quota exhausted or rate limited; retry after cooldown')
                now = time.time()
                ordered = keys[self.key_index:] + keys[:self.key_index]
                candidates = [key for key in ordered
                              if key not in self.invalid_keys and self.key_cooldowns.get(key, 0) <= now]
                if not candidates:
                    self.exhausted_until = min(self.key_cooldowns.values()) if self.key_cooldowns else now + 1800
                    raise OddsError('Odds quota exhausted or rate limited; retry after cooldown')
                last_reason = None
                for key in candidates:
                    async with self.store.limit:
                        response = await self.store.client.get(BASE + path, params={'apiKey': key, **(params or {})})
                    self.usage = {name: response.headers.get('x-requests-' + name) for name in ['remaining', 'used', 'last']}
                    if response.status_code == 429 or self.usage['remaining'] == '0':
                        self.key_cooldowns[key] = time.time() + 1800
                    if response.status_code != 200:
                        try:
                            payload = response.json()
                            code = payload.get('error_code') if isinstance(payload, dict) else None
                        except ValueError:
                            code = None
                        if code == 'OUT_OF_USAGE_CREDITS':
                            self.key_cooldowns[key] = time.time() + 1800
                            reason = 'Odds quota insufficient for this request; check remaining credits'
                        elif code in ['INVALID_KEY', 'MISSING_KEY'] or response.status_code == 401:
                            self.invalid_keys.add(key)
                            reason = 'Odds API key rejected; check keys.json'
                        elif code in ['INVALID_MARKET', 'INVALID_MARKETS', 'INVALID_BOOKMAKERS', 'INVALID_REGIONS']:
                            reason = 'Odds provider rejected the requested markets or bookmakers'
                        elif response.status_code == 429:
                            reason = 'Odds provider rate limited the request; retry after cooldown'
                        elif response.status_code == 404:
                            reason = 'Odds event no longer available'
                        else:
                            reason = f'Odds provider returned HTTP {response.status_code}'
                        last_reason = reason
                        if code in ['OUT_OF_USAGE_CREDITS', 'INVALID_KEY', 'MISSING_KEY'] or response.status_code in [401, 429]:
                            continue
                        raise OddsError(reason)
                    self.key_index = keys.index(key)
                    return response.json()
                if all(key in self.invalid_keys for key in keys):
                    raise OddsError('Odds API key rejected; check keys.json')
                if all(key in self.invalid_keys or self.key_cooldowns.get(key, 0) > time.time() for key in keys):
                    self.exhausted_until = min(
                        [until for until in self.key_cooldowns.values() if until > time.time()] or [time.time() + 1800])
                raise OddsError(last_reason or 'Odds quota exhausted or rate limited; retry after cooldown')
            except OddsError:
                raise
            except httpx.TimeoutException:
                raise OddsError('Odds provider request timed out') from None
            except httpx.HTTPError:
                # HTTP exception URLs contain credentials; never propagate them.
                raise OddsError('Odds provider connection failed') from None
            except ValueError:
                raise OddsError('Odds provider returned invalid JSON') from None


def odds_client(store):
    if not hasattr(store, '_odds_client'):
        store._odds_client = OddsClient(store)
    return store._odds_client
