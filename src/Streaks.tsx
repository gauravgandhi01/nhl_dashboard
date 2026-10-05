import { RefreshButton } from "./RefreshButton";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  RefreshCw,
  Flame,
  Trophy,
  Crosshair,
  ShieldCheck,
  TrendingUp,
  Clock3,
} from "lucide-react";
import type { Source } from "./types";
import { usePlayerProps, PropsControls, PropsRefreshButton, CompactProps, type PropsState } from "./PlayerProps";
import type { AppearanceLog } from "./lineCounts";
import { todayEt } from "./dates";

type Entry = {
  id: number;
  name: string;
  team: string;
  position: string;
  logo: string;
  rank: number;
  value: number;
  sample_size: number;
  lower_bound: boolean;
  latest_game: string;
  start_date: string;
  end_date: string;
  seasons: string[];
  stale: boolean;
  recent: { date: string; value: number | string | null; opponent: string }[];
  matchups: { game_id: number; opponent: string; home: boolean }[];
  log?: AppearanceLog | null;
};
type Board = {
  id: string;
  title: string;
  period: string;
  kind: "skater" | "goalie";
  entries: Entry[];
  unit?: "seconds" | "count";
};
type Data = {
  toi_window?: "last5" | "last10" | "season";
  season_label?: string;
  scope: "league" | "tonight";
  boards: Board[];
  date: string;
  as_of: string;
  retrieved_at: string | null;
  ready: boolean;
  stale: boolean;
  error: string | null;
  build: { status: string; done: number; total: number };
  schedule_available: boolean;
  schedule_stale: boolean;
  coverage: {
    partial: boolean | null;
    eligible_players: number | null;
    skipped_players: number | null;
    ambiguous_players: number | null;
    roster_coverage: number | null;
    roster_total: number | null;
  };
  sources: Source[];
};
const today = todayEt;
const formatTOI = (value: number) => {
  const rounded = Math.round(value);
  return `${Math.floor(rounded / 60)}:${String(rounded % 60).padStart(2, "0")}`;
};
const shortDate = (date: string) =>
  new Date(date + "T12:00:00").toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });

function useStreaks(url: string) {
  const [data, setData] = useState<Data | null>(null),
    [error, setError] = useState<string | null>(null),
    [busy, setBusy] = useState(false),
    [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true,
      running = false,
      pending = false;
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
        if (!r.ok) throw new Error(body.detail || "Streaks unavailable");
        if (active) {
          setData(body);
          setError(null);
          pending = body.build.status === "building";
        }
      } catch (e) {
        if (active) {
          setError(e instanceof Error ? e.message : "Streaks unavailable");
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

function Leaderboard({
  board,
  date,
  unavailable,
  props,
}: {
  board: Board;
  date: string;
  unavailable: boolean;
  props?: PropsState;
}) {
  const streak = board.id.endsWith("streak");
  const toi = board.unit === "seconds";
  const lastTen =
    board.id.endsWith("10") || board.period.toLowerCase().includes("last 10");
  const Icon =
    toi ? Clock3 : board.id === "shots10"
      ? Crosshair
      : board.id === "win_streak"
        ? Trophy
        : board.kind === "goalie"
          ? ShieldCheck
          : streak
            ? Flame
            : TrendingUp;
  return (
    <section className={`streak-board${toi ? " streak-board-toi" : ""}`} aria-label={board.title}>
      <div className="streak-board-heading">
        <Icon size={17} />
        <h3>{board.title}</h3>
        <span className="eyebrow">TOP 10</span>
      </div>
      <p className="streak-period">{board.period}</p>
      <div className="streak-columns">
        <span>Player</span>
        {!toi && <span>Odds</span>}
        <span>{toi ? "TOI / G" : streak ? "Streak" : "Total"}</span>
        <span>Recent 5</span>
      </div>
      {board.entries.length ? (
        <div className="streak-list" tabIndex={0}>
          {board.entries.map((p) => (
            <div className="streak-row" key={p.id}>
              <div className="streak-player">
                <span className="streak-rank">{p.rank}</span>
                <img className="logo" src={p.logo} alt="" />
                <div>
                  {board.kind === "skater" ? (
                    <Link className="player-link" to={`/players?date=${date}&player=${p.id}`} title={`${p.name}. Open on Players`}>
                      <strong>{p.name}</strong>
                    </Link>
                  ) : (
                    <strong>{p.name}</strong>
                  )}
                  <div className="streak-player-meta">
                    {p.matchups.map((m) => (
                      <Link
                        key={m.game_id}
                        to={`/matchups/${m.game_id}?date=${date}`}
                        title="Scheduled team matchup; player participation unconfirmed"
                      >
                        {m.home ? "vs" : "@"} {m.opponent}
                      </Link>
                    ))}
                  </div>
                  {p.stale && (
                    <div className="streak-last-game"><span className="warning">Stale</span></div>
                  )}
                </div>
              </div>
              {!toi && <div className="streak-odds">
                {props && board.kind === "skater" && p.matchups.map(m => (
                  <CompactProps key={m.game_id} state={props} gameId={m.game_id} playerId={p.id}
                    family={board.id === "shots10" ? "shots" : ["goals10", "goal_streak"].includes(board.id) ? "scorer" : "points"}
                    showLabel={false} log={p.log} />
                ))}
              </div>}
              <div
                className="streak-value"
                title={`${p.start_date} through ${p.end_date}; ${p.seasons.join(", ")}${p.lower_bound ? "; earlier history is incomplete" : ""}`}
              >
                <strong>
                  {toi ? formatTOI(p.value) : p.value}
                  {p.lower_bound ? "+" : ""}
                </strong>
                {(toi || !lastTen || p.sample_size < 10) && (
                  <span>
                    {streak
                      ? board.id === "win_streak"
                        ? "decisions"
                        : "games"
                      : `${p.sample_size} ${board.kind === "goalie" ? "starts" : "GP"}`}
                  </span>
                )}
              </div>
              <div className="streak-recent">
                {p.recent.map((r, i) => {
                  const good =
                    board.id === "win_streak"
                      ? r.value === "W"
                      : board.id === "low_ga10"
                        ? typeof r.value === "number" && r.value < 2
                        : typeof r.value === "number" && r.value > 0;
                  return (
                    <span
                      key={r.date + i}
                      className={toi ? "streak-toi-time" : good ? "streak-hit" : "streak-miss"}
                      title={`${r.date} vs ${r.opponent || "--"}: ${r.value ?? "--"}${board.id === "low_ga10" ? " goals allowed" : ""}`}
                    >
                      {r.value ?? "--"}
                    </span>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="empty-inline">
          {unavailable
            ? "Schedule unavailable."
            : streak
              ? "No qualifying active streaks."
              : "No qualifying results."}
        </p>
      )}
    </section>
  );
}

export function Streaks() {
  const [params, setParams] = useSearchParams();
  const date = /^\d{4}-\d{2}-\d{2}$/.test(params.get("date") || "")
    ? params.get("date")!
    : today();
  const scope = params.get("scope") === "league" ? "league" : "tonight";
  const kind = params.get("kind") === "goalie" ? "goalie" : "skater";
  const toiWindow = ["last5", "last10", "season"].includes(params.get("toi_window") || "")
    ? params.get("toi_window")! : "last10";
  const props = usePlayerProps(date, undefined, scope === "tonight" && kind === "skater");
  const update = (key: string, value: string) => {
    if (!value) return;
    const next = new URLSearchParams(params);
    next.set(key, value);
    setParams(next);
  };
  const {
    data: response,
    error,
    busy,
    refresh,
  } = useStreaks(`/api/streaks?date=${date}&scope=${scope}&toi_window=${toiWindow}`);
  const data =
    response?.date === date && response.scope === scope && (response.toi_window || "last10") === toiWindow ? response : null;
  return (
    <>
      <div className="toolbar">
        <div className="segments" aria-label="Leaderboard scope">
          <button
            className={scope === "league" ? "selected" : ""}
            aria-pressed={scope === "league"}
            onClick={() => update("scope", "league")}
          >
            League-wide
          </button>
          <button
            className={scope === "tonight" ? "selected" : ""}
            aria-pressed={scope === "tonight"}
            onClick={() => update("scope", "tonight")}
          >
            On slate
          </button>
        </div>
        <div className="toolbar-right refresh-actions" role="group" aria-label="Refresh data">
          <RefreshButton label="Stats" ariaLabel="Refresh streaks"
            description="Reload streak leaderboards for this date and scope. Cached history rebuilds when due."
            busy={busy} onClick={refresh} />
          {scope === "tonight" && kind === "skater" && <PropsRefreshButton state={props} />}
        </div>
      </div>
      {scope === "tonight" && kind === "skater" && <PropsControls state={props} />}
      {error ? (
        <div className="state-message">
          <h2>Streaks unavailable</h2>
          <p>{error}</p>
        </div>
      ) : data ? (
        <>
          {data.build.status === "building" && (
            <div className="loading-label" role="status">
              <RefreshCw size={14} className="spin" />
              Building season history {data.build.done}/
              {data.build.total || "--"}
            </div>
          )}
          {(data.coverage.partial || data.stale || data.error) && (
            <p className="streak-warning warning">
              {data.error || "Some leaderboard history is incomplete."}
            </p>
          )}
          {(!data.schedule_available || data.schedule_stale) && (
            <p className="streak-warning warning">
              {data.schedule_available
                ? "Schedule is stale."
                : "Schedule unavailable; slate membership cannot be verified."}
            </p>
          )}
          {data.ready ? (
            <section className="streak-section">
              <div className="matchup-toolbar streak-mode-toolbar">
                <nav className="tabs" aria-label="Streak leaderboards">
                  {[
                    ["skater", "Skaters"],
                    ["goalie", "Goaltenders"],
                  ].map(([key, name]) => (
                    <button
                      key={key}
                      className={kind === key ? "active" : ""}
                      aria-current={kind === key ? "page" : undefined}
                      onClick={() => update("kind", key)}
                    >
                      {name}
                    </button>
                  ))}
                </nav>
                {kind === "skater" && <label className="streak-toi-window">
                  TOI span
                  <select aria-label="TOI span" value={toiWindow} onChange={event => update("toi_window", event.target.value)}>
                    <option value="last5">Last 5</option>
                    <option value="last10">Last 10</option>
                    <option value="season">Season</option>
                  </select>
                </label>}
              </div>
              <div className="streak-grid">
                {data.boards
                  .filter((b) => b.kind === kind)
                  .map((b) => (
                    <Leaderboard
                      key={b.id}
                      board={b}
                      date={date}
                      props={scope === "tonight" && kind === "skater" ? props : undefined}
                      unavailable={
                        scope === "tonight" && !data.schedule_available
                      }
                    />
                  ))}
              </div>
            </section>
          ) : data.error ? (
            <div className="state-message">
              <h2>Streak history unavailable</h2>
            </div>
          ) : null}
        </>
      ) : (
        <div className="loading-label" role="status">
          <RefreshCw size={14} className="spin" />
          Loading streaks...
        </div>
      )}
    </>
  );
}
