import { test, expect } from "@playwright/test";

const source = { source: "NHL", url: "", retrieved_at: null, status: "available" as const };

function goalie(id: number, name: string, team: string, sv: number, gaa: number, gameId: number | null, games = 10, status: string | null = id === 1 ? "Confirmed" : null) {
  const stats = {
    games, starts: games ? 8 : 0, wins: 6, losses: 3, ot_losses: 1, sv, gaa, shutouts: 1,
    gsax: Number(((sv - 0.9) * 20).toFixed(2)), shots_against: 300, saves: Math.round(sv * 300),
    advanced_games: 10,
  };
  return {
    id, name, team, logo: "", game_id: gameId, opponent: gameId ? "NYR" : null,
    opponent_logo: null, home: true, starter_status: status,
    season_label: "2026-27", windows: { last5: stats, last10: stats, season: stats },
    stats_source: source, advanced_source: source, roster_source: source,
  };
}

test("goalies default to every roster goalie and sort save percentage and goals-against average", async ({ page }) => {
  const goalies = [
    goalie(1, "Ukko-Pekka Luukkonen", "ANA", 0.94, 2.4, 2026010001),
    goalie(2, "Second Goalie", "BOS", 0.925, 2.6, 2026010002),
    goalie(3, "Third Goalie", "CAR", 0.91, 2.8, null),
    goalie(4, "Fourth Goalie", "DET", 0.895, 3.0, null),
    goalie(5, "Fifth Goalie", "EDM", 0.88, 3.2, null),
    goalie(6, "Idle Goalie", "FLA", 0.85, 1.9, null),
    goalie(7, "Zero Games", "NYI", 0, 0, 2026010001, 0),
    goalie(8, "Backup Goalie", "ANA", 0.905, 2.7, 2026010001, 10, null),
  ];
  await page.route("**/api/goalies?*", (route) => route.fulfill({
    json: {
      date: "2026-10-06", goalies, games: [{ id: 2026010001 }, { id: 2026010002 }],
      error: null, schedule_available: true, partial: false, periods: [], sources: [],
    },
  }));
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/goalies?date=2026-10-06");
    await expect(page.getByRole("button", { name: "All goalies", exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("button", { name: "Idle Goalie" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Backup Goalie" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Zero Games" })).toHaveCount(0);
    const nameLines = await page.locator(".player-name span").first().evaluate((el) => el.getClientRects().length);
    expect(nameLines).toBe(1);
    await expect(page.getByRole("button", { name: /odds/i })).toHaveCount(0);
    await expect(page.getByLabel("Refresh goalies")).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "SV%", exact: true })).toHaveAttribute("aria-sort", "descending");
    await expect(page.locator("tbody tr").first()).toContainText("Ukko-Pekka Luukkonen (6-3-1)");
    await expect(page.getByRole("columnheader", { name: "GS", exact: true })).toHaveCount(0);
    await expect(page.getByRole("columnheader", { name: "W", exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "GAA", exact: true }).click();
    await expect(page.getByRole("columnheader", { name: "GAA", exact: true })).toHaveAttribute("aria-sort", "ascending");
    await expect(page.locator("tbody tr").first()).toContainText("Idle Goalie");
    await page.locator(".player-name").first().click();
    await expect(page.locator(".player-expanded strong")).toHaveCount(0);
    await expect(page.locator(".player-name[aria-expanded='true']")).toContainText("Idle Goalie");
    await expect(page.locator(".player-expanded")).toContainText("Last 5");
    await expect(page.getByRole("region", { name: "Player props" })).toHaveCount(0);
    await page.getByRole("button", { name: "On slate", exact: true }).click();
    await expect(page.getByRole("button", { name: "Idle Goalie" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Backup Goalie" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Second Goalie" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Ukko-Pekka Luukkonen" })).toBeVisible();
    await expect(page.getByText("Confirmed")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  }
});
