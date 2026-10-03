import pytest

from backend.signals import matchup_signals


def game(n, win=True, **changes):
    return {'id': n, 'season': 20262027, 'gameDate': f'2026-10-{n:02}', 'gameType': 2,
            'gameState': 'OFF', 'gameScheduleState': 'OK',
            'homeTeam': {'id': 1, 'abbrev': 'HME', 'score': 3 if win else 1},
            'awayTeam': {'id': 2, 'abbrev': 'AWY', 'score': 1 if win else 3}, **changes}


TARGET = game(20, gameState='FUT')
UNKNOWN = {'name': None, 'status': 'Unknown'}
CONFIRMED = {'name': 'Test Goalie', 'status': 'Confirmed'}


def ids(flags):
    return [f['id'] for f in flags]


@pytest.mark.parametrize('state', ['OFF', 'FINAL', 'FUT', 'PRE'])
def test_second_night_includes_played_and_scheduled_previous_night(state):
    assert 'back_to_back' in ids(matchup_signals(TARGET, 1, [game(19, gameState=state)]))


def test_second_night_detail_is_opponent_and_score():
    flags = matchup_signals(TARGET, 1, [game(19)])
    assert flags[0]['detail'] == 'vs AWY: 3-1'
    flags = matchup_signals(TARGET, 2, [game(19)])
    assert flags[0]['detail'] == '@ HME: 1-3'


def test_b2b_excludes_postponed_same_day_and_two_days_ago():
    rows = [game(19, gameScheduleState='PPD'), game(18), game(20)]
    assert 'back_to_back' not in ids(matchup_signals(TARGET, 1, rows))
    assert matchup_signals({**TARGET, 'gameScheduleState': 'PPD'}, 1, [game(19)]) == []


def test_winning_record_with_three_losses_including_overtime():
    rows = [game(n) for n in range(1, 6)] + [game(n, False) for n in range(6, 9)]
    rows[-1]['gameOutcome'] = {'lastPeriodType': 'SO'}
    flags = matchup_signals(TARGET, 1, rows)
    assert flags[0]['label'] == 'Winning team / L3'
    assert '5-2-1' in flags[0]['detail']
    assert matchup_signals(TARGET, 2, rows) == []


def test_two_losses_ties_and_broken_streak_do_not_trigger():
    rows = [game(n) for n in range(1, 6)] + [game(n, False) for n in range(6, 8)]
    assert matchup_signals(TARGET, 1, rows) == []
    tied_record = [game(n) for n in range(1, 4)] + [game(n, False) for n in range(4, 7)]
    assert matchup_signals(TARGET, 1, tied_record) == []
    broken = [game(n) for n in range(1, 6)] + [game(n, False) for n in range(6, 9)] + [game(9)]
    assert matchup_signals(TARGET, 1, broken) == []


def test_streak_is_not_capped_at_five_and_does_not_cross_seasons():
    rows = [game(n) for n in range(1, 8)] + [game(n, False) for n in range(8, 14)]
    assert matchup_signals(TARGET, 1, rows)[0]['label'] == 'Winning team / L6'
    assert matchup_signals(TARGET, 1, [{**r, 'season': 20252026} for r in rows]) == []
    assert matchup_signals(TARGET, 1, [{**r, 'gameType': 1} for r in rows]) == []


def test_future_selected_game_and_incomplete_scores_not_in_streak():
    rows = [game(n) for n in range(1, 6)] + [game(n, False) for n in range(6, 9)]
    assert 'losing_streak' in ids(matchup_signals(TARGET, 1, rows + [TARGET, game(21)]))
    rows[-1]['homeTeam']['score'] = None
    assert matchup_signals(TARGET, 1, rows) == []
