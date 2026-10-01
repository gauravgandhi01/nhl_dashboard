# NHL Matchup Dashboard

Local daily slate and matchup research: comparison cards with season scoring,
last-five form, and goalie statistics; season/last-10 team statistics, MoneyPuck
5-on-5 metrics, goalie comparisons, current rosters, projected lines, and injuries.

## Start

From this folder:

```sh
python3 run.py
```

Python 3.11+ and npm are required. The launcher installs Python dependencies into
`.venv`, uses Node.js 22+ (or installs a project-local runtime when needed), builds
the React UI, and starts FastAPI on `http://127.0.0.1:8000`. If occupied, it selects
the next free port and prints the URL. Stop with Ctrl+C. Use `--port 8100` to change
the preferred port. First startup and the first matchup can take longer while
dependencies and the published MoneyPuck game dataset are downloaded.

## Data

The **Players** tab (`/players?date=YYYY-MM-DD`) lists current-roster skaters on
teams scheduled that night, excluding postponed/canceled games. It is not a
confirmed lineup, particularly during preseason; goalies are intentionally omitted.
Search, team/position filters, sortable columns, and Last 5 / Last 10 / Season
controls are available. Expanding a player compares all three windows together.
Scoring totals, points/shots per game, average TOI, power-play points and point-game
frequency come from official NHL regular-season appearance logs, across teams.
Season is the default window. Season colors rank scoring, usage and advanced
metrics against same-position-group nightly peers (forwards/defense, 5+ GP).
Top/bottom quartiles are green/red; top/bottom deciles have stronger shading.
Benchmarks do not change when filtering and split-squad duplicates count once.
Recent colors compare with the player's season pace (counting stats normalized
per appearance): 10% changes are colored, 25% changes have stronger shading.
Recent performance colors require 3+ appearances and a 5+ game season baseline;
MoneyPuck metrics use their own coverage counts. Amber marks small samples or
incomplete advanced coverage. Missing values and ties remain neutral. Cell
tooltips identify the comparison; high ice time means more usage, not better play.

Player iCF/60, SOG/60, P/60, ixG/60 and high-danger shots/60 use MoneyPuck's published
skater game ZIP, **all strengths**, with totals divided by total covered ice time.
MP GP shows the actual matched-game coverage; hover for covered minutes. Missing
data is never zero-filled, and stale/partial providers are marked beside players.
Windows end before the selected night (or today for future nights), never cross
statistical seasons, and show smaller samples explicitly. A previous-season
baseline is used only when NHL confirms no regular-season games before the cutoff.
Current rosters are not historical roster snapshots. The first Players load can
take longer while the season ZIP and individual game logs populate SQLite.

- NHL Web/Stats: schedules, scores, regular-season statistics, and current rosters.
- [MoneyPuck](https://moneypuck.com/data.htm): published team game CSV and goalie
  game ZIP. Advanced team metrics are 5-on-5; goalie GSAx uses all strengths.
  MoneyPuck data is for personal/noncommercial use with attribution.
- Daily Faceoff: public starting-goalie and lineup page parsers. Robots rules are
  checked; blocks or schema changes produce unavailable states and source links.
  No browser challenge bypass, hidden API, or guessed goalie confirmations.
- ESPN: team injury lists, joined to NHL players only when names uniquely match
  within the current team's roster. Provider IDs are never assumed equivalent.

Comparison statistics use completed regular-season games in the displayed season.
Before regular-season data exists, the prior season is explicitly shown. Last 10
never crosses seasons. Goalies use their last 10 appearances across teams.
Daily cards use reported starters when available. Otherwise they show the most-used
goalie on the current roster in the displayed season, labeled "Roster leader";
this is a comparison profile, not a predicted starter. Card colors compare like
metrics: higher scoring/save rates and GSAx are green, lower GA/GAA are green;
ties and missing values stay neutral. L5 excludes preseason and unfinished games
and runs oldest to newest, with up to five results from the displayed season.

Matchup flags are team-specific and show their reason on hover/focus:
- **B2B:** a game on the preceding calendar night, using the selected matchup's
  season schedule, including scheduled games. Postponed/canceled games are excluded.
- **Goalie <5 NHL GP:** only a confirmed, uniquely matched starting goalie with
  fewer than five career NHL appearances (regular season plus playoffs, excluding
  preseason). The roster-leader fallback never triggers this flag. Missing or stale
  confirmation/career data is not treated as zero appearances.
- **Winning team / L3+:** current-season regular-season wins exceed all losses
  (regulation plus OT/SO), and the team has lost at least three consecutive completed
  games. Overtime/shootout losses count; the streak is not limited to L5. Prior-season
  baselines never trigger this signal. Results are taken before the matchup date.

Unavailable or stale schedules suppress schedule/record flags; no flag is not a
claim that every signal could be evaluated.

Current-roster skater tables always show full-season totals across teams, even
when the comparison window is Last 10. Rates use summed denominators, not averages
of percentages. NHL statistical goals exclude the shootout-deciding goal.

Upcoming games use the latest available data, not historical pregame snapshots.
Projected lines are latest publications, not promises for the selected game.
No matching confirmation means starter unknown; inspecting a roster goalie does
not change the reported starter. Future rest includes scheduled intervening games.

SQLite (`data/dashboard.sqlite3`) holds original provider responses and normalized
team/goalie game rows. Schedule/game details and goalie news cache for 10
minutes, rosters/injuries for one hour, statistics for six hours. Provider failures
back off for 10 minutes and retain dated last-good data. The source disclosure
shows freshness and individual failures.

## First Period

The **First Period** tab (`/first-period?date=YYYY-MM-DD`) provides comparison
cards, dedicated matchup URLs, goalie inspection, head-to-head scores and sortable
league team rankings. Only Season (default), Last 5 and Last 10 are supported.
The statistical baseline is completed regular-season games before the selected
date, capped before today for future slates. An explicitly labeled previous-season
baseline is used before the regular season starts. The separate league-trends
report, projection model, custom matchups and live tracking are not migrated.

NHL `team/goalsbyperiod` supplies team counts; inconsistent/missing paired rows are
excluded rather than zero-filled. Goalie first-period stats are independently
reconstructed from official play-by-play and starter records, across traded teams.
Unlike the legacy shortcut, team empty-net goals are never charged to a goalie.
Verified zero-shot starters count as appearances, but zero-shot SV% is unavailable.
Multiple verified first-period participants are flagged as partial appearances.
A full-game relief appearance without a first-period shot cannot prove whether
that goalie played in period one; these games receive an attribution caveat and
unverified relief appearances are not invented. Known ambiguous goalie events
exclude the affected team's goalie sample. Windows refer to verified appearances;
coverage warnings remain visible while records are missing or rebuilding.

Goalie rank requires 5+ verified 1P appearances and uses season GA/appearance or
weighted SV%. League Allow 1+% is pooled from each goalie's selected appearance
window, not an average of individual percentages. Team rankings default to season
2+ count with competition ties. Cards compare opposing rates; recent form tables
compare against the player's/team's season baseline. Amber identifies elevated
goals allowed, small samples and incomplete coverage. Ranking frequency colors
mark 65%+ green and below 45% red; these are observed rates, not predictions.

SQLite stores versioned normalized first-period records. One background job per
season builds goalie history while team data remains usable. New/missing games
are fetched incrementally; games in the last seven days refresh every six hours,
older finalized games every seven days. Failed records retain last-good results
and back off ten minutes. Progress polls every three seconds only while building,
and pauses in hidden tabs. There is no live-score polling. Initial uncached season
builds can take a few minutes; no legacy folder/cache is required.

### Optional First-Period Prices

Add The Odds API credentials to the workspace-level `../keys.json` file before
launching. The application reads the `api_keys` array from that file and does not
read `firstperiodstats/key.json` or any other legacy credential file.
The tab reads cached prices without making provider requests. **Load odds** is
the only action that requests current `totals_p1` event markets. By default odds
requests use the configured US regions (`us,us2,us_ex`). Edit
`config/odds.json` and set `"bookmakers": ["fanduel", "draftkings", "kalshi"]`
to request only specific supported bookmaker keys instead. It uses a 30-minute cache, serializes refreshes, stops on
exhausted quota and skips started, postponed and canceled games. No subscriptions
or keys are required for stats.
Prices show the actual paired market total (prefer 1.5) and update timestamp;
another total is never presented as a 1.5 line. No historical odds are fetched.
Credentials never enter the response cache or public source metadata.

API additions:
- `GET /api/first-period?date=YYYY-MM-DD&window=season|last5|last10`
- `GET /api/first-period/matchups/{gameId}?window=season|last5|last10`
- `GET /api/first-period/odds?date=YYYY-MM-DD` (cache only)
- `POST /api/first-period/odds/refresh?date=YYYY-MM-DD` (explicit opt-in)

## Streaks and Leaders

The **Streaks** tab (`/streaks?date=YYYY-MM-DD`) contains eight top-10 boards:
points, goals and shots in the last ten appearances; active point and goal
streaks; consecutive goalie wins; starts allowing 0-1 goals in the last ten starts;
and official shutouts in those starts. League-wide is the default; **On slate**
recomputes the top ten among players whose current teams play on the selected
date. Scheduled-team badges are not player/goalie participation confirmations.

Only NHL regular-season appearances count, before the selected date (capped before
today for future dates). Last ten and active streaks cross season boundaries and
trades; postseason and preseason are excluded rather than mixed in. Missed games
do not break appearance-based streaks. Goalie wins are consecutive decisions:
no-decisions are skipped, regulation and overtime/shootout losses end the streak.
The low-GA and shutout boards use starts, excluding short relief appearances.
Exact sample sizes, latest appearance dates, and crossover labels are displayed.

Eligibility uses current NHL rosters and regular-season activity in the selected
statistical season or preceding season. These are not historical roster snapshots.
Older game logs are loaded using each player's available-season manifest until
the last-ten sample and active streak endings can be established, including missed
seasons. If the manifest is absent and the streak remains open, a `+` denotes a
lower bound. Missing history excludes the affected player and marks coverage
partial rather than joining a streak across an unknown gap. Current-roster ID
collisions are unresolved, not fuzzy-matched.

Ranks share ties by value, but lists are capped at ten rows. Ties are ordered by
larger sample, latest appearance date, name, then ID. Boards with no positive
results remain empty. Short career samples are not inflated to ten appearances.

`GET /api/streaks?date=YYYY-MM-DD&scope=league|tonight` serves a project-local SQLite
snapshot. A single background build per cutoff reuses the NHL game-log cache,
persists normalized records, and refreshes every six hours. Failures/partial data
retry after ten minutes and retain last-good snapshots. The page polls only while
building, pauses in hidden tabs, and never polls live scores. Date/scope changes
do not mutate any upstream data. First league-wide loads may take a minute.

## Matchup Moneylines and Player-Prop Coverage

Matchups cards show the best available paired two-way moneyline for each side
across the requested The Odds API US regions (`us,us2,us_ex`), with the source
bookmaker and timestamp shown under each away/home price.
Use **Load moneylines** for the selected date. Navigation reads the 30-minute
SQLite cache only; there is no automatic polling or quota spend. Missing, stale,
and pregame-snapshot prices are labeled. Market favorites use a separate highlight
from statistical advantages.

Add keys to the workspace-level `../keys.json` file before launching
`python3 run.py`:

```json
{
  "api_keys": ["..."]
}
```

Restart the backend after changing the file. The backend chooses from the
configured key pool and can try another key when one is rejected, rate-limited,
or out of credits. No key is included in frontend assets, source, cached URLs,
or application logs. First Period uses the same key file. Manual odds refresh
buttons are enabled by default; set `NHL_MANUAL_ODDS_REFRESH_ENABLED=false` to
disable the POST refresh routes while keeping cached odds reads available.
Set optional `config/odds.json` `"bookmakers"` to a supported-key subset to
request those books directly instead of all configured US regions. Supported keys
include `fanduel`, `draftkings`, `betmgm`, `espnbet`, `fanatics`, `ballybet`,
`bovada`, `betrivers`, `betonlineag`, `hardrockbet`, `williamhill_us`,
`betparx`, `betus`, `fliff`, `lowvig`, `mybookieag`, `betanysports`,
`betopenly`, `kalshi`, `novig`, `polymarket`, and `prophetx`.

- `GET /api/odds/moneyline?date=YYYY-MM-DD` (cache only)
- `POST /api/odds/moneyline/refresh?date=YYYY-MM-DD` (explicit loading)

See [the odds coverage report](docs/odds-markets.md) for the live probe, actual
player-prop coverage, quota costs, and identity caveats.

## Shared Player Props

Player odds appear in expanded Players rows (assists, goals/anytime, points,
shots on goal, and first goalscorer), compact Lines tiles, and the relevant
On-slate skater Streaks rows. League-wide streaks and goalie boards do not load
player props. Goalies remain outside this skater integration.

Prop requests and responses are restricted to `ballybet`, `betonlineag`,
`draftkings`, `fanatics`, `fanduel`, `kalshi`, `novig`, `prophetx`, and
`williamhill_us`. This dedicated allowlist does not change the broader moneyline
or first-period configuration. Prices may be missing at any of these books.

**Load game props** fetches one event; **Load slate props** fetches uncached
eligible games for the selected date. Navigation/expansion only reads the shared
SQLite cache. Ten requested markets across nine books cost at most ten credits
per game with nonempty coverage; each load button's tooltip gives an upper bound.
Prices cache for 30 minutes, concurrent refreshes deduplicate, failures back off
for ten minutes, and last-good quotes remain visibly stale. Started games do
not fetch new prices. Postponed/canceled games suppress cached player quotes.

Canonical identity is `(NHL game ID, NHL player ID)`. Both event rosters must be
current before fetching paid prices. Match complete normalized names only,
with accent/punctuation normalization; never guess from surnames or initials.
`config/player_aliases.json` optionally maps verified alternate full names to NHL
IDs, for example `{"Verified Alternate Name": 1234567}`. An alias is accepted
only when that ID uniquely belongs to the event rosters and does not conflict
with an exact match. Ambiguous and out-of-roster names are excluded and counted.
Daily Faceoff line entries use the same resolver to expose `lineup_player_ids`.

Expanded rows default to the best available price on each side of the displayed
line, with alternative thresholds and individual books selectable. Same-stat,
same-threshold standard/alternate prices can compete; different thresholds never
do. Anytime Yes/No and goals Over/Under 0.5 share one option and compete for the
best price; higher goal thresholds stay separate. Original provider markets
remain in the cache, with source details retained in quote tooltips. Points default to
the lowest offered threshold; SOG defaults to the most widely offered standard
threshold. Lines use only standard SOG prices, lowest-threshold points Over, and
the best Anytime/goals Over 0.5 price. Missing sides stay unavailable.
Book/time and stale status are exposed on quotes; exchanges may have liquidity
or settlement conditions not captured by their listed price. No bets are placed.

- `GET /api/player-props?date=YYYY-MM-DD&game_id=...` reads cached props; game ID optional.
- `POST /api/player-props/refresh?date=YYYY-MM-DD&game_id=...` explicitly fetches props.

There are no player-specific historical hit-rate calculations in this change;
existing L5/L10/season form remains alongside the quotes.

Player prop provider names are matched to the current NHL rosters by normalized
name. When a provider name is ambiguous or does not match the roster, its prices
are excluded and the UI reports names needing aliases. Add explicit mappings in
`config/player_aliases.json` as provider display name to NHL player ID:

```json
{
  "Provider Name": 8480018
}
```

## Render Deployment

Deploy as a Docker web service. The Docker build creates a compact
`data/seed.sqlite3` with normalized MoneyPuck rows for the previous NHL season
and the current season when MoneyPuck has published it.
At runtime the app copies that seed to `NHL_DASHBOARD_DB`, which should stay on
Render's writable ephemeral disk:

```text
NHL_DASHBOARD_DB=/tmp/dashboard.sqlite3
```

Optional build/runtime settings:

- `NHL_SEED_SEASONS=20252026,20262027` seeds explicit seasons during Docker
  build. If omitted, the previous and current seasons are attempted.
- `NHL_MONEYPUCK_REFRESH_HOURS=24` controls how long normalized MoneyPuck rows
  are trusted before a runtime refresh attempt. Use `0` to trust seeded rows
  indefinitely on small free instances; the Docker image defaults to `0`.
- `NHL_DFO_TTL=120` controls the Daily Faceoff starting-goalie and projected-line
  caches in seconds. The default is two minutes so confirmed starters and line
  changes appear quickly. `NHL_DFO_GOALIES_TTL` is still accepted for backwards
  compatibility.
- `../keys.json` with an `api_keys` array enables moneylines, player props, and
  first-period odds.
- `NHL_MANUAL_ODDS_REFRESH_ENABLED=false` disables manual odds refresh requests.
  The default is enabled.

Daily Faceoff access can differ between your machine and the hosted server.
If `robots.txt` cannot be retrieved, no lineup-page request is made. The app
retains a dated last-good projection when available; otherwise Lines shows an
explicit NHL roster-only fallback, not inferred line assignments. Server logs
identify the failing stage (`robots` or `page`) and HTTP status when available.
The default `/tmp` database does not survive instance replacement; preserving
last-good feeds across deployments requires a persistent mounted database path.

Player-prop failures are independent of lineup availability. Responses and logs
distinguish roster/event validation, rejected credentials, provider errors, and
insufficient odds quota without exposing the API key. A multi-market request can
exceed the remaining quota even when the account still has some credits.

The daily slate is designed to render from small NHL/Daily Faceoff/odds feeds
plus normalized MoneyPuck rows when available; large MoneyPuck CSV/ZIP files are
not stored as raw SQLite response blobs.

The Players page stores a built dashboard snapshot by date for one hour. Browser
navigation also reuses the current date's last payload in memory, so returning to
the tab should not rebuild every skater game log.

## Development and Checks

```sh
.venv/bin/python -m pytest -q
npm run build
npm run test:browser
.venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
npm run dev
```

The last two commands run in separate terminals; Vite proxies `/api` to port 8000.
Browser tests use a running dashboard at port 8001 by default; set `DASHBOARD_URL`
to its actual URL. Install Chromium once with `npx playwright install chromium`.
Use Node.js 22+ for npm commands. The project-local fallback binaries are under
`.runtime/node_modules/node/bin` and `.runtime/node_modules/npm/bin`.

Read-only API: `/api/slate?date=YYYY-MM-DD`, `/api/players?date=YYYY-MM-DD`,
`/api/matchups/{gameId}?window=season|last10`, and `/api/health`.
FastAPI's schema and interactive reference are available at `/docs`.

Futures models and historical research are intentionally deferred. Existing
sibling projects remain independently runnable and are not runtime dependencies.
Daily cards and detailed pages refresh on navigation or manual refresh only.
There are no live score displays, live filters, or automatic polling.
