// Pricing logic for the prepaid plan screen. Pure functions only (tested with node --test), no React.
//
// THE AMOUNTS ARE NOT HERE. They live in one place, backend/app/services/plans.py (TERM_PRICES_PAISE), and arrive through GET /billing/plans as `terms`.
// Nothing below invents or caches a price: if the server sends no terms, the screen shows "unavailable" instead of a guess.
// A saving is always computed against the plan's own 1-month price from the same list. There is no "was" price anywhere in this file, on purpose.
import type { Plan, PrepaidTerms as Terms } from "./types";
export type { Terms };

/** The prepaid price of `code` for `months`, in paise, or null when the server has no such price. */
export function termPrice(terms: Terms | null | undefined, code: string, months: number): number | null {
  const v = terms?.prices_paise?.[code]?.[String(months)];
  return typeof v === "number" && v > 0 ? v : null;
}

/** What one month costs on that term, in whole rupees expressed in paise (a 3-month price of Rs 1,399 is Rs 466 a month). */
export function effectiveMonthlyPaise(totalPaise: number, months: number): number {
  return Math.round(totalPaise / months / 100) * 100;
}

export interface Saving { paise: number; percent: number }

/** How much less this term costs than paying for the same number of months at the plan's own 1-month price. null when there is no saving to show (1 month, a missing price, or no difference). */
export function termSaving(terms: Terms | null | undefined, code: string, months: number): Saving | null {
  if (months <= 1) return null;
  const total = termPrice(terms, code, months), one = termPrice(terms, code, 1);
  if (total === null || one === null) return null;
  const paise = one * months - total;
  if (paise <= 0) return null;
  return { paise, percent: Math.round((paise / (one * months)) * 100) };
}

export const monthsLabel = (m: number) => (m === 1 ? "1 month" : `${m} months`);
export const termTabLabel = (m: number) => (m === 1 ? "Monthly" : `${m} months`);

// ------------------------------------------------------------------------------------------------------------------------------- what each plan includes
// Presentation only: which backend entitlement key sits in which group, in plain words. Whether a plan HAS a key comes from the plan row served by the API (`features`),
// never from this file. Keys not listed here are deliberately not advertised (see HELD_BACK).

export interface FeatureGroup { id: string; title: string; items: readonly (readonly [string, string])[] }

export const FEATURE_GROUPS: readonly FeatureGroup[] = [
  { id: "reviews", title: "Review management", items: [["review_sync", "Google review sync"], ["qr_campaigns", "QR and NFC review campaigns"], ["review_generation", "AI review suggestions for customers"]] },
  { id: "ai", title: "AI assistance", items: [["ai_replies", "AI reply drafts"], ["ai_posts", "AI-written Google Posts"], ["profile_optimizer", "AI profile optimiser"], ["growth_agent", "AI growth agent"]] },
  { id: "marketing", title: "Marketing", items: [["gbp_posts", "Google Posts"], ["gbp_media", "Photo management"], ["multi_location", "Multi-location management"]] },
  { id: "seo", title: "Local SEO", items: [["gbp_connection", "Google Business Profile connection"], ["gbp_info", "Edit business info, hours and categories"], ["local_seo", "Local SEO"], ["keyword_tracking", "Keyword tracking"]] },
  { id: "analytics", title: "Analytics", items: [["review_analytics", "Review analytics"], ["insights", "Sentiment and topic insights"], ["gbp_performance", "Google performance metrics"]] },
];

/** Real entitlements that exist in the backend but are not advertised here: they are not ready to be sold as a headline benefit. Listed so the omission is visible and deliberate. */
export const HELD_BACK: readonly string[] = ["geo_ranking", "autonomy"];

/** Plan order, lowest first. Growth is the recommended plan. */
export const PLAN_ORDER = ["starter", "growth", "pro"] as const;
export const RECOMMENDED = "growth";
export const POSITIONING: Record<string, string> = {
  starter: "Start managing your reputation",
  growth: "Improve your local visibility",
  pro: "Turn local presence into a growth engine",
};

/** The groups of features this plan has that the plan below it does not (the first plan: everything it has). Empty groups are dropped. */
export function newFeatureGroups(plan: Plan, below: Plan | null): { id: string; title: string; items: string[] }[] {
  const have = new Set(plan.features), had = new Set(below?.features ?? []);
  return FEATURE_GROUPS
    .map((g) => ({ id: g.id, title: g.title, items: g.items.filter(([k]) => have.has(k) && !had.has(k)).map(([, label]) => label) }))
    .filter((g) => g.items.length > 0);
}

export interface LimitRow { id: string; label: string; value: (p: Plan) => number }
/** The numeric limits that the plan really enforces (entitlements.py): locations, team members, and the two monthly AI allowances. */
export const LIMIT_ROWS: readonly LimitRow[] = [
  { id: "locations", label: "Business locations", value: (p) => p.max_locations },
  { id: "staff", label: "Team members", value: (p) => p.max_staff },
  { id: "review_generations", label: "AI review suggestions a month", value: (p) => p.review_generations },
  { id: "review_replies", label: "AI review replies a month", value: (p) => p.review_replies },
];

/** Every advertised feature, in display order, for the comparison table: [group title, key, label]. */
export const ALL_FEATURE_ROWS: readonly (readonly [string, string, string])[] = FEATURE_GROUPS.flatMap((g) => g.items.map(([k, l]) => [g.title, k, l] as const));
