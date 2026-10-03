"""Authenticated, timestamp-preserving transport for laptop-collected lineups."""
from __future__ import annotations

import hmac
import json
import os
import time
from datetime import date, datetime, timezone
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator, model_validator

from .cache import Feed
from .providers import TEAM_NAMES

MAX_BODY_BYTES = 256 * 1024
FRESH_SECONDS = 20 * 60
MAX_AGE_SECONDS = 24 * 60 * 60
GOALIE_MAX_AGE_SECONDS = FRESH_SECONDS
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
router = APIRouter(prefix='/api/admin/lineups')


def recent_collection(value):
    age = time.time() - value.timestamp()
    if age < -60 or age > MAX_AGE_SECONDS:
        raise ValueError('Collection time must be within the last 24 hours, with at most 60 seconds of clock skew')
    return value


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
        return recent_collection(value)


class GoalieGame(BaseModel):
    # Keep only fields consumed by starter_for; omit source logos, salaries, and news HTML.
    model_config = ConfigDict(extra='ignore')
    dateGmt: AwareDatetime
    awayTeamName: Name
    homeTeamName: Name
    awayGoalieName: str | None = Field(max_length=120)
    homeGoalieName: str | None = Field(max_length=120)
    awayNewsStrengthName: str | None = Field(max_length=120)
    homeNewsStrengthName: str | None = Field(max_length=120)
    awayNewsCreatedAt: str | None = Field(default=None, max_length=100)
    homeNewsCreatedAt: str | None = Field(default=None, max_length=100)


class GoalieSnapshot(BaseModel):
    model_config = ConfigDict(extra='forbid')
    date: date
    retrieved_at: AwareDatetime
    data: list[GoalieGame] = Field(max_length=16)

    @field_validator('retrieved_at')
    @classmethod
    def recent_collection(cls, value):
        return recent_collection(value)

    @model_validator(mode='after')
    def matching_games(self):
        games = set()
        for row in self.data:
            if row.dateGmt.astimezone(ZoneInfo('America/New_York')).date() != self.date:
                raise ValueError('Goalie game does not match the snapshot date in Eastern time')
            pair = (row.awayTeamName, row.homeTeamName)
            if pair in games or row.awayTeamName == row.homeTeamName:
                raise ValueError('Duplicate or invalid goalie matchup')
            games.add(pair)
        return self


class LineupBatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: Literal[1]
    lineups: list[LineupSnapshot] = Field(default_factory=list, max_length=32)
    goalies: list[GoalieSnapshot] = Field(default_factory=list, max_length=7)

    @field_validator('lineups')
    @classmethod
    def unique_teams(cls, entries):
        if len({entry.team for entry in entries}) != len(entries):
            raise ValueError('Duplicate teams in upload')
        return entries

    @model_validator(mode='after')
    def valid_batch(self):
        if not self.lineups and not self.goalies:
            raise ValueError('At least one lineup or goalie snapshot is required')
        if len({entry.date for entry in self.goalies}) != len(self.goalies):
            raise ValueError('Duplicate goalie dates in upload')
        return self


def ensure_table(store):
    store.db.execute('''CREATE TABLE IF NOT EXISTS uploaded_lineups (
        team TEXT PRIMARY KEY, body TEXT NOT NULL, fetched REAL NOT NULL,
        uploaded REAL NOT NULL
    )''')
    store.db.execute('''CREATE TABLE IF NOT EXISTS uploaded_goalies (
        date TEXT PRIMARY KEY, body TEXT NOT NULL, fetched REAL NOT NULL,
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


def uploaded_goalies(store, date, url):
    ensure_table(store)
    row = store.db.execute('SELECT body,fetched FROM uploaded_goalies WHERE date=?', (date,)).fetchone()
    if row is None:
        return Feed(None, 'Daily Faceoff', url, error='Waiting for a starting-goalie upload for this date')
    stamp = datetime.fromtimestamp(row[1], timezone.utc).isoformat()
    if time.time() - row[1] > GOALIE_MAX_AGE_SECONDS:
        return Feed(None, 'Daily Faceoff', url, stamp,
                    error='Uploaded starting-goalie status expired; laptop collector has not refreshed it in 20 minutes')
    return Feed(json.loads(row[0]), 'Daily Faceoff', url, stamp)


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
        raise HTTPException(422, 'Invalid lineup or goalie snapshot, date, or collection timestamp') from None
    store = request.app.state.dashboard.p.store
    ensure_table(store)
    accepted, ignored = [], []
    accepted_goalies, ignored_goalies = [], []
    with store.db:
        for entry in batch.lineups:
            result = store.db.execute('''INSERT INTO uploaded_lineups VALUES(?,?,?,?)
                ON CONFLICT(team) DO UPDATE SET body=excluded.body, fetched=excluded.fetched,
                uploaded=excluded.uploaded WHERE excluded.fetched > uploaded_lineups.fetched''',
                (entry.team, entry.data.model_dump_json(), entry.retrieved_at.timestamp(), time.time()))
            (accepted if result.rowcount else ignored).append(entry.team)
        for entry in batch.goalies:
            result = store.db.execute('''INSERT INTO uploaded_goalies VALUES(?,?,?,?)
                ON CONFLICT(date) DO UPDATE SET body=excluded.body, fetched=excluded.fetched,
                uploaded=excluded.uploaded WHERE excluded.fetched > uploaded_goalies.fetched''',
                (entry.date.isoformat(), json.dumps([row.model_dump(mode='json') for row in entry.data]),
                 entry.retrieved_at.timestamp(), time.time()))
            (accepted_goalies if result.rowcount else ignored_goalies).append(entry.date.isoformat())
        store.db.execute('DELETE FROM uploaded_goalies WHERE fetched < ?', (time.time() - 7 * MAX_AGE_SECONDS,))
    result = {'accepted': accepted, 'ignored': ignored}
    if batch.goalies:
        result.update(accepted_goalies=accepted_goalies, ignored_goalies=ignored_goalies)
    return result


@router.get('', dependencies=[Depends(require_upload_token)])
async def upload_status(request: Request):
    store = request.app.state.dashboard.p.store
    ensure_table(store)
    rows = store.db.execute('SELECT team,fetched,uploaded FROM uploaded_lineups ORDER BY team').fetchall()
    goalie_rows = store.db.execute('SELECT date,fetched,uploaded,body FROM uploaded_goalies ORDER BY date').fetchall()
    now = time.time()
    return {'mode': os.environ.get('NHL_DFO_LINEUP_MODE', 'direct'), 'goalie_uploads': True, 'goalies': [
        {'date': day, 'retrieved_at': datetime.fromtimestamp(fetched, timezone.utc).isoformat(),
         'uploaded_at': datetime.fromtimestamp(uploaded, timezone.utc).isoformat(), 'games': len(json.loads(body)),
         'status': 'expired' if now - fetched > GOALIE_MAX_AGE_SECONDS else 'available'}
        for day, fetched, uploaded, body in goalie_rows], 'teams': [
        {'team': team, 'retrieved_at': datetime.fromtimestamp(fetched, timezone.utc).isoformat(),
         'uploaded_at': datetime.fromtimestamp(uploaded, timezone.utc).isoformat(),
         'status': 'expired' if now - fetched > MAX_AGE_SECONDS else 'stale' if now - fetched > FRESH_SECONDS else 'available'}
        for team, fetched, uploaded in rows]}
