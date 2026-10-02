import { useEffect, useRef, useState } from "react";
import { RefreshButton } from "./RefreshButton";
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
  manual_refresh_enabled?: boolean;
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
const oddsNotConfigured =
  "Odds not configured: add api_keys to the workspace keys.json file.";

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
  const { data, busy, error } = odds;
  const details = [
    error || data?.error,
    data?.retrieved_at ? `Retrieved ${stamp(data.retrieved_at)}` : null,
    data?.usage?.remaining != null
      ? `${data.usage.remaining} credits at retrieval`
      : null,
  ]
    .filter(Boolean)
    .join(" / ");
  if (!data?.manual_refresh_enabled) return null;
  return (
    <RefreshButton
      label="Moneylines"
      description={`Fetch latest moneylines for all games on this date. Uses odds API credits.${details ? ` ${details}` : ""}`}
      busy={busy}
      onClick={odds.load}
    />
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
  return (
    <section className="moneyline-card" aria-label="Moneylines">
      <div className="moneyline-heading">
        <span>Moneyline / best available</span>
        <span className="muted">
          {postponed
            ? "Postponed / canceled"
            : snapshot
              ? "Pregame snapshot"
              : "American"}
        </span>
      </div>
      {!postponed && prices.length ? (
        prices.map((p) => {
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
                <small>
                  {p.away_name || p.name}
                  {" / "}
                  {stamp(p.away_updated_at || p.updated_at)}
                </small>
              </strong>
              <span>
                {p.name}
              </span>
              <strong className={favorite === "home" ? "ml-favorite" : ""}>
                {american(p.home)}
                <small>
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
            ? oddsNotConfigured
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
  const favorite =
    price.away < price.home ? "away" : price.home < price.away ? "home" : null;
  const book = side === "away" ? price.away_name : price.home_name;
  const value = side === "away" ? price.away : price.home;
  return (
    <span
      className={`team-moneyline ${favorite === side ? "ml-favorite" : ""}`}
      title={`${game[side].abbrev} best moneyline at ${book || price.name}`}
    >
      <span>{american(value)}</span>
      <small>{book || price.name}</small>
    </span>
  );
}
