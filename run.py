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
import venv

ROOT = Path(__file__).resolve().parent


def run(args, env=None):
    subprocess.run([str(a) for a in args], cwd=ROOT, env=env, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--serve', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.serve:
        import uvicorn
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
    os.execv(str(python), [str(python), str(ROOT / 'run.py'), '--serve', '--port', str(args.port)])


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
