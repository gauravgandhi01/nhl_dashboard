from __future__ import annotations

import asyncio
import csv
import io
import json
import zipfile
from datetime import datetime
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup

from .cache import Feed, Store
from .stats import normalized_name

WEB = 'https://api-web.nhle.com/v1'
STATS = 'https://api.nhle.com/stats/rest/en'
MP_TEAMS = 'https://moneypuck.com/moneypuck/playerData/careers/gameByGame/all_teams.csv'
DFO = 'https://www.dailyfaceoff.com'
TEAM_NAMES = {
    'ANA': 'Anaheim Ducks', 'BOS': 'Boston Bruins', 'BUF': 'Buffalo Sabres', 'CAR': 'Carolina Hurricanes',
    'CBJ': 'Columbus Blue Jackets', 'CGY': 'Calgary Flames', 'CHI': 'Chicago Blackhawks', 'COL': 'Colorado Avalanche',
    'DAL': 'Dallas Stars', 'DET': 'Detroit Red Wings', 'EDM': 'Edmonton Oilers', 'FLA': 'Florida Panthers',
    'LAK': 'Los Angeles Kings', 'MIN': 'Minnesota Wild', 'MTL': 'Montreal Canadiens', 'NJD': 'New Jersey Devils',
    'NSH': 'Nashville Predators', 'NYI': 'New York Islanders', 'NYR': 'New York Rangers', 'OTT': 'Ottawa Senators',
    'PHI': 'Philadelphia Flyers', 'PIT': 'Pittsburgh Penguins', 'SEA': 'Seattle Kraken', 'SJS': 'San Jose Sharks',
    'STL': 'St Louis Blues', 'TBL': 'Tampa Bay Lightning', 'TOR': 'Toronto Maple Leafs', 'UTA': 'Utah Mammoth',
    'VAN': 'Vancouver Canucks', 'VGK': 'Vegas Golden Knights', 'WPG': 'Winnipeg Jets', 'WSH': 'Washington Capitals',
}
ALIASES = {'L.A': 'LAK', 'N.J': 'NJD', 'S.J': 'SJS', 'T.B': 'TBL', 'UTAH': 'UTA'}


def object_json(raw):
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError('Expected object')
    return data


def stats_json(raw):
    data = object_json(raw)
    if not isinstance(data.get('data'), list) or not isinstance(data.get('total'), int):
        raise ValueError('Stats schema changed')
    return data


def csv_rows(raw, required):
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    if not required.issubset(set(reader.fieldnames or [])):
        raise ValueError('CSV schema changed')
    return reader


def parse_mp_teams(raw, year):
    keep = {'team', 'gameId', 'gameDate', 'iceTime', 'xGoalsFor', 'xGoalsAgainst', 'shotAttemptsFor', 'shotAttemptsAgainst'}
    return [{k: r[k] for k in keep} for r in csv_rows(raw, keep | {'season', 'situation', 'playoffGame'})
            if r['season'] == str(year) and r['situation'] == '5on5' and r['playoffGame'] == '0']


def parse_mp_goalies(raw):
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
        names = [n for n in archive.namelist() if n.endswith('.csv')]
        if not names:
            raise ValueError('No CSV in archive')
        rows = csv_rows(archive.read(names[0]), {'playerId', 'gameId', 'situation', 'xGoals', 'goals'})
        return [{k: r.get(k) for k in ['playerId', 'gameId', 'gameDate', 'xGoals', 'goals']}
                for r in rows if r['situation'] == 'all']
    except zipfile.BadZipFile as exc:
        raise ValueError('Invalid archive') from exc


def parse_mp_skaters(raw):
    keep = {'playerId', 'gameId', 'icetime', 'I_F_shotAttempts', 'I_F_points',
            'I_F_shotsOnGoal', 'I_F_xGoals', 'I_F_highDangerShots', 'situation'}
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = [n for n in archive.namelist() if n.endswith('.csv')]
            if len(names) != 1:
                raise ValueError('Unexpected skater archive')
            with archive.open(names[0]) as file:
                rows = csv.DictReader(io.TextIOWrapper(file, encoding='utf-8-sig'))
                if not (keep | {'situation'}).issubset(set(rows.fieldnames or [])):
                    raise ValueError('Skater CSV schema changed')
                return [{k: r[k] for k in keep} for r in rows
                        if r['situation'] in ['all', '5on5'] and str(r['gameId'])[4:6] == '02']
    except zipfile.BadZipFile as exc:
        raise ValueError('Invalid skater archive') from exc


def parse_goalies(raw):
    soup = BeautifulSoup(raw, 'html.parser')
    script = soup.find('script', id='__NEXT_DATA__')
    if script is None:
        raise ValueError('Starting-goalie page data unavailable')
    data = page_props(script).get('data')
    if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
        raise ValueError('Starting-goalie schema changed')
    return data


def page_props(script):
    try:
        result = json.loads(script.string or '')['props']['pageProps']
        if not isinstance(result, dict):
            raise ValueError('Page props changed')
        return result
    except (TypeError, KeyError) as exc:
        raise ValueError('Page props changed') from exc


def parse_lineups(raw):
    soup = BeautifulSoup(raw, 'html.parser')
    script = soup.find('script', id='__NEXT_DATA__')
    if script:
        payload = page_props(script).get('combinations') or {}
        if not isinstance(payload, dict):
            raise ValueError('Lineup schema changed')
        if isinstance(payload.get('players'), list):
            groups = {}
            group_labels = {'f1': 'Forward line 1', 'f2': 'Forward line 2', 'f3': 'Forward line 3', 'f4': 'Forward line 4',
                            'd1': 'Defense pair 1', 'd2': 'Defense pair 2', 'd3': 'Defense pair 3'}
            for player in payload['players']:
                if not isinstance(player, dict):
                    raise ValueError('Lineup player schema changed')
                category, group = player.get('categoryIdentifier'), player.get('groupIdentifier')
                label = group_labels.get(group) if category == 'ev' else None
                if category in ['g', 'goalie', 'goalies'] or group in ['g', 'g1', 'g2']:
                    label = 'Goalies'
                if category == 'pp':
                    label = 'Power play ' + str(group or '').lstrip('p')
                if label and player.get('name'):
                    groups.setdefault(label, []).append(player['name'])
            if groups:
                return {'sections': groups, 'updated_at': payload.get('updatedAt')}
    if 'DFO Projected Lineup' not in soup.get_text(' ', strip=True):
        raise ValueError('Lineup page unavailable')
    sections = {}
    current = None
    headings = {'Forwards', 'Defensive Pairings', '1st Powerplay Unit', '2nd Powerplay Unit', 'Goalies', 'Injuries'}
    stop = {'1st Penalty Kill Unit', '2nd Penalty Kill Unit', 'Team News', 'Team Sites'}
    for node in soup.find_all(['h2', 'h3', 'h4', 'h5', 'div', 'a']):
        if node.name != 'a':
            if len(node.find_all(recursive=False)) > 1:
                continue
            label = node.get_text(' ', strip=True)
            if label in headings:
                current = label
                sections.setdefault(current, [])
            elif label in stop:
                current = None
        elif current and '/players/' in node.get('href', ''):
            name = node.get_text(' ', strip=True)
            if name and name not in sections[current]:
                sections[current].append(name)
    if not sections.get('Forwards') and not sections.get('Defensive Pairings'):
        raise ValueError('Projected lineup schema changed')
    stamp = soup.find('time')
    return {'sections': sections, 'updated_at': stamp.get('datetime') if stamp else None}


def starter_for(game, rows):
    empty = {'away': {'name': None, 'status': 'Unknown', 'updated_at': None},
             'home': {'name': None, 'status': 'Unknown', 'updated_at': None}}
    if not rows:
        return empty
    for row in rows:
        if any(normalized_name(row.get(f'{side}TeamName')) != normalized_name(TEAM_NAMES.get(game[f'{side}Team']['abbrev'], ''))
               for side in ['away', 'home']):
            continue
        try:
            source_time = datetime.fromisoformat((row.get('dateGmt') or '').replace('Z', '+00:00'))
            game_time = datetime.fromisoformat(game['startTimeUTC'].replace('Z', '+00:00'))
            if abs((source_time - game_time).total_seconds()) > 3600:
                continue
        except (KeyError, ValueError, TypeError):
            continue
        for side in ['away', 'home']:
            name = row.get(f'{side}GoalieName')
            status = row.get(f'{side}NewsStrengthName') or 'Unconfirmed'
            if status not in ['Confirmed', 'Likely', 'Unconfirmed']:
                status = 'Unconfirmed'
            empty[side] = {'name': name, 'status': status if name else 'Unknown',
                           'updated_at': row.get(f'{side}NewsCreatedAt')}
        return empty
    return empty


class Providers:
    def __init__(self, store: Store):
        self.store = store
        self.memo = {}
        self.locks = {}

    async def nhl(self, path, ttl=600):
        return await self.store.fetch(f'{WEB}/{path}', 'NHL', ttl, object_json)

    async def stats(self, report, season, extra='', is_game=True):
        params = {'isGame': str(is_game).lower(), 'cayenneExp': f'seasonId={season} and gameTypeId=2{extra}',
                  'limit': 100, 'start': 0,
                  'sort': json.dumps(([{'property': 'gameId', 'direction': 'DESC'}] if is_game else []) +
                                     [{'property': 'teamId' if report.startswith('team/') else 'playerId', 'direction': 'ASC'}])}
        rows, metas = [], []
        while True:
            feed = await self.store.fetch(f'{STATS}/{report}', 'NHL Stats', 21600, stats_json, params)
            metas.append(feed)
            data = feed.data
            if data is None or not isinstance(data.get('data'), list):
                return Feed(None, feed.source, feed.url, feed.retrieved_at, feed.stale, feed.error or 'Stats schema changed')
            rows.extend(data['data'])
            if len(rows) >= data.get('total', len(rows)):
                break
            if not data['data']:
                return Feed(None, feed.source, feed.url, error='Incomplete stats pagination')
            params['start'] += len(data['data'])
        return Feed(rows, feed.source, feed.url, min((f.retrieved_at for f in metas if f.retrieved_at), default=None),
                    any(f.stale for f in metas))

    async def mp(self, kind, season):
        key = (kind, season)
        import time
        async with self.locks.setdefault(key, asyncio.Lock()):
            existing = self.memo.get(key)
            if existing and time.monotonic() - existing[0] < 600:
                return existing[1]
            year = season // 10000
            url = MP_TEAMS if kind == 'teams' else f'https://peter-tanner.com/moneypuck/downloads/seasonPlayersSummary/{kind}/{year}.zip'
            parser = (lambda raw: parse_mp_teams(raw, year)) if kind == 'teams' else parse_mp_skaters if kind == 'skaters' else parse_mp_goalies
            feed = await self.store.fetch(url, 'MoneyPuck', 21600, parser)
            self.memo[key] = (time.monotonic(), feed)
            if feed.data:
                self.store.save_games('moneypuck_' + kind, season, feed.data, 'team' if kind == 'teams' else 'playerId')
            return feed

    async def dfo(self, path, parser):
        url = DFO + path
        robots = await self.store.fetch(DFO + '/robots.txt', 'Daily Faceoff', 86400, lambda raw: raw.decode())
        if robots.data is None:
            return Feed(None, 'Daily Faceoff', url, error='Source access rules unavailable')
        rules = RobotFileParser()
        rules.parse(robots.data.splitlines())
        if not rules.can_fetch('NHLMatchupDashboard', url):
            return Feed(None, 'Daily Faceoff', url, error='Automated access unavailable')
        return await self.store.fetch(url, 'Daily Faceoff', 600, parser)

    async def goalies(self, date):
        return await self.dfo(f'/starting-goalies/{date}', parse_goalies)

    async def lineup(self, abbrev):
        name = TEAM_NAMES.get(abbrev)
        if not name:
            return Feed(None, 'Daily Faceoff', DFO, error='Team mapping unavailable')
        slug = name.lower().replace(' ', '-')
        return await self.dfo(f'/teams/{slug}/line-combinations', parse_lineups)

    async def injuries(self):
        return await self.store.fetch('https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/injuries', 'ESPN', 3600, object_json)
