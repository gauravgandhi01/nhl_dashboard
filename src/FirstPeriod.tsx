import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Download,
  ArrowDown,
  ArrowUp,
} from "lucide-react";
import type { Game, Source, Stats, Starter, Team } from "./types";

type Window = "season" | "last5" | "last10";
type Windows = Record<Window, Stats>;
type Goalie = {
  id: number;
  name: string;
  windows: Windows;
  rank: { ga: number; sv: number | null; qualified: number } | null;
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
  retrieved_at: string | null;
  error: string | null;
  source: string;
};
const windows: [Window, string][] = [
  ["season", "Season"],
  ["last5", "Last 5"],
  ["last10", "Last 10"],
];
const today = () =>
  new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
const f = (value: number | null | undefined, digits = 2) =>
  value == null ? "--" : value.toFixed(digits);
const pct = (value: number | null | undefined) =>
  value == null ? "--" : `${value.toFixed(1)}%`;
const money = (value: number) => `${value > 0 ? "+" : ""}${value}`;
const timestamp = (s: string | null) =>
  s
    ? new Date(s).toLocaleString("en-US", {
        timeZone: "America/New_York",
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      }) + " ET"
    : "Unavailable";
const shift = (date: string, days: number) => {
  const d = new Date(date + "T12:00:00Z");
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
};
const selected = (s: Side) => s.goalies.find((g) => g.id === s.selected_goalie);

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
function PriceLine({ price, stale }: { price?: Price; stale: boolean }) {
  return (
    <div
      className={`fp-price ${stale ? "warning" : ""}`}
      title={
        price
          ? `FanDuel updated ${timestamp(price.updated_at)}${stale ? "; cached/stale prices" : ""}`
          : "No matching FanDuel first-period market"
      }
    >
      <span>FanDuel 1P</span>
      {price ? (
        <>
          <strong>{price.total}</strong>
          <span>O {money(price.over)}</span>
          <span>U {money(price.under)}</span>
          {stale && <span>Stale</span>}
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
  percent = false,
  digits = 2,
  risk = false,
  neutral = false,
}: {
  label: string;
  a: number | null | undefined;
  h: number | null | undefined;
  percent?: boolean;
  digits?: number;
  risk?: boolean;
  neutral?: boolean;
}) {
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
  return (
    <div className="card-metric">
      <strong className={style(a, h)}>{percent ? pct(a) : f(a, digits)}</strong>
      <span
        title={
          risk
            ? "Higher goals allowed, not better performance"
            : neutral
              ? label
              : "Higher/lower than the opposing comparison value"
        }
      >
        {label}
      </span>
      <strong className={style(h, a)}>{percent ? pct(h) : f(h, digits)}</strong>
    </div>
  );
}
function PeriodCard({
  m,
  window,
  date,
  odds,
}: {
  m: Matchup;
  window: Window;
  date: string;
  odds: Odds | null;
}) {
  const a = m.away.windows[window],
    h = m.home.windows[window];
  const ag = selected(m.away)?.windows[window],
    hg = selected(m.home)?.windows[window];
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
          label="Sample GP"
          a={a.games}
          h={h.games}
          digits={0}
          neutral
        />
        <ComparisonRow label="1P goals for / G" a={a.gf_pg} h={h.gf_pg} />
        <ComparisonRow
          label="1P goals against / G"
          a={a.ga_pg}
          h={h.ga_pg}
          risk
        />
        <ComparisonRow
          label="Combined goals / G"
          a={a.combined_pg}
          h={h.combined_pg}
        />
        <ComparisonRow label="2+ goal games" a={a.hits} h={h.hits} digits={0} />
        <ComparisonRow
          label="2+ goal frequency"
          a={a.hit_pct}
          h={h.hit_pct}
          percent
        />
        <div className="card-goalie-heading">
          <span>FIRST-PERIOD GOALTENDING</span>
        </div>
        <div className="card-goalie-names">
          {[m.away, m.home].map((s) => (
            <div key={s.team.id}>
              <strong>{selected(s)?.name || "Unavailable"}</strong>
              <span>{s.goalie_basis}</span>
              <span
                className={
                  s.starter.status === "Confirmed" ? "positive" : "muted"
                }
              >
                {s.starter.name
                  ? `${s.starter.name} / ${s.starter.status}`
                  : "Starter not announced"}
              </span>
            </div>
          ))}
        </div>
        <ComparisonRow
          label="Verified 1P GP"
          a={ag?.games}
          h={hg?.games}
          digits={0}
          neutral
        />
        <ComparisonRow
          label="1P GA / appearance"
          a={ag?.ga_pg}
          h={hg?.ga_pg}
          risk
        />
        <ComparisonRow label="1P save %" a={ag?.sv} h={hg?.sv} digits={3} />
        <ComparisonRow
          label="Allowed 1+ frequency"
          a={ag?.allow_pct}
          h={hg?.allow_pct}
          percent
          risk
        />
        {!["PPD", "CNCL"].includes(m.game.schedule_state) && (
          <PriceLine
            price={odds?.prices[String(m.game.id)]}
            stale={odds?.status === "stale"}
          />
        )}
      </div>
    </Link>
  );
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
}: {
  stats: Windows;
  goalie?: boolean;
  league?: Windows;
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
                const comparable =
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
                const cls =
                  k === "games" && (n ?? 0) < 5
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
                      comparable
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
function GoalieDetail({ side, league }: { side: Side; league: Windows }) {
  const [choice, setChoice] = useState<number | null>(null);
  const goalie = side.goalies.find(
    (g) => g.id === (choice ?? side.selected_goalie),
  );
  return (
    <section>
      <div className="section-heading">
        <h2>{side.team.abbrev} goaltending</h2>
        <span
          className={side.starter.status === "Confirmed" ? "positive" : "muted"}
        >
          {side.starter.status}
        </span>
      </div>
      <p className="fp-starter">
        Reported starter:{" "}
        <strong>{side.starter.name || "Not announced"}</strong>
      </p>
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
        {goalie?.rank
          ? `Season GA rank #${goalie.rank.ga} / SV rank ${goalie.rank.sv == null ? "--" : "#" + goalie.rank.sv} of ${goalie.rank.qualified} (5+ 1P GP)`
          : "Unranked / fewer than 5 verified 1P appearances"}
      </p>
      {goalie && <FormTable stats={goalie.windows} goalie league={league} />}
    </section>
  );
}
function Rankings({ data, window }: { data: Data; window: Window }) {
  const [sort, setSort] = useState({ key: "season_hits", desc: true });
  const keys: [string, string][] = [
    ["season_hits", "Season 2+ count"],
    ["hit_pct", "2+ %"],
    ["combined_pg", "Combined/G"],
    ["last5", "L5 2+ %"],
    ["last10", "L10 2+ %"],
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
    <section className="fp-rankings">
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
              {keys.map(([key, label]) => (
                <th
                  key={key}
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
                <td>#{r.rank}</td>
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
                {keys.map(([key]) => {
                  const n = metric(r, key);
                  return (
                    <td
                      key={key}
                      className={
                        n != null &&
                        key !== "season_hits" &&
                        key !== "combined_pg"
                          ? n >= 65
                            ? "positive"
                            : n < 45
                              ? "fp-lower"
                              : ""
                          : ""
                      }
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

export function FirstPeriod({
  Sources,
}: {
  Sources: React.ComponentType<{ sources: Source[] }>;
}) {
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
        Sources,
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
  Sources,
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
  Sources: React.ComponentType<{ sources: Source[] }>;
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
  const { odds, busy: oddsBusy, error: oddsError, load } = useOdds(oddsDate);
  const match = data?.matchups?.[0];
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
          <div className="eyebrow">{id ? "MATCHUP" : "DAILY SLATE"}</div>
          <h1>
            {id && match
              ? `${match.game.away.abbrev} at ${match.game.home.abbrev}`
              : "First Period"}
          </h1>
          <p className="subline">
            {new Date(oddsDate + "T12:00:00").toLocaleDateString("en-US", {
              weekday: "long",
              month: "long",
              day: "numeric",
            })}
            {id && match ? (
              <>
                {" "}
                / <Status game={match.game} />
              </>
            ) : (
              <> / {data?.matchups?.length ?? "--"} games / Eastern Time</>
            )}
          </p>
        </div>
        {!id && (
          <div className="date-controls">
            <button
              className="icon-button"
              title="Previous day"
              aria-label="Previous day"
              onClick={() => update("date", shift(date, -1))}
            >
              <ChevronLeft size={17} />
            </button>
            <label className="date-input">
              <input
                type="date"
                aria-label="First-period date"
                value={date}
                onChange={(e) => update("date", e.target.value)}
              />
            </label>
            <button
              className="icon-button"
              title="Next day"
              aria-label="Next day"
              onClick={() => update("date", shift(date, 1))}
            >
              <ChevronRight size={17} />
            </button>
            <button
              className="text-button"
              onClick={() => update("date", today())}
            >
              Today
            </button>
          </div>
        )}
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
        <div className="toolbar-right">
          <button
            className="text-button"
            onClick={load}
            disabled={oddsBusy || !odds?.configured}
            title={
              !odds?.configured
                ? "THE_ODDS_API_KEY is not configured"
                : "Fetch FanDuel first-period markets; respects the 30-minute cache"
            }
          >
            <Download size={14} />
            {oddsBusy ? "Loading odds" : "Load odds"}
          </button>
          <button
            className="icon-button"
            onClick={refresh}
            disabled={busy}
            title="Refresh first-period statistics"
            aria-label="Refresh first-period statistics"
          >
            <RefreshCw size={15} className={busy ? "spin" : ""} />
          </button>
        </div>
      </div>
      <div className="fp-odds-meta">
        <a
          href={odds?.source || "https://the-odds-api.com/"}
          target="_blank"
          rel="noreferrer"
        >
          FanDuel / The Odds API
        </a>
        <span
          className={
            odds?.status === "stale" || oddsError || odds?.error
              ? "warning"
              : "muted"
          }
        >
          {oddsError ||
            odds?.error ||
            odds?.status.replaceAll("_", " ") ||
            "Loading cache"}
          {odds?.retrieved_at
            ? ` / Retrieved ${timestamp(odds.retrieved_at)}`
            : ""}
        </span>
      </div>
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
            <div className="data-context">
              <span>
                {data.season_label} regular season
                {data.previous_season ? " / Previous-season baseline" : ""} /
                Before {data.as_of}
              </span>
              <span>
                {windows.find(([w]) => w === window)?.[1]} / All strengths
              </span>
            </div>
            <div className="fp-coverage">
              <span
                className={
                  data.coverage.goalie_games < data.coverage.games ||
                  data.coverage.stale_games ||
                  data.coverage.incomplete_games
                    ? "warning"
                    : "muted"
                }
              >
                Goalie history: {data.coverage.goalie_games}/
                {data.coverage.games} games / {data.coverage.incomplete_games}{" "}
                with attribution caveats / {data.coverage.stale_games} stale
              </span>
              {data.build.status === "building" ? (
                <span role="status">
                  <RefreshCw className="spin" size={12} /> Building{" "}
                  {data.build.done}/{data.build.total}
                </span>
              ) : data.build.error ? (
                <span className="warning">{data.build.error}</span>
              ) : null}
            </div>
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
                    stale={odds?.status === "stale"}
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
                              <td>{g.date}</td>
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
                    {data.matchups.map((m) => (
                      <PeriodCard
                        key={m.game.id}
                        m={m}
                        window={window}
                        date={date}
                        odds={odds}
                      />
                    ))}
                  </div>
                ) : (
                  <div className="state-message">
                    <h2>No games scheduled</h2>
                  </div>
                )}
                <Rankings data={data} window={window} />
              </>
            )}
            <Sources sources={data.sources} />
          </>
        )
      )}
    </>
  );
}
