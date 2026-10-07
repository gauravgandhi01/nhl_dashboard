import type { Stats } from "./types";

type Window = "last5" | "last10" | "season";
type Profile = { id: number; position: string; season_label: string; windows: Record<Window, Stats> };
export type Peers = Map<string, number[]>;
const totals = new Set(["goals", "assists", "points", "powerPlayPoints"]);
const advanced = new Set(["attempts_pg", "attempts60", "shots60", "points60", "ixg60", "hd60"]);
const metrics = [...totals, ...advanced, "points_pg", "shots_pg", "toi_pg", "point_games_pct"];
const group = (p: Profile, key: string) => `${p.season_label}:${p.position === "D" ? "D" : "F"}:${key}`;

export function buildPeers(players: Profile[]): Peers {
  const peers: Peers = new Map();
  // Split-squad games may list one player twice; filters must not change benchmarks.
  const unique = new Map(players.map(p => [`${p.season_label}:${p.id}`, p]));
  for (const p of unique.values()) {
    const s = p.windows.season;
    if ((s.games ?? 0) < 5) continue;
    for (const key of metrics) {
      const value = s[key];
      if (value == null || (advanced.has(key) && (s.advanced_games ?? 0) < 5)) continue;
      const id = group(p, key);
      const values = peers.get(id) || [];
      values.push(value);
      peers.set(id, values);
    }
  }
  return peers;
}

export function cellFormat(p: Profile, window: Window, key: string, peers: Peers, peerLabel = "nightly") {
  const s = p.windows[window], base = p.windows.season, value = s[key];
  const neutral = { className: "", title: "" };
  if (value == null) return neutral;
  if (key === "games") return value < 5
    ? { className: "sample-warning", title: `Small sample: ${value} appearances` } : neutral;
  if (key === "advanced_games") return {
    className: value < (s.games ?? 0) || value < 5 ? "sample-warning" : "muted",
    title: `MoneyPuck coverage: ${value}/${s.games ?? "unknown"} appearances; ${s.advanced_minutes?.toFixed(1) ?? "unknown"} minutes`,
  };
  if (!metrics.includes(key)) return neutral;
  if ((s.games ?? 0) < (window === "season" ? 5 : 3) || (advanced.has(key) && (s.advanced_games ?? 0) < (window === "season" ? 5 : 3)))
    return { ...neutral, title: "Sample too small for performance coloring" };
  if (window === "season") {
    const values = peers.get(group(p, key)) || [];
    if (values.length < 5) return neutral;
    const rank = (values.filter(v => v < value).length + values.filter(v => v === value).length / 2) / values.length;
    return {
      className: rank >= .9 ? "form-up form-strong" : rank >= .75 ? "form-up" : rank <= .1 ? "form-down form-strong" : rank <= .25 ? "form-down" : "",
      title: `${Math.round(rank * 100)}th percentile among ${values.length} ${peerLabel} ${p.position === "D" ? "defensemen" : "forwards"} with 5+ ${advanced.has(key) ? "MoneyPuck " : ""}GP; higher value, not overall player quality`,
    };
  }
  const baseline = base[key];
  if (baseline == null || (base.games ?? 0) < 5 || (advanced.has(key) && (base.advanced_games ?? 0) < 5)) return neutral;
  const current = totals.has(key) ? value / s.games! : value;
  const reference = totals.has(key) ? baseline / base.games! : baseline;
  const change = reference ? (current - reference) / reference : current > 0 ? 1 : 0;
  return {
    className: Math.abs(change) < .1 ? "" : `${change > 0 ? "form-up" : "form-down"}${Math.abs(change) >= .25 ? " form-strong" : ""}`,
    title: `${totals.has(key) ? "Per-game pace" : "Rate"}: ${current.toFixed(2)} vs season ${reference.toFixed(2)}${reference ? ` (${change >= 0 ? "+" : ""}${Math.round(change * 100)}%)` : ""}${key === "toi_pg" ? " seconds/game" : ""}`,
  };
}

type GoalieProfile = { id: number; season_label: string; windows: Record<Window, Stats> };
const goalieMetrics = ["sv", "gaa", "gsax"];
const goalieAdvanced = new Set(["gsax"]);
const goalieLower = new Set(["gaa"]);
const goalieGroup = (p: GoalieProfile, key: string) => `${p.season_label}:${key}`;

export function buildGoaliePeers(goalies: GoalieProfile[]): Peers {
  const peers: Peers = new Map();
  const unique = new Map(goalies.map((g) => [`${g.season_label}:${g.id}`, g]));
  for (const g of unique.values()) {
    const s = g.windows.season;
    if ((s.games ?? 0) < 5) continue;
    for (const key of goalieMetrics) {
      const value = s[key];
      if (value == null || (goalieAdvanced.has(key) && (s.advanced_games ?? 0) < 5)) continue;
      const id = goalieGroup(g, key);
      const values = peers.get(id) || [];
      values.push(value);
      peers.set(id, values);
    }
  }
  return peers;
}

export function goalieCellFormat(p: GoalieProfile, window: Window, key: string, peers: Peers) {
  const s = p.windows[window], base = p.windows.season, value = s[key];
  const neutral = { className: "", title: "" };
  if (value == null) return neutral;
  if (key === "games") return value < 5
    ? { className: "sample-warning", title: `Small sample: ${value} appearances` } : neutral;
  if (!goalieMetrics.includes(key)) return neutral;
  const lower = goalieLower.has(key);
  if ((s.games ?? 0) < (window === "season" ? 5 : 3) || (goalieAdvanced.has(key) && (s.advanced_games ?? 0) < (window === "season" ? 5 : 3)))
    return { ...neutral, title: "Sample too small for performance coloring" };
  if (window === "season") {
    const values = peers.get(goalieGroup(p, key)) || [];
    if (values.length < 5) return neutral;
    const better = lower
      ? values.filter((v) => v > value).length
      : values.filter((v) => v < value).length;
    const rank = (better + values.filter((v) => v === value).length / 2) / values.length;
    return {
      className: rank >= .9 ? "form-up form-strong" : rank >= .75 ? "form-up" : rank <= .1 ? "form-down form-strong" : rank <= .25 ? "form-down" : "",
      title: `${Math.round(rank * 100)}th percentile among ${values.length} goalies with 5+ ${goalieAdvanced.has(key) ? "MoneyPuck " : ""}GP; ${lower ? "lower" : "higher"} value, not overall player quality`,
    };
  }
  const baseline = base[key];
  if (baseline == null || (base.games ?? 0) < 5 || (goalieAdvanced.has(key) && (base.advanced_games ?? 0) < 5)) return neutral;
  const raw = baseline ? (value - baseline) / baseline : value > 0 ? 1 : value < 0 ? -1 : 0;
  const change = lower ? -raw : raw;
  return {
    className: Math.abs(change) < .1 ? "" : `${change > 0 ? "form-up" : "form-down"}${Math.abs(change) >= .25 ? " form-strong" : ""}`,
    title: `Rate: ${value.toFixed(2)} vs season ${baseline.toFixed(2)}${baseline ? ` (${raw >= 0 ? "+" : ""}${Math.round(raw * 100)}%)` : ""}`,
  };
}
