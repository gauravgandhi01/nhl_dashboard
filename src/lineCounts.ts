export type AppearanceLog = {
  goals: (number | null)[];
  assists: (number | null)[];
  points: (number | null)[];
  shots: (number | null)[];
};

export type LineCount = {
  games: number;
  over: number;
  under: number;
  push: number;
};

const WINDOWS = [
  ["L5", 5],
  ["L10", 10],
  ["Season", null],
] as const;

export function countWindow(
  values: (number | null)[] | undefined,
  point: number,
  limit: number | null,
): LineCount | null {
  if (!values) return null;
  const sample = (limit == null ? values : values.slice(0, limit)).filter(
    (value): value is number => value != null && Number.isFinite(value),
  );
  let over = 0,
    under = 0,
    push = 0;
  for (const value of sample) {
    if (value > point) over += 1;
    else if (value < point) under += 1;
    else push += 1;
  }
  return { games: sample.length, over, under, push };
}

export function statLine(
  family: string,
  point: number | null,
): { key: keyof AppearanceLog; point: number; label: string } | null {
  if (family === "assists" && point != null) return { key: "assists", point, label: "assists" };
  if (family === "points" && point != null) return { key: "points", point, label: "points" };
  if (family === "shots" && point != null) return { key: "shots", point, label: "shots" };
  if (family === "scorer") return { key: "goals", point: point ?? 0.5, label: "goals" };
  return null;
}

export function formatCount(count: LineCount) {
  const base = `${count.over}/${count.games}`;
  if (!count.push) return base;
  return `${base} · ${count.push} push${count.push === 1 ? "" : "es"}`;
}

export function countTitle(
  window: string,
  count: LineCount,
  point: number,
  stat: string,
) {
  const windowName = window === "L5" ? "Last 5" : window === "L10" ? "Last 10" : "Season";
  if (!count.games) return `${windowName}: no recorded ${stat} in this window.`;
  const pushes = `${count.push} push${count.push === 1 ? "" : "es"}`;
  return `${windowName}: ${count.over} of ${count.games} appearances over ${point} ${stat}. ${pushes}. Count of regular-season appearances before this date, not a probability.`;
}

export function lineWindows(log: AppearanceLog | null | undefined, family: string, point: number | null) {
  const spec = statLine(family, point);
  if (log == null || !spec) return null;
  const values = log[spec.key];
  if (!values?.length) return { empty: true as const, spec, windows: [] };
  return {
    empty: false as const,
    spec,
    windows: WINDOWS.map(([label, limit]) => ({
      label,
      count: countWindow(values, spec.point, limit),
    })),
  };
}
