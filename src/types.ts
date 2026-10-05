import type { AppearanceLog } from "./lineCounts";

export type Source = {
  source: string;
  url: string;
  retrieved_at: string | null;
  status: "available" | "stale" | "unavailable";
  error?: string;
};
export type Starter = {
  name: string | null;
  status: string;
  updated_at: string | null;
  player_id?: number | null;
};
export type Team = {
  id: number;
  abbrev: string;
  name: string;
  logo: string;
  record: string | null;
  score: number | null;
  starter?: Starter;
};
export type Game = {
  id: number;
  date: string;
  season: number;
  start: string;
  state: string;
  schedule_state: string;
  game_type: number;
  venue: string;
  period: number | null;
  clock: { timeRemaining: string } | null;
  away: Team & { starter: Starter };
  home: Team & { starter: Starter };
};
export type Stats = Record<string, number | null>;
export type Player = {
  id: number;
  name: string;
  position: string;
  number?: number;
  headshot?: string;
  stats: Stats;
  summary?: Stats;
};
export type Log = {
  gameId: number;
  gameDate: string;
  homeRoad: string;
  opponentTeamAbbrev: string;
  goalsFor: number;
  goalsAgainst: number;
  scoreFor: number | null;
  scoreAgainst: number | null;
  result: string;
};
export type Side = {
  team: Team;
  summary: Stats;
  advanced: Stats;
  recent: Log[];
  rest: { days: number | null; back_to_back: boolean };
  starter: Starter;
  goalies: Player[];
  roster: Player[];
  roster_source: Source;
  lineup: {
    sections: Record<string, string[]>;
    updated_at: string | null;
  } | null;
  // Keyed by NHL player ID, independent of provider display names.
  lineup_usage: Record<string, Stats>;
  lineup_logs?: Record<string, AppearanceLog | null>;
  lineup_player_ids?: Record<string, number | null>;
  lineup_source: Source;
  injuries: {
    name: string;
    player_id: number | null;
    status: string;
    note: string;
    updated_at: string;
  }[];
  injury_source: Source;
  stats_source: Source;
};
export type SlateData = {
  date: string;
  games: Game[];
  comparisons?: Record<string, CardComparison>;
  sources: Source[];
  error: string | null;
  next_date?: string | null;
};
export type CardSide = {
  ranks?: Record<string, { rank: number | null; eligible: number }>;
  signals?: { id: string; label: string; detail: string }[];
  summary: Stats;
  advanced: Stats;
  form: { result: string; date: string; opponent: string; home?: boolean }[];
  goalie: {
    name: string | null;
    basis: string;
    stats: Stats;
    advanced_games: number;
  };
};
export type CardComparison = {
  season_label: string;
  previous_season: boolean;
  away: CardSide;
  home: CardSide;
};
export type MatchupData = {
  game: Game;
  season: number;
  season_label: string;
  previous_season: boolean;
  window: string;
  as_of: string;
  away: Side;
  home: Side;
  sources: Source[];
};
