import { test, expect } from "@playwright/test";

test("team bars share a scale, respect direction, and leave missing values neutral", async ({ page }) => {
  const date = "2026-09-29";
  const team = (abbrev: string) => ({ id: 1, abbrev, name: abbrev, logo: `https://assets.nhle.com/logos/nhl/svg/${abbrev}_light.svg`, score: null, starter: { name: null, status: "Unconfirmed" } });
  const game = { id: 2026020002, date, start: "2099-09-29T23:00:00Z", state: "FUT", schedule_state: "OK", game_type: 2, away: team("MTL"), home: team("TOR") };
  const side = (home: boolean) => ({
    summary: { gf: home ? 4 : 2, ga: home ? 3 : 2, sf: 30, pp: home ? 25 : null },
    advanced: { xgf_pct: 0 }, form: [],
    goalie: { name: "Test Goalie", basis: "Likely", stats: { games: 20, sv: .915, gaa: 2.5, gsax: 4 }, advanced_games: 20 },
  });
  await page.route("**/api/**", route => route.fulfill({ json: route.request().url().includes("/api/slate?")
    ? { date, games: [game], comparisons: { [game.id]: { season_label: "2025-26", away: side(false), home: side(true) } }, sources: [], error: null }
    : { date, status: "available", configured: true, prices: {}, error: null } }));
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto(`/?date=${date}`);
    const card = page.locator(".game-card");
    await expect(card).toBeVisible();
    const row = (label: string) => card.locator(".card-metric").filter({ has: page.getByText(label, { exact: true }) });
    const fills = (label: string) => row(label).locator(".metric-track > span");
    await expect(fills("Goals for / G").first()).toHaveAttribute("style", "width: 50%;");
    await expect(fills("Goals for / G").last()).toHaveAttribute("style", "width: 100%;");
    await expect(row("Goals for / G").locator("strong.better")).toHaveText("4.00");
    await expect(row("Goals against / G").locator("strong.better")).toHaveText("2.00");
    await expect(fills("Shots / G").first()).toHaveAttribute("style", "width: 100%;");
    await expect(row("Shots / G").locator(".better, .worse")).toHaveCount(0);
    await expect(fills("5v5 xG%").first()).toHaveAttribute("style", "width: 0%;");
    await expect(fills("Power play")).toHaveCount(0);
    await expect(row("Power play").locator(".better, .worse")).toHaveCount(0);
    await expect(fills("Save %")).toHaveCount(0);
    await expect(page.getByText("Goals for / G", { exact: true })).toHaveAttribute("title", /Gap: 2.00.*zero-based/);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const before = await row("Goals for / G").boundingBox();
    await card.hover();
    expect((await row("Goals for / G").boundingBox())?.height).toBe(before?.height);
    await card.focus();
    await expect(card).toBeFocused();
    await page.screenshot({ path: `test-results/card-bars-${width}.png`, fullPage: true });
  }
});
