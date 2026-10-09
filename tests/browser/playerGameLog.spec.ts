import { test, expect } from "@playwright/test";

const source = { source: "NHL", url: "", retrieved_at: null, status: "available" };
const stats = { games: 5, goals: 2, assists: 3, points: 5, toi_pg: 754 };
const recent = Array.from({ length: 5 }, (_, index) => ({
  game_id: 2026020005 - index, date: `2026-10-0${5 - index}`,
  opponent: index % 2 ? "MTL" : "BOS", home: index % 2 === 1,
  goals: 0, assists: 1, points: 1, toi: 754,
  toi_5v5: index === 1 ? null : 501, shots: 0, shot_attempts: index === 1 ? null : 0,
}));

for (const width of [1440, 375]) {
  test(`player game logs and empty states at ${width}px`, async ({ page }) => {
    const skater = (id: number, name: string, games: typeof recent | null) => ({
      id, name, position: "C", team: "NJD", logo: "", game_id: 2026020010,
      opponent: "BOS", home: false, season_label: "2026-27",
      windows: { last5: stats, last10: stats, season: stats }, recent_games: games,
      log: { goals: [0], assists: [1], points: [1], shots: [0] },
      stats_source: source, advanced_source: source, roster_source: source,
    });
    await page.route("**/api/players?*", route => route.fulfill({ json: {
      date: "2026-10-06", as_of: "2026-10-06", periods: [], sources: [], error: null,
      ready: true, schedule_available: true, games: [{ id: 2026020010 }],
      players: [skater(1, "Test Skater", recent), skater(2, "New Skater", []),
        skater(3, "Unavailable Skater", null), skater(4, "Short History", recent.slice(0, 2))],
    } }));
    await page.route("**/api/player-props**", route => route.fulfill({ json: {
      date: "2026-10-06", configured: false, manual_refresh_enabled: false, error: null, games: {},
    } }));
    await page.setViewportSize({ width, height: 900 });
    for (const scope of ["On slate", "All players"]) {
      await page.goto(`/players?date=2026-10-06&scope=${scope === "On slate" ? "tonight" : "league"}`);
      await expect(page.getByRole("button", { name: scope, exact: true })).toHaveAttribute("aria-pressed", "true");
      const button = page.getByRole("button", { name: "Test Skater", exact: true });
      if (await button.getAttribute("aria-expanded") !== "true") {
        await button.focus();
        await page.keyboard.press("Enter");
      }
      const table = page.getByRole("table", { name: "Test Skater game log", exact: true });
      const scroll = page.getByRole("region", { name: "Test Skater last five games", exact: true });
      await expect(table.locator("thead th")).toHaveText([
        "Date", "Opponent", "G", "A", "P", "TOI", "5v5 TOI", "Shots", "Shot Attempts",
      ]);
      await expect(table.locator("tbody tr")).toHaveCount(5);
      await expect(table.locator("tbody tr").first().locator("td")).toHaveText([
        "2026-10-05", "@ BOS", "0", "1", "1", "12:34", "8:21", "0", "0",
      ]);
      await expect(table.locator("tbody tr").nth(1).locator("td")).toHaveText([
        "2026-10-04", "vs MTL", "0", "1", "1", "12:34", "--", "0", "--",
      ]);
      await expect(table.locator("tbody tr").last()).toContainText("2026-10-01");
      await expect(page.locator(".player-expanded")).not.toContainText("Window");
      await expect(page.getByRole("region", { name: "Player props", exact: true })).toBeVisible();
      expect(await scroll.evaluate(el => el.scrollHeight > el.clientHeight)).toBe(true);
      await scroll.focus();
      await page.keyboard.press("ArrowDown");
      await expect.poll(() => scroll.evaluate(el => el.scrollTop)).toBeGreaterThan(0);
      expect(await table.locator("th").first().evaluate(el => getComputedStyle(el).position)).toBe("sticky");
      if (width === 375) {
        expect(await scroll.evaluate(el => el.scrollWidth > el.clientWidth)).toBe(true);
        await scroll.evaluate(el => { el.scrollLeft = el.scrollWidth; });
        await expect(table.getByRole("columnheader", { name: "Shot Attempts", exact: true })).toBeInViewport();
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.getByRole("button", { name: "Last 10", exact: true }).click();
      await expect(table.locator("tbody tr")).toHaveCount(5);
      await page.screenshot({ path: `test-results/player-game-log-${width}-${scope.replaceAll(" ", "-")}.png` });
      await button.click();
      await expect(button).toHaveAttribute("aria-expanded", "false");
    }
    await page.getByRole("button", { name: "New Skater", exact: true }).click();
    await expect(page.locator(".player-expanded")).toContainText("No appearances before this date.");
    await page.getByRole("button", { name: "Unavailable Skater", exact: true }).click();
    await expect(page.locator(".player-expanded")).toContainText("Game log unavailable");
    await page.getByRole("button", { name: "Short History", exact: true }).click();
    await expect(page.getByRole("table", { name: "Short History game log", exact: true }).locator("tbody tr")).toHaveCount(2);
  });
}
