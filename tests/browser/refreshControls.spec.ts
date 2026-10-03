import { test, expect } from "@playwright/test";

test("refresh actions share one compact toolbar and keep stats and odds scopes separate", async ({ page, request }) => {
  const date = "2026-09-26";
  const players = await (await request.get(`/api/players?date=${date}`)).json();
  const gameId = players.players[0].game_id;
  const posts: string[] = [];
  await page.route(/\/api\/(player-props|odds\/moneyline|first-period\/odds)/, async route => {
    const url = new URL(route.request().url());
    if (route.request().method() === "POST") posts.push(url.pathname + url.search);
    await route.fulfill({ json: {
      date, configured: true, manual_refresh_enabled: true,
      games: {}, prices: {}, error: null, status: "available", retrieved_at: null,
    } });
  });
  const views = [
    { name: "slate", path: `/?date=${date}`, stats: "Refresh games", endpoint: "/api/slate", odds: "Refresh moneylines + totals", post: "/api/odds/moneyline/refresh" },
    { name: "players", path: `/players?date=${date}`, stats: "Refresh players", endpoint: "/api/players", odds: "Refresh slate player odds", post: "/api/player-props/refresh" },
    { name: "lines", path: `/matchups/${gameId}?date=${date}&tab=lineups`, stats: "Refresh matchup", endpoint: `/api/matchups/${gameId}`, odds: "Refresh game player odds", post: "/api/player-props/refresh" },
    { name: "first-period", path: `/first-period?date=${date}`, stats: "Refresh first-period statistics", endpoint: "/api/first-period", odds: "Refresh first-period odds", post: "/api/first-period/odds/refresh" },
    { name: "streaks", path: `/streaks?date=${date}&scope=tonight`, stats: "Refresh streaks", endpoint: "/api/streaks", odds: "Refresh slate player odds", post: "/api/player-props/refresh" },
  ];
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 950 });
    for (const view of views) {
      await page.goto(view.path);
      const actions = page.getByRole("group", { name: "Refresh data", exact: true });
      await expect(actions).toHaveCount(1);
      await expect(actions.locator(".refresh-button")).toHaveCount(2);
      const stats = actions.getByRole("button", { name: view.stats, exact: true });
      const odds = actions.getByRole("button", { name: view.odds, exact: true });
      await expect(stats).toHaveText("Stats");
      await expect(stats).toBeEnabled();
      await expect(stats).toHaveAttribute("title", /Cached/);
      await expect(odds).toHaveAttribute("title", /Fetch latest/);
      await expect(page.locator(".props-controls button, .fp-odds-meta button")).toHaveCount(0);
      const count = posts.length;
      const response = page.waitForResponse(r => new URL(r.url()).pathname === view.endpoint && r.request().method() === "GET");
      await stats.click();
      await response;
      await expect(stats).toBeEnabled();
      expect(posts.length).toBe(count);
      const refreshed = page.waitForResponse(r => new URL(r.url()).pathname === view.post && r.request().method() === "POST");
      await odds.click();
      await refreshed;
      expect(posts.length).toBe(count + 1);
      const url = new URL(posts.at(-1)!, "http://localhost");
      expect(url.searchParams.get("date")).toBe(date);
      expect(url.searchParams.get("game_id")).toBe(view.name === "lines" ? String(gameId) : null);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      for (const button of await actions.locator("button").all()) {
        expect((await button.boundingBox())!.height).toBe(28);
      }
      await page.screenshot({ path: `test-results/refresh-${view.name}-${width}.png` });
    }
  }
});
