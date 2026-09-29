# NHL Odds: Observed Coverage and Integration

## Implemented Player Integration

The Players expansion, Lines tiles, and On-slate skater Streaks now share cached
props keyed by NHL game and player IDs. The dedicated book allowlist is
`ballybet,betonlineag,draftkings,fanatics,fanduel,kalshi,novig,prophetx,williamhill_us`.
Only explicit load actions request paid odds. See the README's Shared Player Props
section for selection rules, matching safeguards, aliases, and endpoints.
Anytime Yes and goals Over 0.5 are one displayed market (likewise No/Under 0.5),
including alternate 0.5-goal offers. Best prices compete across both feeds in all
three views. Higher thresholds stay separate; raw market provenance is retained.

One September 29 live verification fetched ten markets for FLA/CAR, matched 36
players uniquely to NHL rosters, and had zero unresolved provider names in that
response. It cost ten credits, leaving 448 at retrieval. This is a new snapshot,
not evidence that the earlier roster anomaly never occurred. Historical research
notes below describe the coverage at their respective probe times.

## Expanded US/US2 Probe: September 29, 2026, 03:07 UTC

This follow-up used the then-current `us,us2` configuration, checked the FLA/CAR and
MTL/TOR market catalogs, and retrieved eight markets of actual prices for FLA/CAR.
The two catalogs exposed 18 player-market keys across 11 books, versus eight keys
in the earlier three-book sample. This is limited event coverage, not a league-wide
inventory. Raw results are in `data/player_props_probe.json`.

The probe spent 18 credits: two catalogs at one credit each, then eight markets
across two regions at 16 credits. Account quota went from 490 to 472. It did not
refresh moneylines, alter dashboard caches, or enable automatic prop requests.

### Newly Verified Prices

| Market | Books returning prices in FLA/CAR | Paired Over/Under available? |
| --- | --- | --- |
| Shots on goal | Hard Rock Bet, theScore Bet, BetOnline.ag, Bally Bet | Yes at all four |
| Points | Hard Rock Bet, theScore Bet, BetOnline.ag | Yes at all three |
| Assists | Hard Rock Bet, theScore Bet | Yes at both |
| Goals | Hard Rock Bet, theScore Bet, Bally Bet, BetRivers | Yes at theScore Bet; others returned Over-only |
| Power-play points | Hard Rock Bet, theScore Bet | Yes at theScore Bet; Hard Rock returned Over-only |
| Goalie saves | Hard Rock Bet, theScore Bet, BetOnline.ag | Yes at all three |
| First goalscorer | DraftKings, FanDuel, Hard Rock Bet, theScore Bet, Bally Bet, BetRivers, Bovada | Yes-only outcomes, not paired |
| Last goalscorer | DraftKings | Yes-only outcomes, not paired |

Pair counts were checked per player and identical line, not merely by finding
both outcome labels somewhere in the market. For example, theScore Bet returned
17 paired points lines, 17 assists, 16 shots, 36 goals, 18 PP points, and two goalie
save lines. BetOnline returned 26 paired points lines; Bally Bet returned 22
paired shots lines. Counts are per-book lines and may overlap across books.

Snapshot examples (not current guarantees or betting recommendations):

- Hard Rock Bet: Jordan Staal shots 1.5, Over -125 / Under -105.
- theScore Bet: Sebastian Aho points 0.5, Over -170 / Under +135.
- theScore Bet: Sebastian Aho assists 0.5, Over +100 / Under -135.
- theScore Bet: Nikolaj Ehlers PP points 0.5, Over +185 / Under -280.

### Discovered but Not Priced in This Follow-Up

- Hard Rock Bet lists `player_goals_against`, `player_shutouts`, and
  `player_shots_alternate`. The latter key should retain its provider meaning
  until its payload is inspected; do not silently alias it to shots on goal.
- BetOnline lists `player_total_saves_alternate` plus alternate skater lines.
- Caesars lists standard shots on goal and alternate points. No Caesars prices
  appeared in the requested FLA/CAR price response, despite those catalog entries.
- Fanatics lists alternate assists, goals, points, shots, and scorer markets.
- First-period anytime goalscorer remains listed by DraftKings and FanDuel.
- `player_blocked_shots` was absent from both sampled catalogs. This does not
  establish that it is unavailable for every game or later in the day.

Provider display names matter: `espnbet` returned the title **theScore Bet** and
`williamhill_us` returned **Caesars**. Keep stable provider keys for identity while
displaying the response's current title.

### Integration Implications

We can now support both Over and Under in the Players view, not just milestones.
Prioritize shots, points, assists, goals, and PP points. Show the selected line,
both available prices, book/time, L5/L10/season form, and eligible games over/under
that exact line. Preserve integer-line pushes and actual samples. Add PP usage
context for PP-point lines; keep goalie markets for a later goalie view.

For best-price comparisons, group by NHL player ID, event, market, exact line,
and outcome side before comparing books. Show each side's book; never combine
different thresholds or compute a same-book margin from cross-book best prices.
The earlier roster/identity anomaly remains in this sample, so strict roster
matching is still required before displaying player odds. Price presence alone
does not confirm a player will dress or a goalie will start.

The diagnostic `.venv/bin/python -m backend.probe_player_props` repeats this
bounded check using an environment key. Its conservative maximum is 20 credits
for `us,us2,us_ex`; it does not run on navigation. Edit `config/odds.json`
`"bookmakers"` to probe only selected supported bookmaker keys. `us_ex`
documented options are `betopenly`, `kalshi`, `novig`, `polymarket`, and
`prophetx`; response presence still needs a live sport/event probe because
coverage can vary. Set `config/odds.json` `"player_prop_market_limit"` to cap
the sample odds request. The report now includes
`bookmaker_coverage`, `bookmaker_regions`, `us_exchange_bookmakers`,
`available_bookmaker_options`, `odds_scope`, request params, selected markets,
and the sampled event. This diagnostic is separate from the now-implemented
shared player-prop cache and UI described above.

## US Exchange Probe: September 29, 2026, 03:30 UTC

The Odds API bookmaker reference lists the `us_ex` exchange region with
`betopenly`, `kalshi`, `novig`, `polymarket`, and `prophetx`. A narrow live NHL
probe using `regions=us_ex` confirmed all five returned current `h2h` game
markets. The `h2h` request returned 33 NHL events and cost one credit, leaving
471 remaining after that request.

Two event-market catalogs were then checked for FLA/CAR and MTL/TOR, followed by
one four-market player-prop sample for MTL/TOR. That exchange prop probe spent
six credits total and left 465 remaining. Raw results are saved locally in
`data/us_ex_props_probe.json`.

Observed exchange coverage in the two sampled event catalogs:

| Exchange | NHL game markets | NHL player markets |
| --- | --- | --- |
| BetOpenly | h2h, h2h_ot, spreads, totals, alternate totals | None observed |
| Kalshi | h2h, h2h_ot, spreads, totals, overtime, alternate spreads/totals/team totals | None observed |
| Novig | h2h, h2h_ot, spreads, totals, alternates | assists, goals, points, shots on goal, goalie saves |
| Polymarket | h2h, h2h_ot, spreads, totals, alternates | None observed |
| ProphetX | h2h, h2h_ot, spreads, totals | anytime goalscorer |

The sampled MTL/TOR prop odds response returned Novig prices for
`player_assists`, `player_goals`, `player_points`, and `player_shots_on_goal`.
The shots market had only one listed outcome in that response, so integration
must preserve one-sided availability instead of assuming an Over/Under pair.

## Live Probe: September 28, 2026

The server-side probe began at 22:40 UTC. It used 8 account credits in total,
leaving 492. Findings are a dated sample, not a guarantee of future coverage.
Raw response bodies and request-quota headers are saved locally in
`data/odds_probe.json` (ignored by git, no credentials or credential-bearing URLs).

- 33 upcoming NHL events; all 33 moneyline events matched official NHL schedules
  using explicit team identities, home/away orientation, and start-time tolerance.
- FanDuel, DraftKings, and BetMGM returned paired two-way `h2h` prices.
- Matched dates run from September 29 through October 10. Prices were populated
  into date caches without additional odds requests.
- Three events were sampled for market discovery: FLA at CAR, MTL at TOR,
  and NYR at BOS. Actual player prices were sampled for FLA at CAR only.

Example snapshot, FLA at CAR: FanDuel FLA +106 / CAR -128; DraftKings +105 / -125;
BetMGM +100 / -120. These are observations at retrieval, not current guarantees.

## Player Props Observed

| Market | Evidence | Books in sample |
| --- | --- | --- |
| Anytime goalscorer | Actual prices returned | FanDuel, DraftKings; also listed by BetMGM for MTL/TOR and NYR/BOS |
| Alternate shots on goal | Actual prices returned | DraftKings; FanDuel also listed it for NYR/BOS |
| Alternate points | Actual prices returned | DraftKings |
| Alternate assists | Actual prices returned | DraftKings |
| Alternate goals | Listed only; prices not requested | FanDuel, DraftKings, and some BetMGM events |
| First goalscorer | Listed only | FanDuel, DraftKings, and some BetMGM events |
| Last goalscorer | Listed only | DraftKings |
| First-period anytime goalscorer | Listed only | FanDuel, DraftKings |

The FLA/CAR price samples contained 36 DraftKings and 33 FanDuel anytime-goalscorer
outcomes, plus 86 shots, 64 points, and 47 assists alternate outcomes at DraftKings.
These are outcome counts, not unique-player counts. Players have multiple lines.
For example, Sebastian Aho points Over 0.5 was -170 and Over 1.5 was +260;
Aleksander Barkov assists Over 0.5 was +105. These are not recommendations.

The [provider's documented NHL catalog](https://the-odds-api.com/sports-odds-data/betting-markets.html)
also supports standard points, assists, goals, shots, blocked shots, power-play
points, goalie saves, and alternate variants. Those additional markets were not
verified with actual prices here. Missing markets may open nearer puck drop.

## Payload and Identity Constraints

Outcomes contain `description` (player name), `name` (Over/Under or Yes/No),
`price` (American odds), and `point` when applicable. Bookmaker/market timestamps
and event identifiers are included. Sampled outcomes do not contain NHL player
IDs or reliable player-team fields.

The sample included Brady Tkachuk in the FLA/CAR event, which appears inconsistent
with the matchup. Do not assume every listed player belongs to the event. Join
to the two NHL rosters using normalized exact names and explicit aliases; require
a unique NHL ID and leave unmatched or ambiguous names unresolved. Keep reported
lineup participation separate.

The sampled alternate markets were Over-only, and goalscorers were Yes-only.
Do not invent a missing side or calculate paired/no-vig probabilities from them.
Over 0.5 corresponds to 1+, Over 1.5 to 2+, etc.; preserve actual lines in storage.

## Recommended Integration Order

1. **Players table and expanded row:** book/market selectors; line and offered
   price beside the corresponding L5/L10/season totals and per-game rate. Add
   empirical games-over-line / eligible games, with pushes separate for integer
   lines, actual samples, and games strictly before the selected date. Label
   preseason comparisons against regular-season form explicitly.
2. **Shots and points detail:** retain TOI, shots-on-goal/game, goals, assists,
   and PP production as context. MoneyPuck shot attempts/60 and 5-on-5 rates are
   different measures, not substitutes for all-strengths shots-on-goal lines.
   Empirical frequency is not a calibrated probability or edge estimate.
3. **Streaks:** optional matched price beside a player already on the selected
   slate; link to the player's expanded row. Preserve performance-based top-10
   rankings rather than ranking by bookmaker coverage.
4. **Later:** first-period scorers need actual first-period player samples;
   goalie saves need a separate goalie workflow and confirmed-starter context.
   Do not compare first-period lines with whole-game trends.

Start with shots, points, assists, and anytime goalscorer. Use one explicit
"Load props" action for selected events/markets, cache and deduplicate, and show
source/time/availability. Do not fetch all props on navigation. This original
proposal is now partly implemented; historical games-over-line counts remain deferred.

## Moneyline Behavior and Cost

Cards show the best available paired `h2h` price for each side across requested
The Odds API US regions (`us,us2,us_ex`), not regulation three-way or first-period
prices. Away and home prices may come from different sportsbooks.
The [NHL provider notes](https://the-odds-api.com/sports/nhl-odds.html) explain that
US books typically feature overtime-inclusive moneylines. The parser rejects a draw/third outcome and
never labels mixed markets as equivalent. Bookmaker settlement rules still apply.

`GET /api/odds/moneyline?date=YYYY-MM-DD` reads SQLite only.
`POST /api/odds/moneyline/refresh?date=YYYY-MM-DD` explicitly fetches eligible
pregame prices for that Eastern date. No live or historical prices are requested.
The 30-minute cache deduplicates refreshes and preserves last-good data on errors;
failed attempts back off for 10 minutes. First-period and moneyline requests share
a credential-safe transport, request lock, and quota cooldown.

Moneyline requests use all requested regions and one market unless
`config/odds.json` selects specific books, so cost scales by provider region or bookmaker
accounting rather than the former three-bookmaker filter. Player queries are per
event and charged per returned market/region or selected bookmaker. Market
discovery also costs credits. See the [API documentation](https://the-odds-api.com/liveapi/guides/v4/).
Displayed quota figures are from that cache's retrieval, not a live balance.
Browsing and automated tests spend no odds credits.

Explicitly running `.venv/bin/python -m backend.probe_odds` repeats bounded
discovery across `us,us2,us_ex`: one moneyline market, three event catalogs,
and up to four player markets for one event. It requires an environment key and
does not read legacy credentials. This is a diagnostic command, not a refresh job.
