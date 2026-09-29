import pytest

from backend.signals import career_nhl_games, matchup_signals


def game(n, win=True, **changes):
    return {'id': n, 'season': 20262027, 'gameDate': f'2026-10-{n:02}', 'gameType': 2,
            'gameState': 'OFF', 'gameScheduleState': 'OK',
            'homeTeam': {'id': 1, 'score': 3 if win else 1},
            'awayTeam': {'id': 2, 'score': 1 if win else 3}, **changes}


TARGET = game(20, gameState='FUT')
UNKNOWN = {'name': None, 'status': 'Unknown'}
CONFIRMED = {'name': 'Test Goalie', 'status': 'Confirmed'}


def ids(flags):
    return [f['id'] for f in flags]


@pytest.mark.parametrize('state', ['OFF', 'FINAL', 'FUT', 'PRE'])
def test_second_night_includes_played_and_scheduled_previous_night(state):
    assert 'back_to_back' in ids(matchup_signals(TARGET, 1, [game(19, gameState=state)], UNKNOWN))


def test_b2b_excludes_postponed_same_day_and_two_days_ago():
    rows = [game(19, gameScheduleState='PPD'), game(18), game(20)]
    assert 'back_to_back' not in ids(matchup_signals(TARGET, 1, rows, UNKNOWN))
    assert matchup_signals({**TARGET, 'gameScheduleState': 'PPD'}, 1, [game(19)], CONFIRMED, 1) == []


@pytest.mark.parametrize('gp,expected', [(0, True), (4, True), (5, False), (30, False), (None, False)])
def test_goalie_threshold_is_strictly_under_five(gp, expected):
    assert ('inexperienced_goalie' in ids(matchup_signals(TARGET, 1, [], CONFIRMED, gp))) is expected


@pytest.mark.parametrize('status', ['Likely', 'Unconfirmed', 'Roster leader', 'Unknown'])
def test_only_confirmed_starter_triggers_goalie_flag(status):
    assert matchup_signals(TARGET, 1, [], {'name': 'Test Goalie', 'status': status}, 2) == []


def test_career_total_includes_playoffs_not_minor_leagues():
    assert career_nhl_games({'careerTotals': {'regularSeason': {'gamesPlayed': 3}, 'playoffs': {'gamesPlayed': 2}}}) == 5
    assert career_nhl_games({'careerTotals': {'regularSeason': {'gamesPlayed': 4}}}) == 4
    assert career_nhl_games({'careerTotals': {}, 'seasonTotals': [{'leagueAbbrev': 'AHL', 'gamesPlayed': 99}]}) == 0
    assert career_nhl_games({'careerTotals': {}}) is None
    assert career_nhl_games({}) is None
    assert career_nhl_games(None) is None
    assert career_nhl_games({'careerTotals': {'regularSeason': {'gamesPlayed': -1}}}) is None


def test_winning_record_with_three_losses_including_overtime():
    rows = [game(n) for n in range(1, 6)] + [game(n, False) for n in range(6, 9)]
    rows[-1]['gameOutcome'] = {'lastPeriodType': 'SO'}
    flags = matchup_signals(TARGET, 1, rows, UNKNOWN)
    assert flags[0]['label'] == 'Winning team / L3'
    assert '5-2-1' in flags[0]['detail']
    assert matchup_signals(TARGET, 2, rows, UNKNOWN) == []


def test_two_losses_ties_and_broken_streak_do_not_trigger():
    rows = [game(n) for n in range(1, 6)] + [game(n, False) for n in range(6, 8)]
    assert matchup_signals(TARGET, 1, rows, UNKNOWN) == []
    tied_record = [game(n) for n in range(1, 4)] + [game(n, False) for n in range(4, 7)]
    assert matchup_signals(TARGET, 1, tied_record, UNKNOWN) == []
    broken = [game(n) for n in range(1, 6)] + [game(n, False) for n in range(6, 9)] + [game(9)]
    assert matchup_signals(TARGET, 1, broken, UNKNOWN) == []


def test_streak_is_not_capped_at_five_and_does_not_cross_seasons():
    rows = [game(n) for n in range(1, 8)] + [game(n, False) for n in range(8, 14)]
    assert matchup_signals(TARGET, 1, rows, UNKNOWN)[0]['label'] == 'Winning team / L6'
    assert matchup_signals(TARGET, 1, [{**r, 'season': 20252026} for r in rows], UNKNOWN) == []
    assert matchup_signals(TARGET, 1, [{**r, 'gameType': 1} for r in rows], UNKNOWN) == []


def test_future_selected_game_and_incomplete_scores_not_in_streak():
    rows = [game(n) for n in range(1, 6)] + [game(n, False) for n in range(6, 9)]
    assert 'losing_streak' in ids(matchup_signals(TARGET, 1, rows + [TARGET, game(21)], UNKNOWN))
    rows[-1]['homeTeam']['score'] = None
    assert matchup_signals(TARGET, 1, rows, UNKNOWN) == []
