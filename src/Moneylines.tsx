import { useEffect, useRef, useState } from "react";
import { Download } from "lucide-react";
import type { Game } from "./types";

type Price = {
  bookmaker: string;
  name: string;
  away: number;
  home: number;
  updated_at: string | null;
  away_bookmaker?: string;
  away_name?: string;
  away_updated_at?: string | null;
  home_bookmaker?: string;
  home_name?: string;
  home_updated_at?: string | null;
};
type Odds = {
  date: string;
  configured: boolean;
  status: string;
  error: string | null;
  retrieved_at: string | null;
  prices: Record<string, Price[]>;
  usage?: { remaining: string | null } | null;
};
const stamp = (s: string | null) =>
  s
    ? new Date(s).toLocaleString("en-US", {
        timeZone: "America/New_York",
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      }) + " ET"
    : "Unknown";
const american = (n: number) => (n > 0 ? `+${n}` : String(n));

export function useMoneylines(date: string) {
  const [data, setData] = useState<Odds | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const controller = useRef<AbortController | null>(null);
  const request = async (post: boolean) => {
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setBusy(true);
    setError(null);
    try {
      const r = await fetch(
        `/api/odds/moneyline${post ? "/refresh" : ""}?date=${date}`,
        { method: post ? "POST" : "GET", signal: current.signal },
      );
      if (!r.ok) throw new Error();
      const result = await r.json();
      if (!current.signal.aborted) setData(result);
    } catch {
      if (!current.signal.aborted) setError("Moneylines unavailable");
    } finally {
      if (!current.signal.aborted) setBusy(false);
    }
  };
  useEffect(() => {
    setData(null);
    void request(false);
    return () => controller.current?.abort();
  }, [date]);
  return {
    data: data?.date === date ? data : null,
    busy,
    error,
    load: () => void request(true),
  };
}

export function MoneylineControls({
  odds,
}: {
  odds: ReturnType<typeof useMoneylines>;
}) {
  const { data, busy, error, load } = odds;
  return (
    <div className="moneyline-controls">
      <button
        className="text-button"
        disabled={busy || !data?.configured}
        onClick={load}
        title={
          data?.configured
            ? "Fetch pregame moneylines; cached for 30 minutes"
            : "THE_ODDS_API_KEY is not configured in the backend environment"
        }
      >
        <Download size={14} />
        {busy ? "Loading moneylines" : "Load moneylines"}
      </button>
      <span
        className={data?.status === "stale" || error ? "warning-text" : "muted"}
        role="status"
      >
        {error ||
          data?.error ||
          (data?.status === "available"
            ? Object.keys(data.prices).length
              ? "Moneylines loaded"
              : "No pregame prices available"
            : data?.status.replaceAll("_", " ") || "Checking cache")}
        {data?.retrieved_at && ` / Retrieved ${stamp(data.retrieved_at)}`}
        {data?.usage?.remaining != null &&
          ` / ${data.usage.remaining} credits at retrieval`}
      </span>
      <a
        href="https://the-odds-api.com/sports/nhl-odds.html"
        target="_blank"
        rel="noreferrer"
      >
        The Odds API
      </a>
    </div>
  );
}

export function MoneylineRows({
  game,
  odds,
}: {
  game: Game;
  odds: ReturnType<typeof useMoneylines>;
}) {
  const { data, error } = odds;
  const prices = data?.prices[String(game.id)] || [];
  const snapshot =
    !["FUT", "PRE"].includes(game.state) ||
    new Date(game.start).getTime() <= Date.now();
  const postponed = ["PPD", "CNCL"].includes(game.schedule_state);
  const stale = data?.status === "stale" || !!error;
  return (
    <section className="moneyline-card" aria-label="Moneylines">
      <div className="moneyline-heading">
        <span>Moneyline / best available</span>
        <span className={stale ? "warning-text" : "muted"}>
          {postponed
            ? "Postponed / canceled"
            : snapshot
              ? "Pregame snapshot"
              : stale
                ? "Stale snapshot"
                : "American"}
        </span>
      </div>
      {!postponed && prices.length ? (
        prices.map((p) => {
          const old =
            !p.updated_at ||
            Date.now() - new Date(p.updated_at).getTime() > 1800000;
          const favorite =
            p.away < p.home ? "away" : p.home < p.away ? "home" : null;
          return (
            <div
              className="moneyline-row"
              key={p.bookmaker}
              title={`${game.away.abbrev} away best at ${p.away_name || p.name}: updated ${stamp(p.away_updated_at || p.updated_at)}. ${game.home.abbrev} home best at ${p.home_name || p.name}: updated ${stamp(p.home_updated_at || p.updated_at)}. Lower price identifies the market favorite, not a statistical advantage. Check bookmaker settlement rules.`}
            >
              <strong className={favorite === "away" ? "ml-favorite" : ""}>
                {american(p.away)}
                <small className={old || stale ? "warning-text" : ""}>
                  {p.away_name || p.name}
                  {" / "}
                  {stamp(p.away_updated_at || p.updated_at)}
                </small>
              </strong>
              <span>
                {p.name}
                {(old || stale) && (
                  <small className="warning-text">Stale</small>
                )}
              </span>
              <strong className={favorite === "home" ? "ml-favorite" : ""}>
                {american(p.home)}
                <small className={old || stale ? "warning-text" : ""}>
                  {p.home_name || p.name}
                  {" / "}
                  {stamp(p.home_updated_at || p.updated_at)}
                </small>
              </strong>
            </div>
          );
        })
      ) : (
        <div className="moneyline-empty">
          {data?.status === "not_configured"
            ? "Odds not configured"
            : data?.status === "not_loaded"
              ? "Odds not loaded"
              : "Moneylines unavailable"}
        </div>
      )}
    </section>
  );
}

export function TeamMoneyline({
  game,
  odds,
  side,
}: {
  game: Game;
  odds: ReturnType<typeof useMoneylines>;
  side: "away" | "home";
}) {
  const { data, error } = odds;
  const price = data?.prices[String(game.id)]?.[0];
  const postponed = ["PPD", "CNCL"].includes(game.schedule_state);
  if (!price || postponed) return null;
  const stale = data?.status === "stale" || !!error;
  const favorite =
    price.away < price.home ? "away" : price.home < price.away ? "home" : null;
  const book = side === "away" ? price.away_name : price.home_name;
  const value = side === "away" ? price.away : price.home;
  return (
    <span
      className={`team-moneyline ${favorite === side ? "ml-favorite" : ""} ${stale ? "warning-text" : ""}`}
      title={`${game[side].abbrev} best moneyline at ${book || price.name}`}
    >
      <span>{american(value)}</span>
      <small>{book || price.name}</small>
    </span>
  );
}
