import { test, expect } from "@playwright/test";

test("first-period cards, windows, goalie inspection, rankings and desktop/mobile navigation", async ({
  page,
  request,
}) => {
  const data = await (await request.get("/api/first-period?date=2026-09-26")).json();
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const posts: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST") posts.push(r.url());
  });
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/first-period?date=2026-09-26");
    await expect(page.locator(".fp-card").first()).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Season", exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
    await expect(
      page.getByRole("button", { name: "Last 15", exact: true }),
    ).toHaveCount(0);
    await expect(page.locator(".fp-card").first()).toContainText(
      "2+ goal frequency",
    );
    await expect(page.locator(".fp-card").first()).toContainText("1P save %");
    for (const label of ["1P GA / appearance", "1P save %", "Allowed 1+ frequency"]) {
      const row = page.locator(".fp-card").first().locator(".card-metric", { hasText: label });
      await expect(row.locator(".league-rank")).toHaveCount(2);
      await expect(row.locator(".better, .worse")).toHaveCount(0);
    }
    await expect(
      page.locator(".fp-card").first().getByLabel("Roster leader").first(),
    ).toBeVisible();
    await expect(page.locator(".fp-team-rankings tbody tr")).toHaveCount(data.rankings.length);
    await expect(page.getByRole("heading", { name: "League goalie rankings" })).toBeVisible();
    await expect(page.locator(".fp-goalie-rankings tbody tr")).toHaveCount(
      (data.goalie_rankings ?? []).length,
    );
    const teamHeading = await page.getByRole("heading", { name: "League team rankings" }).boundingBox();
    const goalieHeading = await page.getByRole("heading", { name: "League goalie rankings" }).boundingBox();
    if (width === 1440) {
      expect(goalieHeading!.x).toBeGreaterThan(teamHeading!.x + 200);
      expect(Math.abs(goalieHeading!.y - teamHeading!.y)).toBeLessThan(8);
    } else {
      expect(goalieHeading!.y).toBeGreaterThan(teamHeading!.y + 24);
    }
    for (const panel of [".fp-team-rankings", ".fp-goalie-rankings"]) {
      const scroller = page.locator(`${panel} .table-scroll`);
      if (await scroller.count()) {
        expect(
          await scroller.evaluate((element) => element.scrollWidth <= element.clientWidth + 1),
        ).toBeTruthy();
      }
    }
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    ).toBeTruthy();
    const l5 = page.getByRole("button", { name: "L5 2+ %", exact: true });
    if (width === 1440) {
      await l5.click();
      await expect(page.locator(".fp-team-rankings th[aria-sort='descending']")).toContainText("L5");
    } else {
      await expect(l5).toBeHidden();
      await page.getByRole("button", { name: "2+ %", exact: true }).click();
      await expect(page.locator(".fp-team-rankings th[aria-sort='descending']")).toContainText("2+ %");
    }
    await page.getByRole("button", { name: "Last 5", exact: true }).click();
    await expect(page).toHaveURL(/window=last5/);
    await expect(page.locator(".fp-card").first()).toBeVisible();
    await page.screenshot({
      path: `test-results/first-period-slate-${width}.png`,
      fullPage: true,
    });
    const link = await page.locator(".fp-card").first().getAttribute("href");
    await page.locator(".fp-card").first().focus();
    await page.keyboard.press("Enter");
    await expect(
      page.getByRole("heading", { name: "Head-to-head first periods" }),
    ).toBeVisible();
    await expect(page.locator(".fp-details .fp-form")).toHaveCount(4);
    await expect(page.getByText("5+ 1P GP")).toHaveCount(0);
    await expect(
      page.getByText(/1\+ 1P GP|no verified 1P appearances/).first(),
    ).toBeVisible();
    await expect(
      page.locator(".fp-details section").nth(2).locator("td[title*='1+ GP']").first(),
    ).toBeVisible();
    const report = await page.locator(".fp-starter").first().innerText();
    const selector = page.locator(".goalie-picker select").first();
    if ((await selector.locator("option").count()) > 1)
      await selector.selectOption({ index: 1 });
    await expect(page.locator(".fp-starter").first()).toHaveText(report);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
    await page.screenshot({
      path: `test-results/first-period-detail-${width}.png`,
      fullPage: true,
    });
    await page
      .getByRole("link", { name: "First-period slate", exact: true })
      .click();
    await expect(page).toHaveURL(/first-period\?date=2026-09-26&window=last5/);
    await page
      .getByRole("navigation", { name: "Dashboard views" })
      .getByRole("link", { name: "Players", exact: true })
      .click();
    await expect(page).toHaveURL("/players?date=2026-09-26");
    await page.goto(link!);
    await expect(
      page.getByRole("heading", { name: "Head-to-head first periods" }),
    ).toBeVisible();
  }
  expect(posts).toEqual([]);
  expect(errors).toEqual([]);
});

test("first-period empty date, schedule outage, postponed games and automatic odds", async ({
  page,
  request,
}) => {
  const response = await request.get("/api/first-period?date=2026-09-26");
  const data = await response.json();
  data.matchups = [data.matchups[0]];
  data.matchups[0].game.schedule_state = "PPD";
  await page.route("**/api/first-period?*", (r) => r.fulfill({ json: data }));
  let oddsCalls = 0;
  await page.route("**/api/first-period/odds?*", (r) => {
    oddsCalls++;
    r.fulfill({
      json: {
        prices: {},
        configured: true,
        status: "unavailable",
        retrieved_at: null,
        source: "https://the-odds-api.com",
        error: "Odds quota exhausted",
      },
    });
  });
  await page.goto("/first-period?date=2026-09-26");
  await expect(page.getByText("Postponed", { exact: true })).toBeVisible();
  await expect(page.locator(".fp-card .fp-price")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Load odds", exact: true })).toHaveCount(0);
  await expect(
    page.getByText("Odds quota exhausted", { exact: true }),
  ).toBeVisible();
  expect(oddsCalls).toBe(1);
  data.matchups = [];
  await page
    .getByRole("button", { name: "Refresh first-period statistics" })
    .click();
  await expect(
    page.getByRole("heading", { name: "No games scheduled" }),
  ).toBeVisible();
  await page.route("**/api/first-period?*", (r) =>
    r.fulfill({ json: { error: "NHL schedule unavailable", sources: [] } }),
  );
  await page
    .getByRole("button", { name: "Refresh first-period statistics" })
    .click();
  await expect(
    page.getByRole("heading", { name: "First period unavailable" }),
  ).toBeVisible();
});
