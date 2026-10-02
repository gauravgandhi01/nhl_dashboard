"""Authenticated, timestamp-preserving transport for laptop-collected lineups."""
from __future__ import annotations

import hmac
import json
import os
import time
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator

from .cache import Feed
from .providers import TEAM_NAMES

MAX_BODY_BYTES = 256 * 1024
FRESH_SECONDS = 20 * 60
MAX_AGE_SECONDS = 24 * 60 * 60
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
router = APIRouter(prefix='/api/admin/lineups')


class LineupData(BaseModel):
    model_config = ConfigDict(extra='forbid')
    sections: dict[Name, list[Name]] = Field(min_length=1, max_length=20)
    updated_at: str | None = Field(default=None, max_length=100)

    @field_validator('sections')
    @classmethod
    def valid_sections(cls, sections):
        if any(len(players) > 30 for players in sections.values()):
            raise ValueError('Too many players in a section')
        if not any(players for label, players in sections.items()
                   if label in {'Forwards', 'Defensive Pairings'} or label.startswith(('Forward line ', 'Defense pair '))):
            raise ValueError('A lineup must include forwards or defense pairs')
        return sections


class LineupSnapshot(BaseModel):
    model_config = ConfigDict(extra='forbid')
    team: str
    retrieved_at: AwareDatetime
    data: LineupData

    @field_validator('team')
    @classmethod
    def known_team(cls, team):
        if team not in TEAM_NAMES:
            raise ValueError('Unknown NHL team')
        return team

    @field_validator('retrieved_at')
    @classmethod
    def recent_collection(cls, value):
        age = time.time() - value.timestamp()
        if age < -60 or age > MAX_AGE_SECONDS:
            raise ValueError('Collection time must be within the last 24 hours, with at most 60 seconds of clock skew')
        return value


class LineupBatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: Literal[1]
    lineups: list[LineupSnapshot] = Field(min_length=1, max_length=32)

    @field_validator('lineups')
    @classmethod
    def unique_teams(cls, entries):
        if len({entry.team for entry in entries}) != len(entries):
            raise ValueError('Duplicate teams in upload')
        return entries


def ensure_table(store):
    store.db.execute('''CREATE TABLE IF NOT EXISTS uploaded_lineups (
        team TEXT PRIMARY KEY, body TEXT NOT NULL, fetched REAL NOT NULL,
        uploaded REAL NOT NULL
    )''')
    store.db.commit()


def uploaded_lineup(store, team, url):
    ensure_table(store)
    row = store.db.execute('SELECT body,fetched FROM uploaded_lineups WHERE team=?', (team,)).fetchone()
    if row is None:
        return Feed(None, 'Daily Faceoff', url, error='Waiting for a lineup upload from the laptop collector')
    stamp = datetime.fromtimestamp(row[1], timezone.utc).isoformat()
    age = time.time() - row[1]
    if age > MAX_AGE_SECONDS:
        return Feed(None, 'Daily Faceoff', url, stamp, error='Uploaded lineup expired; laptop collector has not refreshed it in 24 hours')
    stale = age > FRESH_SECONDS
    return Feed(json.loads(row[0]), 'Daily Faceoff', url, stamp, stale,
                'Laptop collector has not refreshed this lineup in 20 minutes' if stale else None)


async def require_upload_token(request: Request):
    token = os.environ.get('NHL_LINEUP_UPLOAD_TOKEN', '')
    if len(token) < 32:
        raise HTTPException(503, 'Lineup uploads are not configured')
    supplied = request.headers.get('authorization', '')
    if not hmac.compare_digest(supplied.encode(), ('Bearer ' + token).encode()):
        raise HTTPException(401, 'Invalid upload credentials', headers={'WWW-Authenticate': 'Bearer'})


@router.post('', dependencies=[Depends(require_upload_token)])
async def upload_lineups(request: Request):
    # Authenticate before reading and bound the streamed body, including chunked requests.
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_BODY_BYTES:
            raise HTTPException(413, 'Lineup upload is too large')
    try:
        batch = LineupBatch.model_validate_json(raw)
    except ValidationError:
        raise HTTPException(422, 'Invalid lineup snapshot, team, or collection timestamp') from None
    store = request.app.state.dashboard.p.store
    ensure_table(store)
    accepted, ignored = [], []
    with store.db:
        for entry in batch.lineups:
            result = store.db.execute('''INSERT INTO uploaded_lineups VALUES(?,?,?,?)
                ON CONFLICT(team) DO UPDATE SET body=excluded.body, fetched=excluded.fetched,
                uploaded=excluded.uploaded WHERE excluded.fetched > uploaded_lineups.fetched''',
                (entry.team, entry.data.model_dump_json(), entry.retrieved_at.timestamp(), time.time()))
            (accepted if result.rowcount else ignored).append(entry.team)
    return {'accepted': accepted, 'ignored': ignored}


@router.get('', dependencies=[Depends(require_upload_token)])
async def upload_status(request: Request):
    store = request.app.state.dashboard.p.store
    ensure_table(store)
    rows = store.db.execute('SELECT team,fetched,uploaded FROM uploaded_lineups ORDER BY team').fetchall()
    now = time.time()
    return {'mode': os.environ.get('NHL_DFO_LINEUP_MODE', 'direct'), 'teams': [
        {'team': team, 'retrieved_at': datetime.fromtimestamp(fetched, timezone.utc).isoformat(),
         'uploaded_at': datetime.fromtimestamp(uploaded, timezone.utc).isoformat(),
         'status': 'expired' if now - fetched > MAX_AGE_SECONDS else 'stale' if now - fetched > FRESH_SECONDS else 'available'}
        for team, fetched, uploaded in rows]}
