import { test, expect } from "@playwright/test";

test("moneylines stay cache-only on navigation, load paired prices, and fit mobile", async ({
  page,
  request,
}) => {
  const slate = await (await request.get("/api/slate?date=2026-09-26")).json();
  const game = slate.games[0];
  slate.games = [{ ...game, state: "FUT", start: "2099-09-26T23:00:00Z" }];
  await page.route("**/api/slate?*", (route) => route.fulfill({ json: slate }));
  let posts = 0;
  await page.route("**/api/odds/moneyline**", (route) => {
    const post = route.request().method() === "POST";
    if (post) posts++;
    return route.fulfill({
      json: {
        date: new URL(route.request().url()).searchParams.get("date"),
        configured: true,
        status: post ? "available" : "not_loaded",
        error: null,
        retrieved_at: post ? new Date().toISOString() : null,
        prices: post
          ? {
              [game.id]: [
                {
                  bookmaker: "best",
                  name: "Best available",
                  away: 125,
                  home: -140,
                  away_bookmaker: "fanduel",
                  away_name: "FanDuel",
                  away_updated_at: new Date().toISOString(),
                  home_bookmaker: "draftkings",
                  home_name: "DraftKings",
                  home_updated_at: "2020-01-01T00:00:00Z",
                  updated_at: "2020-01-01T00:00:00Z",
                },
              ],
            }
          : {},
      },
    });
  });
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 1000 });
    const before = posts;
    await page.goto("/?date=2026-09-26");
    await expect(page.locator(".team-moneyline")).toHaveCount(0);
    await expect(page.locator(".moneyline-card")).toHaveCount(0);
    expect(posts).toBe(before);
    const load = page.getByRole("button", { name: "Load moneylines" });
    await load.focus();
    await page.keyboard.press("Enter");
    const firstCard = page.locator(".game-card").first();
    await expect(firstCard.locator(".team-moneyline")).toHaveCount(2);
    await expect(firstCard.locator(".team-moneyline").first()).toContainText(
      "+125",
    );
    await expect(firstCard.locator(".team-moneyline").first()).toContainText(
      "FanDuel",
    );
    await expect(firstCard.locator(".team-moneyline").last()).toContainText(
      "DraftKings",
    );
    await expect(
      firstCard.locator(".team-moneyline.ml-favorite").first(),
    ).toContainText("-140");
    expect(posts).toBe(before + 1);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
    await page.screenshot({
      path: `test-results/moneyline-${width}.png`,
      fullPage: true,
    });
    await page.getByRole("button", { name: "Next day" }).click();
    await expect(page.locator(".team-moneyline")).toHaveCount(0);
    expect(posts).toBe(before + 1);
  }
});

test("moneylines show configuration and retained stale states", async ({
  page,
  request,
}) => {
  const slate = await (await request.get("/api/slate?date=2026-09-26")).json();
  slate.games = slate.games.slice(0, 1);
  await page.route("**/api/slate?*", (route) => route.fulfill({ json: slate }));
  await page.route("**/api/odds/moneyline**", (route) =>
    route.fulfill({
      json: {
        date: "2026-09-26",
        configured: false,
        status: "not_configured",
        prices: {},
        error: null,
      },
    }),
  );
  await page.goto("/?date=2026-09-26");
  await expect(
    page.getByRole("button", { name: "Load moneylines" }),
  ).toBeDisabled();
  await expect(page.locator(".team-moneyline")).toHaveCount(0);
  await page.route("**/api/odds/moneyline**", (route) =>
    route.fulfill({
      json: {
        date: "2026-09-26",
        configured: true,
        status: "stale",
        error: "Odds quota exhausted",
        prices: {
          [slate.games[0].id]: [
            {
              bookmaker: "best",
              name: "Best available",
              away: 100,
              home: -120,
              away_name: "FanDuel",
              away_updated_at: "2026-09-20T12:00:00Z",
              home_name: "FanDuel",
              home_updated_at: "2026-09-20T12:00:00Z",
              updated_at: "2026-09-20T12:00:00Z",
            },
          ],
        },
      },
    }),
  );
  await page.reload();
  await expect(page.locator(".moneyline-controls")).toContainText(
    "Odds quota exhausted",
  );
  await expect(page.locator(".team-moneyline").first()).toContainText("+100");
  await expect(page.locator(".team-moneyline").first()).toContainText(
    "FanDuel",
  );
});
