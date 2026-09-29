import pytest

from backend.odds_config import (
    configured_bookmakers,
    market_params,
    odds_scope,
    player_prop_market_limit,
)
from backend.probe_player_props import (
    PRIORITY,
    PREVIOUSLY_PRICED,
    bookmaker_coverage,
    choose_markets,
    prop_keys,
)


def test_discovery_selection_is_bounded_prioritized_and_skips_prior_samples():
    keys = ['h2h', *PRIORITY, *PREVIOUSLY_PRICED, 'player_shutouts']
    catalog = {'bookmakers': [{'markets': [{'key': k} for k in keys]}]}
    assert 'h2h' not in prop_keys(catalog)
    assert choose_markets(catalog) == PRIORITY[:8]
    assert not set(choose_markets(catalog)) & PREVIOUSLY_PRICED


def test_discovery_handles_empty_and_deduplicated_catalogs():
    assert choose_markets({}) == []
    book = {'markets': [{'key': 'player_goals_against'}, {'key': None}]}
    assert choose_markets({'bookmakers': [book, book]}) == ['player_goals_against']


def test_bookmaker_filtering_and_observed_options():
    config = {'bookmakers': ['fanduel', 'espnbet', 'kalshi', 'novig', 'fanduel']}
    assert configured_bookmakers(config) == ['fanduel', 'espnbet', 'kalshi', 'novig']
    assert market_params({'markets': 'h2h'}, config) == {'markets': 'h2h', 'bookmakers': 'fanduel,espnbet,kalshi,novig'}
    assert odds_scope(config)['mode'] == 'bookmakers'
    catalog = {'bookmakers': [
        {'key': 'fanduel', 'title': 'FanDuel', 'markets': [{'key': 'player_goals'}]},
        {'key': 'draftkings', 'title': 'DraftKings', 'markets': [{'key': 'player_points'}]},
        {'key': 'espnbet', 'title': 'ESPN BET', 'markets': [{'key': 'player_assists'}]},
        {'key': 'kalshi', 'title': 'Kalshi', 'markets': [{'key': 'player_total_saves'}]},
    ]}
    assert prop_keys(catalog, configured_bookmakers(config)) == {'player_goals', 'player_assists', 'player_total_saves'}
    assert choose_markets(catalog, configured_bookmakers(config)) == ['player_assists', 'player_goals', 'player_total_saves']


def test_invalid_bookmaker_keys_are_explicit():
    with pytest.raises(ValueError, match='unknownbook'):
        configured_bookmakers({'bookmakers': ['fanduel', 'unknownbook']})


def test_market_limit_comes_from_config():
    assert player_prop_market_limit({'player_prop_market_limit': 4}) == 4
    with pytest.raises(ValueError, match='between 1 and 20'):
        player_prop_market_limit({'player_prop_market_limit': 0})


def test_bookmaker_coverage_reports_player_markets():
    catalogs = [{'id': 'a1', 'bookmakers': [
        {'key': 'kalshi', 'title': 'Kalshi', 'markets': [
            {'key': 'player_shots_on_goal'}, {'key': 'h2h'}, {'key': 'player_total_saves'},
        ]},
    ]}]
    coverage = bookmaker_coverage(catalogs)
    assert coverage[0]['key'] == 'kalshi'
    assert coverage[0]['region'] == 'us_ex'
    assert coverage[0]['events'] == 1
    assert coverage[0]['player_markets'] == ['player_shots_on_goal', 'player_total_saves']
