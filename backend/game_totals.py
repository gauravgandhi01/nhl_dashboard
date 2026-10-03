"""Choose a balanced full-game total, then compare prices at that exact line."""
from collections import defaultdict
from statistics import median

from .odds_fees import american_to_decimal, effective_american, net_decimal
from .stats import number


def total_price(event, allowed_books=None):
    allowed = set(allowed_books or [])
    lines = defaultdict(list)
    seen_books = set()
    for book in event.get('bookmakers', []):
        key = book.get('key')
        if not key or key in seen_books or (allowed and key not in allowed):
            continue
        seen_books.add(key)
        markets = [market for market in book.get('markets', []) if market.get('key') == 'totals']
        if len(markets) != 1:
            continue
        market = markets[0]
        pairs, invalid = defaultdict(dict), set()
        for outcome in market.get('outcomes', []):
            point, price = number(outcome.get('point')), number(outcome.get('price'))
            side = str(outcome.get('name', '')).lower()
            if point is None or point <= 0 or not (point * 2).is_integer():
                continue
            if side not in {'over', 'under'} or price is None or abs(price) < 100 or not price.is_integer():
                invalid.add(point)
                continue
            if side in pairs[point]:
                invalid.add(point)
            pairs[point][side] = int(price)
        for point, pair in pairs.items():
            if point in invalid or set(pair) != {'over', 'under'}:
                continue
            over, under = (1 / american_to_decimal(pair[side]) for side in ['over', 'under'])
            lines[point].append({'bookmaker': key, 'name': book.get('title') or key, **pair,
                                 'fair_over': over / (over + under),
                                 'updated_at': market.get('last_update') or book.get('last_update')})
    if not lines:
        return None
    fair = {point: median(row['fair_over'] for row in rows) for point, rows in lines.items()}
    # Stable ties prefer broader book coverage, then the smaller threshold.
    point = min(lines, key=lambda value: (round(abs(fair[value] - .5), 12), -len(lines[value]), value))
    result = {'total': point, 'fair_over': fair[point], 'paired_books': len(lines[point])}
    for side in ['over', 'under']:
        best = min(lines[point], key=lambda row: (-net_decimal(row['bookmaker'], row[side]), row['bookmaker']))
        result.update({side: best[side], side + '_effective': effective_american(best['bookmaker'], best[side]),
                       side + '_bookmaker': best['bookmaker'], side + '_name': best['name'],
                       side + '_updated_at': best['updated_at']})
    return result
