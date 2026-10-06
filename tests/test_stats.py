import pytest

from backend.providers import parse_goalies, parse_lineups, parse_mp_teams, starter_for
from backend.stats import advanced_summary, season_for_date, goalie_summary, match_player, recent, rest_context, team_summary
from backend.stats import card_goalie, card_team_stats, goalie_league_ranks, last_five


def test_weighted_special_teams_and_missing_data():
    rows = [{'wins': 1, 'losses': 0, 'otLosses': 0, 'goalsFor': 3, 'goalsAgainst': 1, 'shotsForPerGame': 30,
             'shotsAgainstPerGame': 20, 'powerPlayGoalsFor': 1, 'ppOpportunities': 1, 'ppGoalsAgainst': 1, 'timesShorthanded': 2},
            {'wins': 0, 'losses': 1, 'otLosses': 0, 'goalsFor': 2, 'goalsAgainst': 4, 'shotsForPerGame': 40,
             'shotsAgainstPerGame': 30, 'powerPlayGoalsFor': 0, 'ppOpportunities': 9, 'ppGoalsAgainst': 0, 'timesShorthanded': 3}]
    s = team_summary(rows)
    assert s['pp'] == 10
    assert s['pk'] == 80
    assert s['gf'] == 2.5
    assert s['sf'] == 35
    rows[0]['ppOpportunities'] = None
    assert team_summary(rows)['pp'] is None


def test_empty_and_zero_opportunities_are_not_zero_rates():
    assert team_summary([])['gf'] is None
    assert team_summary([{'powerPlayGoalsFor': 0, 'ppOpportunities': 0}])['pp'] is None
    assert advanced_summary([])['xgf_pct'] is None
    assert goalie_summary([], [])['gsax'] is None


def test_advanced_weighted_by_ice_time_and_attempts():
    rows = [{'xGoalsFor': 2, 'xGoalsAgainst': 1, 'iceTime': 1800, 'shotAttemptsFor': 20, 'shotAttemptsAgainst': 10},
            {'xGoalsFor': 1, 'xGoalsAgainst': 3, 'iceTime': 3600, 'shotAttemptsFor': 10, 'shotAttemptsAgainst': 40}]
    s = advanced_summary(rows)
    assert s['xgf60'] == 2
    assert s['xgf_pct'] == pytest.approx(300 / 7)
    assert s['cf_pct'] == 37.5


def test_goalies_weight_saves_and_time_not_averages():
    s = goalie_summary([{'saves': 9, 'shotsAgainst': 10, 'goalsAgainst': 1, 'timeOnIce': 1200},
                         {'saves': 38, 'shotsAgainst': 40, 'goalsAgainst': 2, 'timeOnIce': 3600}],
                        [{'xGoals': 3.5, 'goals': 2}])
    assert s['sv'] == .94
    assert s['gaa'] == 2.25
    assert s['gsax'] == 1.5
    assert s['advanced_games'] == 1


def test_last_ten_and_incomplete_samples():
    rows = [{'gameDate': f'2026-01-{i:02}', 'gameId': i} for i in range(1, 15)]
    assert len(recent(rows, 'last10')) == 10
    assert recent(rows, 'last10')[0]['gameId'] == 14
    assert len(recent(rows[:3], 'last10')) == 3
    assert len(recent(rows, 'season')) == 14


def test_season_rollover_and_preseason():
    assert season_for_date("2026-10-02") == 20262027
    assert season_for_date("2027-01-01") == 20262027
    assert season_for_date("2026-07-01") == 20262027


def test_identity_never_guesses_duplicate_names():
    players = [{'id': 1, 'name': 'Alex Smith'}, {'id': 2, 'name': 'Alex Smith'}]
    assert match_player('Alex Smith', players) is None
    assert match_player('A. Smith', players) is None
    assert match_player('Alex Smith', players[:1]) == 1


def test_rest_uses_scheduled_intervening_games_and_ignores_postponed():
    games = [{'gameDate': '2026-10-01', 'gameScheduleState': 'OK'}, {'gameDate': '2026-10-02', 'gameScheduleState': 'PPD'}]
    assert rest_context(games, '2026-10-03') == {'days': 1, 'back_to_back': False}
    assert rest_context(games, '2026-10-02')['back_to_back']
    assert rest_context([], '2026-10-03')['days'] is None


def test_goalie_confirmation_requires_exact_matchup_time():
    game = {'awayTeam': {'abbrev': 'TOR'}, 'homeTeam': {'abbrev': 'OTT'}, 'startTimeUTC': '2026-10-01T23:00:00Z'}
    row = {'awayTeamName': 'Toronto Maple Leafs', 'homeTeamName': 'Ottawa Senators', 'dateGmt': '2026-10-01T23:00:00Z',
           'awayGoalieName': 'Anthony Stolarz', 'awayNewsStrengthName': 'Confirmed'}
    assert starter_for(game, [row])['away']['status'] == 'Confirmed'
    row['dateGmt'] = '2026-10-02T23:00:00Z'
    assert starter_for(game, [row])['away']['name'] is None
    row['dateGmt'] = None
    assert starter_for(game, [row])['away']['status'] == 'Unknown'


def test_confirmed_daily_faceoff_starters_map_to_slate_games():
    games = [
        {'awayTeam': {'abbrev': 'MTL'}, 'homeTeam': {'abbrev': 'TOR'}, 'startTimeUTC': '2026-09-29T23:00:00Z'},
        {'awayTeam': {'abbrev': 'NYR'}, 'homeTeam': {'abbrev': 'BOS'}, 'startTimeUTC': '2026-09-30T00:00:00Z'},
    ]
    rows = [
        {'awayTeamName': 'Montreal Canadiens', 'homeTeamName': 'Toronto Maple Leafs',
         'dateGmt': '2026-09-29T23:00:00Z', 'awayGoalieName': 'Jakub Dobes',
         'awayNewsStrengthName': 'Confirmed', 'awayNewsCreatedAt': '2026-09-29T16:56:27.996Z',
         'homeGoalieName': 'Sergei Bobrovsky', 'homeNewsStrengthName': 'Likely'},
        {'awayTeamName': 'New York Rangers', 'homeTeamName': 'Boston Bruins',
         'dateGmt': '2026-09-30T00:00:00Z', 'awayGoalieName': 'Igor Shesterkin',
         'awayNewsStrengthName': 'Likely', 'homeGoalieName': 'Jeremy Swayman',
         'homeNewsStrengthName': 'Confirmed', 'homeNewsCreatedAt': '2026-09-29T15:02:24.985Z'},
    ]
    mtl_tor = starter_for(games[0], rows)
    nyr_bos = starter_for(games[1], rows)
    assert mtl_tor['away'] == {'name': 'Jakub Dobes', 'status': 'Confirmed',
                               'updated_at': '2026-09-29T16:56:27.996Z'}
    assert nyr_bos['home'] == {'name': 'Jeremy Swayman', 'status': 'Confirmed',
                               'updated_at': '2026-09-29T15:02:24.985Z'}


def test_goalie_parser_rejects_challenge_and_schema_changes():
    with pytest.raises(ValueError):
        parse_goalies(b'<html>Blocked</html>')


def test_lineup_parser_sections():
    raw = b'<h1>DFO Projected Lineup</h1><h3>Forwards</h3><a href="/players/a">Player A</a><h3>Defensive Pairings</h3><a href="/players/b">Player B</a><h3>1st Powerplay Unit</h3><a href="/players/a">Player A</a>'
    result = parse_lineups(raw)
    assert result['sections']['Forwards'] == ['Player A']
    assert result['sections']['Defensive Pairings'] == ['Player B']
    with pytest.raises(ValueError):
        parse_lineups(b'<html>Challenge</html>')


def test_moneypuck_filters_season_strength_and_playoffs():
    header = 'team,gameId,gameDate,iceTime,xGoalsFor,xGoalsAgainst,shotAttemptsFor,shotAttemptsAgainst,season,situation,playoffGame\n'
    rows = 'TOR,2025020001,20251001,3000,2,1,20,10,2025,5on5,0\nTOR,2025030001,20260501,3000,2,1,20,10,2025,5on5,1\nTOR,2025020001,20251001,3600,2,1,20,10,2025,all,0\n'
    assert len(parse_mp_teams((header + rows).encode(), 2025)) == 1
    assert parse_mp_teams((header + rows).encode(), 2026) == []


def test_card_scoring_rates_preserve_missing_values():
    assert card_team_stats(None)['gf'] is None
    stats = card_team_stats({'gamesPlayed': 82, 'goalsForPerGame': 3.2, 'powerPlayPct': .25})
    assert stats['gf'] == 3.2
    assert stats['pp'] == 25
    assert stats['ga'] is None


def test_goalie_ranks_include_every_goalie_with_playing_time():
    rows = [
        {'playerId': 1, 'gamesPlayed': 10, 'savePct': .900, 'goalsAgainstAverage': 3.0},
        {'playerId': 2, 'gamesPlayed': 10, 'savePct': .910, 'goalsAgainstAverage': 2.5},
        {'playerId': 3, 'gamesPlayed': 1, 'savePct': .930, 'goalsAgainstAverage': 2.0},
        {'playerId': 4, 'gamesPlayed': 0, 'savePct': .990, 'goalsAgainstAverage': 0.5},
        {'playerId': 5, 'gamesPlayed': 4, 'savePct': None, 'goalsAgainstAverage': 2.5},
    ]
    advanced = [
        {'playerId': '1', 'xGoals': 4, 'goals': 3},
        {'playerId': '1', 'xGoals': 1, 'goals': 0},
        {'playerId': '3', 'xGoals': 2, 'goals': 2},
    ]
    ranks = goalie_league_ranks(rows, advanced)
    assert ranks[1]['sv'] == {'rank': 3, 'eligible': 3}
    assert ranks[3]['sv']['rank'] == 1
    assert ranks[4]['sv'] == {'rank': None, 'eligible': 3}
    assert ranks[5]['sv']['rank'] is None
    assert [ranks[pid]['gaa']['rank'] for pid in [3, 2, 5, 1]] == [1, 2, 2, 4]
    assert ranks[2]['gaa']['eligible'] == 4
    assert ranks[1]['gsax'] == {'rank': 1, 'eligible': 2}
    assert ranks[3]['gsax']['rank'] == 2
    assert ranks[2]['gsax'] == {'rank': None, 'eligible': 2}
    shown = card_goalie({'name': 'Goalie 1', 'status': 'Confirmed'},
                        [{'id': 1, 'firstName': {'default': 'Goalie'}, 'lastName': {'default': '1'}}],
                        rows, advanced, ranks)
    assert shown['ranks']['sv']['rank'] == 3
    assert shown['ranks']['gsax']['rank'] == 1
    assert shown['stats']['gsax'] == 2


def test_card_goalie_prefers_reported_starter_then_roster_leader():
    roster = [{'id': i, 'firstName': {'default': 'Goalie'}, 'lastName': {'default': str(i)}} for i in [1,2]]
    rows = [{'playerId': 1, 'gamesPlayed': 50, 'savePct': .92, 'goalsAgainstAverage': 2.1},
            {'playerId': 2, 'gamesPlayed': 15, 'savePct': .90, 'goalsAgainstAverage': 2.8},
            {'playerId': 3, 'gamesPlayed': 60}]
    goalie = card_goalie({'name': None, 'status': 'Unknown'}, roster, rows, [])
    assert goalie['name'] == 'Goalie 1'
    assert goalie['basis'] == 'Roster leader'
    assert goalie['stats']['gsax'] is None
    confirmed = card_goalie({'name': 'Goalie 2', 'status': 'Confirmed'}, roster, rows,
                           [{'playerId': '2', 'xGoals': 3, 'goals': 1}])
    assert confirmed['name'] == 'Goalie 2'
    assert confirmed['basis'] == 'Confirmed'
    assert confirmed['stats']['gsax'] == 2
    unknown = card_goalie({'name': 'Unmatched Player', 'status': 'Likely'}, roster, rows, [])
    assert unknown['name'] == 'Unmatched Player'
    assert unknown['stats'] == {}


def test_l5_uses_completed_regular_games_oldest_to_newest():
    games = [{'id': n, 'gameDate': f'2026-01-{n:02}', 'gameType': 2, 'gameState': 'OFF',
              'homeTeam': {'id': 1, 'abbrev': 'CAR', 'score': 3},
              'awayTeam': {'id': 2, 'abbrev': 'NSH', 'score': 2}} for n in range(1,9)]
    games[-1]['gameState'] = 'LIVE'
    games[-2]['gameType'] = 1
    games[-3]['homeTeam']['score'] = 1
    games[-3]['gameOutcome'] = {'lastPeriodType': 'OT'}
    form = last_five(games, 1)
    assert len(form) == 5
    assert form[0]['date'] == '2026-01-02'
    assert form[0]['home'] is True
    assert form[-1]['result'] == 'OTL'
    assert last_five(games, 2)[0]['home'] is False
    assert len(last_five(games[:2], 1)) == 2
