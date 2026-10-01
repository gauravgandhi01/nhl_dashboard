"""Shared odds-provider region and bookmaker configuration."""
import json
from pathlib import Path

REGIONS = 'us,us2,us_ex'
CONFIG_PATH = Path(__file__).resolve().parents[1] / 'config' / 'odds.json'

BOOKMAKER_REGIONS = {
    'ballybet': 'us2',
    'betanysports': 'us2',
    'betmgm': 'us',
    'betonlineag': 'us',
    'betopenly': 'us_ex',
    'betparx': 'us2',
    'betrivers': 'us',
    'betus': 'us',
    'bovada': 'us',
    'draftkings': 'us',
    'espnbet': 'us2',
    'fanatics': 'us',
    'fanduel': 'us',
    'fliff': 'us2',
    'hardrockbet': 'us2',
    'kalshi': 'us_ex',
    'lowvig': 'us',
    'mybookieag': 'us',
    'novig': 'us_ex',
    'polymarket': 'us_ex',
    'prophetx': 'us_ex',
    'williamhill_us': 'us',
}

OBSERVED_BOOKMAKERS = {
    'ballybet': 'Bally Bet',
    'betanysports': 'BetAnything',
    'betmgm': 'BetMGM',
    'betonlineag': 'BetOnline.ag',
    'betopenly': 'BetOpenly',
    'betparx': 'betPARX',
    'betrivers': 'BetRivers',
    'betus': 'BetUS',
    'bovada': 'Bovada',
    'draftkings': 'DraftKings',
    'espnbet': 'ESPN BET / theScore Bet',
    'fanatics': 'Fanatics',
    'fanduel': 'FanDuel',
    'fliff': 'Fliff',
    'hardrockbet': 'Hard Rock Bet',
    'kalshi': 'Kalshi',
    'lowvig': 'LowVig.ag',
    'mybookieag': 'MyBookie.ag',
    'novig': 'Novig',
    'polymarket': 'Polymarket',
    'prophetx': 'ProphetX',
    'williamhill_us': 'Caesars',
}


def load_config(path=None):
    target = Path(path) if path else CONFIG_PATH
    if not target.exists():
        return {}
    try:
        data = json.loads(target.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid odds config: {target}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Invalid odds config: {target}")
    return data


def configured_bookmakers(config=None):
    data = load_config() if config is None else config
    raw = data.get('bookmakers', [])
    if not raw:
        return []
    if isinstance(raw, str):
        raw = raw.split(',')
    if not isinstance(raw, list):
        raise ValueError('Odds config bookmakers must be a list')
    keys = []
    for item in raw:
        key = str(item).strip().lower()
        if key and key not in keys:
            keys.append(key)
    unknown = [key for key in keys if key not in OBSERVED_BOOKMAKERS]
    if unknown:
        raise ValueError(f"Unknown bookmaker key(s): {', '.join(unknown)}")
    return keys


def odds_scope(config=None):
    books = configured_bookmakers(config)
    return {
        'regions': REGIONS,
        'bookmakers': books,
        'config_path': str(CONFIG_PATH),
        'mode': 'bookmakers' if books else 'regions',
    }


def market_params(extra=None, config=None):
    params = dict(extra or {})
    books = configured_bookmakers(config)
    if books:
        params['bookmakers'] = ','.join(books)
    else:
        params['regions'] = REGIONS
    return params


def player_prop_market_limit(config=None):
    data = load_config() if config is None else config
    value = data.get('player_prop_market_limit', 8)
    try:
        limit = int(value)
    except (TypeError, ValueError):
        raise ValueError('Odds config player_prop_market_limit must be an integer') from None
    if limit < 1 or limit > 20:
        raise ValueError('Odds config player_prop_market_limit must be between 1 and 20')
    return limit


DEFAULT_BOOKMAKER_FEES = {
    'prophetx': {'type': 'profit_pct', 'value': 0.02},
    'kalshi': {'type': 'kalshi_taker', 'coefficient': 0.07},
}


def bookmaker_fees(config=None):
    data = load_config() if config is None else config
    raw = data.get('bookmaker_fees', {})
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError('Odds config bookmaker_fees must be an object')
    result = {**DEFAULT_BOOKMAKER_FEES}
    for key, value in raw.items():
        bookmaker = str(key).strip().lower()
        if bookmaker not in OBSERVED_BOOKMAKERS:
            raise ValueError(f"Unknown bookmaker fee key: {bookmaker}")
        if value is None:
            result.pop(bookmaker, None)
            continue
        if not isinstance(value, dict):
            raise ValueError('Odds config bookmaker fee entries must be objects')
        fee_type = value.get('type')
        if fee_type == 'profit_pct':
            pct = float(value.get('value'))
            if pct < 0 or pct >= 1:
                raise ValueError('profit_pct bookmaker fees must be between 0 and 1')
            result[bookmaker] = {'type': fee_type, 'value': pct}
        elif fee_type == 'kalshi_taker':
            coefficient = float(value.get('coefficient'))
            if coefficient < 0 or coefficient >= 1:
                raise ValueError('kalshi_taker coefficient must be between 0 and 1')
            result[bookmaker] = {'type': fee_type, 'coefficient': coefficient}
        else:
            raise ValueError(f"Unsupported bookmaker fee type: {fee_type}")
    return result
