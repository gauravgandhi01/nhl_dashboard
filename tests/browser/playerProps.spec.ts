import { test, expect } from "@playwright/test";
import {
  bestQuote,
  propLines,
  type PropPlayer,
  type PropLine,
} from "../../src/PlayerProps";

const now = new Date().toISOString();
function line(
  market: string,
  point: number | null,
  price = 120,
  book = "fanduel",
): PropLine {
  return {
    id: `${market}:${point}`,
    market,
    point,
    alternate: market.endsWith("_alternate"),
    quotes: [
      {
        side: point == null ? "yes" : "over",
        price,
        bookmaker: book,
        book: book === "fanduel" ? "FanDuel" : "DraftKings",
        market,
        updated_at: now,
      },
      ...(point == null
        ? []
        : [
            {
              side: "under",
              price: -140,
              bookmaker: book,
              book: "FanDuel",
              market,
              updated_at: now,
            },
          ]),
    ],
  };
}
function player(id = 1, name = "Test Player"): PropPlayer {
  return {
    id,
    name,
    team: "CAR",
    markets: {
      points: [
        line("player_points", 0.5),
        line("player_points_alternate", 0.5, 130, "draftkings"),
        line("player_points_alternate", 1.5, 240),
      ],
      shots: [
        line("player_shots_on_goal", 2.5),
        line("player_shots_on_goal_alternate", 0.5, -400),
      ],
      assists: [line("player_assists_alternate", 0.5)],
      anytime: [line("player_goal_scorer_anytime", null, 210)],
      goals: [
        line("player_goals", 0.5, 260, "draftkings"),
        line("player_goals_alternate", 1.5, 900),
      ],
      first_goal: [line("player_goal_scorer_first", null, 1200)],
    },
  };
}

test("prop selection groups identical thresholds, retains alternates, and prefers fresh prices", () => {
  const p = player();
  const points = propLines(p, "points");
  expect(points).toHaveLength(2);
  expect(bestQuote(points[0], "over")?.price).toBe(130);
  expect(bestQuote(points[0], "under")?.price).toBe(-140);
  expect(propLines(p, "shots")[0].point).toBe(2.5);
  expect(propLines(p, "shots", true)).toHaveLength(1);
  expect(propLines(p, "scorer")[0].market).toBe("player_goal_scorer_anytime");
  points[0].quotes.find((q) => q.price === 130)!.updated_at =
    "2020-01-01T00:00:00Z";
  expect(bestQuote(points[0], "over")?.price).toBe(120);
  points[0].quotes.push({
    side: "over",
    price: 135,
    effective_price: 118,
    bookmaker: "prophetx",
    book: "ProphetX",
    market: "player_points",
    updated_at: now,
  });
  expect(bestQuote(points[0], "over")?.price).toBe(120);
  expect(bestQuote(undefined, "over")).toBeUndefined();
});

test("anytime and half-goal lines compete as one market without mixing higher thresholds", () => {
  const p = player();
  p.markets.goals.push(line("player_goals_alternate", 0.5, 275, "novig"));
  const goals = propLines(p, "scorer");
  expect(goals).toHaveLength(2);
  expect(goals[0].point).toBeNull();
  expect(bestQuote(goals[0], "yes")?.price).toBe(275);
  expect(bestQuote(goals[0], "no")?.price).toBe(-140);
  expect(bestQuote(goals[1], "over")?.price).toBe(900);
  expect(p.markets.goals[0].quotes[0].side).toBe("over");
  expect(bestQuote(goals[0], "yes")?.source_point).toBe(0.5);
  delete p.markets.anytime;
  expect(propLines(p, "scorer")[0].id).toBe(
    "scorer:player_goal_scorer_anytime",
  );
  p.markets.anytime = [line("player_goal_scorer_anytime", null, 300)];
  expect(bestQuote(propLines(p, "scorer")[0], "yes")?.price).toBe(300);
});

test("shared player props render in expansion, lines, and only on-slate relevant streaks", async ({
  page,
  request,
}) => {
  test.setTimeout(120000);
  const date = "2026-09-26";
  const players = await (await request.get(`/api/players?date=${date}`)).json();
  const p = players.players[0];
  players.players = [p];
  const matchup = await (
    await request.get(`/api/matchups/${p.game_id}`)
  ).json();
  const entity = player(p.id, p.name);
  const response = {
    date,
    configured: true,
    max_credits_per_game: 10,
    error: null,
    games: {
      [p.game_id]: {
        game_id: p.game_id,
        eligible: true,
        status: "available",
        error: null,
        retrieved_at: now,
        unmatched_names: ["Provider Alias"],
        players: { [p.id]: entity },
      },
    },
  };
  let posts = 0;
  await page.route("**/api/player-props**", (route) => {
    if (route.request().method() === "POST") posts++;
    const d = new URL(route.request().url()).searchParams.get("date");
    return route.fulfill({
      json: { ...response, date: d, games: d === date ? response.games : {} },
    });
  });
  await page.route("**/api/players?*", (route) =>
    route.fulfill({ json: players }),
  );
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto(`/players?date=${date}`);
    await expect(page.locator(".props-controls")).not.toContainText(
      "Player odds checked",
    );
    await expect(page.locator(".props-controls")).not.toContainText(
      "games cached",
    );
    await expect(page.locator(".props-controls .warning")).toHaveAttribute(
      "title",
      /Provider Alias/,
    );
    await page.locator(".player-name").first().click();
    const panel = page.getByRole("region", {
      name: "Player props",
      exact: true,
    });
    await expect(panel.getByRole("heading", { name: "Player odds" })).toHaveCount(0);
    await expect(panel).not.toContainText("names need aliases");
    await expect(page.locator(".props-controls .warning")).toHaveAttribute(
      "title",
      /Provider Alias/,
    );
    await expect(panel.locator(".prop-market-head")).toHaveText(/O\s*U\s*L5\s*L10\s*Season/);
    const stampBox = await panel.locator(".prop-panel-heading span").boundingBox();
    const labelBox = await panel.locator(".prop-market-label").first().boundingBox();
    expect(Math.abs(stampBox!.x - labelBox!.x)).toBeLessThanOrEqual(2);
    await expect(panel.locator(".prop-market-row")).toHaveCount(5);
    await expect(panel.locator(".prop-market-row .prop-count").first()).not.toContainText("L5");
    const points = panel
      .locator(".prop-market-row")
      .filter({ has: page.getByLabel("Points line", { exact: true }) });
    const pointsLine = panel.getByLabel("Points line", { exact: true });
    await expect(points).toContainText("+130");
    const columns = await panel.locator(".prop-market-row").evaluateAll((rows) =>
      rows.map((row) => ({
        lines: Math.round(row.querySelector(".prop-line-carousel, .prop-missing")!.getBoundingClientRect().x),
        counts: [...row.querySelectorAll(".prop-count")].map((el) => Math.round(el.getBoundingClientRect().x)),
        over: Math.round(row.querySelector(".prop-side.over")!.getBoundingClientRect().x),
        under: Math.round(row.querySelector(".prop-side.under")!.getBoundingClientRect().x),
      })),
    );
    const aligned = (values: number[]) => Math.max(...values) - Math.min(...values) <= 1;
    expect(aligned(columns.map((row) => row.lines))).toBeTruthy();
    expect(aligned(columns.map((row) => row.over))).toBeTruthy();
    expect(aligned(columns.map((row) => row.under))).toBeTruthy();
    for (const index of [0, 1, 2]) expect(aligned(columns.map((row) => row.counts[index]))).toBeTruthy();
    const head = await panel.locator(".prop-market-head").evaluate((row) =>
      [...row.querySelectorAll("[role=columnheader]")].map((el) => Math.round(el.getBoundingClientRect().x)),
    );
    expect(head).toHaveLength(5);
    expect(Math.abs(head[0] - columns[0].over)).toBeLessThanOrEqual(1);
    expect(Math.abs(head[1] - columns[0].under)).toBeLessThanOrEqual(1);
    for (const index of [0, 1, 2]) expect(Math.abs(head[index + 2] - columns[0].counts[index])).toBeLessThanOrEqual(1);
    expect(columns[0].lines).toBeLessThan(columns[0].over);
    expect(columns[0].under).toBeLessThan(columns[0].counts[0]);
    const row = await points.boundingBox();
    expect(row!.height).toBeLessThan(24);
    await expect(pointsLine).toContainText("0.5");
    await pointsLine.getByRole("button", { name: "Next Points line" }).click();
    await expect(pointsLine).toContainText("1.5");
    await expect(points).toContainText("+240");
    await pointsLine.getByRole("button", { name: "Previous Points line" }).click();
    await expect(pointsLine).toContainText("0.5");
    await expect(points).toContainText("+130");
    await expect(panel.getByLabel("Goals line", { exact: true })).toContainText("0.5");
    await expect(panel.getByText("First goal", { exact: true })).toHaveCount(0);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
    await panel.screenshot({
      path: `test-results/player-props-expanded-${width}.png`,
    });
  }
  await expect(
    page.getByRole("button", { name: "Load game props", exact: true }),
  ).toHaveCount(0);
  expect(posts).toBe(0);

  for (const side of ["away", "home"]) {
    matchup[side].lineup = {
      sections: {
        "Forward Line 1": [p.name, "Unmatched Prospect", "Another Skater"],
      },
      updated_at: now,
    };
    matchup[side].lineup_player_ids = side === "away" ? { [p.name]: p.id } : {};
  }
  matchup.game.date = date;
  await page.route("**/api/matchups/*", (route) =>
    route.fulfill({ json: matchup }),
  );
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto(`/matchups/${p.game_id}?date=${date}&tab=lineups`);
    const matched = page.locator(".line-player").first();
    await expect(matched.locator(".compact-prop-label").first()).toHaveText("PTS");
    await expect(matched).toContainText("SOG O2.5");
    await expect(matched).not.toContainText("DK");
    await expect(matched).not.toContainText("FanDuel");
    await expect(matched).toContainText("+260");
    await expect(matched.locator(".prop-slash")).toHaveCount(0);
    await expect(matched.locator(".prop-quote")).toHaveCount(3);
    await expect(page.locator(".line-player")).not.toContainText("Pregame snapshot");
    response.games[p.game_id].eligible = false;
    await page.reload();
    await expect(matched).toContainText("+260");
    await expect(page.locator(".line-player")).not.toContainText("Pregame snapshot");
    response.games[p.game_id].eligible = true;
    await expect(matched.locator('.prop-quote[aria-label*="under"], .prop-quote[aria-label*="no "]')).toHaveCount(0);
    await expect(matched.locator(".prop-quote").first()).toHaveAttribute(
      "title",
      /FanDuel|DraftKings/,
    );
    await expect(
      page.locator(".line-player").nth(1).locator(".prop-quote"),
    ).toHaveCount(0);
    await expect(
      page.locator(".line-player").nth(1).locator(".compact-props"),
    ).toHaveCount(0);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
    await page.screenshot({
      path: `test-results/player-props-lines-${width}.png`,
      fullPage: true,
    });
  }
  entity.markets.points = [line("player_points_alternate", 1.5, 240)];
  const entry = {
    ...p,
    rank: 1,
    value: 10,
    sample_size: 10,
    lower_bound: false,
    latest_game: date,
    start_date: date,
    end_date: date,
    seasons: ["2025-26"],
    stale: false,
    recent: [],
    matchups: [{ game_id: p.game_id, opponent: "CAR", home: true }],
  };
  await page.route("**/api/streaks?*", (route) =>
    route.fulfill({
      json: {
        date,
        scope: new URL(route.request().url()).searchParams.get("scope"),
        as_of: date,
        ready: true,
        stale: false,
        error: null,
        build: { status: "ready" },
        schedule_available: true,
        coverage: { eligible_players: 1 },
        sources: [],
        boards: ["points10", "goals10", "shots10"].map((id) => ({
          id,
          title: id,
          kind: "skater",
          period: "Last 10",
          entries: [entry],
        })),
      },
    }),
  );
  await page.goto(`/streaks?date=${date}&scope=tonight`);
  await expect(page.locator(".single-prop")).toHaveCount(3);
  await expect(page.locator(".streak-board").nth(0)).toContainText("1.5");
  await expect(page.locator(".streak-board").nth(0)).toContainText("+240");
  await expect(page.locator(".streak-board").nth(0)).not.toContainText("PTS");
  await expect(page.locator(".streak-board").nth(1)).not.toContainText("ATG");
  await expect(page.locator(".streak-board").nth(1)).not.toContainText("SOG");
  await expect(page.locator(".streak-board").nth(2)).toContainText("+120");
  await expect(page.locator(".streak-board").nth(2)).toContainText("2.5");
  await expect(page.locator(".streak-board").nth(2)).not.toContainText("SOG");
  await page.screenshot({
    path: "test-results/player-props-streaks-mobile.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "League-wide", exact: true }).click();
  await expect(page.locator(".compact-props")).toHaveCount(0);
  expect(posts).toBe(0);
});

test("missing configuration and provider errors remain explicit", async ({
  page,
  request,
}) => {
  const date = "2026-09-26";
  const players = await (await request.get(`/api/players?date=${date}`)).json();
  const p = players.players[0];
  players.players = [p];
  await page.route("**/api/players?*", (r) => r.fulfill({ json: players }));
  let mode = "missing";
  await page.route("**/api/player-props**", (r) =>
    r.fulfill({
      json: {
        date,
        configured: mode !== "missing",
        max_credits_per_game: 10,
        error: null,
        games: {
          [p.game_id]: {
            game_id: p.game_id,
            eligible: true,
            status: mode === "missing" ? "not_loaded" : "stale",
            error: mode === "missing" ? null : "Quota exhausted",
            retrieved_at: now,
            unmatched_names: [],
            players: mode === "missing" ? {} : { [p.id]: player(p.id, p.name) },
          },
        },
      },
    }),
  );
  await page.goto(`/players?date=${date}`);
  await page.locator(".player-name").first().click();
  await expect(
    page.getByRole("button", { name: "Load game props", exact: true }),
  ).toHaveCount(0);
  await expect(page.locator(".player-prop-panel")).toContainText("Unavailable");
  mode = "stale";
  await page.reload();
  await expect(page).toHaveURL(new RegExp(`player=${p.id}`));
  await expect(page.locator(".player-prop-panel")).toContainText(
    "Quota exhausted",
  );
  await expect(
    page.locator(".player-prop-panel .prop-quote").first(),
  ).toBeVisible();
  await expect(page.locator(".player-prop-panel")).not.toContainText("stale");
});
