export const fmtNum = (n: number | null | undefined) => (n === null || n === undefined ? "–" : new Intl.NumberFormat("en-IN").format(n));
export const fmtPct = (n: number | null | undefined) => (n === null || n === undefined ? "–" : `${Math.round(n * 100)}%`);
export function fmtDate(iso: string | null | undefined, opts: Intl.DateTimeFormatOptions = { day: "numeric", month: "short", year: "numeric" }) {
  if (!iso) return "–";
  return new Intl.DateTimeFormat("en-IN", opts).format(new Date(iso));
}
export function timeAgo(iso: string | null | undefined) {
  if (!iso) return "never";
  const s = Math.max(1, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return "just now";
  const units: [number, string][] = [[86400, "d"], [3600, "h"], [60, "m"]];
  for (const [sec, label] of units) if (s >= sec) return `${Math.floor(s / sec)}${label} ago`;
  return "just now";
}
/** One decimal, as ratings are read (4.3, not 4.33). */
export const fmtRating = (n: number | null | undefined) => (n === null || n === undefined ? "–" : (Math.round(n * 10) / 10).toFixed(1));
export const fmtHours = (h: number | null | undefined) => (h === null || h === undefined ? "–" : h < 48 ? `${h}h` : `${Math.round(h / 24)}d`);
export const inr = (n: number) => new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(n);
export const isoDay = (d: Date) => d.toISOString().slice(0, 10);
export const LANGS = [{ v: "en", l: "English" }, { v: "hi", l: "हिन्दी (Hindi)" }, { v: "hinglish", l: "Hinglish" }];
export const TIMEZONES = ["Asia/Kolkata", "Asia/Dubai", "Asia/Singapore", "Europe/London", "America/New_York", "Australia/Sydney"];
export const CATEGORIES = ["Physiotherapy clinic", "Dental clinic", "Healthcare practice", "Restaurant", "Hotel", "Salon / Spa", "Automobile service centre", "Retail store", "Gym / Fitness", "Coaching institute", "Other local business"];
