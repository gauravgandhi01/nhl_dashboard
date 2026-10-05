from contextlib import asynccontextmanager
from datetime import date as Date
import asyncio
import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .cache import Store
from .providers import Providers
from .service import Dashboard, today_et
from .players import players_dashboard
from .first_period import FirstPeriod
from .first_period_odds import FirstPeriodOdds
from .streaks import Streaks
from .moneyline import Moneylines
from .odds_client import odds_configured
from .player_props import PlayerProps
from .stanley_cup import StanleyCup
from .runtime_db import database_path
from .retention import compact
from .lineup_uploads import router as lineup_upload_router

ROOT = Path(__file__).resolve().parents[1]
FALSE_VALUES = {'0', 'false', 'no', 'off', 'disabled'}
TRUE_VALUES = {'1', 'true', 'yes', 'on', 'enabled'}


def manual_odds_refresh_enabled():
    return os.environ.get('NHL_MANUAL_ODDS_REFRESH_ENABLED', 'true').strip().lower() not in FALSE_VALUES


def automatic_odds_refresh_enabled():
    return os.environ.get('NHL_AUTOMATIC_ODDS_REFRESH_ENABLED', 'false').strip().lower() in TRUE_VALUES


def require_manual_odds_refresh():
    if not manual_odds_refresh_enabled():
        raise HTTPException(403, 'Manual odds refresh is disabled')


def odds_refresh_payload(payload):
    return {**payload, 'manual_refresh_enabled': manual_odds_refresh_enabled()}


async def automatic_odds_refresh(app, interval=3600):
    try:
        while True:
            if odds_configured():
                try:
                    current = today_et()
                    await app.state.moneylines.refresh(current, force=True)
                    await app.state.first_period_odds.refresh(current, force=True)
                except Exception:
                    pass
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        raise


@asynccontextmanager
async def lifespan(app):
    if os.environ.get('NHL_DFO_LINEUP_MODE', 'direct') not in {'direct', 'uploaded'}:
        raise RuntimeError('NHL_DFO_LINEUP_MODE must be direct or uploaded')
    store = Store(database_path(ROOT))
    providers = Providers(store)
    app.state.dashboard = Dashboard(providers)
    app.state.first_period = FirstPeriod(providers)
    app.state.first_period_odds = FirstPeriodOdds(providers)
    app.state.streaks = Streaks(providers)
    app.state.moneylines = Moneylines(providers)
    app.state.player_props = PlayerProps(providers)
    app.state.stanley_cup = StanleyCup(providers)
    compact(store, vacuum=True)
    app.state.automatic_odds_refresh = None
    if automatic_odds_refresh_enabled():
        app.state.automatic_odds_refresh = asyncio.create_task(automatic_odds_refresh(app))
    try:
        yield
    finally:
        if app.state.automatic_odds_refresh:
            app.state.automatic_odds_refresh.cancel()
            try:
                await app.state.automatic_odds_refresh
            except asyncio.CancelledError:
                pass
        await app.state.first_period.close()
        await app.state.streaks.close()
        await store.close()


app = FastAPI(title='NHL Matchup Dashboard', lifespan=lifespan)
app.include_router(lineup_upload_router)


@app.get('/api/health')
async def health():
    return {'status': 'ok', 'today': today_et()}


@app.get('/api/slate')
async def slate(date: Date | None = None):
    return await app.state.dashboard.slate(date.isoformat() if date else today_et())


@app.get('/api/players')
async def players(date: Date | None = None):
    return await players_dashboard(app.state.dashboard.p, date.isoformat() if date else today_et())


@app.get('/api/odds/moneyline')
async def moneyline(date: Date | None = None):
    return odds_refresh_payload(app.state.moneylines.cached(date.isoformat() if date else today_et()))


@app.post('/api/odds/moneyline/refresh')
async def moneyline_refresh(date: Date | None = None):
    require_manual_odds_refresh()
    return odds_refresh_payload(await app.state.moneylines.refresh(date.isoformat() if date else today_et(), force=True))


@app.get('/api/streaks')
async def streaks(date: Date | None = None, scope: Literal['league', 'tonight'] = 'league',
                  toi_window: Literal['last5', 'last10', 'season'] = 'last10'):
    return await app.state.streaks.view(date.isoformat() if date else today_et(), scope, toi_window)


@app.get('/api/player-props')
async def player_props(date: Date | None = None, game_id: int | None = None):
    return odds_refresh_payload(await app.state.player_props.view(date.isoformat() if date else today_et(), game_id))


@app.post('/api/player-props/refresh')
async def player_props_refresh(date: Date | None = None, game_id: int | None = None):
    require_manual_odds_refresh()
    return odds_refresh_payload(await app.state.player_props.view(date.isoformat() if date else today_et(), game_id, refresh=True))


@app.get('/api/first-period')
async def first_period(date: Date | None = None, window: Literal['season', 'last5', 'last10'] = 'season'):
    return await app.state.first_period.view(date.isoformat() if date else today_et(), window)


@app.get('/api/first-period/matchups/{game_id}')
async def first_period_matchup(game_id: int, window: Literal['season', 'last5', 'last10'] = 'season'):
    if not 2000000000 <= game_id <= 2100999999:
        raise HTTPException(404, 'Game not found')
    return await app.state.first_period.view(today_et(), window, game_id)


@app.get('/api/first-period/odds')
async def first_period_odds(date: Date | None = None):
    return odds_refresh_payload(app.state.first_period_odds.cached(date.isoformat() if date else today_et()))


@app.post('/api/first-period/odds/refresh')
async def first_period_odds_refresh(date: Date | None = None):
    require_manual_odds_refresh()
    return odds_refresh_payload(await app.state.first_period_odds.refresh(date.isoformat() if date else today_et(), force=True))


@app.get('/api/stanley-cup')
async def stanley_cup():
    return await app.state.stanley_cup.view()


@app.post('/api/stanley-cup/refresh')
async def stanley_cup_refresh():
    require_manual_odds_refresh()
    return await app.state.stanley_cup.view(refresh=True)


@app.get('/api/matchups/{game_id}')
async def matchup(game_id: int, window: Literal['season', 'last10'] = 'season'):
    if not 2000000000 <= game_id <= 2100999999:
        raise HTTPException(404, 'Game not found')
    result = await app.state.dashboard.matchup(game_id, window)
    if result is None:
        raise HTTPException(503, 'Game details are unavailable. Try again shortly.')
    return result


if (ROOT / 'dist' / 'assets').exists():
    app.mount('/assets', StaticFiles(directory=ROOT / 'dist' / 'assets'), name='assets')


@app.get('/{path:path}')
async def frontend(path: str):
    if path.startswith('api/'):
        raise HTTPException(404, 'Unknown API route')
    index = ROOT / 'dist' / 'index.html'
    if not index.exists():
        raise HTTPException(503, 'Build the frontend first with npm run build.')
    return FileResponse(index, headers={'Cache-Control': 'no-store'})


@app.head('/{path:path}')
async def frontend_head(path: str):
    if path.startswith('api/'):
        raise HTTPException(404, 'Unknown API route')
    index = ROOT / 'dist' / 'index.html'
    return Response(status_code=200 if index.exists() else 503,
                    headers={'Cache-Control': 'no-store'})
