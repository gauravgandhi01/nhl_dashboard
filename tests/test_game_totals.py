import asyncio
import json
import time

import pytest

from backend.cache import Store
from backend.game_totals import total_price
from backend.moneyline import Moneylines


def book(key, line, over=-110, under=-110):
    return {'key': key, 'title': key, 'last_update': '2026-10-03T10:00:00Z', 'markets': [
        {'key': 'totals', 'outcomes': [{'name': 'Over', 'point': line, 'price': over},
                                     {'name': 'Under', 'point': line, 'price': under}]}]}


def test_balanced_line_and_best_prices_keep_exact_threshold_and_provenance():
    event = {'bookmakers': [book('fanduel', 5.5, -180, 150), book('draftkings', 6.5, -105, -115),
                           book('betmgm', 6.5, -115, -105)]}
    result = total_price(event)
    assert result['total'] == 6.5
    assert result['fair_over'] == pytest.approx(.5)
    assert result['over'] == result['under'] == -105
    assert result['over_bookmaker'] == 'draftkings'
    assert result['under_bookmaker'] == 'betmgm'
    assert result['over_updated_at'] == '2026-10-03T10:00:00Z'
    assert result['paired_books'] == 2


def test_consensus_is_median_of_same_book_pairs_not_cross_book_best_prices():
    event = {'bookmakers': [book('fanduel', 5.5, -110, -110),
                           book('draftkings', 5.5, -200, 160), book('betmgm', 5.5, -180, 150),
                           book('betrivers', 6.5, -115, -105)]}
    assert total_price(event)['total'] == 6.5


@pytest.mark.parametrize('case', ['one_sided', 'different_lines', 'duplicate', 'bad_price', 'nan_line', 'period', 'duplicate_market'])
def test_invalid_and_unpaired_totals_are_not_shown(case):
    item = book('fanduel', 6.5)
    market = item['markets'][0]
    if case == 'one_sided':
        market['outcomes'].pop()
    elif case == 'different_lines':
        market['outcomes'][1]['point'] = 5.5
    elif case == 'duplicate':
        market['outcomes'].append(dict(market['outcomes'][0]))
    elif case == 'bad_price':
        market['outcomes'][0]['price'] = 99
    elif case == 'nan_line':
        market['outcomes'][0]['point'] = float('nan')
    elif case == 'period':
        market['key'] = 'totals_p1'
    else:
        item['markets'].append(dict(market))
    assert total_price({'bookmakers': [item]}) is None


def test_configured_books_fees_and_deterministic_ties():
    event = {'bookmakers': [book('prophetx', 6, 102, -102), book('fanduel', 6, 101, -110),
                           book('unrequested', 6, 200, 200)]}
    result = total_price(event, ['prophetx', 'fanduel'])
    assert result['total'] == 6
    assert result['over_bookmaker'] == 'fanduel'
    assert result['under_bookmaker'] == 'prophetx'
    assert result['under_effective'] < result['under']
    event = {'bookmakers': [book('draftkings', 6.5), book('fanduel', 6)]}
    assert total_price(event)['total'] == 6
    event['bookmakers'].append(book('betmgm', 6.5))
    assert total_price(event)['total'] == 6.5


def test_old_moneyline_cache_reads_without_fetching_or_inventing_totals(tmp_path):
    async def scenario():
        store = Store(tmp_path / 'cache.sqlite3')
        class Provider:
            pass
        p = Provider()
        p.store = store
        service = Moneylines(p)
        store.db.execute('INSERT INTO moneyline_odds VALUES(?,?,?,?,NULL)',
                         ('2026-10-03', json.dumps({'prices': {'test': []}}), time.time(), time.time()))
        store.db.commit()
        result = service.cached('2026-10-03')
        assert result['prices'] == {'test': []}
        assert result['totals'] == {} and not result['totals_loaded']
        await store.close()
    asyncio.run(scenario())
