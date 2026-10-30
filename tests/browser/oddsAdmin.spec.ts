import { test, expect } from "@playwright/test";

test("hidden odds trigger authenticates, reports budget, and forgets its token", async ({ page }) => {
  const calls: string[] = [];
  await page.route("**/api/admin/odds/**", async route => {
    expect(route.request().headers()["authorization"]).toBe("Bearer TEST_ADMIN_TOKEN");
    const url = new URL(route.request().url());
    calls.push(url.pathname);
    const budget = { key_count: 54, known_keys: 54, remaining: 26000, spent_today: 100, daily_budget: 783 };
    if (url.pathname.endsWith("refresh")) {
      expect(route.request().method()).toBe("POST");
      expect(url.searchParams.get("date")).toBe("2026-10-30");
      expect(url.searchParams.get("feed")).toBe("props");
      await route.fulfill({ json: { props: { games: {} }, budget } });
    } else await route.fulfill({ json: budget });
  });
  await page.goto("/not-a-page?date=2026-10-30");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(calls).toHaveLength(0);
  await page.keyboard.press("Alt+Shift+KeyO");
  const dialog = page.getByRole("dialog", { name: "Odds refresh" });
  await expect(dialog).toBeVisible();
  expect(calls).toHaveLength(0);
  await dialog.getByLabel("Admin token").fill("TEST_ADMIN_TOKEN");
  await dialog.getByRole("button", { name: "Check budget" }).click();
  await expect(dialog).toContainText("54/54 keys checked");
  await dialog.getByLabel("Feed", { exact: true }).selectOption("props");
  await dialog.getByRole("button", { name: "Refresh odds", exact: true }).click();
  await expect(dialog.getByRole("status")).toContainText("Refresh checked");
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await page.keyboard.press("Alt+Shift+KeyO");
  await expect(page.getByLabel("Admin token")).toHaveValue("");
  expect(await page.evaluate(() => JSON.stringify([localStorage, sessionStorage]))).not.toContain("TEST_ADMIN_TOKEN");
});
