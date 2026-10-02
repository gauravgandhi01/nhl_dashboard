"""Run on the laptop: python -m backend.collect_lineups --help."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import plistlib
import secrets
import subprocess
import sys
from urllib.parse import urlsplit

import httpx

from .cache import Store
from .lineup_uploads import LineupBatch
from .providers import Providers, TEAM_NAMES, parse_lineups

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / 'data' / 'lineup-upload.json'
LABEL = 'com.nhl-dashboard.lineup-collector'


def site_url(value):
    parsed = urlsplit(value)
    local = parsed.hostname in {'localhost', '127.0.0.1'}
    if (not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {'', '/'} or (parsed.scheme != 'https' and not (local and parsed.scheme == 'http'))):
        raise ValueError('Site must be an HTTPS origin, such as https://your-site.onrender.com (HTTP allowed only for localhost)')
    return value.rstrip('/')


def read_config(path):
    config = json.loads(path.read_text())
    config['site'] = site_url(config['site'])
    if not isinstance(config.get('token'), str) or len(config['token']) < 32:
        raise ValueError('Configure an upload token of at least 32 characters')
    return config


def initialize(path, site):
    config = {'site': site_url(site), 'token': secrets.token_urlsafe(32)}
    path.parent.mkdir(parents=True, exist_ok=True)
    # Refuse to overwrite an existing secret; never put it in stdout or process arguments.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as file:
        json.dump(config, file, indent=2)
        file.write('\n')
    print(f'Created private config: {path}')
    print('Set Render NHL_LINEUP_UPLOAD_TOKEN to the token in that file, and NHL_DFO_LINEUP_MODE=uploaded.')


async def remote_request(client, config, method, payload=None):
    for attempt in range(3):
        try:
            response = await client.request(method, config['site'] + '/api/admin/lineups',
                                            headers={'Authorization': 'Bearer ' + config['token']}, json=payload)
        except httpx.RequestError:
            if attempt == 2:
                raise RuntimeError('Could not reach lineup upload endpoint') from None
        else:
            if response.is_success:
                try:
                    result = response.json()
                    if not isinstance(result, dict):
                        raise ValueError('Expected object')
                    return result
                except ValueError:
                    raise RuntimeError('Upload endpoint did not return JSON; check the deployed backend') from None
            if response.status_code not in {429, 502, 503, 504} or attempt == 2:
                raise RuntimeError(f'Upload endpoint returned HTTP {response.status_code}; check deployment and Render token settings')
        await asyncio.sleep(2 ** (attempt + 1))


async def collect(store, teams, pause=1):
    provider = Providers(store)
    entries, failures = [], []
    for index, team in enumerate(teams):
        slug = TEAM_NAMES[team].lower().replace(' ', '-')
        # Explicitly use direct fetching, even if the server's uploaded-mode env is set locally.
        feed = await provider.dfo(f'/teams/{slug}/line-combinations', parse_lineups, ttl=120)
        if feed.data is None or feed.stale or feed.error or not feed.retrieved_at:
            failures.append(team)
            print(f'{team}: skipped ({feed.error or "no fresh lineup"})', file=sys.stderr, flush=True)
        else:
            entry = {'team': team, 'retrieved_at': feed.retrieved_at, 'data': feed.data}
            # Apply the same schema locally so one bad source cannot spoil the whole batch.
            try:
                LineupBatch.model_validate({'version': 1, 'lineups': [entry]})
            except ValueError:
                failures.append(team)
                print(f'{team}: skipped (invalid lineup snapshot)', file=sys.stderr, flush=True)
            else:
                entries.append(entry)
        if pause and index + 1 < len(teams):
            await asyncio.sleep(pause)
    return {'version': 1, 'lineups': entries}, failures


async def run(args):
    config = None if args.dry_run else read_config(args.config)
    async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=20), follow_redirects=False) as client:
        if config:
            status = await remote_request(client, config, 'GET')
            if status.get('mode') != 'uploaded':
                raise RuntimeError('Set NHL_DFO_LINEUP_MODE=uploaded on Render before running the collector')
        store = Store(ROOT / 'data' / 'lineup-collector.sqlite3')
        try:
            payload, failures = await collect(store, args.teams or sorted(TEAM_NAMES))
        finally:
            await store.close()
        if not payload['lineups']:
            raise RuntimeError('No fresh lineups collected; the server was left unchanged')
        if args.dry_run:
            print(f'Validated {len(payload["lineups"])} lineups; no upload performed. Failed teams: {", ".join(failures) or "none"}')
        else:
            result = await remote_request(client, config, 'POST', payload)
            if not isinstance(result.get('accepted'), list) or not isinstance(result.get('ignored'), list):
                raise RuntimeError('Unexpected upload acknowledgement')
            print(f'Uploaded {len(result["accepted"])} newer lineups; {len(result["ignored"])} already current. Failed teams: {", ".join(failures) or "none"}', flush=True)
        return 1 if failures else 0


async def status(config):
    async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=20), follow_redirects=False) as client:
        return await remote_request(client, config, 'GET')


def install_schedule(args):
    if sys.platform != 'darwin':
        raise RuntimeError('The scheduler installer requires macOS; run the collector with your system scheduler elsewhere')
    config = read_config(args.config)
    if not args.write_only:
        result = asyncio.run(status(config))
        if result.get('mode') != 'uploaded':
            raise RuntimeError('Configure uploaded mode on Render first')
    logs = ROOT / 'data' / 'lineup-collector-logs'
    logs.mkdir(parents=True, exist_ok=True)
    plist = Path.home() / 'Library' / 'LaunchAgents' / (LABEL + '.plist')
    plist.parent.mkdir(parents=True, exist_ok=True)
    content = {
        'Label': LABEL,
        'ProgramArguments': [sys.executable, '-u', '-m', 'backend.collect_lineups',
                             '--config', str(args.config.resolve()), 'run'],
        'WorkingDirectory': str(ROOT), 'StartInterval': 300, 'RunAtLoad': True,
        'StandardOutPath': str(logs / 'stdout.log'), 'StandardErrorPath': str(logs / 'stderr.log'),
        'ProcessType': 'Background',
    }
    plist.write_bytes(plistlib.dumps(content))
    if args.write_only:
        print(f'Wrote {plist}; scheduler has not been activated.')
        return
    domain = f'gui/{os.getuid()}'
    subprocess.run(['launchctl', 'bootout', domain + '/' + LABEL], capture_output=True)
    subprocess.run(['launchctl', 'bootstrap', domain, str(plist)], check=True)
    print(f'Collector scheduled every five minutes while logged in and awake. Logs: {logs}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    commands = parser.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init', help='Create a private configuration and shared secret')
    init.add_argument('--site', required=True)
    run_parser = commands.add_parser('run', help='Collect and upload current lineups')
    run_parser.add_argument('--dry-run', action='store_true', help='Fetch and validate without contacting the live site')
    run_parser.add_argument('--teams', nargs='+', choices=sorted(TEAM_NAMES), help='Default: all 32 teams')
    commands.add_parser('status', help='Show authenticated server snapshot status')
    schedule = commands.add_parser('install-schedule', help='Install a macOS LaunchAgent')
    schedule.add_argument('--write-only', action='store_true', help='Prepare the plist without activating it')
    args = parser.parse_args()
    try:
        if args.command == 'init':
            initialize(args.config, args.site)
        elif args.command == 'run':
            return asyncio.run(run(args))
        elif args.command == 'status':
            print(json.dumps(asyncio.run(status(read_config(args.config))), indent=2))
        else:
            install_schedule(args)
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f'Collector: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
