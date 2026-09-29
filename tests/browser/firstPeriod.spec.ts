import { test, expect } from "@playwright/test";

test("first-period cards, windows, goalie inspection, rankings and desktop/mobile navigation", async ({
  page,
}) => {
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
    await expect(page.locator(".fp-card").first()).toContainText(
      "Roster leader",
    );
    await expect(page.locator(".fp-rankings tbody tr")).toHaveCount(32);
    await page.getByRole("button", { name: "L5 2+ %", exact: true }).click();
    await expect(page.locator('th[aria-sort="descending"]')).toContainText(
      "L5",
    );
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

test("first-period empty date, schedule outage, postponed games and on-demand odds", async ({
  page,
  request,
}) => {
  const response = await request.get("/api/first-period?date=2026-09-26");
  const data = await response.json();
  data.matchups = [data.matchups[0]];
  data.matchups[0].game.schedule_state = "PPD";
  await page.route("**/api/first-period?*", (r) => r.fulfill({ json: data }));
  let loads = 0;
  await page.route("**/api/first-period/odds?*", (r) =>
    r.fulfill({
      json: {
        prices: {},
        configured: true,
        status: "not_loaded",
        retrieved_at: null,
        source: "https://the-odds-api.com",
        error: null,
      },
    }),
  );
  await page.route("**/api/first-period/odds/refresh?*", (r) => {
    loads++;
    return r.fulfill({
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
  expect(loads).toBe(0);
  await page.getByRole("button", { name: "Load odds", exact: true }).click();
  await expect(
    page.getByText("Odds quota exhausted", { exact: true }),
  ).toBeVisible();
  expect(loads).toBe(1);
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
