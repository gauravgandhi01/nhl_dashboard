import { RefreshButton } from "./RefreshButton";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ArrowDown,
  ArrowUp,
  ChevronRight,
  RefreshCw,
  Search,
} from "lucide-react";
import type { Source, Stats } from "./types";
import { buildPeers, cellFormat, type Peers } from "./playerFormatting";
import { usePlayerProps, PropsControls, PropsRefreshButton, PlayerPropPanel, type PropsState } from "./PlayerProps";
import type { AppearanceLog } from "./lineCounts";
import { todayEt } from "./dates";

type Window = "last5" | "last10" | "season";
type RecentGame = {
  game_id: number;
  date: string;
  opponent: string | null;
  opponent_logo?: string | null;
  home: boolean | null;
  goals: number | null;
  assists: number | null;
  points: number | null;
  toi: number | null;
  toi_5v5: number | null;
  shots: number | null;
  shot_attempts: number | null;
};
type Skater = {
  id: number;
  name: string;
  position: string;
  team: string;
  logo: string;
  game_id: number | null;
  opponent: string | null;
  opponent_logo?: string | null;
  home: boolean | null;
  season_label: string;
  windows: Record<Window, Stats>;
  log?: AppearanceLog | null;
  recent_games?: RecentGame[] | null;
  stats_source: Source;
  advanced_source: Source;
  roster_source: Source;
};
type Data = {
  date: string;
  as_of: string;
  retrieved_at?: string | null;
  cache_status?: string;
  players: Skater[];
  games: { id: number }[];
  periods: { season_label: string; previous_season: boolean }[];
  sources: Source[];
  error: string | null;
  ready?: boolean;
  partial?: boolean;
  schedule_available?: boolean;
  build?: { status: string; done: number; total: number };
};
const pageCache = new Map<string, Data>();
const today = todayEt;
const numeric = (n: number | null | undefined, digits = 2) =>
  n == null ? "--" : n.toFixed(digits);
const clock = (n: number | null | undefined) =>
  n == null
    ? "--"
    : `${Math.floor(Math.round(n) / 60)}:${String(Math.round(n) % 60).padStart(2, "0")}`;
const shortDate = (date: string) => {
  const [, month, day] = date.split("-");
  return month && day ? `${month}/${day}` : date;
};
const columns = [
  {
    key: "games",
    label: "GP",
    help: "NHL appearances in the selected window",
    digits: 0,
  },
  { key: "goals", label: "G", help: "Goals", digits: 0 },
  { key: "assists", label: "A", help: "Assists", digits: 0 },
  { key: "points", label: "P", help: "Points", digits: 0 },
  {
    key: "points_pg",
    label: "P/G",
    help: "Points per appearance. Season colors: nightly position peers; recent colors: own season pace.",
  },
  {
    key: "shots_pg",
    label: "SOG/G",
    help: "Shots per appearance. Season colors: nightly position peers; recent colors: own season pace.",
  },
  {
    key: "toi_pg",
    label: "TOI/G",
    help: "Average ice time. Season colors: nightly position peers; recent colors: own season usage.",
  },
  {
    key: "powerPlayPoints",
    label: "PPP",
    help: "Power-play points",
    digits: 0,
  },
  {
    key: "point_games_pct",
    label: "P in %",
    help: "Percentage of appearances with at least one point",
    digits: 0,
  },
  {
    key: "attempts_pg",
    label: "iCF/G",
    help: "MoneyPuck individual shot attempts per matched appearance, including blocked and missed attempts",
  },
  {
    key: "attempts60",
    label: "iCF/60",
    help: "MoneyPuck individual shot attempts per 60 minutes, including blocked and missed attempts",
  },
  {
    key: "shots60",
    label: "SOG/60",
    help: "MoneyPuck individual shots on goal per 60 minutes",
  },
  { key: "points60", label: "P/60", help: "MoneyPuck points per 60 minutes" },
  {
    key: "ixg60",
    label: "ixG/60",
    help: "MoneyPuck individual expected goals per 60 minutes",
  },
  {
    key: "hd60",
    label: "HD/60",
    help: "MoneyPuck individual high-danger shots per 60 minutes",
  },
];

export function Players() {
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
  const scope = params.get("scope") === "league" ? "league" : "tonight";
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [search, setSearch] = useState("");
  const [team, setTeam] = useState("all");
  const [position, setPosition] = useState("all");
  const [sort, setSort] = useState({ key: "points_pg", desc: true });
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const appliedPlayer = useRef<string | null>(null);
  const props = usePlayerProps(date);
  const requestedPlayer = Number(params.get("player"));
  const requestedId = Number.isInteger(requestedPlayer) && requestedPlayer > 0 ? requestedPlayer : null;
  const update = (key: string, value: string) => {
    if (!value) return;
    const next = new URLSearchParams(params);
    next.set(key, value);
    setParams(next);
  };
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let active = true;
    let pending = false;
    const key = `${scope}:${date}`;
    const cached = pageCache.get(key);
    setData(cached || null);
    setError(null);
    setBusy(true);
    if (!cached) {
      setTeam("all");
      setExpanded(null);
    }
    const load = () => {
      clearTimeout(timer);
      fetch(`/api/players?date=${date}&scope=${scope}`, { signal: controller.signal })
        .then(async (r) => {
          const body = await r.json();
          if (!r.ok) throw new Error(body.detail || "Players unavailable");
          if (!active) return;
          if (body.ready !== false) pageCache.set(key, body);
          setData(body);
          setError(null);
          pending = body.build?.status === "building";
          if (pending && !document.hidden) timer = setTimeout(load, 3000);
        })
        .catch((e) => {
          pending = false;
          if (active && !controller.signal.aborted) setError(e.message);
        })
        .finally(() => { if (active) setBusy(false); });
    };
    const visibility = () => {
      clearTimeout(timer);
      if (!document.hidden && pending) load();
    };
    document.addEventListener("visibilitychange", visibility);
    load();
    return () => {
      active = false;
      clearTimeout(timer);
      controller.abort();
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [date, revision, scope]);
  useEffect(() => {
    const token = `${date}:${requestedId ?? ""}`;
    if (appliedPlayer.current === token || !data || data.date !== date || data.ready === false) return;
    appliedPlayer.current = token;
    if (requestedId == null) return;
    const matches = data.players.filter((p) => p.id === requestedId);
    if (!matches.length) return;
    setTeam("all");
    setPosition("all");
    setSearch("");
    const earliest = [...matches].sort((a, b) => (a.game_id ?? Number.MAX_SAFE_INTEGER) - (b.game_id ?? Number.MAX_SAFE_INTEGER))[0];
    setExpanded(`${earliest.game_id}-${earliest.id}`);
  }, [data, date, requestedId]);
  const choosePlayer = (id: number | null, key: string | null) => {
    appliedPlayer.current = `${date}:${id ?? ""}`;
    setExpanded(key);
    const next = new URLSearchParams(params);
    if (id == null) next.delete("player");
    else next.set("player", String(id));
    setParams(next, { replace: true });
  };
  const playerMissing = requestedId != null && data?.date === date && data.ready !== false && !data.players.some((p) => p.id === requestedId);
  const peerLabel = scope === "league" ? "league" : "nightly";
  const teams = [...new Set(data?.players.map((p) => p.team) || [])].sort();
  const teamValue = team === "all" || teams.includes(team) ? team : "all";
  const peers = useMemo(() => buildPeers(data?.players || []), [data]);
  const rows = useMemo(
    () =>
      (data?.players || [])
        .filter(
          (p) =>
            (teamValue === "all" || p.team === teamValue) &&
            (position === "all" ||
              (position === "D" ? p.position === "D" : p.position !== "D")) &&
            `${p.name} ${p.team}`.toLowerCase().includes(search.toLowerCase()),
        )
        .sort((a, b) => {
          const av = a.windows[window][sort.key],
            bv = b.windows[window][sort.key];
          if (av == null || bv == null)
            return av == null
              ? bv == null
                ? a.name.localeCompare(b.name)
                : 1
              : -1;
          return (
            (sort.desc ? bv - av : av - bv) || a.name.localeCompare(b.name)
          );
        }),
    [data, teamValue, position, search, sort, window],
  );
  const format = (
    key: string,
    n: number | null | undefined,
    digits?: number,
  ) =>
    key === "toi_pg"
      ? clock(n)
      : numeric(n, digits ?? 2) +
        (key === "point_games_pct" && n != null ? "%" : "");
  return (
    <>
      <div className="toolbar player-toolbar">
        <div className="segments" aria-label="Player list">
          {([["league", "All players"], ["tonight", "On slate"]] as const).map(([key, label]) => (
            <button
              key={key}
              aria-pressed={scope === key}
              className={scope === key ? "selected" : ""}
              onClick={() => update("scope", key)}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="segments" aria-label="Player statistics window">
          {(
            [
              ["last5", "Last 5"],
              ["last10", "Last 10"],
              ["season", "Season"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              aria-pressed={window === key}
              className={window === key ? "selected" : ""}
              onClick={() => update("window", key)}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="player-filters">
          <label className="search">
            <Search size={14} />
            <input
              aria-label="Search players"
              placeholder="Search players"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
          <select
            aria-label="Player team"
            value={teamValue}
            onChange={(e) => setTeam(e.target.value)}
          >
            <option value="all">All teams</option>
            {teams.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
          <select
            aria-label="Player position"
            value={position}
            onChange={(e) => setPosition(e.target.value)}
          >
            <option value="all">All skaters</option>
            <option value="F">Forwards</option>
            <option value="D">Defense</option>
          </select>
          <div className="refresh-actions" role="group" aria-label="Refresh data">
            <RefreshButton label="Stats" ariaLabel="Refresh players"
              description="Reload player stats and rosters for this date. Cached sources refresh when due."
              busy={busy} onClick={() => setRevision((r) => r + 1)} />
            <PropsRefreshButton state={props} />
          </div>
        </div>
      </div>
      <PropsControls state={props} />
      {playerMissing && (
        <p className="player-missing warning" role="status">
          This player is not on the skater list.
        </p>
      )}
      {!data && !error ? (
        <div className="loading-label" role="status">
          <RefreshCw className="spin" size={14} />
          Loading skater game logs and MoneyPuck data...
        </div>
      ) : error || data?.error ? (
        <div className="state-message">
          <h2>Players unavailable</h2>
          <p>{error || data?.error}</p>
        </div>
      ) : data?.ready === false ? (
        <div className="loading-label" role="status">
          <RefreshCw className="spin" size={14} />
          Building skater logs {data.build?.done ?? 0}/{data.build?.total || "--"}
        </div>
      ) : (
        data && (
          <>
            {data.build?.status === "building" && (
              <div className="loading-label" role="status">
                <RefreshCw className="spin" size={14} />
                Building skater logs {data.build.done}/{data.build.total || "--"}
              </div>
            )}
            {scope === "league" && data.schedule_available === false && (
              <p className="player-missing warning" role="status">
                Schedule unavailable. Matchups are hidden.
              </p>
            )}
            {data.partial && (
              <p className="player-missing warning" role="status">
                Some skater history is incomplete.
              </p>
            )}
            {scope === "tonight" && !data.games.length ? (
              <div className="state-message">
                <h2>No scheduled games</h2>
              </div>
            ) : (
              <div
                className="table-scroll players-scroll"
                tabIndex={0}
                aria-label="Skater statistics"
              >
                <table className="players-table">
                  <colgroup>
                    <col className="player-column" />
                    <col style={{ width: 58 }} />
                    {columns.map((c) => (
                      <col key={c.key} />
                    ))}
                  </colgroup>
                  <thead>
                    <tr>
                      <th scope="col">Player</th>
                      <th scope="col">Matchup</th>
                      {columns.map((c) => (
                        <th
                          scope="col"
                          key={c.key}
                          aria-sort={
                            sort.key === c.key
                              ? sort.desc
                                ? "descending"
                                : "ascending"
                              : "none"
                          }
                        >
                          <button
                            title={scope === "league" ? c.help.replaceAll("nightly", "league") : c.help}
                            onClick={() =>
                              setSort({
                                key: c.key,
                                desc: sort.key === c.key ? !sort.desc : true,
                              })
                            }
                          >
                            {c.label}
                            {sort.key === c.key &&
                              (sort.desc ? (
                                <ArrowDown size={10} />
                              ) : (
                                <ArrowUp size={10} />
                              ))}
                          </button>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((p) => {
                      const key = `${p.game_id}-${p.id}`;
                      return (
                        <PlayerRows
                          key={key}
                          p={p}
                          window={window}
                          expanded={expanded === key}
                          toggle={() =>
                            choosePlayer(expanded === key ? null : p.id, expanded === key ? null : key)
                          }
                          date={date}
                          format={format}
                          peers={peers}
                          peerLabel={peerLabel}
                          props={props}
                        />
                      );
                    })}
                  </tbody>
                </table>
                {!rows.length && (
                  <p className="empty-inline">
                    {data.players.length
                      ? "No matching skaters."
                      : "Skater rosters unavailable."}
                  </p>
                )}
              </div>
            )}
          </>
        )
      )}
    </>
  );
}

function PlayerRows({
  p,
  window,
  expanded,
  toggle,
  date,
  format,
  peers,
  peerLabel,
  props,
}: {
  p: Skater;
  window: Window;
  expanded: boolean;
  toggle: () => void;
  date: string;
  peers: Peers;
  peerLabel: string;
  props: PropsState;
  format: (
    key: string,
    n: number | null | undefined,
    digits?: number,
  ) => string;
}) {
  const s = p.windows[window];
  const rowRef = useRef<HTMLTableRowElement>(null);
  useEffect(() => {
    if (expanded) rowRef.current?.scrollIntoView({ block: "center" });
  }, [expanded]);
  const delayed = [p.stats_source, p.advanced_source, p.roster_source].filter(
    (s) => s.status !== "available",
  );
  return (
    <>
      <tr ref={rowRef}>
        <td>
          <button
            className="player-name"
            aria-expanded={expanded}
            onClick={toggle}
          >
            <ChevronRight size={12} className={expanded ? "expanded" : ""} />
            {p.logo && <img className="logo player-team-logo" src={p.logo} alt="" />}
            <span>{p.name}</span>
          </button>
          {delayed.length > 0 && (
            <span
              className="player-delay warning"
              title={delayed
                .map(
                  (s) =>
                    `${s.source}: ${s.status}; retrieved ${s.retrieved_at || "never"}`,
                )
                .join("; ")}
            >
              {delayed.some((s) => s.status === "stale")
                ? "Stale data"
                : "Partial data"}
            </span>
          )}
        </td>
        <td>
          {p.game_id == null ? (
            <span className="muted">—</span>
          ) : (
            <Link
              className="player-matchup"
              to={`/matchups/${p.game_id}?date=${date}`}
              title={`${p.team} ${p.home ? "vs" : "@"} ${p.opponent}`}
              aria-label={`${p.team} ${p.home ? "versus" : "at"} ${p.opponent}`}
            >
              <span className="venue-marker">{p.home ? "vs" : "@"}</span>
              {p.opponent_logo ? (
                <img className="logo" src={p.opponent_logo} alt="" />
              ) : (
                <span className="muted">{p.opponent}</span>
              )}
            </Link>
          )}
        </td>
        {columns.map((c) => {
          const color = cellFormat(p, window, c.key, peers, peerLabel);
          return (
            <td
              key={c.key}
              className={color.className}
              title={color.title || undefined}
            >
              {format(c.key, s[c.key], c.digits)}
            </td>
          );
        })}
      </tr>
      {expanded && (
        <tr className="player-expanded">
          <td colSpan={columns.length + 2}>
            <div className="player-details">
              <div className="player-game-log-heading">Last 5 games</div>
              {p.recent_games == null ? (
                <p className="muted">Game log unavailable</p>
              ) : p.recent_games.length === 0 ? (
                <p className="muted">No appearances before this date.</p>
              ) : (
                <div className="player-game-log-scroll" role="region" aria-label={`${p.name} last five games`} tabIndex={0}>
                  <table className="player-game-log" aria-label={`${p.name} game log`}>
                    <thead>
                      <tr>
                        {["Date", "Opponent", "G", "A", "P", "TOI", "5v5 TOI", "Shots", "Shot Attempts"].map(label => (
                          <th key={label} scope="col">{label}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {p.recent_games.map(game => (
                        <tr key={game.game_id}>
                          <td><time dateTime={game.date}>{shortDate(game.date)}</time></td>
                          <td>
                            {game.opponent ? (
                              <span className="player-game-opponent" title={`${game.home === true ? "vs " : game.home === false ? "@ " : ""}${game.opponent}`}>
                                <span>{game.home === true ? "vs" : game.home === false ? "@" : ""}</span>
                                {game.opponent_logo ? <img className="logo" src={game.opponent_logo} alt={game.opponent} /> : <span>{game.opponent}</span>}
                              </span>
                            ) : "--"}
                          </td>
                          <td>{numeric(game.goals, 0)}</td>
                          <td>{numeric(game.assists, 0)}</td>
                          <td>{numeric(game.points, 0)}</td>
                          <td>{clock(game.toi)}</td>
                          <td>{clock(game.toi_5v5)}</td>
                          <td>{numeric(game.shots, 0)}</td>
                          <td>{numeric(game.shot_attempts, 0)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {p.game_id != null && (
                <PlayerPropPanel state={props} gameId={p.game_id} playerId={p.id} log={p.log} />
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
