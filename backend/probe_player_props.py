"""Explicit player-prop discovery across configured US odds coverage.

Run from the project folder: .venv/bin/python -m backend.probe_player_props
Requires api_keys in ../keys.json.
Optional bookmaker selection lives in config/odds.json.
Does not modify dashboard caches. Maximum conservative budget: 20 credits.
"""
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from .cache import Store
from .odds_client import odds_client
from .odds_config import (
    BOOKMAKER_REGIONS,
    OBSERVED_BOOKMAKERS,
    REGIONS,
    configured_bookmakers,
    market_params,
    odds_scope,
    player_prop_market_limit,
)

PRIORITY = [
    'player_shots_on_goal', 'player_points', 'player_assists', 'player_goals',
    'player_blocked_shots', 'player_power_play_points', 'player_total_saves',
    'player_goal_scorer_first', 'player_goal_scorer_last',
    'player_goal_scorer_anytime_p1', 'player_goals_alternate',
]
PREVIOUSLY_PRICED = {'player_goal_scorer_anytime', 'player_shots_on_goal_alternate',
                    'player_points_alternate', 'player_assists_alternate'}


def prop_keys(catalog, bookmakers=None):
    allowed = set(bookmakers or [])
    return {m['key'] for b in catalog.get('bookmakers', []) for m in b.get('markets', [])
            if (not allowed or b.get('key') in allowed)
            if isinstance(m.get('key'), str) and m['key'].startswith('player_')}


def choose_markets(catalog, bookmakers=None, limit=8):
    keys = prop_keys(catalog, bookmakers) - PREVIOUSLY_PRICED
    return ([k for k in PRIORITY if k in keys] + sorted(keys - set(PRIORITY)))[:8]


def bookmaker_coverage(catalogs):
    coverage = {}
    for catalog in catalogs:
        event_id = catalog.get('id')
        for book in catalog.get('bookmakers', []):
            key = book.get('key')
            if not key:
                continue
            record = coverage.setdefault(key, {
                'key': key, 'title': book.get('title') or OBSERVED_BOOKMAKERS.get(key) or key,
                'region': BOOKMAKER_REGIONS.get(key),
                'events': 0, 'player_markets': set(), 'all_markets': set(),
            })
            if book.get('title'):
                record['title'] = book['title']
            if event_id:
                record.setdefault('_events', set()).add(event_id)
            for market in book.get('markets', []):
                market_key = market.get('key')
                if not isinstance(market_key, str):
                    continue
                record['all_markets'].add(market_key)
                if market_key.startswith('player_'):
                    record['player_markets'].add(market_key)
    result = []
    for record in coverage.values():
        events = record.pop('_events', set())
        result.append({
            **record,
            'events': len(events) or record['events'],
            'player_markets': sorted(record['player_markets']),
            'all_markets': sorted(record['all_markets']),
        })
    return sorted(result, key=lambda r: (-len(r['player_markets']), -r['events'], r['key']))


async def probe():
    root = Path(__file__).resolve().parents[1]
    store = Store(root / 'data' / 'dashboard.sqlite3')
    client = odds_client(store)
    report = {'retrieved_at': datetime.now(timezone.utc).isoformat(), 'regions': REGIONS,
              'odds_scope': None, 'available_bookmaker_options': OBSERVED_BOOKMAKERS,
              'bookmaker_regions': BOOKMAKER_REGIONS,
              'us_exchange_bookmakers': sorted(
                  key for key, region in BOOKMAKER_REGIONS.items() if region == 'us_ex'
              ),
              'requests': [], 'catalogs': [], 'bookmaker_coverage': [], 'sample': None,
              'requested_markets': [], 'sample_event': None}
    async def request(path, params=None):
        body = await client.request(path, params)
        safe_params = {k: v for k, v in (params or {}).items() if k != 'apiKey'}
        report['requests'].append({'path': path, 'params': safe_params, 'usage': dict(client.usage)})
        return body
    try:
        limit = player_prop_market_limit()
        selected_books = configured_bookmakers()
        report['odds_scope'] = odds_scope()
        if REGIONS != 'us,us2,us_ex':
            raise ValueError('Review discovery budget before changing regions')
        events = await request('/events')
        events = sorted([e for e in events if isinstance(e.get('id'), str) and e['id'].isalnum()
                        and datetime.fromisoformat(e['commence_time'].replace('Z', '+00:00')).timestamp() > time.time()],
                        key=lambda e: e['commence_time'])[:2]
        for event in events:
            catalog = await request(f"/events/{event['id']}/markets", market_params())
            if catalog.get('id') != event['id']:
                raise ValueError('Unexpected event identity')
            report['catalogs'].append(catalog)
            print(event['away_team'], '@', event['home_team'], flush=True)
            for book in catalog.get('bookmakers', []):
                if selected_books and book.get('key') not in selected_books:
                    continue
                keys = sorted(prop_keys({'bookmakers': [book]}, selected_books))
                if keys:
                    print(' ', book['key'], ':', ', '.join(keys), flush=True)
        report['bookmaker_coverage'] = bookmaker_coverage(report['catalogs'])
        ranked = sorted(report['catalogs'], key=lambda c: len(choose_markets(c, selected_books, limit)), reverse=True)
        if ranked and choose_markets(ranked[0], selected_books, limit):
            catalog = ranked[0]
            markets = choose_markets(catalog, selected_books, limit)
            report['requested_markets'] = markets
            report['sample_event'] = {'id': catalog.get('id'), 'away_team': catalog.get('away_team'),
                                      'home_team': catalog.get('home_team'), 'commence_time': catalog.get('commence_time')}
            report['sample'] = await request(f"/events/{catalog['id']}/odds", market_params({
                'markets': ','.join(markets), 'oddsFormat': 'american'}))
        costs = [int(r['usage'].get('last') or 0) for r in report['requests']]
        report['credits_used'] = sum(costs)
        print('Probe credits:', sum(costs), '; last quota:', client.usage, flush=True)
    except (ValueError, KeyError, TypeError):
        report['error'] = 'Probe stopped: unavailable provider, invalid response, missing key, or quota limit.'
        print(report['error'], flush=True)
    finally:
        path = root / 'data' / 'player_props_probe.json'
        path.write_text(json.dumps(report, indent=2))
        await store.close()
    return report


if __name__ == '__main__':
    asyncio.run(probe())
