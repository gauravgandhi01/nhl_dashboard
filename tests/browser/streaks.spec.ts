import { test, expect } from "@playwright/test";

test("top-ten streak boards, slate filter, mobile layout and preserved dates", async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const league = await (
    await request.get("/api/streaks?date=2026-09-28&scope=league")
  ).json();
  const slate = await (
    await request.get("/api/streaks?date=2026-09-28&scope=tonight")
  ).json();
  const skaterBoardCount = league.boards.filter(
    (b: { kind: string }) => b.kind === "skater",
  ).length;
  const goalieBoardCount = league.boards.filter(
    (b: { kind: string }) => b.kind === "goalie",
  ).length;
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 950 });
    await page.goto("/streaks?date=2026-09-28");
    await expect(page.locator(".streak-board")).toHaveCount(skaterBoardCount, {
      timeout: 120000,
    });
    await expect(
      page.getByRole("button", { name: "Skaters", exact: true }),
    ).toHaveAttribute("aria-current", "page");
    await expect(
      page.getByRole("button", { name: "On slate", exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
    const rows = page.locator(".streak-row");
    await expect(rows).toHaveCount(
      slate.boards
        .filter((b: { kind: string }) => b.kind === "skater")
        .reduce(
          (n: number, b: { entries: unknown[] }) => n + b.entries.length,
          0,
        ),
    );
    for (const board of await page.locator(".streak-board").all()) {
      const count = await board.locator(".streak-row").count();
      expect(count).toBeLessThanOrEqual(10);
      if (count > 0) {
        const listBox = await board.locator(".streak-list").boundingBox();
        expect(listBox!.height).toBeLessThanOrEqual(270);
      }
    }
    await expect(
      page.getByRole("region", { name: "Active win streak", exact: true }),
    ).toHaveCount(0);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
    if ((await page.locator(".streak-row").count()) > 0) {
      await page.waitForFunction(() => {
        const img = document.querySelector<HTMLImageElement>(".streak-row img");
        return !!img && img.complete && img.naturalWidth > 0;
      });
      await expect(page.locator(".streak-row").first()).not.toContainText(
        "Last GP",
      );
    }
    await page.screenshot({
      path: `test-results/streaks-${width}.png`,
      fullPage: true,
    });
    await page
      .getByRole("button", { name: "Goaltenders", exact: true })
      .click();
    await expect(page).toHaveURL(/kind=goalie/);
    await expect(page.locator(".streak-board")).toHaveCount(goalieBoardCount);
    await expect(
      page.getByRole("region", { name: "Active win streak", exact: true }),
    ).toContainText("Consecutive decisions");
    await expect(
      page.getByRole("region", { name: "Starts with 0-1 GA", exact: true }),
    ).toContainText("Last 10 starts");
    await page.getByRole("button", { name: "Skaters", exact: true }).click();
    const leagueResponse = page.waitForResponse(
      (r) =>
        r.url().includes("/api/streaks?") && r.url().includes("scope=league"),
    );
    await page.getByRole("button", { name: "League-wide", exact: true }).click();
    await leagueResponse;
    await expect(page).toHaveURL(/scope=league/);
    await expect(page.locator(".streak-board")).toHaveCount(skaterBoardCount);
    await page.getByRole("button", { name: "On slate", exact: true }).click();
    await expect(page).toHaveURL(/scope=tonight/);
    await page
      .getByRole("navigation", { name: "Dashboard views" })
      .getByRole("link", { name: "Players", exact: true })
      .click();
    await expect(page).toHaveURL("/players?date=2026-09-28");
    await page
      .getByRole("navigation", { name: "Dashboard views" })
      .getByRole("link", { name: "Streaks", exact: true })
      .click();
    await expect(page).toHaveURL("/streaks?date=2026-09-28");
  }
  expect(errors).toEqual([]);
});

test("streaks cross-season, partial, empty slate and failed provider states", async ({
  page,
  request,
}) => {
  const data = await (await request.get("/api/streaks?date=2026-09-28")).json();
  data.boards[0].entries[0].seasons = ["2025-26", "2026-27"];
  data.coverage.partial = true;
  data.coverage.skipped_players = 1;
  await page.route("**/api/streaks?*", (r) =>
    r.fulfill({
      json: {
        ...data,
        scope: new URL(r.request().url()).searchParams.get("scope"),
      },
    }),
  );
  await page.goto("/streaks?date=2026-09-28");
  await expect(
    page.getByText("Across seasons", { exact: true }).first(),
  ).toBeVisible();
  await expect(page.getByText(/Partial leaderboard coverage/)).toBeVisible();
  data.boards.forEach((b: { entries: unknown[] }) => (b.entries = []));
  await page.getByRole("button", { name: "League-wide", exact: true }).click();
  await page.getByRole("button", { name: "On slate", exact: true }).click();
  await expect(page.getByText("No qualifying results.").first()).toBeVisible();
  await page.route("**/api/streaks?*", (r) =>
    r.fulfill({ status: 503, json: { detail: "Provider unavailable" } }),
  );
  await page
    .getByRole("button", { name: "Refresh streaks", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Streaks unavailable" }),
  ).toBeVisible();
});
