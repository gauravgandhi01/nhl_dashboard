import { test, expect } from "@playwright/test";
import { formatDate, formatTimestamp } from "../../src/dates";

test("date displays preserve calendar dates and timestamp Eastern time", () => {
  expect(formatDate("2026-01-02")).toBe("01/02");
  expect(formatDate("2028-02-29")).toBe("02/29");
  expect(formatDate("2026-12-31")).toBe("12/31");
  expect(formatDate("--")).toBe("--");
  expect(formatTimestamp("2027-01-01T00:30:00Z")).toMatch(/^12\/31,? (at )?7:30 PM ET$/);
  expect(formatTimestamp("2026-07-01T00:30:00Z")).toMatch(/^06\/30,? (at )?8:30 PM ET$/);
  expect(formatTimestamp(null, "Not loaded")).toBe("Not loaded");
  expect(formatTimestamp("invalid", "Unavailable")).toBe("Unavailable");
});

for (const width of [1440, 375]) {
  test(`shared date control displays MM/DD and preserves the selected year at ${width}px`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.route("**/api/**", route => route.fulfill({ json: {
      date: "2099-12-31", error: "Fixture unavailable", games: [], players: [], goalies: [],
      prices: {}, sources: [], periods: [], configured: false,
    } }));
    await page.setViewportSize({ width, height: 900 });
    for (const path of ["/", "/players", "/goalies", "/first-period", "/streaks", "/stanley-cup"]) {
      await page.goto(`${path}?date=2099-12-31`);
      const input = page.getByLabel("Game date", { exact: true });
      await expect(page.locator(".date-display")).toHaveText("12/31");
      await expect(input).toHaveValue("2099-12-31");
      await page.getByRole("button", { name: "Next day", exact: true }).click();
      await expect(page.locator(".date-display")).toHaveText("01/01");
      await expect(input).toHaveValue("2100-01-01");
      await expect(page).toHaveURL(/date=2100-01-01/);
      await input.fill("2100-02-03");
      await expect(page.locator(".date-display")).toHaveText("02/03");
      await expect(page).toHaveURL(/date=2100-02-03/);
      await expect(input).toBeFocused();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    }
    await page.getByLabel("Game date", { exact: true }).click();
    await page.keyboard.press("Escape");
    await page.screenshot({ path: `test-results/date-control-${width}.png` });
    expect(errors).toEqual([]);
  });
}
