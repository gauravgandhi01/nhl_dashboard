import { useEffect, useRef, useState } from "react";
import { RefreshButton } from "./RefreshButton";

export type Quote = {
  side: string;
  price: number;
  effective_price?: number | null;
  bookmaker: string;
  book: string;
  market?: string;
  source_side?: string;
  source_point?: number;
  updated_at: string | null;
};
export type PropLine = {
  id: string;
  market: string;
  point: number | null;
  alternate: boolean;
  quotes: Quote[];
};
export type PropPlayer = {
  id: number;
  name: string;
  team: string;
  markets: Record<string, PropLine[]>;
};
type PropGame = {
  game_id: number;
  eligible: boolean;
  status: string;
  retrieved_at: string | null;
  error: string | null;
  players: Record<string, PropPlayer>;
  unmatched_names: string[];
};
type PropData = {
  date: string;
  configured: boolean;
  manual_refresh_enabled?: boolean;
  games: Record<string, PropGame>;
  error: string | null;
  max_credits_per_game: number;
};
export type PropsState = ReturnType<typeof usePlayerProps>;

export const american = (n: number) => (n > 0 ? `+${n}` : String(n));
const shortBook: Record<string, string> = {
  ballybet: "Bally",
  betonlineag: "BOL",
  draftkings: "DK",
  fanatics: "FAN",
  fanduel: "FD",
  kalshi: "KAL",
  novig: "NV",
  prophetx: "PX",
  williamhill_us: "CZR",
};
const stamp = (s: string | null) =>
  s
    ? new Date(s).toLocaleString("en-US", {
        timeZone: "America/New_York",
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      }) + " ET"
    : "time unavailable";
const old = (q: Quote) =>
  !q.updated_at ||
  !Number.isFinite(Date.parse(q.updated_at)) ||
  Date.now() - Date.parse(q.updated_at) >= 3600000;
const oddsNotConfigured =
  "Odds not configured: add api_keys to the workspace keys.json file.";

export function bestQuote(line: PropLine | undefined, side: string) {
  const all = line?.quotes.filter((q) => q.side === side) || [];
  const fresh = all.filter((q) => !old(q));
  return [...(fresh.length ? fresh : all)].sort(
    (a, b) =>
      (b.effective_price ?? b.price) - (a.effective_price ?? a.price) ||
      a.bookmaker.localeCompare(b.bookmaker),
  )[0];
}

export function propLines(
  player: PropPlayer | undefined,
  family: string,
  standardOnly = false,
) {
  const lines =
    family === "scorer"
      ? [...(player?.markets.anytime || []), ...(player?.markets.goals || [])]
      : player?.markets[family] || [];
  const grouped = new Map<string, PropLine>();
  for (const raw of lines.filter((l) => !standardOnly || !l.alternate)) {
    // One goal is the same outcome whether offered as Anytime Yes or goals O0.5.
    const line =
      family === "scorer" && raw.point === 0.5
        ? {
            ...raw,
            market: "player_goal_scorer_anytime",
            point: null,
            alternate: false,
            quotes: raw.quotes.map((q) => ({
              ...q,
              source_side: q.side,
              source_point: 0.5,
              side:
                q.side === "over" ? "yes" : q.side === "under" ? "no" : q.side,
            })),
          }
        : raw;
    const key = line.point == null ? line.market : String(line.point);
    const existing = grouped.get(key);
    if (existing) {
      existing.quotes.push(...line.quotes);
      existing.alternate = existing.alternate && line.alternate;
    } else
      grouped.set(key, {
        ...line,
        id: `${family}:${key}`,
        quotes: [...line.quotes],
      });
  }
  return [...grouped.values()].sort((a, b) => {
    if (family === "scorer" && (a.point == null) !== (b.point == null))
      return a.point == null ? -1 : 1;
    if (family === "shots") {
      if (a.alternate !== b.alternate) return a.alternate ? 1 : -1;
      const count = (l: PropLine) =>
        new Set(
          l.quotes
            .filter((q) => l.alternate || !q.market?.endsWith("_alternate"))
            .map((q) => q.bookmaker),
        ).size;
      if (count(a) !== count(b)) return count(b) - count(a);
    }
    return (
      (a.point ?? 0) - (b.point ?? 0) ||
      Number(a.alternate) - Number(b.alternate) ||
      a.id.localeCompare(b.id)
    );
  });
}

export function usePlayerProps(date: string, gameId?: number, enabled = true) {
  const [data, setData] = useState<PropData | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const controller = useRef<AbortController | null>(null);
  const request = async (refresh = false, target = gameId) => {
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setBusy(true);
    setError(null);
    try {
      const params = new URLSearchParams({ date });
      if (target != null) params.set("game_id", String(target));
      const r = await fetch(
        `/api/player-props${refresh ? "/refresh" : ""}?${params}`,
        { method: refresh ? "POST" : "GET", signal: current.signal },
      );
      if (!r.ok) throw new Error();
      const body: PropData = await r.json();
      if (!current.signal.aborted)
        setData((previous) => ({
          ...body,
          games: {
            ...(previous?.date === date ? previous.games : {}),
            ...body.games,
          },
        }));
    } catch {
      if (!current.signal.aborted) setError("Player odds unavailable");
    } finally {
      if (!current.signal.aborted) setBusy(false);
    }
  };
  useEffect(() => {
    setData(null);
    setError(null);
    setBusy(false);
    if (enabled) void request();
    return () => controller.current?.abort();
  }, [date, gameId, enabled]);
  return {
    data: enabled && data?.date === date ? data : null,
    busy,
    error,
    load: (id?: number) => void request(true, id ?? gameId),
  };
}

export function PropsRefreshButton({ state, gameId }: { state: PropsState; gameId?: number }) {
  if (!state.data?.manual_refresh_enabled) return null;
  return <RefreshButton
    label="Player odds"
    ariaLabel={gameId == null ? "Refresh slate player odds" : "Refresh game player odds"}
    description={`Fetch latest player odds for ${gameId == null ? "all games on this date" : "this game"}. Uses odds API credits.`}
    busy={state.busy}
    onClick={() => state.load(gameId)}
  />;
}

export function PropsControls({
  state,
  gameId,
}: {
  state: PropsState;
  gameId?: number;
}) {
  const games = Object.values(state.data?.games || {}).filter(
    (g) => gameId == null || g.game_id === gameId,
  );
  const unmatched = games.reduce(
    (n, g) => n + (g.unmatched_names?.length || 0),
    0,
  );
  const unmatchedNames = games.flatMap((g) => g.unmatched_names || []);
  const status =
    state.error || state.data?.error || games.find((g) => g.error)?.error;
  const message = state.busy
    ? "Checking player odds"
    : status ||
      (state.data?.configured === false ? oddsNotConfigured : null);
  return (
    <div className="props-controls">
      {message && (
        <span className={status ? "warning" : "muted"} role="status">
          {message}
        </span>
      )}
      {unmatched > 0 && (
        <span
          className="warning"
          title={`Provider names without a unique match on this game's NHL rosters are excluded. Add aliases in config/player_aliases.json using provider name to NHL player ID. Names: ${unmatchedNames.join(", ")}`}
        >
          {unmatched} names need aliases
        </span>
      )}
    </div>
  );
}

function Price({
  quote,
  prefix = "",
  showBook = true,
}: {
  quote?: Quote;
  prefix?: string;
  showBook?: boolean;
}) {
  if (!quote) return <span className="prop-missing">{prefix} --</span>;
  const title = `${quote.book}: ${quote.side} ${american(quote.price)}${quote.source_side ? `; source: goals ${quote.source_side} ${quote.source_point}` : ""}${quote.market?.endsWith("_alternate") ? "; alternate market" : ""}; updated ${stamp(quote.updated_at)}`;
  return (
    <span
      className="prop-quote"
      title={title}
      tabIndex={0}
      aria-label={title}
    >
      {prefix && <span>{prefix} </span>}
      <b>{american(quote.price)}</b>
      {showBook && <small>{shortBook[quote.bookmaker] || quote.book}</small>}
    </span>
  );
}

const lineLabel = (line: PropLine) =>
  line.market === "player_goal_scorer_anytime"
    ? "ATG / O0.5"
    : line.point == null
      ? "First goal"
      : `${line.point}${line.alternate ? " alt" : ""}`;

function MarketRow({
  player,
  family,
  label,
}: {
  player?: PropPlayer;
  family: string;
  label: string;
}) {
  const lines = propLines(player, family);
  const [choice, setChoice] = useState("");
  const [book, setBook] = useState("best");
  const selected = lines.find((l) => l.id === choice) || lines[0];
  const books = [
    ...new Map(
      (selected?.quotes || []).map((q) => [q.bookmaker, q.book]),
    ).entries(),
  ];
  const selectedBook = books.some(([id]) => id === book) ? book : "best";
  const line =
    selectedBook === "best"
      ? selected
      : selected && {
          ...selected,
          quotes: selected.quotes.filter((q) => q.bookmaker === selectedBook),
        };
  const binary = selected?.point == null;
  return (
    <div className="prop-market-row">
      <span className="prop-market-label">{label}</span>
      {lines.length ? (
        <select
          aria-label={`${label} line`}
          value={selected.id}
          onChange={(e) => setChoice(e.target.value)}
        >
          {lines.map((l) => (
            <option key={l.id} value={l.id}>
              {lineLabel(l)}
            </option>
          ))}
        </select>
      ) : (
        <span className="prop-missing">Unavailable</span>
      )}
      <Price
        quote={bestQuote(line, binary ? "yes" : "over")}
        prefix={binary ? "Yes" : "O"}
      />
      <Price
        quote={bestQuote(line, binary ? "no" : "under")}
        prefix={binary ? "No" : "U"}
      />
      <select
        aria-label={`${label} sportsbook`}
        value={selectedBook}
        disabled={!books.length}
        onChange={(e) => setBook(e.target.value)}
      >
        <option value="best">Best prices</option>
        {books.map(([key, name]) => (
          <option key={key} value={key}>
            {name}
          </option>
        ))}
      </select>
    </div>
  );
}

export function PlayerPropPanel({
  state,
  gameId,
  playerId,
}: {
  state: PropsState;
  gameId: number;
  playerId: number;
}) {
  const game = state.data?.games[String(gameId)];
  const player = game?.players[String(playerId)];
  return (
    <section className="player-prop-panel" aria-label="Player props">
      <div className="prop-panel-heading">
        <h3>Player odds</h3>
        <span>
          {game?.retrieved_at
            ? `${!game.eligible ? "Pregame snapshot / " : ""}${stamp(game.retrieved_at)}`
            : "Not loaded"}
        </span>
      </div>
      <PropsControls state={state} gameId={gameId} />
      {[
        ["assists", "Assists"],
        ["scorer", "Goals"],
        ["points", "Points"],
        ["shots", "Shots on goal"],
        ["first_goal", "First goalscorer"],
      ].map(([family, label]) => (
        <MarketRow
          key={`${gameId}-${playerId}-${family}`}
          player={player}
          family={family}
          label={label}
        />
      ))}
    </section>
  );
}

export function CompactProps({
  state,
  gameId,
  playerId,
  family,
  showLabel = true,
  overOnly = false,
}: {
  state: PropsState;
  gameId: number;
  playerId?: number | null;
  family?: string;
  showLabel?: boolean;
  overOnly?: boolean;
}) {
  const game = state.data?.games[String(gameId)];
  const player = playerId != null ? game?.players[String(playerId)] : undefined;
  const families = family ? [family] : ["points", "shots", "scorer"];
  const rows = families.flatMap((f) => {
    const lines = propLines(player, f, f === "shots" && !family);
    const line =
      f === "scorer"
        ? lines.find((l) => l.point == null) || lines.find((l) => l.point === 0.5)
        : lines[0];
    const binary = f === "scorer";
    const over = bestQuote(line, line?.point == null ? "yes" : "over");
    const under = overOnly ? undefined : bestQuote(line, line?.point == null ? "no" : "under");
    if (!over && !under) return [];
    const label = f === "points" ? "PTS" : f === "shots" ? "SOG" : "ATG";
    return [{ f, line, binary, over, under, label }];
  });
  if (!rows.length) return null;
  return (
    <div
      className={`compact-props ${family ? "single-prop" : ""}`}
      aria-label="Quick player odds"
    >
      {rows.map(({ f, line, binary, over, under, label }) => {
        const showPointOnly =
          !showLabel &&
          line?.point != null &&
          !binary &&
          (f === "shots" || (f === "points" && line.point !== 0.5));
        return (
          <div className="compact-prop-row" key={f}>
            {showLabel && (
              <span className="compact-prop-label">
                {label}
                {line?.point != null && !binary && !(f === "points" && line.point === 0.5)
                  ? ` ${overOnly ? "O" : ""}${line.point}`
                  : ""}
              </span>
            )}
            {showPointOnly && (
              <span className="compact-prop-label">{line.point}</span>
            )}
            {over && (
              <Price
                quote={over}
                showBook={false}
              />
            )}
            {over && under && <span className="prop-slash">/</span>}
            {under && (
              <Price quote={under} showBook={false} />
            )}
          </div>
        );
      })}
      {game && !game.eligible && (
        <span className="prop-snapshot">Pregame snapshot</span>
      )}
    </div>
  );
}
