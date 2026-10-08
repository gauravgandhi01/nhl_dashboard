import { test, expect } from "@playwright/test";

const slateDate = "2026-09-26";

test("signal flags identify the team and reveal their reasons on desktop and mobile", async ({
  page,
  request,
}) => {
  const response = await request.get(`/api/slate?date=${slateDate}`);
  const slate = await response.json();
  const game = { ...slate.games[0], state: "FUT" };
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
  const unflagged = { ...game, id: game.id + 1 };
  slate.games.push(unflagged);
  slate.comparisons[String(unflagged.id)] = {
    ...comparison,
    away: { ...comparison.away, signals: [] },
    home: { ...comparison.home, signals: [] },
  };
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
    const flags = page.locator(".card-signals");
    await expect(flags).toContainText("3 flags");
    const offsets = await page.locator(".game-card").evaluateAll(cards =>
      cards.map(card => card.querySelector(".card-metric")!.getBoundingClientRect().top - card.getBoundingClientRect().top),
    );
    expect(Math.abs(offsets[0] - offsets[1])).toBeLessThanOrEqual(1);
    await flags.focus();
    await expect(flags.getByRole("tooltip")).toBeVisible();
    await expect(flags.getByRole("tooltip")).toContainText("Confirmed starter has 4 career NHL appearances.");
    await page.keyboard.press("Escape");
    await expect(flags.getByRole("tooltip")).toBeHidden();
    await flags.click();
    await expect(page).toHaveURL(`/?date=${slateDate}`);
    await expect(flags.getByRole("tooltip")).toBeVisible();
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

test("desktop slate, matchup controls, lineup, and back navigation", async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const slate = await (await request.get(`/api/slate?date=${slateDate}`)).json();
  slate.games = slate.games.map((g: { state: string }) => ({ ...g, state: "FUT" }));
  await page.route("**/api/slate?*", (route) => route.fulfill({ json: slate }));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/?date=${slateDate}`);
  await expect(page.locator(".game-card").first()).toBeVisible();
  const firstCard = await page.locator(".game-card").nth(0).boundingBox();
  const secondCard = await page.locator(".game-card").nth(1).boundingBox();
  expect(Math.abs(secondCard!.y - firstCard!.y)).toBeLessThanOrEqual(2);
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
    page.locator(".game-card").first().locator(".card-form"),
  ).toHaveCount(2);
  const formCells = page.locator(".game-card").first().locator(".card-form").first().locator("span:not(.muted)");
  if ((await formCells.count()) >= 2) {
    const [older, newer] = await Promise.all([
      formCells.first().evaluate((el) => Number(getComputedStyle(el).opacity)),
      formCells.last().evaluate((el) => Number(getComputedStyle(el).opacity)),
    ]);
    expect(newer).toBeGreaterThan(older);
    await expect(formCells.last()).toHaveClass(/form-recent/);
    await expect(formCells.first()).not.toHaveClass(/form-recent/);
  }
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
  await expect(page.locator(".compare-header").first()).toContainText(/\d+ GP/);
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
  await expect(
    page.getByRole("button", { name: "Rosters", exact: true }),
  ).toHaveCount(0);
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
  await page.goto(link!);
  await expect(
    page.getByRole("heading", { name: "Team comparison" }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("slate defaults to upcoming and filters started games", async ({
  page,
  request,
}) => {
  const slate = await (await request.get(`/api/slate?date=${slateDate}`)).json();
  const games = slate.games.slice(0, 3).map((g: { state: string }, i: number) => ({
    ...g,
    state: i === 0 ? "FUT" : i === 1 ? "LIVE" : "OFF",
  }));
  slate.games = games;
  slate.comparisons = Object.fromEntries(
    games.map((g: { id: number }) => [String(g.id), slate.comparisons[String(g.id)]]),
  );
  await page.route("**/api/slate?*", (route) => route.fulfill({ json: slate }));
  await page.goto(`/?date=${slateDate}`);
  await expect(
    page.getByRole("button", { name: /All games/i }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: /Upcoming/i }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".game-card")).toHaveCount(1);
  await page.getByRole("button", { name: /Started/i }).click();
  await expect(page.locator(".game-card")).toHaveCount(2);
  await page.getByRole("button", { name: /Final/i }).click();
  await expect(page.locator(".game-card")).toHaveCount(1);
});

test("phone layout has no page overflow and controls remain usable", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto(`/?date=${slateDate}`);
  await page.getByRole("button", { name: /Started/i }).click();
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
  await expect(
    page.getByRole("button", { name: "Rosters", exact: true }),
  ).toHaveCount(0);
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

test("moneyline refresh button posts for fresh odds", async ({ page, request }) => {
  const slate = await (await request.get(`/api/slate?date=${slateDate}`)).json();
  const payload = {
    date: slateDate,
    configured: true,
    manual_refresh_enabled: true,
    status: "available",
    error: null,
    retrieved_at: "2026-09-26T12:00:00+00:00",
    usage: { remaining: "99" },
    prices: {},
  };
  let posts = 0;
  await page.route("**/api/slate?*", (route) => route.fulfill({ json: slate }));
  await page.route("**/api/odds/moneyline**", (route) => {
    if (route.request().method() === "POST") posts++;
    return route.fulfill({ json: payload });
  });
  await page.goto(`/?date=${slateDate}`);
  await page.getByRole("button", { name: "Refresh moneylines" }).click();
  await expect.poll(() => posts).toBe(1);
});
