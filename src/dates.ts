export const et = "America/New_York";

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
