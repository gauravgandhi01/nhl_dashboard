"""Conservative name-to-NHL-ID resolution shared by lines and prop providers."""
import json
from pathlib import Path

from .stats import normalized_name

ALIAS_PATH = Path(__file__).resolve().parents[1] / 'config' / 'player_aliases.json'


def resolve_player(name, players, aliases=None):
    if aliases is None:
        try:
            aliases = json.loads(ALIAS_PATH.read_text()) if ALIAS_PATH.exists() else {}
        except (OSError, ValueError):
            return None
    if not isinstance(aliases, dict):
        return None
    key = normalized_name(name)
    if not key:
        return None
    ids = {p['id'] for p in players if normalized_name(p['name']) == key}
    alias_ids = {value for alias, value in aliases.items()
                 if normalized_name(alias) == key and isinstance(value, int)}
    ids.update(alias_ids)
    if len(ids) != 1:
        return None
    candidates = [p for p in players if p['id'] in ids]
    # A duplicate ID on two teams is not a verified identity for this event.
    return candidates[0] if len(candidates) == 1 else None
