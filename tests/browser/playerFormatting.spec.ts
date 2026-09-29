import { test, expect } from "@playwright/test";
import { buildPeers, cellFormat } from "../../src/playerFormatting";

const player = (id: number) => ({ id, position: "C", season_label: "2025-26", windows: {
  season: { games: 80, points: id * 8, points_pg: id / 10, attempts_pg: id, attempts60: id, advanced_games: 80 },
  last5: { games: 5, points: id, points_pg: id / 5, attempts_pg: id * 2, attempts60: id * 2, advanced_games: 5 },
  last10: { games: 10, points: id, points_pg: id / 10, attempts_pg: id, attempts60: id, advanced_games: 10 },
} });

test("season colors rank deduplicated position peers; ties and missing values stay neutral", () => {
  const players = Array.from({ length: 10 }, (_, i) => player(i + 1));
  const peers = buildPeers([...players, players[9]]);
  expect(cellFormat(players[9], 'season', 'points', peers).className).toBe('form-up form-strong');
  expect(cellFormat(players[0], 'season', 'attempts_pg', peers).className).toBe('form-down form-strong');
  expect(cellFormat(players[4], 'season', 'points', peers).className).toBe('');
  expect(cellFormat(players[9], 'season', 'points', peers).title).toContain('10 nightly forwards');
  expect(cellFormat({...players[9], position: 'D'}, 'season', 'points', peers).className).toBe('');
  expect(cellFormat(players[9], 'season', 'ixg60', peers).className).toBe('');
  const tied = players.map(p => ({...p, windows: player(2).windows}));
  expect(cellFormat(tied[0], 'season', 'points', buildPeers(tied)).className).toBe('');
});

test("recent totals compare per-game pace, advanced rates compare season, small samples warn", () => {
  const p = player(10), peers = buildPeers([p]);
  expect(cellFormat(p, 'last5', 'points', peers).className).toBe('form-up form-strong');
  expect(cellFormat(p, 'last10', 'points', peers).className).toBe('');
  expect(cellFormat(p, 'last5', 'attempts_pg', peers).className).toBe('form-up form-strong');
  p.windows.last5.advanced_games = 1;
  expect(cellFormat(p, 'last5', 'attempts_pg', peers).className).toBe('');
  expect(cellFormat(p, 'last5', 'advanced_games', peers).className).toBe('sample-warning');
  p.windows.last5.games = 1;
  expect(cellFormat(p, 'last5', 'points', peers).className).toBe('');
});
