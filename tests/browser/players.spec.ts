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
    await page.getByRole("button", { name: "iCF/G", exact: true }).click();
    await expect(page.locator('th[aria-sort="descending"]')).toContainText(
      "iCF/G",
    );
    await page.locator(".player-name").first().focus();
    await page.keyboard.press("Enter");
    await expect(page.locator(".player-expanded")).toBeVisible();
    await expect(page.locator(".player-expanded")).toContainText("Last 5");
    await expect(page.locator(".player-expanded")).toContainText("Last 10");
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
  await expect(page.getByText("No scheduled games")).toBeVisible();
  await page.route("**/api/players?*", (route) =>
    route.fulfill({ status: 503, json: { detail: "Source unavailable" } }),
  );
  await page.getByLabel("Refresh players", { exact: true }).click();
  await expect(page.getByText("Players unavailable")).toBeVisible();
  await expect(page.getByText("Source unavailable")).toBeVisible();
});
