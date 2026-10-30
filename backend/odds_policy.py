"""Refresh policy shared by automatic and explicit odds requests."""
from datetime import datetime
import time
from zoneinfo import ZoneInfo

MONEYLINE_TTL = 30 * 60
MANUAL_COOLDOWN = 5 * 60
FAILURE_COOLDOWN = 10 * 60
EXPENSIVE_REFRESH_HOURS = (11, 15, 18)


def expensive_refresh_after(now=None):
    current = (now or datetime.now(ZoneInfo('America/New_York'))).astimezone(ZoneInfo('America/New_York'))
    slots = [current.replace(hour=hour, minute=0, second=0, microsecond=0)
             for hour in EXPENSIVE_REFRESH_HOURS if hour <= current.hour]
    return slots[-1].timestamp() if slots else None


def refresh_due(row, ttl, force=False, refresh_after=None, now=None):
    """Rows are (body, fetched, attempted, error); forced requests still deduplicate."""
    now = time.time() if now is None else now
    if not row:
        return True
    body, fetched, attempted, error = row
    if now - (attempted or 0) < (FAILURE_COOLDOWN if error else MANUAL_COOLDOWN):
        return False
    if force:
        return True
    if refresh_after is not None:
        return not body or (fetched or 0) < refresh_after
    return not body or now - (fetched or 0) >= ttl
