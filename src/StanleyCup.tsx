import React, { useEffect, useState } from "react";
import { RefreshButton } from "./RefreshButton";
import type { Source } from "./types";

type CupTeam = {
  abbrev: string;
  name: string;
  logo: string | null;
  wins: number | null;
  losses: number | null;
  ot_losses: number | null;
  points: number | null;
  games_played: number | null;
  gf_per_game: number | null;
  ga_per_game: number | null;
  sf_per_game: number | null;
  sa_per_game: number | null;
  power_play_pct: number | null;
  penalty_kill_pct: number | null;
  xgf_pct: number | null;
  odds: string | null;
  odds_price: number | null;
  odds_updated_at: string | null;
};

type CupData = {
  teams: CupTeam[];
  odds_status: "fresh" | "stale" | "empty";
  odds_fetched_at: string | null;
  bookmaker: string;
  error: string | null;
  sources: Source[];
};

const et = "America/New_York";
const record = (team: CupTeam) =>
  team.wins == null ? "--" : `${team.wins}-${team.losses}-${team.ot_losses}`;
const num = (value: number | null, digits = 1, suffix = "") =>
  value == null ? "--" : `${value.toFixed(digits)}${suffix}`;
const stamp = (value: string | null) =>
  value
    ? new Date(value).toLocaleString("en-US", {
        timeZone: et,
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      }) + " ET"
    : "Not loaded";

type SortKey =
  | "name"
  | "record"
  | "games_played"
  | "points"
  | "gf_per_game"
  | "ga_per_game"
  | "sf_per_game"
  | "sa_per_game"
  | "power_play_pct"
  | "penalty_kill_pct"
  | "xgf_pct"
  | "odds_price";

type Column = {
  key: SortKey;
  label: string;
  align?: "left" | "right";
  numeric?: boolean;
  lowerBetter?: boolean;
  value: (team: CupTeam) => React.ReactNode;
  sortValue: (team: CupTeam) => number | string | null;
};

const columns: Column[] = [
  {
    key: "name",
    label: "Team",
    align: "left",
    value: (team) => (
      <div className="cup-team">
        <TeamLogo team={team} />
        <div>
          <strong>{team.name}</strong>
          <span>{team.abbrev}</span>
        </div>
      </div>
    ),
    sortValue: (team) => team.name,
  },
  {
    key: "record",
    label: "Record",
    numeric: true,
    value: record,
    sortValue: (team) => (team.wins ?? 0) * 2 + (team.ot_losses ?? 0),
  },
  { key: "games_played", label: "GP", numeric: true, value: (team) => team.games_played ?? "--", sortValue: (team) => team.games_played },
  { key: "points", label: "Pts", numeric: true, value: (team) => team.points ?? "--", sortValue: (team) => team.points },
  { key: "gf_per_game", label: "GF/G", numeric: true, value: (team) => num(team.gf_per_game), sortValue: (team) => team.gf_per_game },
  { key: "ga_per_game", label: "GA/G", numeric: true, lowerBetter: true, value: (team) => num(team.ga_per_game), sortValue: (team) => team.ga_per_game },
  { key: "sf_per_game", label: "SF/G", numeric: true, value: (team) => num(team.sf_per_game), sortValue: (team) => team.sf_per_game },
  { key: "sa_per_game", label: "SA/G", numeric: true, lowerBetter: true, value: (team) => num(team.sa_per_game), sortValue: (team) => team.sa_per_game },
  { key: "power_play_pct", label: "PP%", numeric: true, value: (team) => num(team.power_play_pct, 1, "%"), sortValue: (team) => team.power_play_pct },
  { key: "penalty_kill_pct", label: "PK%", numeric: true, value: (team) => num(team.penalty_kill_pct, 1, "%"), sortValue: (team) => team.penalty_kill_pct },
  { key: "xgf_pct", label: "xGF%", numeric: true, value: (team) => num(team.xgf_pct, 1, "%"), sortValue: (team) => team.xgf_pct },
  {
    key: "odds_price",
    label: "Stanley Cup",
    numeric: true,
    value: (team) => (
      <span title={team.odds_updated_at ? `Updated ${stamp(team.odds_updated_at)}` : undefined}>
        {team.odds || "--"}
      </span>
    ),
    sortValue: (team) => team.odds_price,
  },
];

function TeamLogo({ team }: { team: CupTeam }) {
  const [failed, setFailed] = useState(false);
  if (failed || !team.logo) return <span className="cup-logo fallback">{team.abbrev}</span>;
  return (
    <img
      className="cup-logo"
      src={team.logo}
      alt=""
      onError={() => setFailed(true)}
    />
  );
}

export function StanleyCup() {
  const [data, setData] = useState<CupData | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState<{ key: SortKey; direction: "asc" | "desc" }>({
    key: "points",
    direction: "desc",
  });

  const load = async (refresh = false) => {
    setBusy(true);
    setError(null);
    try {
      const r = await fetch(`/api/stanley-cup${refresh ? "/refresh" : ""}`, {
        method: refresh ? "POST" : "GET",
      });
      const body = await r.json();
      if (!r.ok) throw new Error(body.detail || "Stanley Cup odds unavailable");
      setData(body);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Stanley Cup odds unavailable");
    } finally {
      setLoading(false);
      setBusy(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const sortedTeams = [...(data?.teams || [])].sort((a, b) => {
    const column = columns.find((c) => c.key === sort.key) || columns[0];
    const av = column.sortValue(a);
    const bv = column.sortValue(b);
    if (av == null && bv == null) return a.name.localeCompare(b.name);
    if (av == null) return 1;
    if (bv == null) return -1;
    const base =
      typeof av === "string" || typeof bv === "string"
        ? String(av).localeCompare(String(bv))
        : av - bv;
    return (sort.direction === "asc" ? 1 : -1) * base || a.name.localeCompare(b.name);
  });
  const setSortKey = (key: SortKey) => {
    setSort((current) => {
      if (current.key === key) {
        return { key, direction: current.direction === "asc" ? "desc" : "asc" };
      }
      const column = columns.find((c) => c.key === key);
      return { key, direction: column?.numeric && !column.lowerBetter ? "desc" : "asc" };
    });
  };

  return (
    <>
      <section className="section-head cup-head">
        <div>
          <h2>Stanley Cup</h2>
          <span className="eyebrow">TEAM RECORDS / POINTS / FANDUEL ODDS</span>
        </div>
        <RefreshButton
          label="Odds"
          ariaLabel="Refresh Stanley Cup odds"
          description="Fetch latest FanDuel Stanley Cup prices. Uses odds API credits."
          busy={busy}
          onClick={() => void load(true)}
        />
      </section>
      {(error || data?.error) && (
        <p className="confirmation warning">{error || data?.error}</p>
      )}
      <div className="cup-meta">
        <span>{data?.bookmaker || "FanDuel"}</span>
        <span>Updated {stamp(data?.odds_fetched_at || null)}</span>
        {data?.odds_status === "stale" && <span>Cached odds</span>}
      </div>
      <div className="table-scroll cup-scroll">
        <table className="cup-table">
          <thead>
            <tr>
              {columns.map((column) => (
                <th
                  key={column.key}
                  className={column.align === "left" ? "left" : undefined}
                  aria-sort={
                    sort.key === column.key
                      ? sort.direction === "asc"
                        ? "ascending"
                        : "descending"
                      : "none"
                  }
                >
                  <button
                    type="button"
                    className="cup-sort"
                    onClick={() => setSortKey(column.key)}
                  >
                    {column.label}
                    <span>{sort.key === column.key ? (sort.direction === "asc" ? "^" : "v") : ""}</span>
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={columns.length}>Loading Stanley Cup board...</td>
              </tr>
            )}
            {!loading &&
              sortedTeams.map((team) => (
                <tr key={team.abbrev}>
                  {columns.map((column) => (
                    <td key={column.key} className={column.align === "left" ? "left" : undefined}>
                      {column.value(team)}
                    </td>
                  ))}
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
