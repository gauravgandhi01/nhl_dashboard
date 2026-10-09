import { test, expect } from "@playwright/test";

test("matchup cards show numeric comparisons without bars and leave missing values neutral", async ({ page }) => {
  const date = "2026-09-29";
  const team = (abbrev: string) => ({ id: 1, abbrev, name: abbrev, logo: `https://assets.nhle.com/logos/nhl/svg/${abbrev}_light.svg`, score: null, starter: { name: null, status: "Unconfirmed" } });
  const game = { id: 2026020002, date, start: "2099-09-29T23:00:00Z", state: "FUT", schedule_state: "OK", game_type: 2, away: team("MTL"), home: team("TOR") };
  const side = (home: boolean) => ({
    summary: { gf: home ? 4 : 2, ga: home ? 3 : 2, sf: 30, pp: home ? 25 : null },
    advanced: { xgf_pct: 0 }, form: [],
    ranks: Object.fromEntries(["gf", "ga", "sf", "pp", "xgf_pct"].map(key => [key,
      { rank: key === "pp" && !home ? null : home ? 16 : 30, eligible: 32 }])),
    goalie: {
      name: home ? "Home Goalie" : "Away Goalie", basis: "Likely", advanced_games: 20,
      stats: { games: 20, sv: home ? .930 : .900, gaa: home ? 2.1 : 3.2, gsax: home ? 1 : 9 },
      ranks: {
        sv: { rank: home ? 40 : 5, eligible: 60 },
        gaa: { rank: home ? 45 : 8, eligible: 60 },
        gsax: home ? { rank: 6, eligible: 60 } : { rank: null, eligible: 60 },
      },
    },
  });
  await page.route("**/api/**", route => route.fulfill({ json: route.request().url().includes("/api/slate?")
    ? { date, games: [game], comparisons: { [game.id]: { season_label: "2025-26", away: side(false), home: side(true) } }, sources: [], error: null }
    : { date, status: "available", configured: true, prices: {}, error: null } }));
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto(`/?date=${date}`);
    const card = page.locator(".game-card");
    await expect(card).toBeVisible();
    const row = (label: string) => card.locator(".card-metric").filter({ has: page.getByText(label, { exact: true }) });
    await expect(card.locator(".metric-track, .card-metric-bars")).toHaveCount(0);
    await expect(row("Goals for / G").locator("strong").nth(1)).toHaveClass(/rank-average/);
    await expect(row("Goals for / G").locator("strong").nth(1)).toHaveText("4.00");
    await expect(row("Goals against / G").locator("strong").nth(0)).toHaveClass(/rank-bad/);
    await expect(row("Goals against / G").locator("strong").nth(0)).toHaveText("2.00");
    await expect(row("Goals for / G").locator(".better, .worse")).toHaveCount(0);
    await expect(row("Shots / G").locator(".better, .worse")).toHaveCount(0);
    await expect(row("Shots / G").locator(".league-rank")).toHaveText([/^#?30$/, /^#?16$/]);
    await expect(row("Power play").locator(".league-rank").first()).toHaveText("—");
    await expect(row("Shots / G").locator(".league-rank").first()).toHaveAttribute("title", /all 32 NHL teams considered/);
    const positions = await row("Shots / G").locator(":scope > *").evaluateAll(elements =>
      elements.map(element => ({ left: element.getBoundingClientRect().left, right: element.getBoundingClientRect().right })));
    expect(positions).toHaveLength(5);
    for (let i = 1; i < positions.length; i++) expect(positions[i].left).toBeGreaterThanOrEqual(positions[i - 1].right);
    await expect(row("Power play").locator(".better, .worse")).toHaveCount(0);
    const save = row("Save %");
    await expect(save.locator("strong").nth(0)).toHaveClass(/rank-elite/);
    await expect(save.locator("strong").nth(0)).toHaveText("0.900");
    await expect(save.locator("strong").nth(1)).toHaveClass(/rank-poor/);
    await expect(save.locator("strong").nth(1)).toHaveText("0.930");
    await expect(save.locator(".better, .worse")).toHaveCount(0);
    await expect(save.locator(".league-rank")).toHaveText(["5", "40"]);
    await expect(save.locator(".league-rank").first()).toHaveAttribute("title", /every goalie with playing time/);
    await expect(row("GAA").locator("strong").nth(0)).toHaveClass(/rank-elite/);
    await expect(row("GAA").locator("strong").nth(1)).toHaveClass(/rank-poor/);
    await expect(row("GAA").locator(".better, .worse")).toHaveCount(0);
    await expect(row("GSAx").locator("strong").nth(0)).not.toHaveClass(/rank-|better|worse/);
    await expect(row("GSAx").locator(".league-rank").first()).toHaveText("—");
    await expect(row("GSAx").locator("strong").nth(1)).toHaveClass(/rank-elite/);
    await expect(row("Appearances").locator(".league-rank, .better, .worse, .rank-elite")).toHaveCount(0);
    const goaliePositions = await save.locator(":scope > *").evaluateAll(elements =>
      elements.map(element => ({ left: element.getBoundingClientRect().left, right: element.getBoundingClientRect().right })));
    expect(goaliePositions).toHaveLength(5);
    for (let i = 1; i < goaliePositions.length; i++) expect(goaliePositions[i].left).toBeGreaterThanOrEqual(goaliePositions[i - 1].right);
    await expect(page.getByText("Goals for / G", { exact: true })).toHaveAttribute("title", "Higher is better");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const before = await row("Goals for / G").boundingBox();
    await card.hover();
    expect((await row("Goals for / G").boundingBox())?.height).toBe(before?.height);
    await card.focus();
    await expect(card).toBeFocused();
    await page.screenshot({ path: `test-results/card-comparisons-${width}.png`, fullPage: true });
  }
});

test("L5 form mirrors both timelines outward from the matchup center", async ({ page }) => {
  const date = "2026-10-09";
  const form = ["BOS", "MTL", "TOR", "NYR", "NJD"].map((opponent, index) => ({
    date: `2026-10-0${index + 1}`, opponent, home: index % 2 === 0,
    result: index === 2 ? "OTL" : index % 2 === 0 ? "W" : "L",
    goals_for: index % 2 === 0 && index !== 2 ? 3 : 0,
    goals_against: index % 2 === 0 && index !== 2 ? 0 : 3,
  }));
  const team = (abbrev: string) => ({ id: abbrev === "COL" ? 1 : 2, abbrev, name: abbrev, logo: "", score: null, starter: { name: null, status: "Unconfirmed" } });
  const games = [5, 2, 1, 0].map((count, index) => ({
    id: 2026020001 + index, date, start: "2099-10-09T23:00:00Z", state: "FUT", schedule_state: "OK", game_type: 2,
    away: team("COL"), home: team("DAL"), count,
  }));
  const side = (count: number, name: string) => ({ summary: {}, advanced: {},
    form: count ? form.slice(-count).map((game, index) => ({ ...game, starting_goalie: index === 0 ? null : name })) : [],
    goalie: { name: "Goalie", basis: "Likely", advanced_games: 0, stats: {} } });
  await page.route("**/api/**", route => route.fulfill({ json: route.request().url().includes("/api/slate?")
    ? { date, games, comparisons: Object.fromEntries(games.map(game => [game.id, { season_label: "2026-27", away: side(game.count, "Away Starter"), home: side(game.count, "Home Starter") }])), sources: [], error: null }
    : { date, configured: false, prices: {}, error: null } }));
  for (const width of [1440, 375, 320]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto(`/?date=${date}`);
    for (const [index, count] of [5, 2, 1, 0].entries()) {
      const card = page.locator(".game-card").nth(index);
      await expect(card).toBeVisible();
      const away = card.locator(".card-form.away");
      const home = card.locator(".card-form.home");
      const sample = count ? form.slice(-count) : [];
      await expect(away.locator("small")).toHaveText(sample.map(g => `${g.home ? "" : "@"}${g.opponent}`));
      await expect(home.locator("small")).toHaveText([...sample].reverse().map(g => `${g.home ? "" : "@"}${g.opponent}`));
      if (!count) {
        await expect(card.locator(".form-recent")).toHaveCount(0);
        await expect(away).toHaveText("--");
        await expect(home).toHaveText("--");
        continue;
      }
      await expect(away.locator("span").last()).toHaveClass(/form-recent/);
      await expect(home.locator("span").first()).toHaveClass(/form-recent/);
      await away.locator("span").last().hover();
      await expect(away.locator("span").last()).toHaveAttribute("title", count > 1 ? /Starting goalie: Away Starter/ : /Starter unavailable/);
      await home.locator("span").first().hover();
      await expect(home.locator("span").first()).toHaveAttribute("title", count > 1 ? /Starting goalie: Home Starter/ : /Starter unavailable/);
      await expect(away.locator("span").first()).toHaveAttribute("title", /Starter unavailable/);
      await expect(away.locator("span").last()).toHaveAttribute("title", /^10\/05 vs NJD: W\. Most recent\nFinal: 3–0\n/);
      await expect(home.locator("span").first()).toHaveAttribute("title", /^10\/05 vs NJD: W\. Most recent\nFinal: 3–0\n/);
      if (count > 1) await expect(away.locator("span").nth(count - 2)).toHaveAttribute("title", /^10\/04 at NYR: L\nFinal: 0–3\n/);
      for (const strip of [away, home]) {
        const cells = await strip.locator(":scope > span").evaluateAll(elements => elements.map(el => ({
          top: el.getBoundingClientRect().top, left: el.getBoundingClientRect().left,
          opacity: Number(getComputedStyle(el).opacity),
          fits: el.scrollWidth <= el.clientWidth,
        })));
        expect(cells.filter(cell => cell.top !== cells[0].top || !cell.fits)).toEqual([]);
        for (let i = 1; i < cells.length; i++) expect(cells[i].left).toBeGreaterThan(cells[i - 1].left);
        const opacity = cells.map(cell => cell.opacity);
        expect(opacity).toEqual([...opacity].sort((a, b) => strip === away ? a - b : b - a));
      }
      const awayEdge = (await away.boundingBox())!;
      const homeEdge = (await home.boundingBox())!;
      const awayNewest = (await away.locator(".form-recent").boundingBox())!;
      const homeNewest = (await home.locator(".form-recent").boundingBox())!;
      expect(Math.abs(awayNewest.x + awayNewest.width - awayEdge.x - awayEdge.width)).toBeLessThan(1);
      expect(Math.abs(homeNewest.x - homeEdge.x)).toBeLessThan(1);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `test-results/card-form-${width}.png`, fullPage: true });
  }
});
