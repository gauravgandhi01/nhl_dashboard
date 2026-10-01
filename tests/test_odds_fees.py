from backend.odds_fees import effective_american, net_decimal


def test_prophetx_profit_fee_reduces_net_odds():
    assert round(effective_american('prophetx', 200)) == 196
    assert round(effective_american('prophetx', -200)) == -204


def test_kalshi_taker_fee_uses_contract_price_formula():
    # Approximate current COL/LAK examples from 1.48x and 2.73x decimal quotes.
    assert round(net_decimal('kalshi', -208), 3) == 1.448
    assert round(net_decimal('kalshi', 173), 3) == 2.614
