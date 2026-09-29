from __future__ import annotations

import os
import shutil
from pathlib import Path


def database_path(root: Path) -> Path:
    target = Path(os.environ.get('NHL_DASHBOARD_DB', root / 'data' / 'dashboard.sqlite3'))
    seed = Path(os.environ.get('NHL_SEED_DB', root / 'data' / 'seed.sqlite3'))
    if seed.exists() and not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(seed, target)
    return target
