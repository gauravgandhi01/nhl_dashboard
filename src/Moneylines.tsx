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
  totals?: Record<string, {
    total: number; over: number; under: number;
    over_bookmaker: string; over_name: string; over_updated_at: string | null; over_effective?: number;
    under_bookmaker: string; under_name: string; under_updated_at: string | null; under_effective?: number;
    fair_over: number; paired_books: number;
  }>;
  totals_loaded?: boolean;
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
      if (!current.signal.aborted) setError("Game odds unavailable");
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
      label="Moneylines + totals"
      description={`Fetch latest moneylines and game totals for all games on this date. Uses odds API credits for two markets.${details ? ` ${details}` : ""}`}
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

const bookCodes: Record<string, string> = {
  ballybet: "BB", betmgm: "MG", betonlineag: "BO", betrivers: "BR",
  draftkings: "DK", fanatics: "FN", fanduel: "FD", kalshi: "KL",
  mybookieag: "MB", novig: "NV", prophetx: "PX", williamhill_us: "CZ",
  betonline: "BO", mybookie: "MB", caesars: "CZ", williamhill: "CZ",
};
export function sportsbookCode(key: string | undefined, name: string) {
  const known = bookCodes[key || ""] || bookCodes[name.toLowerCase().replace(/[^a-z0-9]/g, "")];
  if (known) return known;
  const words = name.replace(/([a-z])([A-Z])/g, "$1 $2").match(/[A-Za-z0-9]+/g) || [];
  return (words.length > 1 ? words.map(word => word[0]).join("").slice(0, 2) : words[0]?.slice(0, 2) || "--").toUpperCase();
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
  const bookKey = (side === "away" ? price.away_bookmaker : price.home_bookmaker) || price.bookmaker;
  return (
    <span
      className={`team-moneyline ${favorite === side ? "ml-favorite" : ""}`}
      title={`${game[side].abbrev} best moneyline at ${book || price.name}`}
    >
      <span>{american(value)}</span>
      <small title={book || price.name} aria-label={book || price.name}>{sportsbookCode(bookKey, book || price.name)}</small>
    </span>
  );
}

export function GameTotal({ game, odds }: { game: Game; odds: ReturnType<typeof useMoneylines> }) {
  const { data, error, busy } = odds;
  if (["PPD", "CNCL"].includes(game.schedule_state)) return null;
  const price = data?.totals?.[String(game.id)];
  const snapshot = !["FUT", "PRE"].includes(game.state) || new Date(game.start).getTime() <= Date.now();
  const stale = data?.status === "stale" || !!error;
  if (!price) return <div className="card-total card-total-empty" aria-label="Game total">
    {busy ? "Loading total…" : data?.status === "not_configured" ? "Total unavailable · odds not configured"
      : data?.totals_loaded === false || !data?.totals ? "Total not loaded" : "Total unavailable"}
  </div>;
  const outcome = (side: "over" | "under") => {
    const book = price[`${side}_name`];
    const effective = price[`${side}_effective`];
    return <span className="total-price" aria-label={`${side === "over" ? "Over" : "Under"} ${price.total}: ${american(price[side])} at ${book}`} title={`${side === "over" ? "Over" : "Under"} ${price.total} at ${book}. Updated ${stamp(price[`${side}_updated_at`])}.${effective != null && Math.abs(effective - price[side]) > .5 ? ` Estimated odds after fees: ${american(Math.round(effective))}.` : ""}`}>
      <span>{american(price[side])}</span>
      <small title={book}>{sportsbookCode(price[`${side}_bookmaker`], book)}</small>
    </span>;
  };
  return <div className={`card-total${stale ? " total-stale" : ""}`} aria-label={`Game total ${price.total}`}>
    <span className="total-line" title={`Offered game-total line closest to a 50/50 split across paired books after removing margin. Best prices shown at this exact line; books may differ. Integer totals can push. Retrieved ${stamp(data?.retrieved_at || null)}.`}><strong>{price.total}</strong></span>
    <span className="total-prices">{outcome("under")}{outcome("over")}</span>
    {(stale || snapshot) && <small className="total-status">{[stale && "Stale", snapshot && "Pregame snapshot"].filter(Boolean).join(" · ")}</small>}
  </div>;
}
