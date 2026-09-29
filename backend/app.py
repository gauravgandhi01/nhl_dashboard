from contextlib import asynccontextmanager
from datetime import date as Date
from pathlib import Path
from typing import Literal
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .cache import Store
from .providers import Providers
from .service import Dashboard, today_et
from .players import players_dashboard
from .first_period import FirstPeriod
from .first_period_odds import FirstPeriodOdds
from .streaks import Streaks
from .moneyline import Moneylines

ROOT = Path(__file__).resolve().parents[1]


@asynccontextmanager
async def lifespan(app):
    store = Store(Path(os.environ.get('NHL_DASHBOARD_DB', ROOT / 'data' / 'dashboard.sqlite3')))
    providers = Providers(store)
    app.state.dashboard = Dashboard(providers)
    app.state.first_period = FirstPeriod(providers)
    app.state.first_period_odds = FirstPeriodOdds(providers)
    app.state.streaks = Streaks(providers)
    app.state.moneylines = Moneylines(providers)
    yield
    await app.state.first_period.close()
    await app.state.streaks.close()
    await store.close()


app = FastAPI(title='NHL Matchup Dashboard', lifespan=lifespan)


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
    return app.state.moneylines.cached(date.isoformat() if date else today_et())


@app.post('/api/odds/moneyline/refresh')
async def moneyline_refresh(date: Date | None = None):
    return await app.state.moneylines.refresh(date.isoformat() if date else today_et())


@app.get('/api/streaks')
async def streaks(date: Date | None = None, scope: Literal['league', 'tonight'] = 'league'):
    return await app.state.streaks.view(date.isoformat() if date else today_et(), scope)


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
    return app.state.first_period_odds.cached(date.isoformat() if date else today_et())


@app.post('/api/first-period/odds/refresh')
async def first_period_odds_refresh(date: Date | None = None):
    return await app.state.first_period_odds.refresh(date.isoformat() if date else today_et())


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
    return FileResponse(index)
