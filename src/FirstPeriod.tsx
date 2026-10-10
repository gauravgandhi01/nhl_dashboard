import { RefreshButton } from "./RefreshButton";
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  ArrowRight,
  RefreshCw,
  ArrowDown,
  ArrowUp,
} from "lucide-react";
import type { Game, Source, Stats, Starter, Team } from "./types";
import { todayEt, formatDate, formatTimestamp } from "./dates";

type Window = "season" | "last5" | "last10";
type Windows = Record<Window, Stats>;
type MetricRank = { rank: number | null; eligible: number };
type GoalieRanks = Record<Window, { ga_pg: MetricRank; sv: MetricRank; allow_pct: MetricRank }>;
type Goalie = {
  id: number;
  name: string;
  windows: Windows;
  rank: GoalieRanks | null;
};
type Side = {
  team: Team;
  windows: Windows;
  starter: Starter;
  goalies: Goalie[];
  selected_goalie: number | null;
  goalie_basis: string;
};
type Meeting = {
  gameId: number;
  date: string;
  away: { abbrev: string; gf: number };
  home: { abbrev: string; gf: number };
};
type Matchup = {
  game: Game;
  away: Side;
  home: Side;
  h2h: { recent: Meeting[]; summary: Stats };
};
type Data = {
  date: string;
  season_label: string;
  previous_season: boolean;
  as_of: string;
  matchups: Matchup[];
  rankings: {
    id: number;
    name: string;
    abbrev: string;
    rank: number;
    windows: Windows;
    playing: boolean;
  }[];
  goalie_rankings: {
    id: number;
    name: string;
    abbrev: string;
    windows: Windows;
    rank: GoalieRanks;
    playing: boolean;
  }[];
  league_goalies: Windows;
  coverage: {
    games: number;
    goalie_games: number;
    incomplete_games: number;
    stale_games: number;
    rejected_team_games: number;
  };
  build: { status: string; done: number; total: number; error: string | null };
  sources: Source[];
  error: string | null;
  stats_error: string | null;
};
type Price = {
  total: number;
  over: number;
  under: number;
  updated_at: string | null;
};
type Odds = {
  prices: Record<string, Price>;
  status: string;
  configured: boolean;
  manual_refresh_enabled?: boolean;
  retrieved_at: string | null;
  error: string | null;
  source: string;
};
const windows: [Window, string][] = [
  ["season", "Season"],
  ["last5", "Last 5"],
  ["last10", "Last 10"],
];
const today = todayEt;
const f = (value: number | null | undefined, digits = 2) =>
  value == null ? "--" : value.toFixed(digits);
const pct = (value: number | null | undefined) =>
  value == null ? "--" : `${value.toFixed(1)}%`;
const money = (value: number) => `${value > 0 ? "+" : ""}${value}`;
const oddsNotConfigured =
  "Odds not configured: add api_keys to the workspace keys.json file.";
const oddsMessage = (odds: Odds | null, error: string | null) => {
  if (error || odds?.error) return error || odds?.error;
  if (!odds) return null;
  if (odds.status === "not_configured") return oddsNotConfigured;
  if (odds.status === "stale") return "Odds cached";
  return null;
};
const timestamp = (value: string | null) => formatTimestamp(value, "Unavailable");
const selected = (s: Side) => s.goalies.find((g) => g.id === s.selected_goalie);
const GOALIE_RATE_KEYS = ["ga_pg", "sv", "allow_pct"] as const;
type GoalieRate = (typeof GOALIE_RATE_KEYS)[number];
const leagueRankClass = (rank: number | null | undefined, eligible?: number) => {
  if (rank == null) return "";
  const size = eligible ?? 32;
  if (!size) return "";
  const percentile = rank / size;
  if (percentile <= 0.2) return "rank-elite";
  if (percentile <= 0.4) return "rank-good";
  if (percentile <= 0.6) return "rank-average";
  if (percentile <= 0.8) return "rank-poor";
  return "rank-bad";
};
const goalieRateHelp = (key: string) =>
  key === "sv" ? "Higher save percentage is better." : "Lower is better.";
const goalieStatusIcon = (status: string | null | undefined) =>
  status === "Confirmed" ? "✅" : status === "Likely" ? "⚠️" : "⛔️";
const lastName = (name: string | null | undefined) => {
  const parts = (name || "").trim().split(/\s+/).filter(Boolean);
  return parts.length ? parts[parts.length - 1] : "Unavailable";
};

function usePeriod(url: string) {
  const [data, setData] = useState<Data | null>(null),
    [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true,
      pending = false,
      running = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    setData(null);
    setError(null);
    const load = async () => {
      if (!active || running) return;
      running = true;
      setBusy(true);
      try {
        const r = await fetch(url, { signal: controller.signal });
        const body = await r.json();
        if (!r.ok)
          throw new Error(body.detail || "First-period data unavailable");
        if (active) {
          setData(body);
          setError(null);
          pending = body.build?.status === "building";
        }
      } catch (e) {
        if (active) {
          setError(e instanceof Error ? e.message : "Data unavailable");
          pending = false;
        }
      } finally {
        running = false;
        if (active) {
          setBusy(false);
          if (pending && !document.hidden) timer = setTimeout(load, 3000);
        }
      }
    };
    const visibility = () => {
      clearTimeout(timer);
      if (!document.hidden && pending) void load();
    };
    document.addEventListener("visibilitychange", visibility);
    void load();
    return () => {
      active = false;
      controller.abort();
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [url, revision]);
  return { data, error, busy, refresh: () => setRevision((n) => n + 1) };
}

function useOdds(date: string) {
  const [odds, setOdds] = useState<Odds | null>(null),
    [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setOdds(null);
    setError(null);
    setBusy(false);
    fetch(`/api/first-period/odds?date=${date}`, { signal: controller.signal })
      .then((r) => {
        if (!r.ok) throw new Error("Cached odds unavailable");
        return r.json();
      })
      .then((d) => {
        if (!controller.signal.aborted) setOdds(d);
      })
      .catch(() => {
        if (!controller.signal.aborted) setError("Cached odds unavailable");
      });
    return () => controller.abort();
  }, [date]);
  const load = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await fetch(`/api/first-period/odds/refresh?date=${date}`, {
        method: "POST",
      });
      if (!r.ok) throw new Error("Odds unavailable");
      setOdds(await r.json());
    } catch {
      setError("Odds unavailable");
    } finally {
      setBusy(false);
    }
  };
  return { odds, busy, error, load };
}

function Logo({ team }: { team: Team }) {
  return (
    <img
      className="logo"
      src={
        team.logo ||
        `https://assets.nhle.com/logos/nhl/svg/${team.abbrev}_light.svg`
      }
      alt=""
    />
  );
}
function Status({ game }: { game: Game }) {
  if (game.schedule_state === "PPD")
    return <span className="warning">Postponed</span>;
  if (game.schedule_state === "CNCL")
    return <span className="warning">Canceled</span>;
  return (
    <span>
      {new Date(game.start).toLocaleTimeString("en-US", {
        timeZone: "America/New_York",
        hour: "numeric",
        minute: "2-digit",
      })}{" "}
      ET
    </span>
  );
}
function PriceLine({ price }: { price?: Price }) {
  return (
    <div
      className="fp-price"
      title={
        price
          ? `FanDuel updated ${timestamp(price.updated_at)}`
          : "No matching FanDuel first-period market"
      }
    >
      <span>FanDuel 1P</span>
      {price ? (
        <>
          <strong>{price.total}</strong>
          <span>O {money(price.over)}</span>
          <span>U {money(price.under)}</span>
        </>
      ) : (
        <span>Unavailable</span>
      )}
    </div>
  );
}
function ComparisonRow({
  label,
  a,
  h,
  awayRank,
  homeRank,
  awayEligible,
  homeEligible,
  rankTitle = "League rank",
  percent = false,
  digits = 2,
  risk = false,
  neutral = false,
  ranked = false,
}: {
  label: string;
  a: number | null | undefined;
  h: number | null | undefined;
  awayRank?: number;
  homeRank?: number;
  awayEligible?: number;
  homeEligible?: number;
  rankTitle?: string;
  percent?: boolean;
  digits?: number;
  risk?: boolean;
  neutral?: boolean;
  ranked?: boolean;
}) {
  const leagueMode = ranked || awayRank != null || homeRank != null;
  const awayRankClass = leagueRankClass(awayRank, ranked ? awayEligible : undefined);
  const homeRankClass = leagueRankClass(homeRank, ranked ? homeEligible : undefined);
  const style = (v: typeof a, other: typeof a) =>
    neutral && label.includes("GP") && v != null && v < 5
      ? "warning"
      : neutral || v == null || other == null || v === other
        ? ""
        : v > other
          ? risk
            ? "warning"
            : "better"
          : risk
            ? ""
            : "worse";
  const awayClass = leagueMode ? awayRankClass : style(a, h);
  const homeClass = leagueMode ? homeRankClass : style(h, a);
  const badgeTitle = (rank?: number, eligible?: number) =>
    rank != null
      ? `League rank ${rank} of ${eligible ?? "—"}. ${rankTitle}`
      : rankTitle;
  return (
    <div className={`card-metric${leagueMode ? " card-metric-ranked fp-rank-row" : ""}`}>
      <strong className={awayClass}>{percent ? pct(a) : f(a, digits)}</strong>
      {leagueMode && <span className={`league-rank ${awayRankClass}`} title={badgeTitle(awayRank, awayEligible)}>{awayRank ?? "—"}</span>}
      <span
        title={
          ranked
            ? rankTitle
            : risk
              ? "Higher goals allowed, not better performance"
              : neutral
                ? label
                : leagueMode
                  ? "League-rank based conditional formatting"
                  : "Higher/lower than the opposing comparison value"
        }
      >
        {label}
      </span>
      {leagueMode && <span className={`league-rank ${homeRankClass}`} title={badgeTitle(homeRank, homeEligible)}>{homeRank ?? "—"}</span>}
      <strong className={homeClass}>{percent ? pct(h) : f(h, digits)}</strong>
    </div>
  );
}
function PeriodCard({
  m,
  window,
  date,
  odds,
  ranks,
}: {
  m: Matchup;
  window: Window;
  date: string;
  odds: Odds | null;
  ranks: Record<string, Map<number, number>>;
}) {
  const a = m.away.windows[window],
    h = m.home.windows[window];
  const awayGoalie = selected(m.away),
    homeGoalie = selected(m.home);
  const ag = awayGoalie?.windows[window],
    hg = homeGoalie?.windows[window];
  const goalieRank = (goalie: Goalie | undefined, metric: GoalieRate) =>
    goalie?.rank?.[window]?.[metric];
  const awayRates = {
    ga_pg: goalieRank(awayGoalie, "ga_pg"),
    sv: goalieRank(awayGoalie, "sv"),
    allow_pct: goalieRank(awayGoalie, "allow_pct"),
  };
  const homeRates = {
    ga_pg: goalieRank(homeGoalie, "ga_pg"),
    sv: goalieRank(homeGoalie, "sv"),
    allow_pct: goalieRank(homeGoalie, "allow_pct"),
  };
  return (
    <Link
      className="game-card fp-card"
      to={`/first-period/matchups/${m.game.id}?date=${date}&window=${window}`}
    >
      <div className="game-time">
        <Status game={m.game} />
        <ArrowRight size={14} />
      </div>
      <div>
        <div className="card-matchup">
          <div>
            <Logo team={m.game.away} />
            <strong>{m.game.away.abbrev}</strong>
          </div>
          <span className="eyebrow">FIRST PERIOD</span>
          <div>
            <Logo team={m.game.home} />
            <strong>{m.game.home.abbrev}</strong>
          </div>
        </div>
        <ComparisonRow
          label="1P goals for / G"
          a={a.gf_pg}
          h={h.gf_pg}
          awayRank={ranks.gf_pg.get(m.game.away.id)}
          homeRank={ranks.gf_pg.get(m.game.home.id)}
          rankTitle="League rank by first-period goals for per game"
        />
        <ComparisonRow
          label="1P goals against / G"
          a={a.ga_pg}
          h={h.ga_pg}
          awayRank={ranks.ga_pg.get(m.game.away.id)}
          homeRank={ranks.ga_pg.get(m.game.home.id)}
          rankTitle="League rank by first-period goals against per game; lower is better"
          risk
        />
        <ComparisonRow
          label="Combined goals / G"
          a={a.combined_pg}
          h={h.combined_pg}
          awayRank={ranks.combined_pg.get(m.game.away.id)}
          homeRank={ranks.combined_pg.get(m.game.home.id)}
          rankTitle="League rank by combined first-period goals per game"
        />
        <ComparisonRow
          label="2+ goal games"
          a={a.hits}
          h={h.hits}
          awayRank={ranks.hits.get(m.game.away.id)}
          homeRank={ranks.hits.get(m.game.home.id)}
          rankTitle="League rank by first-period 2+ goal game count"
          digits={0}
        />
        <ComparisonRow
          label="2+ goal frequency"
          a={a.hit_pct}
          h={h.hit_pct}
          awayRank={ranks.hit_pct.get(m.game.away.id)}
          homeRank={ranks.hit_pct.get(m.game.home.id)}
          rankTitle="League rank by first-period 2+ goal frequency"
          percent
        />
        <div className="card-goalie-names">
          {[m.away, m.home].map((s, i) => {
            const name = s.starter.name || selected(s)?.name || "Unavailable";
            const status = s.starter.name ? s.starter.status : s.goalie_basis;
            return (
              <div key={s.team.id} className={i === 0 ? "away" : "home"}>
                {i === 0 && <strong title={name}>{lastName(name)}</strong>}
                <span
                  className="goalie-status-icon"
                  title={
                    status === "Roster leader"
                      ? "Most-used goalie on the current roster during the displayed season. Not a projected starter."
                      : `Reported starter status: ${status || "Unknown"}`
                  }
                  aria-label={status || "Unknown"}
                >
                  {goalieStatusIcon(status)}
                </span>
                {i === 1 && <strong title={name}>{lastName(name)}</strong>}
              </div>
            );
          })}
        </div>
        <ComparisonRow
          label="GP"
          a={ag?.games}
          h={hg?.games}
          digits={0}
          neutral
        />
        <ComparisonRow
          label="1P GA / appearance"
          a={ag?.ga_pg}
          h={hg?.ga_pg}
          awayRank={awayRates.ga_pg?.rank ?? undefined}
          homeRank={homeRates.ga_pg?.rank ?? undefined}
          awayEligible={awayRates.ga_pg?.eligible}
          homeEligible={homeRates.ga_pg?.eligible}
          ranked
          rankTitle="League rank by first-period goals against per appearance among goalies with 1+ GP. Lower is better. Ties share a rank."
        />
        <ComparisonRow
          label="1P save %"
          a={ag?.sv}
          h={hg?.sv}
          digits={3}
          awayRank={awayRates.sv?.rank ?? undefined}
          homeRank={homeRates.sv?.rank ?? undefined}
          awayEligible={awayRates.sv?.eligible}
          homeEligible={homeRates.sv?.eligible}
          ranked
          rankTitle="League rank by first-period save percentage among goalies with 1+ GP and a save percentage. Higher is better. Ties share a rank."
        />
        <ComparisonRow
          label="Allowed 1+ frequency"
          a={ag?.allow_pct}
          h={hg?.allow_pct}
          percent
          awayRank={awayRates.allow_pct?.rank ?? undefined}
          homeRank={homeRates.allow_pct?.rank ?? undefined}
          awayEligible={awayRates.allow_pct?.eligible}
          homeEligible={homeRates.allow_pct?.eligible}
          ranked
          rankTitle="League rank by first-period allow-1+ frequency among goalies with 1+ GP. Lower is better. Ties share a rank."
        />
        {!["PPD", "CNCL"].includes(m.game.schedule_state) && (
          <PriceLine
            price={odds?.prices[String(m.game.id)]}
          />
        )}
      </div>
    </Link>
  );
}

function teamMetricRanks(rankings: Data["rankings"], window: Window) {
  const rankMetric = (metric: string, lower = false) => {
    const values = rankings
      .map((r) => ({ id: r.id, value: r.windows[window][metric] }))
      .filter((r): r is { id: number; value: number } => r.value != null);
    return new Map(
      values.map((r) => [
        r.id,
        1 + values.filter((other) => lower ? other.value < r.value : other.value > r.value).length,
      ]),
    );
  };
  return {
    gf_pg: rankMetric("gf_pg"),
    ga_pg: rankMetric("ga_pg", true),
    combined_pg: rankMetric("combined_pg"),
    hits: rankMetric("hits"),
    hit_pct: rankMetric("hit_pct"),
  };
}

const teamCols: [string, string][] = [
  ["games", "GP"],
  ["gf_pg", "GF/G"],
  ["ga_pg", "GA/G"],
  ["combined_pg", "Combined/G"],
  ["hits", "2+ count"],
  ["hit_pct", "2+ %"],
];
const goalieCols: [string, string][] = [
  ["games", "1P GP"],
  ["ga_total", "GA"],
  ["ga_pg", "GA/GP"],
  ["sa", "SA"],
  ["sv", "SV%"],
  ["allow_count", "Allow 1+"],
  ["allow_pct", "Allow 1+%"],
  ["partial_games", "Partial GP"],
];
const value = (key: string, n: number | null | undefined) =>
  key.endsWith("_pct")
    ? pct(n)
    : f(
        n,
        [
          "games",
          "hits",
          "ga_total",
          "sa",
          "allow_count",
          "partial_games",
        ].includes(key)
          ? 0
          : key === "sv"
            ? 3
            : 2,
      );
function FormTable({
  stats,
  goalie = false,
  league,
  ranks,
}: {
  stats: Windows;
  goalie?: boolean;
  league?: Windows;
  ranks?: GoalieRanks | null;
}) {
  const cols = goalie ? goalieCols : teamCols;
  return (
    <div className="table-scroll">
      <table className="fp-form">
        <thead>
          <tr>
            <th>Window</th>
            {cols.map(([k, l]) => (
              <th key={k}>{l}</th>
            ))}
            {league && <th>Lg allow 1+%</th>}
          </tr>
        </thead>
        <tbody>
          {windows.map(([w, label]) => (
            <tr key={w}>
              <th>{label}</th>
              {cols.map(([k]) => {
                const n = stats[w][k],
                  baseline = stats.season[k];
                const metricRank =
                  goalie && (GOALIE_RATE_KEYS as readonly string[]).includes(k)
                    ? ranks?.[w]?.[k as GoalieRate]
                    : undefined;
                const comparable =
                  !metricRank &&
                  w !== "season" &&
                  [
                    "gf_pg",
                    "ga_pg",
                    "combined_pg",
                    "hit_pct",
                    "sv",
                    "allow_pct",
                  ].includes(k) &&
                  n != null &&
                  baseline != null &&
                  (stats[w].games ?? 0) >= 3;
                const cls = metricRank
                  ? leagueRankClass(metricRank.rank, metricRank.eligible)
                  : k === "games" && (n ?? 0) < 5
                    ? "warning"
                    : comparable && n! > baseline!
                      ? ["ga_pg", "allow_pct"].includes(k)
                        ? "warning"
                        : "positive"
                      : comparable &&
                          n! < baseline! &&
                          !["ga_pg", "allow_pct"].includes(k)
                        ? "fp-lower"
                        : "";
                return (
                  <td
                    className={cls}
                    key={k}
                    title={
                      metricRank
                        ? metricRank.rank != null
                          ? `League rank ${metricRank.rank} of ${metricRank.eligible} goalies with 1+ GP. ${goalieRateHelp(k)} Ties share a rank.`
                          : `Unranked among goalies with 1+ GP. ${goalieRateHelp(k)}`
                        : comparable
                          ? `Season baseline: ${value(k, baseline)}`
                          : k === "partial_games"
                            ? "Multiple verified first-period goalies in the same game"
                            : undefined
                    }
                  >
                    {value(k, n)}
                  </td>
                );
              })}
              {league && <td className="muted">{pct(league[w].allow_pct)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
const rankPiece = (label: string, metric: MetricRank | undefined) =>
  `${label} ${metric?.rank == null ? "--" : `${metric.rank}/${metric.eligible}`}`;
const goalieRankNote = (goalie: Goalie | undefined) => {
  const season = goalie?.rank?.season;
  if ((goalie?.windows.season.games ?? 0) < 1 || !season) {
    return "Unranked / no verified 1P appearances";
  }
  return `Season ranks among goalies with 1+ 1P GP: ${rankPiece("GA", season.ga_pg)} / ${rankPiece("SV", season.sv)} / ${rankPiece("Allow 1+", season.allow_pct)}`;
};
function GoalieDetail({ side, league }: { side: Side; league: Windows }) {
  const [choice, setChoice] = useState<number | null>(null);
  const goalie = side.goalies.find(
    (g) => g.id === (choice ?? side.selected_goalie),
  );
  return (
    <section>
      <div className="fp-starter">
        <strong>{side.starter.name || "--"}</strong>
        {"\n"}
        <span
          className={side.starter.status === "Confirmed" ? "positive" : "muted"}
        >
          {side.starter.status}
        </span>
      </div>
      <p className="footnote">
        Source updated {timestamp(side.starter.updated_at)}
      </p>
      <label className="goalie-picker">
        <span>Inspect goalie</span>
        <select
          aria-label={`${side.team.abbrev} first-period goalie`}
          value={goalie?.id || ""}
          disabled={!side.goalies.length}
          onChange={(e) => setChoice(Number(e.target.value))}
        >
          {!side.goalies.length && <option value="">Roster unavailable</option>}
          {side.goalies.map((g) => (
            <option value={g.id} key={g.id}>
              {g.name}
            </option>
          ))}
        </select>
      </label>
      <p className="footnote">
        {choice == null ? side.goalie_basis : "Inspecting roster goalie"} /{" "}
        {goalieRankNote(goalie)}
      </p>
      {goalie && (
        <FormTable stats={goalie.windows} goalie league={league} ranks={goalie.rank} />
      )}
    </section>
  );
}
function Rankings({ data, window }: { data: Data; window: Window }) {
  const [sort, setSort] = useState({ key: "season_hits", desc: true });
  const keys: [string, string, boolean][] = [
    ["season_hits", "Season 2+ count", false],
    ["hit_pct", "2+ %", false],
    ["combined_pg", "Combined/G", true],
    ["last5", "L5 2+ %", true],
    ["last10", "L10 2+ %", true],
  ];
  const metric = (r: Data["rankings"][number], key: string) =>
    key === "season_hits"
      ? r.windows.season.hits
      : key === "last5" || key === "last10"
        ? r.windows[key].hit_pct
        : r.windows[window][key];
  const rows = [...data.rankings].sort((a, b) => {
    const av = metric(a, sort.key),
      bv = metric(b, sort.key);
    if (av == null || bv == null) return av == null ? (bv == null ? 0 : 1) : -1;
    return (sort.desc ? bv - av : av - bv) || a.abbrev.localeCompare(b.abbrev);
  });
  return (
    <section className="fp-rankings fp-team-rankings">
      <div className="section-heading">
        <h2>League team rankings</h2>
        <span className="eyebrow">FIRST-PERIOD 2+ GOALS</span>
      </div>
      <div className="table-scroll">
        <table className="fp-form">
          <thead>
            <tr>
              <th>Season rank</th>
              <th>Team</th>
              <th>GP</th>
              {keys.map(([key, label, extra]) => (
                <th
                  key={key}
                  className={extra ? "fp-col-extra" : undefined}
                  aria-sort={
                    sort.key === key
                      ? sort.desc
                        ? "descending"
                        : "ascending"
                      : "none"
                  }
                >
                  <button
                    className="fp-sort"
                    onClick={() =>
                      setSort({
                        key,
                        desc: sort.key === key ? !sort.desc : true,
                      })
                    }
                  >
                    {label}
                    {sort.key === key &&
                      (sort.desc ? (
                        <ArrowDown size={11} />
                      ) : (
                        <ArrowUp size={11} />
                      ))}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className={r.playing ? "fp-playing" : ""}>
                <td>{r.rank}</td>
                <td>
                  <span className="player-matchup">
                    <img
                      className="logo"
                      src={`https://assets.nhle.com/logos/nhl/svg/${r.abbrev}_light.svg`}
                      alt=""
                    />
                    {r.abbrev}
                  </span>
                </td>
                <td
                  className={
                    (r.windows[window].games ?? 0) < 5 ? "warning" : ""
                  }
                >
                  {r.windows[window].games}
                </td>
                {keys.map(([key, , extra]) => {
                  const n = metric(r, key);
                  const tone =
                    n != null &&
                    key !== "season_hits" &&
                    key !== "combined_pg"
                      ? n >= 65
                        ? "positive"
                        : n < 45
                          ? "fp-lower"
                          : ""
                      : "";
                  return (
                    <td
                      key={key}
                      className={[extra ? "fp-col-extra" : "", tone].filter(Boolean).join(" ") || undefined}
                      title={
                        key === "last5" || key === "last10"
                          ? `${r.windows[key].hits ?? "--"}/${r.windows[key].games} games`
                          : undefined
                      }
                    >
                      {key === "season_hits"
                        ? `${f(n, 0)}/${r.windows.season.games}`
                        : key === "combined_pg"
                          ? f(n)
                          : pct(n)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
function GoalieRankings({ data, window }: { data: Data; window: Window }) {
  const [sort, setSort] = useState<{ key: GoalieRate; desc: boolean }>({
    key: "ga_pg",
    desc: false,
  });
  const columns: {
    key: GoalieRate;
    label: string;
    extra?: boolean;
    lower: boolean;
    digits?: number;
    percent?: boolean;
  }[] = [
    { key: "ga_pg", label: "GA/GP", lower: true },
    { key: "sv", label: "SV%", lower: false, digits: 3 },
    { key: "allow_pct", label: "Allow 1+%", extra: true, lower: true, percent: true },
  ];
  const rows = [...(data.goalie_rankings ?? [])].sort((a, b) => {
    const av = a.windows[window][sort.key],
      bv = b.windows[window][sort.key];
    if (av == null || bv == null) return av == null ? (bv == null ? 0 : 1) : -1;
    return (sort.desc ? bv - av : av - bv) || a.name.localeCompare(b.name) || a.id - b.id;
  });
  return (
    <section className="fp-rankings fp-goalie-rankings">
      <div className="section-heading">
        <h2>League goalie rankings</h2>
        <span className="eyebrow">1+ GP</span>
      </div>
      {rows.length ? (
        <div className="table-scroll">
          <table className="fp-form">
            <thead>
              <tr>
                <th title="Goals-against rank for this window among goalies with 1+ GP. Ties share a rank.">
                  Rank
                </th>
                <th>Goalie</th>
                <th>GP</th>
                {columns.map((column) => (
                  <th
                    key={column.key}
                    className={column.extra ? "fp-col-extra" : undefined}
                    aria-sort={
                      sort.key === column.key
                        ? sort.desc
                          ? "descending"
                          : "ascending"
                        : "none"
                    }
                  >
                    <button
                      className="fp-sort"
                      onClick={() =>
                        setSort({
                          key: column.key,
                          desc: sort.key === column.key ? !sort.desc : !column.lower,
                        })
                      }
                    >
                      {column.label}
                      {sort.key === column.key &&
                        (sort.desc ? <ArrowDown size={11} /> : <ArrowUp size={11} />)}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((goalie) => (
                <tr key={goalie.id} className={goalie.playing ? "fp-playing" : ""}>
                  <td>{goalie.rank?.[window]?.ga_pg.rank ?? "—"}</td>
                  <td>
                    <span className="player-matchup" title={goalie.abbrev ? `${goalie.name}, ${goalie.abbrev}` : goalie.name}>
                      {goalie.abbrev && (
                        <img
                          className="logo"
                          src={`https://assets.nhle.com/logos/nhl/svg/${goalie.abbrev}_light.svg`}
                          alt=""
                        />
                      )}
                      {lastName(goalie.name)}
                    </span>
                  </td>
                  <td className={(goalie.windows[window].games ?? 0) < 5 ? "warning" : ""}>
                    {goalie.windows[window].games}
                  </td>
                  {columns.map((column) => {
                    const metric = goalie.rank?.[window]?.[column.key];
                    const n = goalie.windows[window][column.key];
                    return (
                      <td
                        key={column.key}
                        className={[column.extra ? "fp-col-extra" : "", leagueRankClass(metric?.rank, metric?.eligible)]
                          .filter(Boolean)
                          .join(" ") || undefined}
                        title={
                          metric?.rank != null
                            ? `League rank ${metric.rank} of ${metric.eligible} goalies with 1+ GP. ${goalieRateHelp(column.key)} Ties share a rank.`
                            : `Unranked among goalies with 1+ GP. ${goalieRateHelp(column.key)}`
                        }
                      >
                        {column.percent ? pct(n) : f(n, column.digits ?? 2)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="empty-inline">No goalies with a verified first-period appearance.</p>
      )}
    </section>
  );
}

export function FirstPeriod() {
  const { id } = useParams();
  const [params, setParams] = useSearchParams();
  const date = /^\d{4}-\d{2}-\d{2}$/.test(params.get("date") || "")
    ? params.get("date")!
    : today();
  const window: Window =
    params.get("window") === "last5"
      ? "last5"
      : params.get("window") === "last10"
        ? "last10"
        : "season";
  const update = (key: string, v: string) => {
    if (!v) return;
    const p = new URLSearchParams(params);
    p.set(key, v);
    setParams(p);
  };
  // Each response includes all three windows; changing the display needs no refetch.
  const { data, error, busy, refresh } = usePeriod(
    id ? `/api/first-period/matchups/${id}` : `/api/first-period?date=${date}`,
  );
  useEffect(() => {
    if (id && data?.date && !params.has("date")) {
      const next = new URLSearchParams(params);
      next.set("date", data.date);
      setParams(next, { replace: true });
    }
  }, [id, data?.date, params, setParams]);
  const oddsDate = data?.date || date;
  return (
    <PeriodContent
      key={`${id || "slate"}-${oddsDate}`}
      {...{
        id,
        date,
        window,
        update,
        data,
        error,
        busy,
        refresh,
        oddsDate,
      }}
    />
  );
}
function PeriodContent({
  id,
  date,
  window,
  update,
  data,
  error,
  busy,
  refresh,
  oddsDate,
}: {
  id?: string;
  date: string;
  window: Window;
  update: (key: string, value: string) => void;
  data: Data | null;
  error: string | null;
  busy: boolean;
  refresh: () => void;
  oddsDate: string;
}) {
  const {
    odds,
    busy: oddsBusy,
    error: oddsError,
    load: loadOdds,
  } = useOdds(oddsDate);
  const match = data?.matchups?.[0];
  const oddsMeta = oddsMessage(odds, oddsError);
  return (
    <>
      {id && (
        <Link
          className="back-link"
          to={`/first-period?date=${date}&window=${window}`}
        >
          <ArrowLeft size={14} />
          First-period slate
        </Link>
      )}
      <header className="page-heading">
        <div>
          {id && <div className="eyebrow">MATCHUP</div>}
          <h1>
            {id && match
              ? `${match.game.away.abbrev} at ${match.game.home.abbrev}`
              : "First Period"}
          </h1>
        </div>
      </header>
      <div className="toolbar">
        <div className="segments" aria-label="First-period window">
          {windows.map(([w, label]) => (
            <button
              key={w}
              className={window === w ? "selected" : ""}
              aria-pressed={window === w}
              onClick={() => update("window", w)}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="toolbar-right refresh-actions" role="group" aria-label="Refresh data">
          <RefreshButton label="Stats" ariaLabel="Refresh first-period statistics"
            description="Reload first-period team and goalie stats. Cached sources refresh when due."
            busy={busy} onClick={refresh} />
          {odds?.manual_refresh_enabled && (
            <RefreshButton label="1P odds" ariaLabel="Refresh first-period odds"
              description="Fetch latest first-period odds for all games on this date. Uses odds API credits."
              busy={oddsBusy} onClick={loadOdds} />
          )}
        </div>
      </div>
      {oddsMeta && (
        <div className="fp-odds-meta">
          <span className={oddsError || odds?.error ? "warning" : "muted"}>
            {oddsMeta}
          </span>
        </div>
      )}
      {!data && !error ? (
        <div className="loading-label" role="status">
          <RefreshCw size={14} className="spin" />
          Loading first-period statistics...
        </div>
      ) : error || data?.error ? (
        <div className="state-message">
          <h2>First period unavailable</h2>
          <p>{error || data?.error}</p>
        </div>
      ) : (
        data && (
          <>
            {(data.build.status === "building" || data.build.error) && (
              <div className="fp-coverage">
                {data.build.status === "building" ? (
                <span role="status">
                  <RefreshCw className="spin" size={12} /> Building{" "}
                  {data.build.done}/{data.build.total}
                </span>
              ) : data.build.error ? (
                <span className="warning">{data.build.error}</span>
              ) : null}
            </div>
            )}
            {data.stats_error && (
              <p className="warning footnote">{data.stats_error}</p>
            )}
            {data.coverage.rejected_team_games > 0 && (
              <p className="warning footnote">
                {data.coverage.rejected_team_games} incomplete or inconsistent
                team-game pairs excluded.
              </p>
            )}
            {id && match ? (
              <>
                <div className="two-columns fp-details">
                  {[match.away, match.home].map((s) => (
                    <section key={s.team.id}>
                      <div className="section-heading">
                        <h2 className="player-matchup">
                          <Logo team={s.team} />
                          {s.team.abbrev} team form
                        </h2>
                      </div>
                      <FormTable stats={s.windows} />
                    </section>
                  ))}
                </div>
                <div className="two-columns fp-details">
                  {[match.away, match.home].map((s) => (
                    <GoalieDetail
                      key={s.team.id}
                      side={s}
                      league={data.league_goalies}
                    />
                  ))}
                </div>
                {!["PPD", "CNCL"].includes(match.game.schedule_state) && (
                  <PriceLine
                    price={odds?.prices[String(match.game.id)]}
                  />
                )}
                <section className="fp-h2h">
                  <div className="section-heading">
                    <h2>Head-to-head first periods</h2>
                    <span className="muted">
                      {f(match.h2h.summary.hits, 0)}/{match.h2h.summary.games}{" "}
                      with 2+ goals / {pct(match.h2h.summary.hit_pct)}
                    </span>
                  </div>
                  <p className="footnote">
                    {data.season_label} meetings /{" "}
                    {f(match.h2h.summary.combined_pg)} combined goals per game
                  </p>
                  {match.h2h.recent.length ? (
                    <div className="table-scroll">
                      <table className="fp-form">
                        <thead>
                          <tr>
                            <th>Date</th>
                            <th>Away</th>
                            <th>Home</th>
                            <th>1P score</th>
                            <th>2+ goals</th>
                          </tr>
                        </thead>
                        <tbody>
                          {match.h2h.recent.map((g) => (
                            <tr key={g.gameId}>
                              <td>{formatDate(g.date)}</td>
                              <td>{g.away.abbrev}</td>
                              <td>{g.home.abbrev}</td>
                              <td>
                                {g.away.gf} - {g.home.gf}
                              </td>
                              <td
                                className={
                                  g.away.gf + g.home.gf >= 2
                                    ? "positive"
                                    : "muted"
                                }
                              >
                                {g.away.gf + g.home.gf >= 2 ? "Yes" : "No"}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <p className="empty-inline">
                      No meetings in this statistical season.
                    </p>
                  )}
                </section>
              </>
            ) : (
              <>
                {data.matchups.length ? (
                  <div className="slate fp-slate">
                    {(() => {
                      const ranks = teamMetricRanks(data.rankings, window);
                      return data.matchups.map((m) => (
                        <PeriodCard
                          key={m.game.id}
                          m={m}
                          window={window}
                          date={date}
                          odds={odds}
                          ranks={ranks}
                        />
                      ));
                    })()}
                  </div>
                ) : (
                  <div className="state-message">
                    <h2>No games scheduled</h2>
                  </div>
                )}
                <div className="fp-rankings-grid">
                  <Rankings data={data} window={window} />
                  <GoalieRankings data={data} window={window} />
                </div>
              </>
            )}
          </>
        )
      )}
    </>
  );
}
