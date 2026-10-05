import { expect, test, type Page, type Route } from "@playwright/test";
import { countWindow, formatCount, gameLogRows } from "../../src/lineCounts";

const date = "2026-10-04";
const source = { source: "NHL", url: "https://example.test", retrieved_at: null, status: "available" };
const shots = [3, 2, 2, 1, 0, 4, 2, 1, 5, 2];

test("line counts drop missing values and separate integer pushes", () => {
  expect(formatCount(countWindow(shots, 1.5, 5)!)).toBe("3/5");
  expect(formatCount(countWindow(shots, 1.5, 10)!)).toBe("7/10");
  expect(formatCount(countWindow(shots, 2, 5)!)).toBe("1/5 · 2 pushes");
  expect(countWindow([2, null, 1], 1.5, 5)).toEqual({ games: 2, over: 1, under: 1, push: 0 });
  expect(countWindow([], 0.5, null)?.games).toBe(0);
});

test("a hover log lists the stat beside the opponent", () => {
  const logged = gameLogRows({
    goals: [1], assists: [0], points: [2, 1, null], shots: [3],
    opponents: ["BOS", "MTL", null],
    home: [false, true, false],
  }, "points", 0.5);
  expect(logged && !logged.empty && logged).toMatchObject({
    label: "PTS",
    earlier: 0,
    rows: [
      { where: "@", opponent: "BOS", value: 2 },
      { where: "vs", opponent: "MTL", value: 1 },
      { where: "", opponent: null, value: null },
    ],
  });
  const long = gameLogRows({
    goals: [], assists: [], points: Array.from({ length: 12 }, (_, i) => i), shots: [],
  }, "points", 0.5);
  expect(long && !long.empty && long.rows).toHaveLength(10);
  expect(long && !long.empty && long.earlier).toBe(2);
  expect(gameLogRows({ goals: [], assists: [], points: [], shots: [] }, "shots", 1.5)?.empty).toBe(true);
  expect(gameLogRows(null, "points", 0.5)).toBeNull();
});

function quote(point: number | null, side = point == null ? "yes" : "over") {
  return {
    side, price: 120, bookmaker: "fanduel", book: "FanDuel",
    market: "player_shots_on_goal", updated_at: "2026-10-04T12:00:00Z",
  };
}
function propLine(point: number | null, market = "player_shots_on_goal") {
  return {
    id: `${market}:${point}`, market, point, alternate: false,
    quotes: [quote(point), ...(point == null ? [] : [{ ...quote(point, "under"), price: -140 }])],
  };
}

function skater(id: number, name: string, points = 10) {
  const stats = {
    games: 10, goals: 1, assists: 1, points, points_pg: points / 10, shots_pg: 2,
    toi_pg: 900, powerPlayPoints: 0, point_games_pct: 40, attempts_pg: 2,
    shots60: 8, points60: 2, ixg60: 0.4, hd60: 0.2,
  };
  return {
    id, name, position: "C", team: "TOR", logo: "", game_id: 1, opponent: "BOS",
    home: false, season_label: "2026-27",
    windows: { last5: stats, last10: stats, season: stats },
    log: id === 7 ? { goals: [1, 0, 1, 0, 0], assists: [0, 1, 0, 0, 1], points: [1, 1, 1, 0, 1], shots } : { goals: [], assists: [], points: [], shots: [] },
    stats_source: source, advanced_source: source, roster_source: source,
  };
}

const players = {
  date, as_of: date, players: [skater(7, "Alex Skater", 0), ...Array.from({ length: 24 }, (_, i) => skater(100 + i, `Other Skater ${i}`, 20 - i))],
  games: [{ id: 1 }], periods: [], sources: [], error: null,
};
const props = {
  date, configured: true, manual_refresh_enabled: false, error: null, max_credits_per_game: 10,
  games: {
    "1": {
      game_id: 1, eligible: true, status: "fresh", retrieved_at: "2026-10-04T12:00:00Z",
      error: null, unmatched_names: [],
      players: {
        "7": {
          id: 7, name: "Alex Skater", team: "TOR",
          markets: {
            shots: [propLine(1.5), propLine(2)],
            points: [propLine(0.5, "player_points")],
            assists: [], anytime: [], goals: [],
            first_goal: [propLine(null, "player_goal_scorer_first")],
          },
        },
      },
    },
  },
};

async function stubPlayers(page: Page) {
  await page.route("**/api/players?*", (route) => route.fulfill({ json: players }));
  await page.route("**/api/player-props**", (route) => route.fulfill({ json: props }));
}

test("a player link expands that skater and shows appearance counts", async ({ page }) => {
  await stubPlayers(page);
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 700 });
    await page.goto(`/players?date=${date}&player=7`);
    const row = page.locator("tr", { has: page.getByRole("button", { name: "Alex Skater" }) });
    await expect(row).toBeVisible();
    const box = await row.boundingBox();
    expect(box && box.y >= 0 && box.y < 700).toBeTruthy();
    const shotsGroup = page.getByRole("group", { name: "Shots on goal" });
    await expect(shotsGroup).toContainText("3/5");
    await shotsGroup.getByRole("button", { name: "2", exact: true }).click();
    await expect(shotsGroup).toContainText("1/5 · 2 pushes");
    await expect(page.getByRole("group", { name: "First goalscorer" })).not.toContainText("L5");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  }
  await page.goto(`/players?date=${date}&player=404`);
  await expect(page.getByText("This player is not on tonight's skater list.")).toBeVisible();
});

function team(abbrev: string) {
  return { id: 1, abbrev, name: abbrev, logo: "", record: "1-0-0", score: null, starter: { name: null, status: "Unknown", updated_at: null } };
}
function slateGame(id: number, away: string, home: string, schedule = "OK") {
  return {
    id, date, season: 20262027, start: "2026-10-04T23:00:00Z", state: "FUT",
    schedule_state: schedule, game_type: 2, venue: "Arena", period: null, clock: null,
    away: team(away), home: team(home),
  };
}
function cardSide(basis: string, signals: { id: string; label: string; detail: string }[] = []) {
  return { signals, summary: {}, advanced: {}, form: [], goalie: { name: "Goalie", basis, stats: {}, advanced_games: 0 } };
}

test("slate filters and the next-game button", async ({ page }) => {
  const games = [slateGame(1, "TOR", "BOS"), slateGame(2, "NYR", "MTL"), slateGame(3, "BUF", "PIT", "PPD")];
  const slate = {
    date, games, error: null, sources: [], next_date: null,
    comparisons: {
      1: { season_label: "2026-27", previous_season: false, away: cardSide("Likely", [{ id: "back_to_back", label: "B2B", detail: "Played last night" }]), home: cardSide("Unconfirmed") },
      2: { season_label: "2026-27", previous_season: false, away: cardSide("Confirmed"), home: cardSide("Likely") },
      3: { season_label: "2026-27", previous_season: false, away: cardSide("Unknown"), home: cardSide("Unknown") },
    },
  };
  await page.route("**/api/slate?*", (route) => route.fulfill({ json: slate }));
  await page.route("**/api/odds/**", (route) => route.fulfill({ json: { date, configured: false, prices: {}, totals: {}, error: null } }));
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`/?date=${date}`);
    await expect(page.locator(".game-card")).toHaveCount(2);
    await expect(page.getByRole("button", { name: /Postponed/ })).toHaveCount(0);
    await expect(page.getByLabel("Slate team")).toHaveCount(0);
    const toggles = page.locator(".toolbar-right .slate-filter-toggles");
    const refresh = page.locator(".toolbar-right .refresh-actions");
    const toggleBox = await toggles.boundingBox();
    const refreshBox = await refresh.boundingBox();
    const toolbarBox = await page.locator(".toolbar").boundingBox();
    const cardBox = await page.locator(".game-card").first().boundingBox();
    expect(toggleBox && refreshBox && toolbarBox && cardBox).toBeTruthy();
    expect(Math.abs(toggleBox!.y - refreshBox!.y)).toBeLessThan(4);
    expect(refreshBox!.x - (toggleBox!.x + toggleBox!.width)).toBeLessThan(16);
    expect(cardBox!.y).toBeLessThan(toolbarBox!.y + toolbarBox!.height + 24);
    await page.getByRole("button", { name: "Back-to-back" }).click();
    await expect(page.locator(".game-card")).toHaveCount(1);
    await page.getByRole("button", { name: "Confirmed starter" }).click();
    await expect(page.getByRole("heading", { name: "No matching games" })).toBeVisible();
    await page.getByRole("button", { name: "Clear filters" }).click();
    await expect(page.locator(".game-card")).toHaveCount(2);
    await page.getByRole("button", { name: "Confirmed starter" }).click();
    await expect(page.locator(".game-card")).toHaveCount(1);
    await expect(page.locator(".game-card")).toContainText("NYR");
    await page.getByRole("button", { name: "Confirmed starter" }).click();
    await expect(page.locator(".game-card")).toHaveCount(2);
    await expect(page.locator(".game-card", { hasText: "BUF" })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  }
});

test("an empty slate offers the next date with a game", async ({ page }) => {
  await page.route("**/api/slate?*", (route: Route) => {
    const requested = new URL(route.request().url()).searchParams.get("date");
    return route.fulfill({
      json: {
        date: requested, games: requested === "2026-10-07" ? [slateGame(9, "TOR", "BOS")] : [],
        comparisons: {}, sources: [], error: null,
        next_date: requested === date ? "2026-10-07" : null,
      },
    });
  });
  await page.route("**/api/odds/**", (route) => route.fulfill({ json: { date, configured: false, prices: {}, error: null } }));
  await page.goto(`/?date=${date}`);
  await expect(page.getByRole("heading", { name: "No games scheduled" })).toBeVisible();
  await page.getByRole("button", { name: /Next games/ }).click();
  await expect(page).toHaveURL(/date=2026-10-07/);
  await expect(page.locator(".game-card")).toHaveCount(1);
});

function side(abbrev: string, withPlayer: boolean) {
  return {
    team: team(abbrev), summary: {}, advanced: {}, recent: [],
    rest: { days: 2, back_to_back: false },
    starter: { name: null, status: "Unknown", updated_at: null },
    goalies: [], roster: withPlayer ? [{ id: 7, name: "Alex Skater", position: "C", stats: { goals: 3, assists: 2, points: 5 } }] : [],
    roster_source: source,
    lineup: withPlayer ? { sections: { "Forward Line 1": ["Alex Skater", "Hurt Player"] }, updated_at: null } : null,
    lineup_usage: {},
    lineup_logs: withPlayer ? {
      "7": {
        goals: [1, 0, 0, 1, 0], assists: [1, 1, 1, 0, 0], points: [2, 1, 1, 0, 1],
        shots: [3, 2, null, 1, 0],
        opponents: ["BOS", "MTL", "DET", "BUF", "PIT"],
        home: [false, true, false, true, null],
      },
    } : {},
    lineup_player_ids: withPlayer ? { "Alex Skater": 7, "Hurt Player": null } : {},
    lineup_source: source,
    injuries: withPlayer ? [{ name: "Alex Skater", player_id: 7, status: "Day-To-Day", note: "Lower body", updated_at: "2026-10-04T00:00:00Z" }] : [],
    injury_source: source, stats_source: source,
  };
}

test("line, injury, and streak names open the player", async ({ page }) => {
  await stubPlayers(page);
  await page.route("**/api/matchups/**", (route) => route.fulfill({
    json: {
      game: { ...slateGame(1, "TOR", "BOS"), away: team("TOR"), home: team("BOS") },
      season: 20262027, season_label: "2026-27", previous_season: false, window: "season", as_of: date,
      away: side("TOR", true), home: side("BOS", false), sources: [],
    },
  }));
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 800 });
    await page.goto(`/matchups/1?date=${date}&tab=lineups`);
    await page.evaluate(() => document.fonts.ready);
    const player = page.locator(".line-player").first();
    const pts = player.locator(".has-count-tip", { hasText: "PTS" });
    const odds = player.locator(".compact-props");
    const ptsBox = await pts.boundingBox();
    const ptsLabel = await pts.locator(".compact-prop-label").boundingBox();
    const cardBox = await player.boundingBox();
    expect(await odds.evaluate((el) => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1);
    expect(ptsBox && ptsLabel && ptsLabel.x <= ptsBox.x + 2).toBeTruthy();
    if ((cardBox?.width || 0) > 180) expect(ptsBox!.height).toBeLessThan(20);
    const ptsLog = pts.locator(".line-log");
    await page.mouse.move(0, 0);
    await expect(ptsLog).toHaveCSS("opacity", "0");
    await pts.hover();
    await expect(ptsLog).toHaveCSS("opacity", "1");
    const ptsRows = ptsLog.locator(".line-log-row");
    await expect(ptsRows).toHaveCount(5);
    await expect(ptsRows.nth(0)).toContainText("@ BOS");
    await expect(ptsRows.nth(0)).toContainText("2");
    await expect(ptsRows.nth(1)).toContainText("vs MTL");
    await expect(ptsRows.nth(1)).toContainText("1");
    await expect(ptsLog).not.toContainText("L5");
    await expect(ptsLog).not.toContainText("3/5");
    const sog = player.locator(".has-count-tip", { hasText: "SOG" });
    await sog.hover();
    const sogRows = sog.locator(".line-log-row");
    await expect(sog.locator(".line-log")).toHaveCSS("opacity", "1");
    await expect(ptsLog).toHaveCSS("opacity", "0");
    await expect(sogRows.nth(0)).toContainText("@ BOS");
    await expect(sogRows.nth(0)).toContainText("3");
    await expect(sogRows.nth(2)).toContainText("—");
    await expect(sogRows.nth(4)).toContainText("PIT");
    await expect(sogRows.nth(4)).not.toContainText("@");
    await expect(sogRows.nth(4)).not.toContainText("vs");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  }
  await page.setViewportSize({ width: 1440, height: 800 });
  await page.goto(`/matchups/1?date=${date}&tab=lineups`);
  await expect(page.locator(".line-player-heading", { hasText: "H. Player" }).locator("a")).toHaveCount(0);
  await page.getByRole("link", { name: "A. Skater" }).click();
  await expect(page).toHaveURL(new RegExp(`/players\\?date=${date}&player=7`));
  await expect(page.locator(".player-expanded")).toContainText("Alex Skater");
  await page.goBack();
  await page.getByRole("link", { name: "Alex Skater" }).click();
  await expect(page).toHaveURL(new RegExp(`/players\\?date=${date}&player=7`));

  await page.route("**/api/streaks?*", (route) => route.fulfill({
    json: {
      date, scope: "tonight", toi_window: "last10", season_label: "2026-27", as_of: date,
      retrieved_at: null, ready: true, stale: false, error: null,
      build: { status: "ready", done: 1, total: 1 },
      schedule_available: true, schedule_stale: false,
      coverage: { partial: false, eligible_players: 1, skipped_players: 0, ambiguous_players: 0, roster_coverage: 32, roster_total: 32 },
      sources: [],
      boards: [{
        id: "points10", title: "Points", period: "Last 10 appearances", kind: "skater", unit: "count",
        entries: [{
          id: 7, name: "Alex Skater", team: "TOR", position: "C", logo: "", rank: 1, value: 8,
          sample_size: 10, lower_bound: false, latest_game: "2026-10-01", start_date: "2026-09-01",
          end_date: "2026-10-01", seasons: ["2026-27"], stale: false, recent: [],
          matchups: [{ game_id: 1, opponent: "BOS", home: false }],
          log: { goals: [1], assists: [1], points: [2, 1, 1, 0, 1], shots },
        }],
      }, {
        id: "win_streak", title: "Active win streak", period: "Consecutive decisions", kind: "goalie", unit: "count",
        entries: [{
          id: 8, name: "Goalie Name", team: "TOR", position: "G", logo: "", rank: 1, value: 3,
          sample_size: 3, lower_bound: false, latest_game: "2026-10-01", start_date: "2026-09-01",
          end_date: "2026-10-01", seasons: ["2026-27"], stale: false, recent: [],
          matchups: [{ game_id: 1, opponent: "BOS", home: true }],
        }],
      }],
    },
  }));
  await page.goto(`/streaks?date=${date}`);
  await expect(page.getByRole("link", { name: "Alex Skater" })).toBeVisible();
  await page.getByRole("button", { name: "Goaltenders" }).click();
  await expect(page.getByText("Goalie Name")).toBeVisible();
  await expect(page.getByRole("link", { name: "Goalie Name" })).toHaveCount(0);
  await page.getByRole("button", { name: "Skaters" }).click();
  await page.getByRole("link", { name: "Alex Skater" }).click();
  await expect(page).toHaveURL(new RegExp(`/players\\?date=${date}&player=7`));
  await expect(page.locator(".player-expanded")).toContainText("Appearances over this line");
});
