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

test("lineup TOI follows NHL IDs across name variants and explains missing values", async ({ page }) => {
  const source = { source: "NHL", url: "https://example.com", status: "available", retrieved_at: "2026-09-29T12:00:00Z" };
  const team = { id: 3, abbrev: "NYR", name: "Rangers", logo: "", score: null };
  const usage = (seconds: number | null, games: number | null, five: number | null, coverage: number | null) => Object.fromEntries(
    ["season", "l10", "l5"].flatMap(window => [[window, seconds], [`${window}_games`, games], [`${window}_5v5`, five], [`${window}_5v5_games`, coverage]]),
  );
  const side = {
    team, summary: {}, advanced: {}, recent: [], rest: {},
    starter: { name: null, status: "Unconfirmed" }, goalies: [],
    roster: [{ id: 8484210, name: "Gabe Perreault", position: "R", stats: { goals: 0, assists: 4, points: 4 } }],
    roster_source: source,
    lineup: { sections: {
      "Forward Line 1": ["Gabriel Perreault", "Unknown Skater", "New Rookie"],
      "Forward Line 2": ["Unavailable Log", "Uncovered Skater", "Provider Outage"],
      "Defense pair 1": ["Low Defender", "High Defender"],
      "1st Powerplay Unit": ["Gabriel Perreault", "Low Defender"],
    }, updated_at: source.retrieved_at },
    lineup_player_ids: { "Gabriel Perreault": 8484210, "Unknown Skater": null, "New Rookie": 2, "Unavailable Log": 3, "Uncovered Skater": 4, "Provider Outage": 5, "Low Defender": 6, "High Defender": 7 },
    lineup_usage: {
      "8484210": { ...usage(980, 5, 800, 5), l5: 850 },
      "6": usage(980, 5, 900, 5), "7": usage(1200, 5, 700, 5), "2": usage(null, 0, null, 0),
      "3": usage(null, null, null, null), "4": usage(900, 5, null, 0), "5": usage(900, 5, null, null),
      // A conflicting legacy name key must never override the verified NHL ID.
      gabrielperreault: usage(60, 5, 60, 5),
    },
    lineup_source: source, injuries: [], injury_source: source, stats_source: source,
  };
  const payload = {
    game: { id: 2026020002, date: "2026-09-29", start: "2026-09-29T23:00:00Z", state: "FUT", schedule_state: "OK", venue: "Test", away: team, home: { ...team, id: 6, abbrev: "BOS" } },
    away: side, home: { ...side, team: { ...team, id: 6, abbrev: "BOS", name: "Bruins" }, lineup: null, roster: [], lineup_usage: {} },
    season_label: "2025-26", as_of: "2026-09-29", sources: [],
  };
  await page.route("**/api/**", route => route.fulfill({ json: route.request().url().includes("/api/matchups/") ? payload : { configured: false, games: {}, sources: [] } }));
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/matchups/2026020002?date=2026-09-29&tab=lineups");
    await page.evaluate(() => document.fonts.ready);
    const player = (name: string) => page.locator(".line-player").filter({ has: page.locator(`strong[title="${name}"]`) });
    const forward = player("Gabriel Perreault").first();
    const defense = player("Low Defender").first();
    await expect(forward).toContainText("16:20");
    await expect(forward.locator(".line-scoring")).toContainText("G0A4P4");
    await expect(player("Unknown Skater").locator(".line-scoring")).toContainText("G--A--P--");
    await expect(player("Gabriel Perreault").nth(1).locator(".line-scoring")).toContainText("G0A4P4");
    const usage = forward.locator(".line-usage");
    const l10 = usage.locator(".line-toi").nth(1);
    const cardBox = await forward.boundingBox();
    const l10Box = await l10.boundingBox();
    const l10Label = await l10.locator("b").boundingBox();
    expect(await usage.evaluate((el) => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1);
    expect(l10Box && l10Label && l10Label.x < l10Box.x + 12).toBeTruthy();
    if ((cardBox?.width || 0) > 180) expect(l10Box!.height).toBeLessThan(18);
    await expect(forward.locator(".line-toi").nth(0)).toHaveCSS("background-color", "rgba(89, 190, 151, 0.26)");
    await expect(forward.locator(".line-toi").nth(2)).toHaveCSS("background-color", "rgba(222, 132, 145, 0.26)");
    await expect(defense.locator(".line-toi").nth(0)).toHaveCSS("background-color", "rgba(222, 132, 145, 0.26)");
    await expect(forward.locator(".line-toi").nth(0)).toHaveAttribute("title", /displayed NYR forwards: 15:00–16:20/);
    await expect(defense.locator(".line-toi").nth(0)).toHaveAttribute("title", /displayed NYR defense: 16:20–20:00/);
    await expect(player("Gabriel Perreault").nth(1).locator(".line-toi").nth(0)).toHaveCSS("background-color", "rgba(89, 190, 151, 0.26)");
    await expect(player("New Rookie").locator(".line-toi")).toHaveCount(0);
    await expect(forward).not.toContainText("1:00");
    await expect(player("Unknown Skater")).toContainText("Unmatched");
    await expect(player("New Rookie")).toContainText("No prior GP");
    await expect(player("Unavailable Log")).toContainText("NHL unavailable");
    await page.getByRole("button", { name: "5v5 TOI", exact: true }).click();
    await expect(forward).toContainText("13:20");
    await expect(forward.locator(".line-scoring")).toContainText("G0A4P4");
    // A single available forward is neutral; defense uses its own 5v5 range.
    await expect(forward.locator(".line-toi").nth(0)).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
    await expect(defense.locator(".line-toi").nth(0)).toHaveCSS("background-color", "rgba(89, 190, 151, 0.26)");
    await expect(player("Uncovered Skater")).toContainText("No 5v5 data");
    await expect(player("Provider Outage")).toContainText("5v5 unavailable");
    await expect(player("New Rookie")).toContainText("No prior GP");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `test-results/lineup-toi-${width}.png`, fullPage: true });
  }
});
