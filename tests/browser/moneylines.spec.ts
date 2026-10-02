import { test, expect } from "@playwright/test";

test("moneylines auto-load paired prices and fit mobile", async ({
  page,
  request,
}) => {
  const slate = await (await request.get("/api/slate?date=2026-09-26")).json();
  const game = slate.games[0];
  game.away.record = "3-1-0";
  game.home.record = "2-1-1";
  slate.games = [{ ...game, state: "FUT", start: "2099-09-26T23:00:00Z" }];
  await page.route("**/api/slate?*", (route) => route.fulfill({ json: slate }));
  let calls = 0;
  await page.route("**/api/odds/moneyline**", (route) => {
    calls++;
    const date = new URL(route.request().url()).searchParams.get("date");
    return route.fulfill({
      json: {
        date,
        configured: true,
        status: "available",
        error: null,
        retrieved_at: new Date().toISOString(),
        prices: date === "2026-09-26" ? {
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
        } : {},
      },
    });
  });
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 1000 });
    const before = calls;
    await page.goto("/?date=2026-09-26");
    await expect(page.locator(".moneyline-card")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Load moneylines" })).toHaveCount(0);
    const firstCard = page.locator(".game-card").first();
    await expect(firstCard.locator(".team-moneyline")).toHaveCount(2);
    await expect(firstCard.locator(".card-record")).toHaveText(["3-1-0", "2-1-1"]);
    await expect(firstCard.locator(".card-season")).toHaveCount(0);
    await expect(firstCard.locator(".card-matchup")).not.toContainText(game.away.abbrev);
    await expect(firstCard.locator(".card-team .logo").first()).toHaveCSS("width", "40px");
    await expect(firstCard.locator(".team-moneyline small").first()).toHaveAttribute("title", "FanDuel");
    await expect(firstCard.locator(".team-moneyline").first()).toContainText(
      "+125",
    );
    await expect(firstCard.locator(".team-moneyline").first()).toContainText(
      "FD",
    );
    await expect(firstCard.locator(".team-moneyline").last()).toContainText(
      "DK",
    );
    await expect(
      firstCard.locator(".team-moneyline.ml-favorite").first(),
    ).toContainText("-140");
    expect(calls).toBe(before + 1);
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
    expect(calls).toBe(before + 2);
  }
});

test("moneylines show configuration and retained prices on provider errors", async ({
  page,
  request,
}) => {
  const slate = await (await request.get("/api/slate?date=2026-09-26")).json();
  slate.games = slate.games.slice(0, 1);
  slate.games[0].state = "FUT";
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
  ).toHaveCount(0);
  await expect(page.locator(".team-moneyline")).toHaveCount(0);
  await page.route("**/api/odds/moneyline**", (route) =>
    route.fulfill({
      json: {
        date: "2026-09-26",
        configured: true,
        manual_refresh_enabled: true,
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
  await expect(
    page.getByRole("button", { name: "Refresh moneylines" }),
  ).toHaveAttribute(
    "title",
    /Odds quota exhausted/,
  );
  await expect(page.locator(".team-moneyline").first()).toContainText("+100");
  await expect(page.locator(".team-moneyline").first()).toContainText(
    "FD",
  );
  await expect(page.locator("body")).not.toContainText("Stale");
});
