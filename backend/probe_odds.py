"""Explicit bounded market discovery across configured US regions; never runs on navigation.

Run from the project folder: .venv/bin/python -m backend.probe_odds
Requires api_keys in ../keys.json. Writes a credential-free local report.
"""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import time

from .cache import Store
from .providers import Providers
from .moneyline import Moneylines, moneyline_prices
from .first_period_odds import event_game
from .odds_client import odds_client
from .odds_config import market_params, odds_scope


async def probe():
    root = Path(__file__).resolve().parents[1]
    store = Store(root / 'data' / 'dashboard.sqlite3')
    client = odds_client(store)
    report = {'retrieved_at': datetime.now(timezone.utc).isoformat(), 'odds_scope': odds_scope(),
              'requests': [], 'events': [], 'catalogs': [], 'prop_sample': None}
    async def request(path, params=None):
        body = await client.request(path, params)
        report['requests'].append({'path': path, 'usage': dict(client.usage)})
        return body
    def future(event):
        return datetime.fromisoformat(event['commence_time'].replace('Z', '+00:00')).timestamp() > time.time()
    try:
        events = await request('/events')
        if not isinstance(events, list):
            raise ValueError('Invalid events response')
        events = sorted([e for e in events if future(e)], key=lambda e: e['commence_time'])
        report['events'] = events
        print(f"Upcoming NHL events: {len(events)}", flush=True)
        if events:
            lines = await request('/odds', market_params({'markets': 'h2h', 'oddsFormat': 'american'}))
            report['moneylines'] = lines
            print('Moneyline events returned:', len(lines), flush=True)
            providers = Providers(store)
            moneylines = Moneylines(providers)
            dates = sorted({datetime.fromisoformat(e['commence_time'].replace('Z', '+00:00')).astimezone(ZoneInfo('America/New_York')).date().isoformat() for e in events})
            report['cached_dates'] = []
            for date in dates:
                schedule = await providers.nhl(f'score/{date}', 600)
                if schedule.data is None or schedule.stale:
                    continue
                games = [g for g in schedule.data.get('games', []) if g.get('gameState') in ['FUT', 'PRE'] and g.get('gameScheduleState') not in ['PPD', 'CNCL'] and datetime.fromisoformat(g['startTimeUTC'].replace('Z', '+00:00')).timestamp() > time.time()]
                matched = {}
                for event in lines:
                    game = event_game(event, games)
                    if game and future(event):
                        matched.setdefault(str(game['id']), []).append((event, game))
                prices = {gid: moneyline_prices(*items[0]) for gid, items in matched.items() if len(items) == 1}
                prices = {gid: p for gid, p in prices.items() if p}
                body = {'prices': prices, 'eligible_games': len(games), 'usage': dict(client.usage)}
                now = time.time()
                store.db.execute('INSERT OR REPLACE INTO moneyline_odds VALUES(?,?,?,?,NULL)', (date, json.dumps(body), now, now))
                store.db.commit()
                report['cached_dates'].append({'date': date, 'matched_games': len(prices)})
            preferred = ['player_shots_on_goal', 'player_points', 'player_assists', 'player_goal_scorer_anytime']
            for event in events[:3]:
                eid = event.get('id', '')
                if not isinstance(eid, str) or not eid.isalnum():
                    continue
                catalog = await request(f'/events/{eid}/markets', market_params())
                report['catalogs'].append(catalog)
                keys = sorted({m['key'] for b in catalog.get('bookmakers', []) for m in b.get('markets', [])})
                print(event['away_team'], '@', event['home_team'], ':', ', '.join(keys) or 'no listed markets', flush=True)
                props = [k for k in preferred if k in keys]
                alternates = ['player_shots_on_goal_alternate', 'player_points_alternate', 'player_assists_alternate']
                props += [k for k in alternates if k in keys and k not in props][:4 - len(props)]
                if not props:
                    props = [k for k in keys if k.startswith('player_')][:4]
                if props and report['prop_sample'] is None:
                    report['prop_sample'] = await request(f'/events/{eid}/odds', market_params(
                        {'markets': ','.join(props), 'oddsFormat': 'american'}))
    except (ValueError, KeyError, TypeError):
        report['error'] = 'Probe stopped: provider unavailable, quota exhausted, or key not configured.'
        print(report['error'], flush=True)
    finally:
        path = root / 'data' / 'odds_probe.json'
        path.write_text(json.dumps(report, indent=2))
        print('Probe report: data/odds_probe.json; usage:', json.dumps(client.usage), flush=True)
        await store.close()
    return report


if __name__ == '__main__':
    asyncio.run(probe())
