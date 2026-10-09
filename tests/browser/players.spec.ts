import { test, expect } from "@playwright/test";

test("players windows, filters, sorting, expansion and navigation on desktop and phone", async ({
  page,
  request,
}) => {
  // Provide qualified season samples independently of the live season's start date.
  const fixture = await (await request.get("/api/players?date=2026-09-26")).json();
  for (const player of fixture.players) {
    player.windows.season = { ...player.windows.season, games: 10,
      points: player.id % 20, points_pg: (player.id % 20) / 10 };
  }
  await page.route("**/api/players?*", route => route.fulfill({ json: fixture }));
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/players?date=2026-09-26");
    await expect(page.locator(".player-name").first()).toBeVisible({
      timeout: 120000,
    });
    await expect(page.getByRole("button", { name: "Season", exact: true })).toHaveAttribute("aria-pressed", "true");
    expect(await page.locator("td.form-up").count()).toBeGreaterThan(0);
    expect(await page.locator("td.form-down").count()).toBeGreaterThan(0);
    await page.getByRole("button", { name: "Last 10", exact: true }).click();
    await expect(page).toHaveURL(/window=last10/);
    await page.getByRole("button", { name: "Season", exact: true }).click();
    await expect(
      page.getByRole("button", { name: "Season", exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("button", { name: "iCF/60", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "iCF/G", exact: true }).click();
    await expect(page.locator('th[aria-sort="descending"]')).toContainText(
      "iCF/G",
    );
    await page.locator(".player-name").first().focus();
    await page.keyboard.press("Enter");
    await expect(page.locator(".player-expanded")).toBeVisible();
    await expect(page.locator(".player-expanded strong")).toHaveCount(0);
    await expect(page.locator(".player-expanded")).toContainText("Last 5");
    await expect(page.locator(".player-expanded")).not.toContainText("Window");
    await page.getByLabel("Player position", { exact: true }).selectOption("D");
    await expect(page.locator(".player-name").first()).toBeVisible();
    await expect(
      page.getByRole("columnheader", { name: "Pos", exact: true }),
    ).toHaveCount(0);
    await page.getByLabel("Search players").fill("zz-nobody");
    await expect(page.getByText("No matching skaters.")).toBeVisible();
    await page.getByLabel("Search players").fill("");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
    const images = page.locator(".player-matchup img");
    expect(
      await images
        .first()
        .evaluate(
          (img: HTMLImageElement) => img.complete && img.naturalWidth > 0,
        ),
    ).toBeTruthy();
    const teamImages = page.locator(".player-name .player-team-logo");
    expect(
      await teamImages
        .first()
        .evaluate(
          (img: HTMLImageElement) => img.complete && img.naturalWidth > 0,
        ),
    ).toBeTruthy();
    await page.screenshot({
      path: `test-results/players-${width}.png`,
      fullPage: true,
    });
    await page.getByRole("link", { name: "NHL Matchups" }).click();
    await expect(page).toHaveURL("/?date=2026-09-26");
    await page
      .getByRole("navigation", { name: "Dashboard views" })
      .getByRole("link", { name: "Players" })
      .click();
    await expect(page).toHaveURL("/players?date=2026-09-26");
  }
  expect(errors).toEqual([]);
});

test("players empty dates and outages", async ({ page }) => {
  await page.route("**/api/players?*", (route) =>
    route.fulfill({
      json: {
        date: "2026-09-27",
        as_of: "2026-09-26",
        players: [],
        games: [],
        periods: [],
        sources: [],
        error: null,
      },
    }),
  );
  await page.goto("/players?date=2026-09-27");
  await expect(page.getByRole("button", { name: "On slate", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText("No scheduled games")).toBeVisible();
  await page.getByRole("button", { name: "All players", exact: true }).click();
  await expect(page.getByText("Skater rosters unavailable.")).toBeVisible();
  await page.getByRole("button", { name: "On slate", exact: true }).click();
  await expect(page.getByText("No scheduled games")).toBeVisible();
  await page.route("**/api/players?*", (route) =>
    route.fulfill({ status: 503, json: { detail: "Source unavailable" } }),
  );
  await page.getByLabel("Refresh players", { exact: true }).click();
  await expect(page.getByText("Players unavailable")).toBeVisible();
  await expect(page.getByText("Source unavailable")).toBeVisible();
});

test("on slate is the default and hides skaters who are not playing", async ({ page }) => {
  const source = { source: "NHL", url: "", retrieved_at: null, status: "available" as const };
  const stats = {
    games: 10, goals: 4, assists: 6, points: 10, points_pg: 1, shots: 30, shots_pg: 3,
    toi_pg: 900, powerPlayPoints: 2, point_games_pct: 60, attempts_pg: 4,
    shots60: 8, points60: 2, ixg60: 0.8, hd60: 1, advanced_games: 10,
  };
  const skater = (id: number, name: string, team: string, gameId: number | null) => ({
    id, name, position: "C", team, logo: "", game_id: gameId,
    opponent: gameId ? "BOS" : null, opponent_logo: null, home: false,
    season_label: "2026-27", windows: { last5: stats, last10: stats, season: stats },
    log: null, stats_source: source, advanced_source: source, roster_source: source,
  });
  const slate = skater(1, "Slate Skater", "NJD", 2026010001);
  const idle = skater(2, "Idle Skater", "DET", null);
  await page.route("**/api/players?*", (route) => {
    const scope = new URL(route.request().url()).searchParams.get("scope");
    return route.fulfill({ json: {
      date: "2026-10-06", as_of: "2026-10-06", periods: [], sources: [], error: null,
      ready: true, schedule_available: true, build: { status: "ready", done: 1, total: 1 },
      games: [{ id: 2026010001 }], players: scope === "tonight" ? [slate] : [slate, idle],
    } });
  });
  await page.route("**/api/player-props**", (route) => route.fulfill({
    json: { date: "2026-10-06", configured: false, manual_refresh_enabled: false, error: null, games: {} },
  }));
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/players?date=2026-10-06");
    await expect(page.getByRole("button", { name: "On slate", exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("button", { name: "Idle Skater" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Slate Skater" })).toBeVisible();
    await page.getByRole("button", { name: "All players", exact: true }).click();
    await expect(page).toHaveURL(/scope=league/);
    await expect(page.getByRole("button", { name: "Idle Skater" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Slate Skater" })).toBeVisible();
    await page.getByRole("button", { name: "On slate", exact: true }).click();
    await expect(page).toHaveURL(/scope=tonight/);
    await expect(page.getByRole("button", { name: "Idle Skater" })).toHaveCount(0);
    await page.getByRole("button", { name: "All players", exact: true }).click();
    await expect(page.getByRole("button", { name: "Idle Skater" })).toBeVisible();
    const idleRow = page.locator("tr", { has: page.getByRole("button", { name: "Idle Skater" }) });
    await expect(idleRow).toContainText("—");
    await idleRow.getByRole("button", { name: "Idle Skater" }).click();
    await expect(page.locator(".player-expanded")).toBeVisible();
    await expect(page.getByRole("region", { name: "Player props", exact: true })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  }
});
