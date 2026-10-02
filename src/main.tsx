import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  BrowserRouter,
  Link,
  Route,
  Routes,
  useParams,
  useLocation,
  useSearchParams,
} from "react-router-dom";
import {
  ArrowLeft,
  Flag,
  ArrowRight,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  ExternalLink,
  RefreshCw,
  Clock3,
} from "lucide-react";
import type {
  Game,
  MatchupData,
  Player,
  Side,
  SlateData,
  CardComparison,
  CardSide,
  Stats,
  Team,
} from "./types";
import "./style.css";
import { RefreshButton } from "./RefreshButton";
import { Players } from "./Players";
import { FirstPeriod } from "./FirstPeriod";
import { Streaks } from "./Streaks";
import { usePlayerProps, PropsControls, PropsRefreshButton, CompactProps, type PropsState } from "./PlayerProps";
import { useMoneylines, MoneylineControls, TeamMoneyline } from "./Moneylines";
import { et, todayEt } from "./dates";

const today = todayEt;
const time = (value: string) =>
  new Date(value).toLocaleTimeString("en-US", {
    timeZone: et,
    hour: "numeric",
    minute: "2-digit",
  });
const dateTitle = (date: string) =>
  new Date(date + "T12:00:00").toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
  });
const stamp = (value: string | null) =>
  value
    ? new Date(value).toLocaleString("en-US", {
        timeZone: et,
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      }) + " ET"
    : "Not available";
const shift = (date: string, days: number) => {
  const d = new Date(date + "T12:00:00Z");
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
};
const fmt = (n: number | null | undefined, digits = 1, suffix = "") =>
  n == null ? "--" : n.toFixed(digits) + suffix;
const record = (s: Stats) =>
  s.wins == null ? "--" : `${s.wins}-${s.losses}-${s.ot_losses}`;
const isFinal = (g: Game) => ["OFF", "FINAL"].includes(g.state);
const isUpcoming = (g: Game) => ["FUT", "PRE"].includes(g.state);
const isStarted = (g: Game) => !isUpcoming(g);
const keyName = (value: string) =>
  value
    .normalize("NFKD")
    .toLowerCase()
    .replace(/[^a-z0-9]/g, "");
const clock = (value: number | null | undefined) =>
  value == null
    ? "--"
    : `${Math.floor(Math.round(value) / 60)}:${String(Math.round(value) % 60).padStart(2, "0")}`;

function useData<T>(url: string) {
  const [state, setState] = useState<{
    data: T | null;
    error: string | null;
    loading: boolean;
    refreshing: boolean;
  }>({ data: null, error: null, loading: true, refreshing: false });
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    let busy = false;
    const controller = new AbortController();
    setState({ data: null, error: null, loading: true, refreshing: false });
    const load = async () => {
      if (busy) return;
      busy = true;
      setState((s) => ({ ...s, refreshing: true }));
      try {
        const requestUrl = new URL(url, window.location.origin).toString();
        const r = await fetch(requestUrl, { signal: controller.signal });
        const body = await r.json();
        if (!r.ok) throw new Error(body.detail || "Unable to load data.");
        if (active)
          setState({
            data: body,
            error: null,
            loading: false,
            refreshing: false,
          });
      } catch (e) {
        if (active)
          setState((s) => ({
            ...s,
            error: e instanceof Error ? e.message : "Unable to load data.",
            loading: false,
            refreshing: false,
          }));
      } finally {
        busy = false;
      }
    };
    void load();
    return () => {
      active = false;
      controller.abort();
    };
  }, [url, revision]);
  return { ...state, refresh: () => setRevision((r) => r + 1) };
}

function Logo({ team, large = false }: { team: Team; large?: boolean }) {
  const [failed, setFailed] = useState(false);
  return failed || !team.logo ? (
    <span className={`logo fallback ${large ? "large" : ""}`}>
      {team.abbrev}
    </span>
  ) : (
    <img
      className={`logo ${large ? "large" : ""}`}
      src={team.logo}
      alt=""
      onError={() => setFailed(true)}
    />
  );
}

function IconButton({
  label,
  children,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button
      {...props}
      className={`icon-button ${props.className || ""}`}
      title={label}
      aria-label={label}
    >
      {children}
    </button>
  );
}

function TopbarDateControls() {
  const [params, setParams] = useSearchParams();
  const date = /^\d{4}-\d{2}-\d{2}$/.test(params.get("date") || "")
    ? params.get("date")!
    : today();
  const changeDate = (value: string) => {
    if (!value) return;
    const next = new URLSearchParams(params);
    next.set("date", value);
    setParams(next);
  };
  return (
    <div className="date-controls compact-date-controls topbar-date-controls">
      <IconButton
        label="Previous day"
        disabled={date <= today()}
        onClick={() => changeDate(shift(date, -1))}
      >
        <ChevronLeft size={15} />
      </IconButton>
      <label className="date-input compact-date-input">
        <CalendarDays size={13} />
        <input
          type="date"
          aria-label="Game date"
          min={today()}
          value={date}
          onChange={(e) => changeDate(e.target.value)}
        />
      </label>
      <IconButton label="Next day" onClick={() => changeDate(shift(date, 1))}>
        <ChevronRight size={15} />
      </IconButton>
      <button
        className="text-button compact-text-button"
        onClick={() => changeDate(today())}
      >
        Today
      </button>
    </div>
  );
}

function GameStatus({ game }: { game: Game }) {
  if (game.schedule_state === "PPD")
    return <span className="status warning">Postponed</span>;
  if (isFinal(game)) return <span className="status">Final</span>;
  return (
    <span className="status">
      {time(game.start)} <span className="muted">ET</span>
    </span>
  );
}

function StateMessage({
  title,
  detail,
  retry,
}: {
  title: string;
  detail?: string;
  retry?: () => void;
}) {
  return (
    <div className="state-message">
      <h2>{title}</h2>
      {detail && <p>{detail}</p>}
      {retry && (
        <button className="text-button" onClick={retry}>
          <RefreshCw size={14} />
          Retry
        </button>
      )}
    </div>
  );
}

function Loading({ matchup = false }: { matchup?: boolean }) {
  return (
    <div className="loading" role="status" aria-live="polite">
      <div className="loading-label">
        <RefreshCw size={14} className="spin" />
        {matchup ? "Loading matchup and season data..." : "Loading games..."}
      </div>
      {Array.from({ length: 6 }, (_, i) => (
        <div className="skeleton" key={i} />
      ))}
    </div>
  );
}

function CardMetric({
  label,
  away,
  home,
  digits = 2,
  suffix = "",
  lower = false,
  neutral = false,
}: {
  label: string;
  away: number | null | undefined;
  home: number | null | undefined;
  digits?: number;
  suffix?: string;
  lower?: boolean;
  neutral?: boolean;
}) {
  const comparable =
    !neutral &&
    away != null &&
    home != null &&
    away.toFixed(digits) !== home.toFixed(digits);
  const awayBetter = comparable && (lower ? away < home : away > home);
  const help = `${lower ? "Lower" : "Higher"} is better`;
  return (
    <div className="card-metric">
      <strong className={comparable ? (awayBetter ? "better" : "worse") : ""}>
        {fmt(away, digits, suffix)}
      </strong>
      <span title={neutral ? label : help}>
        {label}
      </span>
      <strong className={comparable ? (awayBetter ? "worse" : "better") : ""}>
        {fmt(home, digits, suffix)}
      </strong>
    </div>
  );
}

function CardForm({ side }: { side?: CardSide }) {
  return (
    <div className="card-form" aria-label="Last five games, oldest to newest">
      {side?.form.length ? (
        side.form.map((g) => (
          <span
            key={g.date + g.opponent}
            className={
              g.result === "W"
                ? "win"
                : g.result === "OTL"
                  ? "overtime"
                  : "loss"
            }
            title={`${g.date} ${g.home ? "vs" : "at"} ${g.opponent}: ${g.result}`}
          >
            <strong>{g.result === "OTL" ? "OT" : g.result}</strong>
            <small>
              <b>{g.home ? "vs" : "@"}</b> {g.opponent}
            </small>
          </span>
        ))
      ) : (
        <span className="muted">--</span>
      )}
    </div>
  );
}

function CardSignals({ game, comparison }: { game: Game; comparison?: CardComparison }) {
  const signals = [comparison?.away, comparison?.home].flatMap((side, index) =>
    (side?.signals || []).map(signal => ({
      ...signal,
      team: index === 0 ? game.away.abbrev : game.home.abbrev,
    })),
  );
  if (!signals.length) return null;
  return (
    <span
      className="card-signals"
      tabIndex={0}
      aria-label={signals.map(signal => `${signal.team}: ${signal.detail}`).join("; ")}
      onClick={event => {
        event.preventDefault();
        event.currentTarget.focus();
      }}
      onKeyDown={event => {
        if (event.key === "Enter" || event.key === " ") event.preventDefault();
        if (event.key === "Escape") event.currentTarget.blur();
      }}
    >
      <Flag size={10} />
      <span className="signal-summary">
        {signals.length === 1
          ? `${signals[0].team} ${signals[0].label}`
          : `${signals.length} flags`}
      </span>
      <span className="signal-tooltip" role="tooltip">
        {signals.map(signal => (
          <span className={`signal-flag signal-${signal.id}`} key={`${signal.team}-${signal.id}`}>
            <strong>{signal.team} · {signal.label}</strong>
            <span>{signal.detail}</span>
          </span>
        ))}
      </span>
    </span>
  );
}

function CardStats({
  game,
  comparison,
  odds,
}: {
  game: Game;
  comparison?: CardComparison;
  odds: ReturnType<typeof useMoneylines>;
}) {
  const a = comparison?.away,
    h = comparison?.home;
  return (
    <div className="card-stats">
      <div className="card-matchup">
        <div className="card-team" role="group" aria-label={game.away.name} title={game.away.name}>
          <Logo team={game.away} />
          <span className="card-record" title="Team record (W–L–OT)">{game.away.record || "--"}</span>
          <TeamMoneyline game={game} odds={odds} side="away" />
        </div>
        <span className="eyebrow">AT</span>
        <div className="card-team" role="group" aria-label={game.home.name} title={game.home.name}>
          <Logo team={game.home} />
          <span className="card-record" title="Team record (W–L–OT)">{game.home.record || "--"}</span>
          <TeamMoneyline game={game} odds={odds} side="home" />
        </div>
      </div>
      <CardMetric
        label="5v5 xG%"
        away={a?.advanced.xgf_pct}
        home={h?.advanced.xgf_pct}
        digits={1}
        suffix="%"
      />
      <CardMetric
        label="Goals for / G"
        away={a?.summary.gf}
        home={h?.summary.gf}
      />
      <CardMetric
        label="Goals against / G"
        away={a?.summary.ga}
        home={h?.summary.ga}
        lower
      />
      <CardMetric
        label="Shots / G"
        away={a?.summary.sf}
        home={h?.summary.sf}
        digits={1}
      />
      <CardMetric
        label="Power play"
        away={a?.summary.pp}
        home={h?.summary.pp}
        digits={1}
        suffix="%"
      />
      <div className="card-metric card-form-row">
        <CardForm side={a} />
        <span title="Last five completed regular-season games, oldest to newest">
          L5 form
        </span>
        <CardForm side={h} />
      </div>
      <div className="card-goalie-heading">
        <span>GOALTENDING</span>
        <span>SEASON</span>
      </div>
      <div className="card-goalie-names">
        {[a, h].map((side, i) => (
          <div key={i}>
            <strong>{side?.goalie.name || "--"}</strong>
            <span
              className={
                side?.goalie.basis === "Confirmed" ? "positive" : "muted"
              }
              title={
                side?.goalie.basis === "Roster leader"
                  ? "Most-used goalie on the current roster during the displayed season. Not a projected starter."
                  : "Reported starter status"
              }
            >
              {side?.goalie.basis || "Unknown"}
            </span>
          </div>
        ))}
      </div>
      <CardMetric
        label="Appearances"
        away={a?.goalie.stats.games}
        home={h?.goalie.stats.games}
        digits={0}
        neutral
      />
      <CardMetric
        label="Save %"
        away={a?.goalie.stats.sv}
        home={h?.goalie.stats.sv}
        digits={3}
      />
      <CardMetric
        label="GAA"
        away={a?.goalie.stats.gaa}
        home={h?.goalie.stats.gaa}
        lower
      />
      <CardMetric
        label="GSAx"
        away={a?.goalie.stats.gsax}
        home={h?.goalie.stats.gsax}
      />
      <div
        className="card-coverage"
        title="MoneyPuck games available for goals saved above expected"
      >
        <span>{a?.goalie.advanced_games ?? 0} GP</span>
        <span>GSAx coverage / MoneyPuck</span>
        <span>{h?.goalie.advanced_games ?? 0} GP</span>
      </div>
    </div>
  );
}

function Slate() {
  const [params] = useSearchParams();
  const date = /^\d{4}-\d{2}-\d{2}$/.test(params.get("date") || "")
    ? params.get("date")!
    : today();
  const slateUrl = `/api/slate?${new URLSearchParams({ date })}`;
  const { data, error, loading, refreshing, refresh } = useData<SlateData>(
    slateUrl,
  );
  const [filter, setFilter] = useState("upcoming");
  const odds = useMoneylines(date);
  const games = data?.games || [];
  useEffect(() => {
    setFilter("upcoming");
  }, [date]);
  const filtered = games.filter(
    (g) =>
      (filter === "final"
        ? isFinal(g)
        : filter === "started"
          ? isStarted(g)
          : isUpcoming(g)),
  );
  return (
    <>
      <div className="toolbar">
        <div className="segments" aria-label="Game status">
          {[
            ["upcoming", "Upcoming"],
            ["started", "Started"],
            ["final", "Final"],
          ].map(([key, label]) => (
            <button
              key={key}
              aria-pressed={filter === key}
              className={filter === key ? "selected" : ""}
              onClick={() => setFilter(key)}
            >
              {label}
              <span className="count">
                {key === "upcoming"
                  ? games.filter(isUpcoming).length
                  : key === "started"
                    ? games.filter(isStarted).length
                    : games.filter(isFinal).length}
              </span>
            </button>
          ))}
        </div>
        <div className="toolbar-right">
          <div className="refresh-actions" role="group" aria-label="Refresh data">
            <RefreshButton label="Stats" ariaLabel="Refresh games"
              description="Reload games, scores, team stats and goalie context. Cached sources refresh when due."
              onClick={refresh} busy={refreshing || loading} />
            <MoneylineControls odds={odds} />
          </div>
        </div>
      </div>
      {loading ? (
        <Loading />
      ) : error || data?.error ? (
        <StateMessage
          title="Games unavailable"
          detail={error || data?.error || ""}
          retry={refresh}
        />
      ) : games.length === 0 ? (
        <StateMessage
          title="No games scheduled"
          detail="Choose another date."
        />
      ) : filtered.length === 0 ? (
        <StateMessage title="No matching games" />
      ) : (
        <div className="slate">
          {filtered.map((g) => (
            <Link
              to={`/matchups/${g.id}?date=${date}`}
              className="game-card"
              key={g.id}
            >
              <div className="game-time">
                <GameStatus game={g} />
                <CardSignals game={g} comparison={data?.comparisons?.[g.id]} />
                <ArrowRight size={16} className="card-arrow" />
              </div>
              <CardStats
                game={g}
                comparison={data?.comparisons?.[g.id]}
                odds={odds}
              />
            </Link>
          ))}
        </div>
      )}
    </>
  );
}

const metrics = [
  {
    key: "gf",
    name: "Goals for / game",
    help: "Goals scored divided by completed games. All strengths; excludes shootout-deciding goals.",
    lower: false,
  },
  {
    key: "ga",
    name: "Goals against / game",
    help: "Goals conceded divided by completed games. All strengths; excludes shootout-deciding goals.",
    lower: true,
  },
  {
    key: "sf",
    name: "Shots for / game",
    help: "Shots on goal per completed game, all strengths.",
    lower: false,
  },
  {
    key: "sa",
    name: "Shots against / game",
    help: "Shots allowed per completed game, all strengths.",
    lower: true,
  },
  {
    key: "pp",
    name: "Power play",
    help: "Total power-play goals divided by total opportunities.",
    lower: false,
    pct: true,
  },
  {
    key: "pk",
    name: "Penalty kill",
    help: "One minus total power-play goals allowed divided by times shorthanded.",
    lower: false,
    pct: true,
  },
];
const advancedMetrics = [
  {
    key: "xgf60",
    name: "Expected goals for / 60",
    help: "MoneyPuck expected goals for per 60 minutes of 5-on-5 ice time.",
    lower: false,
  },
  {
    key: "xga60",
    name: "Expected goals against / 60",
    help: "MoneyPuck expected goals against per 60 minutes of 5-on-5 ice time.",
    lower: true,
  },
  {
    key: "xgf_pct",
    name: "Expected-goal share",
    help: "Expected goals for divided by total expected goals for and against, 5-on-5.",
    lower: false,
    pct: true,
  },
  {
    key: "cf_pct",
    name: "Shot-attempt share",
    help: "Shots, missed shots, and blocked attempts for divided by all attempts for and against, 5-on-5.",
    lower: false,
    pct: true,
  },
];

function Comparison({
  data,
  advanced = false,
}: {
  data: MatchupData;
  advanced?: boolean;
}) {
  const a = advanced ? data.away.advanced : data.away.summary;
  const h = advanced ? data.home.advanced : data.home.summary;
  const rows = advanced ? advancedMetrics : metrics;
  return (
    <section className="comparison">
      <div className="section-heading">
        <h2>{advanced ? "Underlying numbers" : "Team comparison"}</h2>
        <span className="eyebrow">{advanced ? "5-ON-5" : "ALL STRENGTHS"}</span>
      </div>
      <div className="compare-table">
        <div className="compare-row compare-header">
          <span>
            {data.game.away.abbrev} <span className="muted">{a.games} GP</span>
          </span>
          <span>METRIC</span>
          <span>
            {data.game.home.abbrev} <span className="muted">{h.games} GP</span>
          </span>
        </div>
        {!advanced && (
          <div className="compare-row">
            <strong>{record(a)}</strong>
            <span>Record</span>
            <strong>{record(h)}</strong>
          </div>
        )}
        {rows.map((m) => {
          const av = a[m.key],
            hv = h[m.key];
          const comparable = av != null && hv != null && av !== hv;
          const aBetter = comparable && (m.lower ? av < hv : av > hv);
          const hBetter = comparable && !aBetter;
          return (
            <div className="compare-row" key={m.key}>
              <strong className={aBetter ? "advantage" : ""}>
                {fmt(av, m.pct ? 1 : 2, m.pct ? "%" : "")}
              </strong>
              <span className="metric-label">
                {m.name}
                <span className="help" tabIndex={0} aria-label={m.help}>
                  <CircleHelp size={12} />
                  <span role="tooltip">{m.help}</span>
                </span>
              </span>
              <strong className={hBetter ? "advantage" : ""}>
                {fmt(hv, m.pct ? 1 : 2, m.pct ? "%" : "")}
              </strong>
            </div>
          );
        })}
      </div>
      {advanced && (
        <p className="footnote">
          Source:{" "}
          <a
            href="https://moneypuck.com/data.htm"
            target="_blank"
            rel="noreferrer"
          >
            MoneyPuck.com <ExternalLink size={10} />
          </a>{" "}
          <span className="divider">/</span> Matched-game coverage shown above
        </p>
      )}
    </section>
  );
}

function GoaliePanel({ side }: { side: Side }) {
  const [choice, setChoice] = useState("");
  const selected = side.goalies.find(
    (g) =>
      String(g.id) ===
      (choice || String(side.starter.player_id || side.goalies[0]?.id)),
  );
  const stats = selected?.summary;
  return (
    <div className="goalie-panel">
      <div className="section-heading">
        <span className="team-caption">{side.team.abbrev}</span>
        <span className={`confirmation ${side.starter.status.toLowerCase()}`}>
          {side.starter.status}
        </span>
      </div>
      <div className="reported-starter">
        <span className="muted">Reported starter</span>
        <strong>{side.starter.name || "--"}</strong>
      </div>
      {side.starter.updated_at && (
        <p className="footnote">Updated {stamp(side.starter.updated_at)}</p>
      )}
      <label className="goalie-picker">
        <span>Inspect goalie</span>
        <select
          aria-label={`${side.team.abbrev} goalie`}
          value={selected?.id || ""}
          onChange={(e) => setChoice(e.target.value)}
          disabled={!side.goalies.length}
        >
          {!side.goalies.length && <option value="">Roster unavailable</option>}
          {side.goalies.map((g) => (
            <option key={g.id} value={g.id}>
              {g.name}
            </option>
          ))}
        </select>
      </label>
      <div className="goalie-stats">
        {[
          ["games", "GP", 0],
          ["sv", "SV%", 3],
          ["gaa", "GAA", 2],
          ["gsax", "GSAx", 2],
        ].map(([key, label, digits]) => (
          <div key={key}>
            <span
              title={
                key === "gsax"
                  ? "Goals saved above expected: expected goals against minus actual goals, all strengths. Source: MoneyPuck."
                  : undefined
              }
            >
              {label}
            </span>
            <strong>{fmt(stats?.[key], Number(digits))}</strong>
          </div>
        ))}
      </div>
      <p className="footnote">
        GSAx: {stats?.advanced_games || 0} matched appearances{" "}
        <span className="divider">/</span>{" "}
        <a
          href="https://moneypuck.com/data.htm"
          target="_blank"
          rel="noreferrer"
        >
          MoneyPuck
        </a>
      </p>
    </div>
  );
}

function RecentGames({ side }: { side: Side }) {
  return (
    <section className="recent-team">
      <div className="section-heading">
        <h3>{side.team.abbrev}</h3>
        <div className="form">
          {side.recent
            .slice(0, 5)
            .reverse()
            .map((g) => (
              <span
                key={g.gameId}
                className={g.result === "W" ? "win" : "loss"}
                title={`${g.gameDate} vs ${g.opponentTeamAbbrev}`}
              >
                {g.result === "OTL" ? "OT" : g.result}
              </span>
            ))}
        </div>
      </div>
      <div className="table-scroll">
        <table className="log-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Opponent</th>
              <th>Score</th>
              <th>Result</th>
            </tr>
          </thead>
          <tbody>
            {side.recent.map((g) => (
              <tr key={g.gameId}>
                <td>
                  {new Date(g.gameDate + "T12:00:00").toLocaleDateString(
                    "en-US",
                    { month: "short", day: "numeric" },
                  )}
                </td>
                <td>
                  <span className="muted">
                    {g.homeRoad === "H" ? "vs" : "@"}
                  </span>{" "}
                  {g.opponentTeamAbbrev}
                </td>
                <td>
                  {g.scoreFor ?? "--"} - {g.scoreAgainst ?? "--"}
                </td>
                <td className={g.result === "W" ? "positive" : "muted"}>
                  {g.result}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!side.recent.length && (
          <p className="empty-inline">No completed games available.</p>
        )}
      </div>
    </section>
  );
}

function Roster({ side, season }: { side: Side; season: string }) {
  type ProjectedPlayer = {
    key: string;
    name: string;
    position: string;
    player?: Player;
  };
  const rosterByName = new Map(side.roster.map((p) => [keyName(p.name), p]));
  const collect = (kind: "forward" | "defense" | "goalie") => {
    const sections = side.lineup?.sections || {};
    const names: string[] = [];
    for (const [section, players] of Object.entries(sections)) {
      const lower = section.toLowerCase();
      const include =
        kind === "forward"
          ? lower === "forwards" || lower.startsWith("forward line")
          : kind === "defense"
            ? lower === "defensive pairings" || lower.startsWith("defense pair")
            : lower === "goalies" || lower === "goalie";
      if (include) names.push(...players);
    }
    if (kind === "goalie" && !names.length && side.starter.name) {
      names.push(side.starter.name);
    }
    const seen = new Set<string>();
    return names.flatMap((name, i) => {
      const key = keyName(name);
      if (!key || seen.has(key)) return [];
      seen.add(key);
      const player = rosterByName.get(key);
      return [
        {
          key: `${kind}-${key}-${i}`,
          name,
          player,
          position:
            player?.position ||
            (kind === "forward" ? "F" : kind === "defense" ? "D" : "G"),
        },
      ];
    });
  };
  const groups: { label: string; players: ProjectedPlayer[] }[] = [
    { label: "Forwards", players: collect("forward") },
    { label: "Defense", players: collect("defense") },
    { label: "Goalies", players: collect("goalie") },
  ].filter((group) => group.players.length);
  const toi = (p?: Player) =>
    p?.stats.timeOnIcePerGame == null
      ? "--"
      : `${Math.floor(p.stats.timeOnIcePerGame / 60)}:${Math.floor(
          p.stats.timeOnIcePerGame % 60,
        )
          .toString()
          .padStart(2, "0")}`;
  return (
    <section>
      <div className="section-heading">
        <h2>{side.team.name}</h2>
        <span className="eyebrow">DAILY FACEOFF LINEUP</span>
      </div>
      <p className="footnote">
        Projected lineup only <span className="divider">/</span> {season}{" "}
        regular-season totals where matched
      </p>
      <div className="table-scroll">
        <table className="roster-table">
          <thead>
            <tr>
              <th>Player</th>
              <th>Pos</th>
              {[
                ["gamesPlayed", "GP"],
                ["goals", "G"],
                ["assists", "A"],
                ["points", "P"],
                ["shots", "SOG"],
                ["timeOnIcePerGame", "TOI/G"],
              ].map(([key, name]) => (
                <th key={key}>{name}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {groups.map((group) => (
              <React.Fragment key={group.label}>
                <tr className="roster-position-row">
                  <th colSpan={8}>
                    {group.label}
                    <span>{group.players.length}</span>
                  </th>
                </tr>
                {group.players.map((p) => (
                  <tr key={p.key}>
                    <td>
                      {p.name}
                      {!p.player && (
                        <span className="roster-unmatched">DFO</span>
                      )}
                    </td>
                    <td className="muted">{p.position}</td>
                    <td>{fmt(p.player?.stats.gamesPlayed, 0)}</td>
                    <td>{fmt(p.player?.stats.goals, 0)}</td>
                    <td>{fmt(p.player?.stats.assists, 0)}</td>
                    <td className="strong">{fmt(p.player?.stats.points, 0)}</td>
                    <td>{fmt(p.player?.stats.shots, 0)}</td>
                    <td>{toi(p.player)}</td>
                  </tr>
                ))}
              </React.Fragment>
            ))}
          </tbody>
        </table>
        {!groups.length && (
          <p className="empty-inline">Daily Faceoff lineup unavailable.</p>
        )}
      </div>
    </section>
  );
}

function Lineups({ side, props, gameId }: { side: Side; props: PropsState; gameId: number }) {
  const sections = Object.entries(side.lineup?.sections || {}).filter(
    ([name, players]) => !["Injuries", "Goalies"].includes(name) && players.length > 0,
  );
  const rosterSkaters = side.roster.filter((p) => p.position !== "G");
  const [strength, setStrength] = useState<"all" | "5v5">("all");
  const hasFiveOnFive = Object.values(side.lineup_usage || {}).some(
    (usage) =>
      usage.season_5v5 != null || usage.l10_5v5 != null || usage.l5_5v5 != null,
  );
  const usageWindows = ["season", "l10", "l5"] as const;
  type PositionGroup = "forwards" | "defense";
  // Deduplicate players who also appear on special-teams units.
  const positionGroups = new Map<number, PositionGroup>();
  for (const [section, names] of sections) {
    for (const name of names) {
      const id = side.lineup_player_ids?.[name];
      if (id == null) continue;
      const position = side.roster.find(player => player.id === id)?.position;
      const group = position === "D" ? "defense"
        : ["C", "L", "R", "LW", "RW", "F"].includes(position || "") ? "forwards"
        : /defen/i.test(section) ? "defense"
        : /forward/i.test(section) ? "forwards" : undefined;
      if (group) positionGroups.set(id, group);
    }
  }
  const usageNumber = (id: number, window: typeof usageWindows[number]) =>
    side.lineup_usage?.[String(id)]?.[strength === "5v5" ? `${window}_5v5` : window];
  const usageRanges = new Map<string, [number, number]>();
  for (const group of ["forwards", "defense"] as const) {
    for (const window of usageWindows) {
      const values = [...positionGroups].filter(([, value]) => value === group)
        .map(([id]) => usageNumber(id, window))
        .filter((value): value is number => value != null && Number.isFinite(value));
      if (values.length) usageRanges.set(`${group}-${window}`, [Math.min(...values), Math.max(...values)]);
    }
  }
  const usageFormatting = (name: string, window: typeof usageWindows[number]) => {
    const id = side.lineup_player_ids?.[name];
    const group = id == null ? undefined : positionGroups.get(id);
    const value = id == null ? undefined : usageNumber(id, window);
    const range = group && usageRanges.get(`${group}-${window}`);
    if (value == null || !Number.isFinite(value) || !range || range[0] === range[1]) return {};
    const relative = (value - range[0]) / (range[1] - range[0]);
    const distance = Math.abs(relative - 0.5) * 2;
    const rgb = relative >= 0.5 ? "89, 190, 151" : "222, 132, 145";
    return {
      style: { backgroundColor: `rgba(${rgb}, ${0.04 + distance * 0.22})` },
      title: `${window === "season" ? "Season" : window.toUpperCase()} ${strength === "5v5" ? "5v5 " : ""}TOI among displayed ${side.team.abbrev} ${group}: ${clock(range[0])}–${clock(range[1])}. Green = higher; rose = lower.`,
    };
  };
  const usageValue = (name: string, window: "season" | "l10" | "l5") => {
    const playerId = side.lineup_player_ids?.[name];
    const usage = playerId == null ? undefined : side.lineup_usage?.[String(playerId)];
    const value = usage?.[strength === "5v5" ? `${window}_5v5` : window];
    if (value != null) return clock(value);
    let label: string, reason: string;
    if (playerId == null) {
      label = "Unmatched";
      reason = "Lineup name could not be matched to a unique NHL roster player.";
    } else if (usage?.[`${window}_games`] == null) {
      label = "NHL unavailable";
      reason = "NHL appearance logs are unavailable for this player.";
    } else if (usage[`${window}_games`] === 0) {
      label = "No prior GP";
      reason = "No eligible regular-season appearances before the selected game date in this statistical season.";
    } else if (strength === "5v5") {
      label = usage[`${window}_5v5_games`] == null ? "5v5 unavailable" : "No 5v5 data";
      reason = usage[`${window}_5v5_games`] == null
        ? "MoneyPuck five-on-five ice-time data is unavailable."
        : "MoneyPuck has no matched five-on-five ice time for these NHL appearances.";
    } else {
      label = "TOI unavailable";
      reason = "NHL appearances are present but usable ice time is unavailable.";
    }
    return <span className="toi-missing" title={reason}>{label}</span>;
  };
  return (
    <section>
      <div className="section-heading">
        <h2>{side.team.name}</h2>
        {hasFiveOnFive ? (
          <div className="segments compact">
            <button
              aria-pressed={strength === "all"}
              className={strength === "all" ? "selected" : ""}
              onClick={() => setStrength("all")}
            >
              All TOI
            </button>
            <button
              aria-pressed={strength === "5v5"}
              className={strength === "5v5" ? "selected" : ""}
              onClick={() => setStrength("5v5")}
            >
              5v5 TOI
            </button>
          </div>
        ) : (
          <span className="eyebrow">{sections.length ? "LATEST PROJECTION" : "ROSTER ONLY"}</span>
        )}
      </div>
      {sections.length ? (
        <>
          {side.lineup_source.status === "stale" && (
            <p className="confirmation warning">Cached projection; refresh unavailable. {side.lineup_source.error}</p>
          )}
          {sections
            .map(([name, players]) => (
              <div className="line-section" key={name}>
                <h3>{name}</h3>
                <div
                  className={`line-grid ${name === "Defensive Pairings" || name.startsWith("Defense pair") ? "pairs" : ""}`}
                >
                  {players.map((p, i) => {
                    const values = usageWindows.map(window => usageValue(p, window));
                    const first = values[0];
                    const sharedReason = typeof first !== "string" && values.every(
                      value => typeof value !== "string" && value.props.title === first.props.title,
                    );
                    return (
                      <div className="line-player" key={p + i}>
                        <strong title={p}>{p.replace(/^(\S+)\s+/, (_, first: string) => first[0] + ". ")}</strong>
                        {sharedReason ? <span className="line-usage-missing">{first}</span> : values.map((value, index) => (
                          <span key={index} className={typeof value === "string" ? "line-toi" : "line-usage-missing"}
                            {...(typeof value === "string" ? usageFormatting(p, usageWindows[index]) : {})}>
                            <b>{["S", "L10", "L5"][index]}</b> {value}
                          </span>
                        ))}
                        <CompactProps state={props} gameId={gameId} playerId={side.lineup_player_ids?.[p]} overOnly />
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          <p className="footnote">
            TOI shading: rose = lower, green = higher within this team’s displayed forwards or defense, per column.
            <br />
            Published {stamp(side.lineup?.updated_at || null)}{" "}
            <span className="divider">/</span> Retrieved{" "}
            {stamp(side.lineup_source.retrieved_at)}
          </p>
        </>
      ) : (
        <div className="unavailable">
          <span>Projected lines unavailable</span>
          <a href={side.lineup_source.url} target="_blank" rel="noreferrer">
            Daily Faceoff <ExternalLink size={12} />
          </a>
          <p>{side.lineup_source.error || "No published lineup available."}</p>
        </div>
      )}
      {!sections.length && rosterSkaters.length > 0 && (
        <div className="line-section">
          <h3>NHL roster only</h3>
          <p className="footnote">Line assignments and game participation unconfirmed. Retrieved {stamp(side.roster_source.retrieved_at)}{side.roster_source.status === "stale" ? " (stale)" : ""}.</p>
          <div className="line-grid">
            {rosterSkaters.map((p) => (
              <div className="line-player" key={p.id}>
                <strong title={p.name}>{p.name.replace(/^(\S+)\s+/, (_, first: string) => first[0] + ". ")}</strong>
                <span>{p.position}</span>
                <CompactProps state={props} gameId={gameId} playerId={p.id} overOnly />
              </div>
            ))}
          </div>
        </div>
      )}
      <div className="section-heading injury-heading">
        <h3>Injuries</h3>
        <span className="eyebrow">ESPN</span>
      </div>
      {side.injuries.map((p, i) => (
        <div className="injury" key={p.name + i}>
          <div>
            <strong>{p.name}</strong>
            <span className="confirmation warning">{p.status}</span>
          </div>
          <p>{p.note}</p>
          <time>{stamp(p.updated_at)}</time>
        </div>
      ))}
      {!side.injuries.length && (
        <p className="empty-inline">
          {side.injury_source.status === "unavailable"
            ? "Injury feed unavailable."
            : "No injuries listed by source."}
        </p>
      )}
    </section>
  );
}

function Matchup() {
  const { id } = useParams();
  const [params, setParams] = useSearchParams();
  const window = params.get("window") === "last10" ? "last10" : "season";
  const tab = ["comparison", "lineups"].includes(
    params.get("tab") || "",
  )
    ? params.get("tab")!
    : "comparison";
  const { data, error, loading, refreshing, refresh } = useData<MatchupData>(
    `/api/matchups/${id}?window=${window}`,
  );
  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    next.set(key, value);
    setParams(next, { replace: true });
  };
  useEffect(() => {
    if (!data) return;
    document.title = `${data.game.away.abbrev} at ${data.game.home.abbrev} | NHL Matchups`;
    return () => {
      document.title = "NHL Matchups";
    };
  }, [data]);
  const slateDate = params.get("date") || data?.game.date || today();
  const props = usePlayerProps(data?.game.date || slateDate, Number(id), tab === "lineups" && !!data);
  return (
    <>
      <Link className="back-link" to={`/?date=${slateDate}`}>
        <ArrowLeft size={14} />
        Daily slate
      </Link>
      {loading ? (
        <Loading matchup />
      ) : error || !data ? (
        <StateMessage
          title="Matchup unavailable"
          detail={error || ""}
          retry={refresh}
        />
      ) : (
        <>
          <div className="matchup-meta">
            <span>{dateTitle(data.game.date)}</span>
            <span className="divider">/</span>
            <GameStatus game={data.game} />
            <span className="divider">/</span>
            <span>{data.game.venue}</span>
          </div>
          <header className="matchup-heading">
            {(["away", "home"] as const).map((side, i) => (
              <React.Fragment key={side}>
                {i === 1 && (
                  <span className="at">
                    {isFinal(data.game)
                      ? `${data.game.away.score ?? "--"} : ${data.game.home.score ?? "--"}`
                      : "AT"}
                  </span>
                )}
                <div className={`matchup-team ${side}`}>
                  <Logo team={data.game[side]} large />
                  <div>
                    <div className="eyebrow">{side.toUpperCase()}</div>
                    <h1>{data.game[side].name}</h1>
                    <div className="team-subline">
                      <span>{record(data[side].summary)}</span>
                      <span className="divider">/</span>
                      <span
                        className={
                          data[side].rest.back_to_back ? "warning" : "muted"
                        }
                      >
                        <Clock3 size={12} />
                        {data[side].rest.days == null
                          ? "Rest unavailable"
                          : data[side].rest.back_to_back
                            ? "Back-to-back"
                            : `${data[side].rest.days} rest days`}
                      </span>
                    </div>
                  </div>
                </div>
              </React.Fragment>
            ))}
          </header>
          <div className="matchup-toolbar">
            <nav className="tabs" aria-label="Matchup views">
              {[
                ["comparison", "Comparison"],
                ["lineups", "Lines & injuries"],
              ].map(([key, name]) => (
                <button
                  key={key}
                  className={tab === key ? "active" : ""}
                  aria-current={tab === key ? "page" : undefined}
                  onClick={() => update("tab", key)}
                >
                  {name}
                </button>
              ))}
            </nav>
            <div className="toolbar-right">
              <div className="segments">
                <button
                  aria-pressed={window === "season"}
                  className={window === "season" ? "selected" : ""}
                  onClick={() => update("window", "season")}
                >
                  Season
                </button>
                <button
                  aria-pressed={window === "last10"}
                  className={window === "last10" ? "selected" : ""}
                  onClick={() => update("window", "last10")}
                >
                  Last 10
                </button>
              </div>
              <div className="refresh-actions" role="group" aria-label="Refresh data">
                <RefreshButton label="Stats" ariaLabel="Refresh matchup"
                  description="Reload matchup stats, lines, injuries and goalie context. Cached sources refresh when due."
                  busy={refreshing} onClick={refresh} />
                {tab === "lineups" && <PropsRefreshButton state={props} gameId={data.game.id} />}
              </div>
            </div>
          </div>
          <div className="data-context">
            <span>
              {data.season_label} regular season
            </span>
            <span>
              {window === "last10"
                ? "Last 10 completed games / Goalies: last 10 appearances"
                : "Season to date"}{" "}
              <span className="divider">/</span> As of {data.as_of}
            </span>
          </div>
          {tab === "comparison" ? (
            <>
              <div className="two-columns stats-columns">
                <Comparison data={data} />
                <Comparison data={data} advanced />
              </div>
              <section className="goalies-section">
                <div className="section-heading">
                  <h2>Goaltending</h2>
                  <a
                    href={`https://www.dailyfaceoff.com/starting-goalies/${data.game.date}`}
                    target="_blank"
                    rel="noreferrer"
                    className="source-link"
                  >
                    Starter updates <ExternalLink size={12} />
                  </a>
                </div>
                <div className="two-columns">
                  <GoaliePanel key={`${id}-away`} side={data.away} />
                  <GoaliePanel key={`${id}-home`} side={data.home} />
                </div>
              </section>
              <section className="recent-section">
                <div className="section-heading">
                  <h2>Recent games</h2>
                  <span className="eyebrow">LATEST FIRST / REGULAR SEASON</span>
                </div>
                <div className="two-columns">
                  <RecentGames side={data.away} />
                  <RecentGames side={data.home} />
                </div>
              </section>
            </>
          ) : (
            <>
              <PropsControls state={props} gameId={data.game.id} />
              <div className="two-columns tab-content">
                <Lineups side={data.away} props={props} gameId={data.game.id} />
                <Lineups side={data.home} props={props} gameId={data.game.id} />
              </div>
            </>
          )}
        </>
      )}
    </>
  );
}

function DashboardNav() {
  const location = useLocation();
  const [params] = useSearchParams();
  const date = params.get("date") || today();
  return (
    <nav className="dashboard-nav" aria-label="Dashboard views">
      <Link
        to={`/players?date=${date}`}
        aria-current={location.pathname === "/players" ? "page" : undefined}
      >
        Players
      </Link>
      <Link
        to={`/first-period?date=${date}`}
        aria-current={
          location.pathname.startsWith("/first-period") ? "page" : undefined
        }
      >
        First Period
      </Link>
      <Link
        to={`/streaks?date=${date}`}
        aria-current={location.pathname === "/streaks" ? "page" : undefined}
      >
        Streaks
      </Link>
    </nav>
  );
}

function TopbarBrand() {
  const location = useLocation();
  const [params] = useSearchParams();
  const date = params.get("date") || today();
  return (
    <Link
      to={`/?date=${date}`}
      className="nav-title"
      aria-current={location.pathname === "/" ? "page" : undefined}
    >
      NHL <span>Matchups</span>
    </Link>
  );
}

function App() {
  return (
    <BrowserRouter>
      <div className="topbar">
        <TopbarBrand />
        <TopbarDateControls />
        <DashboardNav />
      </div>
      <main>
        <Routes>
          <Route path="/" element={<Slate />} />
          <Route path="/players" element={<Players />} />
          <Route path="/streaks" element={<Streaks />} />
          <Route
            path="/first-period"
            element={<FirstPeriod />}
          />
          <Route
            path="/first-period/matchups/:id"
            element={<FirstPeriod />}
          />
          <Route path="/matchups/:id" element={<Matchup />} />
          <Route path="*" element={<StateMessage title="Page not found" />} />
        </Routes>
      </main>
      <footer>
        Official statistics: NHL <span className="divider">/</span> Advanced
        statistics:{" "}
        <a
          href="https://moneypuck.com/data.htm"
          target="_blank"
          rel="noreferrer"
        >
          MoneyPuck
        </a>
        <span className="footer-right">All times Eastern</span>
      </footer>
    </BrowserRouter>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
