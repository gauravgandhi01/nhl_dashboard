export const et = "America/New_York";

// Calendar dates must not shift when the viewer is in a different time zone.
export const formatDate = (value: string) =>
  value.replace(/^\d{4}-(\d{2})-(\d{2})$/, "$1/$2");

export const formatTimestamp = (value: string | null, fallback = "Unavailable") => {
  if (!value || !Number.isFinite(Date.parse(value))) return fallback;
  return new Date(value).toLocaleString("en-US", {
    timeZone: et,
    month: "2-digit",
    day: "2-digit",
    hour: "numeric",
    minute: "2-digit",
  }) + " ET";
};

export const todayEt = () => {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: et,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const value = Object.fromEntries(parts.map((p) => [p.type, p.value]));
  return `${value.year}-${value.month}-${value.day}`;
};
