#!/usr/bin/env python3
"""Bootstrap isolated dependencies, build the UI, and serve on a free local port."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
import venv

ROOT = Path(__file__).resolve().parent
WATCH_PATHS = ['src', 'index.html', 'package.json', 'package-lock.json', 'tsconfig.json', 'vite.config.ts']
FALSE_VALUES = {'0', 'false', 'no', 'off', 'disabled'}


def run(args, env=None):
    subprocess.run([str(a) for a in args], cwd=ROOT, env=env, check=True)


def frontend_files_mtime():
    latest = 0.0
    for name in WATCH_PATHS:
        path = ROOT / name
        if path.is_file():
            latest = max(latest, path.stat().st_mtime)
        elif path.is_dir():
            for item in path.rglob('*'):
                if item.is_file():
                    latest = max(latest, item.stat().st_mtime)
    return latest


def npm_command_from_env():
    node = os.environ.get('NHL_DASHBOARD_NODE') or shutil.which('node')
    npm_cli = os.environ.get('NHL_DASHBOARD_NPM_CLI')
    if node and npm_cli:
        return [node, npm_cli]
    return [shutil.which('npm') or 'npm']


def start_frontend_watcher(interval=1.0):
    npm_command = npm_command_from_env()
    env = {**os.environ}
    if os.environ.get('NHL_DASHBOARD_NODE'):
        env['PATH'] = str(Path(os.environ['NHL_DASHBOARD_NODE']).parent) + os.pathsep + env.get('PATH', '')

    def watch():
        last_seen = frontend_files_mtime()
        last_built = time.time()
        building = False
        while True:
            time.sleep(interval)
            current = frontend_files_mtime()
            if building or current <= last_seen or current <= last_built:
                last_seen = max(last_seen, current)
                continue
            time.sleep(0.25)
            current = frontend_files_mtime()
            building = True
            try:
                print('Frontend change detected; rebuilding UI...', flush=True)
                run([*npm_command, 'run', 'build'], env)
                last_built = time.time()
                print('Frontend rebuild complete. Refresh the browser.', flush=True)
            except subprocess.CalledProcessError as exc:
                print(f'Frontend rebuild failed with exit code {exc.returncode}. Fix the error and save again.', flush=True)
            finally:
                last_seen = current
                building = False

    thread = threading.Thread(target=watch, daemon=True)
    thread.start()


def frontend_watcher_enabled():
    if os.environ.get('NHL_WATCH_FRONTEND') is not None:
        return os.environ.get('NHL_WATCH_FRONTEND', '').strip().lower() not in FALSE_VALUES
    return not (os.environ.get('RENDER') or os.environ.get('PORT'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--serve', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--no-watch-build', action='store_true',
                        help='Disable automatic frontend rebuilds while serving.')
    args = parser.parse_args()
    if args.serve:
        import uvicorn
        if not args.no_watch_build and frontend_watcher_enabled():
            start_frontend_watcher()
        sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        for port in range(args.port, args.port + 100):
            try:
                sock.bind(('127.0.0.1', port))
                break
            except OSError:
                continue
        else:
            raise RuntimeError('No available local port')
        sock.listen(128)
        print(f'\nNHL dashboard: http://127.0.0.1:{port}\n', flush=True)
        config = uvicorn.Config('backend.app:app', log_level='info')
        uvicorn.Server(config).run(sockets=[sock])
        return
    os.chdir(ROOT)
    python = ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not python.exists():
        print('Setting up Python dependencies...', flush=True)
        venv.EnvBuilder(with_pip=True).create(ROOT / '.venv')
    requirements = hashlib.sha256((ROOT / 'requirements.txt').read_bytes()).hexdigest()
    marker = ROOT / '.venv' / 'requirements.sha256'
    if not marker.exists() or marker.read_text() != requirements:
        run([python, '-m', 'pip', 'install', '-r', 'requirements.txt'])
        marker.write_text(requirements)
    node = shutil.which('node')
    local_node = ROOT / '.runtime/node_modules/node/bin/node'
    local_npm = ROOT / '.runtime/node_modules/npm/bin/npm-cli.js'
    if not node or int(subprocess.check_output([node, '--version'], text=True).strip().lstrip('v').split('.')[0]) < 22:
        if not local_node.exists():
            npm = shutil.which('npm')
            if not npm:
                raise RuntimeError('Install Node.js 22 or newer, then rerun python3 run.py.')
            print('Installing a project-local Node.js runtime...', flush=True)
            run([npm, 'install', '--prefix', '.runtime', '--no-audit', '--no-fund', 'node@22', 'npm@10'])
        node = str(local_node)
        npm_command = [node, str(local_npm)]
    else:
        npm_command = [shutil.which('npm') or 'npm']
    env = {**os.environ, 'PATH': str(Path(node).parent) + os.pathsep + os.environ.get('PATH', '')}
    if not (ROOT / 'node_modules').exists():
        run([*npm_command, 'ci' if (ROOT / 'package-lock.json').exists() else 'install', '--no-audit', '--no-fund'], env)
    run([*npm_command, 'run', 'build'], env)
    env['NHL_DASHBOARD_NODE'] = str(node)
    if len(npm_command) == 2 and str(npm_command[0]) == str(node):
        env['NHL_DASHBOARD_NPM_CLI'] = str(npm_command[1])
    os.execve(str(python), [str(python), str(ROOT / 'run.py'), '--serve', '--port', str(args.port)], env)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
