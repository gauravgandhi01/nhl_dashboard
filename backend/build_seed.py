from __future__ import annotations

import asyncio
import os
from datetime import date
from pathlib import Path

from .cache import Store
from .providers import Providers


def default_seasons() -> list[int]:
    today = date.today()
    start = today.year if today.month >= 9 else today.year - 1
    return [(start - 1) * 10000 + start, start * 10000 + start + 1]


def seasons() -> list[int]:
    raw = os.environ.get('NHL_SEED_SEASONS', '').strip()
    if not raw:
        return default_seasons()
    return [int(part.strip()) for part in raw.split(',') if part.strip()]


async def main():
    path = Path(os.environ.get('NHL_SEED_DB', 'data/seed.sqlite3'))
    if path.exists():
        path.unlink()
    store = Store(path)
    providers = Providers(store)
    try:
        for season in seasons():
            for kind in ['teams', 'goalies', 'skaters']:
                feed = await providers.mp(kind, season)
                count = len(feed.data or [])
                print(f'MoneyPuck {kind} {season}: {count} rows ({feed.meta()["status"]})', flush=True)
        store.db.execute("DELETE FROM responses WHERE source='MoneyPuck'")
        store.db.commit()
        store.db.execute('VACUUM')
    finally:
        await store.close()


if __name__ == '__main__':
    asyncio.run(main())
