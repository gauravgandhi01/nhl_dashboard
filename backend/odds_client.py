"""Credential-safe transport and shared quota guard for optional odds feeds."""
import asyncio
import os
import time

import httpx

from .odds_config import REGIONS

BASE = 'https://api.the-odds-api.com/v4/sports/icehockey_nhl'


class OddsError(ValueError):
    """A fixed, credential-free diagnosis safe to surface in logs and responses."""


class OddsClient:
    def __init__(self, store):
        self.store = store
        self.lock = asyncio.Lock()
        self.exhausted_until = 0
        self.usage = {}

    async def request(self, path, params=None):
        async with self.lock:
            key = os.environ.get('THE_ODDS_API_KEY', '').strip()
            if not key:
                raise OddsError('Odds key not configured in the server environment')
            if time.time() < self.exhausted_until:
                raise OddsError('Odds quota exhausted or rate limited; retry after cooldown')
            try:
                async with self.store.limit:
                    response = await self.store.client.get(BASE + path, params={'apiKey': key, **(params or {})})
                self.usage = {name: response.headers.get('x-requests-' + name) for name in ['remaining', 'used', 'last']}
                if response.status_code == 429 or self.usage['remaining'] == '0':
                    self.exhausted_until = time.time() + 1800
                if response.status_code != 200:
                    try:
                        payload = response.json()
                        code = payload.get('error_code') if isinstance(payload, dict) else None
                    except ValueError:
                        code = None
                    if code == 'OUT_OF_USAGE_CREDITS':
                        self.exhausted_until = time.time() + 1800
                        reason = 'Odds quota insufficient for this request; check remaining credits'
                    elif code in ['INVALID_KEY', 'MISSING_KEY'] or response.status_code == 401:
                        reason = 'Odds API key rejected; check the server environment'
                    elif code in ['INVALID_MARKET', 'INVALID_MARKETS', 'INVALID_BOOKMAKERS', 'INVALID_REGIONS']:
                        reason = 'Odds provider rejected the requested markets or bookmakers'
                    elif response.status_code == 429:
                        reason = 'Odds provider rate limited the request; retry after cooldown'
                    elif response.status_code == 404:
                        reason = 'Odds event no longer available'
                    else:
                        reason = f'Odds provider returned HTTP {response.status_code}'
                    raise OddsError(reason)
                return response.json()
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
