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
    exact_matches = [p for p in players if normalized_name(p['name']) == key]
    ids = {p['id'] for p in exact_matches}
    alias_ids = {value for alias, value in aliases.items()
                 if normalized_name(alias) == key and isinstance(value, int)}

    if alias_ids:
        candidates = [p for p in players if p['id'] in alias_ids]
        if len(candidates) == 1 and (not exact_matches or len(exact_matches) > 1 or candidates[0]['id'] in ids):
            return candidates[0]
        return None

    if len(ids) != 1:
        return None
    candidates = [p for p in players if p['id'] in ids]
    # A duplicate ID on two teams is not a verified identity for this event.
    return candidates[0] if len(candidates) == 1 else None
