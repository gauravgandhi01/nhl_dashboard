import { test, expect } from "@playwright/test";

const slateDate = "2026-09-26";

test("signal flags identify the team and reveal their reasons on desktop and mobile", async ({
  page,
  request,
}) => {
  const response = await request.get(`/api/slate?date=${slateDate}`);
  const slate = await response.json();
  const game = slate.games[0];
  slate.games = [game];
  const comparison = slate.comparisons[String(game.id)];
  comparison.away.signals = [
    {
      id: "back_to_back",
      label: "B2B",
      detail: "Second night of a back-to-back.",
    },
    {
      id: "inexperienced_goalie",
      label: "Goalie 4 NHL GP",
      detail: "Confirmed starter has 4 career NHL appearances.",
    },
  ];
  comparison.home.signals = [
    {
      id: "losing_streak",
      label: "Winning team / L3",
      detail:
        "Winning record with three consecutive losses, including overtime.",
    },
  ];
  await page.route("**/api/slate?*", (route) => route.fulfill({ json: slate }));
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`/?date=${slateDate}`);
    await expect(page.locator(".signal-flag")).toHaveCount(3);
    await expect(page.locator(".signal-back_to_back")).toContainText(
      game.away.abbrev,
    );
    await expect(page.locator(".signal-losing_streak")).toContainText(
      game.home.abbrev,
    );
    await page.locator(".signal-inexperienced_goalie").focus();
    await expect(
      page.locator('.signal-inexperienced_goalie [role="tooltip"]'),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
    await page.screenshot({
      path: `test-results/signals-fixture-${width}.png`,
    });
  }
});

test("desktop slate, matchup controls, roster, lineup, and back navigation", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/?date=${slateDate}`);
  await expect(page.locator(".game-card").first()).toBeVisible();
  const firstCard = await page.locator(".game-card").nth(0).boundingBox();
  const secondCard = await page.locator(".game-card").nth(1).boundingBox();
  expect(secondCard!.y).toBe(firstCard!.y);
  expect(secondCard!.x).toBeGreaterThan(firstCard!.x);
  await expect(
    page.getByRole("button", { name: "Live", exact: true }),
  ).toHaveCount(0);
  await expect(page.locator(".game-card").first()).toContainText(
    "Goals for / G",
  );
  await expect(page.locator(".game-card").first()).toContainText("5v5 xG%");
  await expect(page.locator(".game-card").first()).not.toContainText("Games");
  await expect(page.locator(".game-card").first()).toContainText("L5 form");
  await expect(page.locator(".game-card").first()).toContainText("GSAx");
  await expect(
    page.locator(".game-card").first().locator(".card-form > span"),
  ).toHaveCount(10);
  expect(
    await page.locator(".game-card").first().locator(".better").count(),
  ).toBeGreaterThan(0);
  await page.screenshot({
    path: "test-results/slate-desktop.png",
    fullPage: true,
  });
  const link = await page.locator(".game-card").first().getAttribute("href");
  await page.locator(".game-card").first().click();
  await expect(
    page.getByRole("heading", { name: "Team comparison" }),
  ).toBeVisible();
  await expect(page.locator(".compare-table")).toHaveCount(2);
  await page.screenshot({
    path: "test-results/matchup-desktop.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Last 10", exact: true }).click();
  await expect(page.locator(".data-context")).toContainText(
    "Last 10 completed games",
  );
  await expect(page.locator(".compare-header").first()).toContainText("10 GP");
  const starter = await page
    .locator(".reported-starter strong")
    .first()
    .innerText();
  const selector = page.locator(".goalie-picker select").first();
  if ((await selector.locator("option").count()) > 1) {
    await selector.selectOption({ index: 1 });
    await expect(page.locator(".reported-starter strong").first()).toHaveText(
      starter,
    );
  }
  await page.getByRole("button", { name: "Rosters", exact: true }).click();
  await expect(page.locator(".roster-table")).toHaveCount(2);
  await expect(page.locator(".roster-table tbody tr").first()).toBeVisible();
  await page
    .getByRole("button", { name: "Lines & injuries", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Injuries", exact: true }),
  ).toHaveCount(2);
  await page.screenshot({
    path: "test-results/lineups-desktop.png",
    fullPage: true,
  });
  await page.getByRole("link", { name: "Daily slate" }).click();
  await expect(page.locator(".game-card").first()).toBeVisible();
  await page
    .getByRole("textbox", { name: "Filter teams" })
    .fill("nonexistent-team");
  await expect(
    page.getByRole("heading", { name: "No matching games" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Clear filter" }).click();
  await page.goto(link!);
  await expect(
    page.getByRole("heading", { name: "Team comparison" }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("phone layout has no page overflow and controls remain usable", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto(`/?date=${slateDate}`);
  await expect(page.locator(".game-card").first()).toBeVisible();
  const firstCard = await page.locator(".game-card").nth(0).boundingBox();
  const secondCard = await page.locator(".game-card").nth(1).boundingBox();
  expect(secondCard!.x).toBe(firstCard!.x);
  expect(secondCard!.y).toBeGreaterThan(firstCard!.y);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "test-results/slate-mobile.png",
    fullPage: true,
  });
  await page.locator(".game-card").first().click();
  await expect(
    page.getByRole("heading", { name: "Team comparison" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "test-results/matchup-mobile.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Rosters", exact: true }).click();
  await expect(page.locator(".roster-table").first()).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page
    .getByRole("button", { name: "Lines & injuries", exact: true })
    .click();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
});

test("empty date, source outage, and keyboard navigation", async ({ page }) => {
  await page.route("**/api/slate?*", (route) =>
    route.fulfill({
      json: { date: "2026-09-27", games: [], sources: [], error: null },
    }),
  );
  await page.goto("/?date=2026-09-27");
  await expect(
    page.getByRole("heading", { name: "No games scheduled" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Next day" }).focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/date=2026-09-28/);
  await page.route("**/api/slate?*", (route) =>
    route.fulfill({
      json: {
        date: "2026-09-28",
        games: [],
        sources: [],
        error: "The NHL schedule is unavailable.",
      },
    }),
  );
  await page.getByRole("button", { name: "Refresh games" }).click();
  await expect(
    page.getByRole("heading", { name: "Games unavailable" }),
  ).toBeVisible();
});
