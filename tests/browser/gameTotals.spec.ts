import { test, expect } from "@playwright/test";

test("cards show a total with both prices and books without paid navigation requests", async ({ page }) => {
  const date = "2026-10-03";
  const team = (abbrev: string) => ({ id: 1, abbrev, name: abbrev, logo: "", record: "1-0-0", starter: { name: null, status: "Unknown" } });
  const game = { id: 2026020001, date, start: "2099-10-03T23:00:00Z", state: "FUT", schedule_state: "OK", away: team("NYR"), home: team("DET") };
  let stale = false;
  let missing = false;
  let posts = 0;
  await page.route("**/api/**", async route => {
    const request = route.request();
    if (request.method() === "POST") posts++;
    if (request.url().includes("/api/slate")) return route.fulfill({ json: { date, games: [game], sources: [], comparisons: {}, error: null } });
    return route.fulfill({ json: {
      date, configured: true, manual_refresh_enabled: true, status: stale ? "stale" : "available",
      prices: {}, totals_loaded: true, retrieved_at: "2026-10-03T12:00:00Z",
      totals: missing ? {} : { [game.id]: { total: 6, over: -105, under: 100,
        over_name: "DraftKings", over_bookmaker: "draftkings", over_updated_at: "2026-10-03T12:00:00Z",
        under_name: "FanDuel", under_bookmaker: "fanduel", under_updated_at: "2026-10-03T12:01:00Z",
        fair_over: .5, paired_books: 4 } },
    } });
  });
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 950 });
    await page.goto(`/?date=${date}`);
    const total = page.getByLabel("Game total 6", { exact: true });
    await expect(total).toBeVisible();
    await expect(total.locator(".total-price")).toHaveText(["-105DK", "+100FD"]);
    await expect(total.locator(".total-line")).toHaveText("6");
    await expect(total.locator(".total-price").first()).toHaveAttribute("aria-label", /^Over 6:/);
    await expect(total.locator(".total-price").last()).toHaveAttribute("aria-label", /^Under 6:/);
    const lineBox = await total.locator(".total-line").boundingBox();
    const pricesBox = await total.locator(".total-prices").boundingBox();
    expect(pricesBox!.x).toBeGreaterThan(lineBox!.x + lineBox!.width);
    await expect(total.locator(".total-price small").first()).toHaveAttribute("title", "DraftKings");
    expect(posts).toBe(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `test-results/game-totals-${width}.png`, fullPage: true });
  }
  await page.getByRole("button", { name: "Refresh moneylines + totals", exact: true }).click();
  await expect.poll(() => posts).toBe(1);
  stale = true;
  game.state = "LIVE";
  await page.reload();
  await page.getByRole("button", { name: /^Started/ }).click();
  await expect(page.locator(".total-status")).toHaveText("Stale · Pregame snapshot");
  missing = true;
  game.state = "FUT";
  await page.reload();
  await expect(page.locator(".card-total-empty")).toHaveText("Total unavailable");
  game.schedule_state = "PPD";
  await page.reload();
  await expect(page.locator(".card-total")).toHaveCount(0);
});
