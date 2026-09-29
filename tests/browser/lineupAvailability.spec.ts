import { test, expect } from "@playwright/test";

for (const mode of ["missing", "empty", "stale"]) {
  test(`lineups ${mode}: explicit fallback and mobile layout`, async ({ page }) => {
    const source = { source: "NHL", url: "https://example.com", status: "available", retrieved_at: "2026-09-29T12:00:00Z" };
    const team = (abbrev: string) => ({ id: abbrev === "MTL" ? 8 : 10, abbrev, name: abbrev, logo: "", record: "0-0-0", score: null });
    const side = (abbrev: string) => ({
      team: team(abbrev), summary: {}, advanced: {}, recent: [], rest: {},
      starter: { name: null, status: "Unconfirmed", updated_at: null }, goalies: [],
      roster: [{ id: 1, name: "Test Skater", position: "C", stats: {} }, { id: 2, name: "Test Goalie", position: "G", stats: {} }],
      roster_source: source, lineup_usage: {},
      lineup: mode === "missing" ? null : { sections: mode === "empty" ? {} : { "Forward Line 1": ["Test Skater"] }, updated_at: source.retrieved_at },
      lineup_source: { ...source, status: mode === "stale" ? "stale" : "unavailable", error: "Source access rules unavailable (HTTP 403)" },
      injuries: [], injury_source: source, stats_source: source,
    });
    const payload = { game: { id: 2026020002, date: "2026-09-29", start: "2026-09-29T23:00:00Z", state: "FUT", schedule_state: "OK", venue: "Toronto", away: team("MTL"), home: team("TOR") }, away: side("MTL"), home: side("TOR"), season_label: "2025-26", as_of: "2026-09-29", sources: [] };
    await page.route("**/api/**", (route) => route.fulfill({ json: route.request().url().includes("/api/matchups/") ? payload : { configured: false, games: {}, sources: [] } }));
    for (const width of [1440, 375]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.goto("/matchups/2026020002?date=2026-09-29&tab=lineups");
      await expect(page.locator(".line-player")).toHaveCount(2);
      await expect(page.locator(".line-player").first()).toContainText("T. Skater");
      await expect(page.getByRole("heading", { name: "Injuries", exact: true })).toHaveCount(2);
      if (mode === "stale") {
        await expect(page.getByText(/Cached projection; refresh unavailable/)).toHaveCount(2);
      } else {
        await expect(page.getByRole("heading", { name: "NHL roster only" })).toHaveCount(2);
        await expect(page.getByText(/Line assignments and game participation unconfirmed/)).toHaveCount(2);
        await expect(page.getByText("Forward Line 1", { exact: true })).toHaveCount(0);
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: `test-results/lineups-${mode}-${width}.png`, fullPage: true });
    }
  });
}
