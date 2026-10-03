import { test, expect } from "@playwright/test";

test("average TOI boxes separate positions, format time, and preserve span and scope", async ({ page }) => {
  const date = "2026-10-03";
  const requests: string[] = [];
  const entry = (id: number, name: string, position: string, value: number) => ({
    id, name, position, value, team: "CAR", logo: "", rank: 1, sample_size: 2,
    lower_bound: false, latest_game: "2026-10-02", start_date: "2026-10-01", end_date: "2026-10-02",
    seasons: ["2026-27"], stale: false, matchups: [],
    recent: ["20:30", "21:31"].map((value, i) => ({ date: `2026-10-0${i + 1}`, value, opponent: "BOS" })),
  });
  await page.route("**/api/**", route => {
    expect(route.request().method()).toBe("GET");
    const url = new URL(route.request().url());
    if (url.pathname !== "/api/streaks") return route.fulfill({ json: { date, games: {}, prices: {}, configured: false, status: "not_configured" } });
    requests.push(url.search);
    const window = url.searchParams.get("toi_window") || "last10";
    const value = window === "last5" ? 1500 : window === "season" ? 1440 : 1260.5;
    const period = window === "season" ? "Season appearances" : window === "last5" ? "Last 5 appearances" : "Last 10 appearances";
    return route.fulfill({ json: {
      date, scope: url.searchParams.get("scope"), toi_window: window, as_of: date,
      ready: true, build: { status: "ready", done: 3, total: 3 }, coverage: { partial: false },
      schedule_available: true, schedule_stale: false, stale: false, sources: [], error: null,
      boards: [
        { id: "points10", title: "Points", period: "Last 10 appearances", kind: "skater", entries: [{ ...entry(3, "Scorer", "C", 3), recent: [] }] },
        { id: `toi_forward_${window}`, title: "Average TOI · Forwards", period, kind: "skater", unit: "seconds", entries: [entry(1, "Forward Player", "C", value)] },
        { id: `toi_defense_${window}`, title: "Average TOI · Defense", period, kind: "skater", unit: "seconds", entries: [entry(2, "Defense Player", "D", 1600)] },
        { id: "win_streak", title: "Active win streak", period: "Consecutive decisions", kind: "goalie", entries: [] },
      ],
    } });
  });
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto(`/streaks?date=${date}`);
    const forward = page.getByRole("region", { name: "Average TOI · Forwards", exact: true });
    const defense = page.getByRole("region", { name: "Average TOI · Defense", exact: true });
    await expect(forward).toContainText("Forward Player");
    await expect(forward).not.toContainText("Defense Player");
    await expect(defense).toContainText("Defense Player");
    await expect(forward.locator(".streak-value strong")).toHaveText("21:01");
    await expect(defense.locator(".streak-value strong")).toHaveText("26:40");
    await expect(forward.locator(".streak-value span")).toHaveText("2 GP");
    await expect(forward.locator(".streak-recent span")).toHaveText(["20:30", "21:31"]);
    await expect(forward.locator(".streak-odds")).toHaveCount(0);
    await page.getByLabel("TOI span", { exact: true }).selectOption("last5");
    await expect(forward.locator(".streak-value strong")).toHaveText("25:00");
    await expect(page).toHaveURL(/toi_window=last5/);
    await expect(page.getByRole("region", { name: "Points", exact: true })).toContainText("Last 10 appearances");
    await page.getByLabel("TOI span", { exact: true }).selectOption("season");
    await expect(forward.locator(".streak-value strong")).toHaveText("24:00");
    await page.getByRole("button", { name: "League-wide", exact: true }).click();
    await expect(forward).toBeVisible();
    await expect.poll(() => requests.at(-1)).toMatch(/scope=league&toi_window=season/);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `test-results/streak-toi-${width}.png`, fullPage: true });
    await page.getByRole("button", { name: "Goaltenders", exact: true }).click();
    await expect(page.locator(".streak-board-toi")).toHaveCount(0);
    await expect(page.getByLabel("TOI span", { exact: true })).toHaveCount(0);
  }
});
