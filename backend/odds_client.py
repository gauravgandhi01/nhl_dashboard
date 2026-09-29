"""Credential-safe transport and shared quota guard for optional odds feeds."""
import asyncio
import os
import time

import httpx

from .odds_config import REGIONS

BASE = 'https://api.the-odds-api.com/v4/sports/icehockey_nhl'


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
                raise ValueError('Odds key not configured')
            if time.time() < self.exhausted_until:
                raise ValueError('Odds quota exhausted')
            try:
                async with self.store.limit:
                    response = await self.store.client.get(BASE + path, params={'apiKey': key, **(params or {})})
                self.usage = {name: response.headers.get('x-requests-' + name) for name in ['remaining', 'used', 'last']}
                if response.status_code == 429 or self.usage['remaining'] == '0':
                    self.exhausted_until = time.time() + 1800
                if response.status_code != 200:
                    raise ValueError('Odds provider rejected request')
                return response.json()
            except (httpx.HTTPError, ValueError):
                # HTTP exception URLs contain credentials; never propagate them.
                raise ValueError('Odds unavailable; check configuration or quota') from None


def odds_client(store):
    if not hasattr(store, '_odds_client'):
        store._odds_client = OddsClient(store)
    return store._odds_client
