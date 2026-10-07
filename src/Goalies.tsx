import { Fragment, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowDown, ArrowUp, ChevronRight, RefreshCw, Search } from "lucide-react";
import { RefreshButton } from "./RefreshButton";
import { todayEt } from "./dates";
import { buildGoaliePeers, goalieCellFormat } from "./playerFormatting";
import type { Source, Stats } from "./types";

type Window = "last5" | "last10" | "season";
type Goalie = {
  id: number;
  name: string;
  team: string;
  logo: string;
  game_id: number | null;
  opponent: string | null;
  opponent_logo?: string | null;
  home: boolean | null;
  starter_status?: string | null;
  season_label: string;
  windows: Record<Window, Stats>;
  stats_source: Source;
  advanced_source: Source;
  roster_source: Source;
};
type Data = {
  date: string;
  goalies: Goalie[];
  games: { id: number }[];
  error: string | null;
  schedule_available?: boolean;
  partial?: boolean;
};
const columns: { key: string; label: string; help: string; digits: number; lower?: boolean }[] = [
  { key: "games", label: "GP", digits: 0, help: "Appearances with time on ice" },
  { key: "sv", label: "SV%", digits: 3, help: "Saves divided by shots against. Season colors: goalies in this list with 5+ appearances." },
  { key: "gaa", label: "GAA", digits: 2, lower: true, help: "Goals against per 60 minutes. Lower is better. Season colors: goalies in this list with 5+ appearances." },
  { key: "shutouts", label: "SO", digits: 0, help: "Shutouts" },
  { key: "gsax", label: "GSAx", digits: 2, help: "MoneyPuck expected goals against minus goals, all strengths. Higher is better." },
  { key: "shots_against", label: "SA", digits: 0, help: "Shots against" },
  { key: "saves", label: "SV", digits: 0, help: "Saves" },
];
const pageCache = new Map<string, Data>();
const today = todayEt;
const numeric = (n: number | null | undefined, digits = 2) => n == null ? "--" : n.toFixed(digits);

export function Goalies() {
  const [params, setParams] = useSearchParams();
  const date = /^\d{4}-\d{2}-\d{2}$/.test(params.get("date") || "") ? params.get("date")! : today();
  const window: Window = params.get("window") === "last5" ? "last5" : params.get("window") === "last10" ? "last10" : "season";
  const scope = params.get("scope") === "tonight" ? "tonight" : "league";
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [search, setSearch] = useState("");
  const [team, setTeam] = useState("all");
  const [sort, setSort] = useState({ key: "sv", desc: true });
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    next.set(key, value);
    setParams(next);
  };
  useEffect(() => {
    const controller = new AbortController();
    const key = date;
    const cached = pageCache.get(key);
    setData(cached || null);
    setError(null);
    setBusy(true);
    if (!cached) {
      setTeam("all");
      setExpanded(null);
    }
    fetch(`/api/goalies?date=${date}`, { signal: controller.signal })
      .then(async (r) => {
        const body = await r.json();
        if (!r.ok) throw new Error(body.detail || "Goalies unavailable");
        if (!controller.signal.aborted) {
          pageCache.set(key, body);
          setData(body);
        }
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [date, revision]);
  const played = useMemo(
    () => (data?.goalies || []).filter((g) => (g.windows.season?.games ?? 0) >= 1),
    [data],
  );
  const scoped = useMemo(() => {
    const listed = played.filter((g) => scope === "league" || g.game_id != null);
    if (scope !== "tonight") return listed;
    const confirmedTeams = new Set(listed.filter((g) => g.starter_status === "Confirmed").map((g) => g.team));
    return listed.filter((g) => !confirmedTeams.has(g.team) || g.starter_status === "Confirmed");
  }, [played, scope]);
  const peers = useMemo(() => buildGoaliePeers(scoped), [scoped]);
  const teams = [...new Set(scoped.map((g) => g.team))].sort();
  const teamValue = team === "all" || teams.includes(team) ? team : "all";
  const rows = useMemo(
    () => scoped.filter((g) => (teamValue === "all" || g.team === teamValue) && `${g.name} ${g.team}`.toLowerCase().includes(search.toLowerCase()))
      .sort((a, b) => {
        const av = a.windows[window][sort.key], bv = b.windows[window][sort.key];
        if (av == null || bv == null) return av == null ? (bv == null ? a.name.localeCompare(b.name) : 1) : -1;
        return (sort.desc ? bv - av : av - bv) || a.name.localeCompare(b.name);
      }),
    [scoped, teamValue, search, sort, window],
  );
  const format = (key: string, n: number | null | undefined, digits = 2) => numeric(n, digits);
  const record = (s: Stats) => `(${["wins", "losses", "ot_losses"].map((k) => format(k, s[k], 0)).join("-")})`;
  return (
    <>
      <div className="toolbar player-toolbar">
        <div className="segments" aria-label="Goalie list">
          {([["league", "All goalies"], ["tonight", "On slate"]] as const).map(([key, label]) => (
            <button key={key} aria-pressed={scope === key} className={scope === key ? "selected" : ""} onClick={() => update("scope", key)}>
              {label}
            </button>
          ))}
        </div>
        <div className="segments" aria-label="Goalie statistics window">
          {([["last5", "Last 5"], ["last10", "Last 10"], ["season", "Season"]] as const).map(([key, label]) => (
            <button key={key} aria-pressed={window === key} className={window === key ? "selected" : ""} onClick={() => update("window", key)}>
              {label}
            </button>
          ))}
        </div>
        <div className="player-filters">
          <label className="search">
            <Search size={14} />
            <input aria-label="Search goalies" placeholder="Search goalies" value={search} onChange={(e) => setSearch(e.target.value)} />
          </label>
          <select aria-label="Goalie team" value={teamValue} onChange={(e) => setTeam(e.target.value)}>
            <option value="all">All teams</option>
            {teams.map((t) => <option key={t}>{t}</option>)}
          </select>
          <div className="refresh-actions" role="group" aria-label="Refresh data">
            <RefreshButton label="Stats" ariaLabel="Refresh goalies"
              description="Reload goalie stats and rosters for this date. Cached sources refresh when due."
              busy={busy} onClick={() => setRevision((r) => r + 1)} />
          </div>
        </div>
      </div>
      {!data && !error ? (
        <div className="loading-label" role="status">
          <RefreshCw className="spin" size={14} />
          Loading goalie statistics...
        </div>
      ) : error || data?.error ? (
        <div className="state-message">
          <h2>Goalies unavailable</h2>
          <p>{error || data?.error}</p>
        </div>
      ) : data && (
        <>
          {scope === "league" && data.schedule_available === false && (
            <p className="player-missing warning" role="status">Schedule unavailable. Matchups are hidden.</p>
          )}
          {data.partial && (
            <p className="player-missing warning" role="status">Some goalie history is incomplete.</p>
          )}
          {scope === "tonight" && data.schedule_available === false ? (
            <div className="state-message"><h2>Schedule unavailable</h2></div>
          ) : scope === "tonight" && !data.games.length ? (
            <div className="state-message"><h2>No scheduled games</h2></div>
          ) : (
            <div className="table-scroll players-scroll" tabIndex={0} aria-label="Goalie statistics">
              <table className="players-table goalies-table">
                <colgroup>
                  <col className="player-column" />
                  <col style={{ width: 58 }} />
                  {columns.map((c) => <col key={c.key} />)}
                </colgroup>
                <thead>
                  <tr>
                    <th scope="col">Goalie</th>
                    <th scope="col">Matchup</th>
                    {columns.map((c) => (
                      <th scope="col" key={c.key} aria-sort={sort.key === c.key ? (sort.desc ? "descending" : "ascending") : "none"}>
                        <button title={c.help} onClick={() => setSort({ key: c.key, desc: sort.key === c.key ? !sort.desc : !c.lower })}>
                          {c.label}
                          {sort.key === c.key && (sort.desc ? <ArrowDown size={10} /> : <ArrowUp size={10} />)}
                        </button>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((g) => {
                    const key = `${g.game_id ?? "roster"}-${g.id}`;
                    const open = expanded === key;
                    const stats = g.windows[window];
                    const delayed = [g.stats_source, g.advanced_source, g.roster_source].filter((s) => s.status !== "available");
                    return (
                      <Fragment key={key}>
                        <tr>
                          <td>
                            <button className="player-name" aria-expanded={open} onClick={() => setExpanded(open ? null : key)}>
                              <ChevronRight size={12} className={open ? "expanded" : ""} />
                              {g.logo && <img className="logo player-team-logo" src={g.logo} alt="" />}
                              <span>{g.name} <span className="goalie-record">{record(stats)}</span></span>
                            </button>
                            {g.starter_status && (
                              <span className={`confirmation ${g.starter_status.toLowerCase()}`}>{g.starter_status}</span>
                            )}
                            {delayed.length > 0 && (
                              <span className="player-delay warning" title={delayed.map((s) => `${s.source}: ${s.status}`).join("; ")}>
                                {delayed.some((s) => s.status === "stale") ? "Stale data" : "Partial data"}
                              </span>
                            )}
                          </td>
                          <td>
                            {g.game_id == null ? <span className="muted">—</span> : (
                              <Link className="player-matchup" to={`/matchups/${g.game_id}?date=${date}`}
                                title={`${g.team} ${g.home ? "vs" : "@"} ${g.opponent}`}
                                aria-label={`${g.team} ${g.home ? "versus" : "at"} ${g.opponent}`}>
                                <span className="venue-marker">{g.home ? "vs" : "@"}</span>
                                {g.opponent_logo ? <img className="logo" src={g.opponent_logo} alt="" /> : <span className="muted">{g.opponent}</span>}
                              </Link>
                            )}
                          </td>
                          {columns.map((c) => {
                            const color = goalieCellFormat(g, window, c.key, peers);
                            return <td key={c.key} className={color.className} title={color.title || undefined}>{format(c.key, stats[c.key], c.digits)}</td>;
                          })}
                        </tr>
                        {open && (
                          <tr className="player-expanded">
                            <td colSpan={columns.length + 2}>
                              <div>
                                <table aria-label={`${g.name} form comparison`}>
                                  <thead>
                                    <tr>
                                      <th>Window</th>
                                      {["GP", "W", "L", "OTL", "SV%", "GAA", "SO", "GSAx"].map((label) => <th key={label}>{label}</th>)}
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {(["last5", "last10", "season"] as const).map((w) => (
                                      <tr key={w}>
                                        <td>{w === "last5" ? "Last 5" : w === "last10" ? "Last 10" : "Season"}</td>
                                        {["games", "wins", "losses", "ot_losses", "sv", "gaa", "shutouts", "gsax"].map((k) => (
                                          <td key={k} className={goalieCellFormat(g, w, k, peers).className} title={goalieCellFormat(g, w, k, peers).title || undefined}>
                                            {format(k, g.windows[w][k], ["sv"].includes(k) ? 3 : ["gaa", "gsax"].includes(k) ? 2 : 0)}
                                          </td>
                                        ))}
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
              {!rows.length && (
                <p className="empty-inline">
                  {played.length ? "No matching goalies." : data.goalies.length ? "No goalies with a game played." : "Goalie rosters unavailable."}
                </p>
              )}
            </div>
          )}
        </>
      )}
    </>
  );
}
