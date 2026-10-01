from __future__ import annotations

import math

from .odds_config import bookmaker_fees


def american_to_decimal(price: int | float) -> float | None:
    if price is None or not math.isfinite(float(price)) or abs(float(price)) < 100:
        return None
    price = float(price)
    return 1 + price / 100 if price > 0 else 1 + 100 / abs(price)


def decimal_to_american(decimal: float) -> float | None:
    if decimal is None or not math.isfinite(decimal) or decimal <= 1:
        return None
    return (decimal - 1) * 100 if decimal >= 2 else -100 / (decimal - 1)


def net_decimal(bookmaker: str | None, price: int | float, fees=None) -> float | None:
    decimal = american_to_decimal(price)
    if decimal is None:
        return None
    fee = (fees if fees is not None else bookmaker_fees()).get(str(bookmaker or '').lower())
    if not fee:
        return decimal
    if fee['type'] == 'profit_pct':
        return 1 + (decimal - 1) * (1 - fee['value'])
    if fee['type'] == 'kalshi_taker':
        probability = 1 / decimal
        cost = probability + fee['coefficient'] * probability * (1 - probability)
        return 1 / cost if cost > 0 else decimal
    return decimal


def effective_american(bookmaker: str | None, price: int | float, fees=None) -> float | None:
    decimal = net_decimal(bookmaker, price, fees)
    return decimal_to_american(decimal) if decimal is not None else None
