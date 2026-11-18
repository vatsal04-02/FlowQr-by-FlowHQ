// The public pricing section's content, built ONLY from what the server serves (GET /billing/plans: the plan rows and the prepaid price list `terms`).
// No price, allowance or feature is written in this file. What this file adds is wording, order, and the choice of which entitlement keys to show, so the page can never promise
// more than the entitlement system gives a plan. The one exception is COMING_SOON: things the owner has specified but that are not entitlements yet; they are labelled as such and
// carry no number.
import type { Terms } from "./pricing";
import type { Plan } from "./types";

// Two lookups, written out here so this file has no runtime imports (the test runner and the type checker disagree about ".ts" in import paths); tests/plan-compare.test.mjs checks them
// against lib/pricing.ts termPrice / termSaving for every plan and term.
const priceOf = (terms: Terms | null | undefined, code: string, months: number): number | null => {
  const v = terms?.prices_paise?.[code]?.[String(months)];
  return typeof v === "number" && v > 0 ? v : null;
};

export type Billing = "monthly" | "yearly";
export const BILLING_MONTHS: Record<Billing, number> = { monthly: 1, yearly: 12 };
export const BILLING_SUFFIX: Record<Billing, string> = { monthly: "/month", yearly: "/year" };
/** What the buyer is told about paying, per option. True of the prepaid purchase (one payment for the period, no automatic renewal, no mandate). */
export const BILLING_NOTE: Record<Billing, string> = {
  monthly: "Pay for one month at a time. It does not renew by itself.",
  yearly: "Pay once for 12 months. It does not renew by itself.",
};

/** The plan's price for the chosen option, in paise, straight from the served list; null when the server has no such price. */
export function periodPrice(terms: Terms | null | undefined, code: string, billing: Billing): number | null {
  return priceOf(terms, code, BILLING_MONTHS[billing]);
}

/** Paying for 12 months at once compared with paying the plan's own monthly price twelve times (computed from the same list; there is no other "was" price anywhere). */
export function yearlySaving(terms: Terms | null | undefined, code: string): { paise: number; percent: number } | null {
  const year = priceOf(terms, code, 12), month = priceOf(terms, code, 1);
  if (year === null || month === null) return null;
  const paise = month * 12 - year;
  return paise > 0 ? { paise, percent: Math.round((paise / (month * 12)) * 100) } : null;
}

/** A plan is shown only when the list has BOTH of its prices, so the toggle never lands on a missing number. */
export function sellablePlans(plans: Plan[], terms: Terms | null | undefined): Plan[] {
  return plans.filter((p) => periodPrice(terms, p.code, "monthly") !== null && periodPrice(terms, p.code, "yearly") !== null);
}

const has = (p: Plan, k: string) => p.features.includes(k);
export const n = (v: number) => v.toLocaleString("en-IN");

/** Specified by the owner, not yet an entitlement in the backend: shown as "Coming soon" with no number, never as included. */
export const COMING_SOON: { id: string; label: string; plan: string }[] = [
  { id: "campaigns", label: "AI marketing campaigns", plan: "pro" },
];

/** One short line each: what the plan is for. */
export const POSITION: Record<string, string> = {
  starter: "Essential review management for small businesses.",
  growth: "Review management with local SEO and business growth tools.",
  pro: "AI-powered growth for more locations and a bigger team.",
};

/** The bullets on a plan card. Each one is present only if the plan's own entitlements say so; the numbers are the plan row's. */
export function cardPoints(p: Plan): { text: string; soon?: boolean }[] {
  const out: { text: string; soon?: boolean }[] = [];
  out.push({ text: `${n(p.review_generations)} AI review-writing suggestions a month` });
  out.push({ text: `${n(p.review_replies)} AI review replies a month` });
  out.push({ text: has(p, "insights") || has(p, "gbp_performance") ? "Review analytics and Google profile insights" : "Basic review analytics" });
  if (has(p, "qr_campaigns")) out.push({ text: "QR and NFC review campaigns" });
  if (has(p, "local_seo")) out.push({ text: "Local SEO" });
  if (has(p, "keyword_tracking")) out.push({ text: "Keyword and local ranking tracking" });
  if (has(p, "ai_posts")) out.push({ text: "AI-written Google Post text" });
  if (has(p, "profile_optimizer")) out.push({ text: "AI profile optimiser" });
  if (has(p, "growth_agent")) out.push({ text: "AI Growth Agent: a daily plan you approve" });
  if (has(p, "multi_location")) out.push({ text: `Up to ${p.max_locations} business locations` });
  for (const c of COMING_SOON) if (c.plan === p.code) out.push({ text: c.label, soon: true });
  return out;
}

export type Cell = { kind: "value"; text: string } | { kind: "yes" } | { kind: "no" } | { kind: "soon" };
export interface Row { id: string; label: string; note?: string; cells: Record<string, Cell> }

/** The comparison table, one row per thing a buyer decides on. A boolean row is a tick or a dash from the plan's entitlement; a number row is the plan row's number. */
export function comparisonRows(plans: Plan[]): Row[] {
  const each = (f: (p: Plan) => Cell) => Object.fromEntries(plans.map((p) => [p.code, f(p)]));
  const yes = (k: string) => (p: Plan): Cell => (has(p, k) ? { kind: "yes" } : { kind: "no" });
  const rows: Row[] = [
    { id: "review_generations", label: "AI review writing", note: "A month. Resets every month, including on yearly plans.", cells: each((p) => ({ kind: "value", text: `${n(p.review_generations)} a month` })) },
    { id: "review_replies", label: "AI review replies", note: "A month. Resets every month, including on yearly plans.", cells: each((p) => ({ kind: "value", text: `${n(p.review_replies)} a month` })) },
    { id: "analytics", label: "Analytics", cells: each((p) => ({ kind: "value", text: has(p, "insights") || has(p, "gbp_performance") ? "Review analytics + Google profile insights" : "Basic review analytics" })) },
    { id: "local_seo", label: "Local SEO", cells: each(yes("local_seo")) },
    { id: "keyword_tracking", label: "Keyword and local ranking tracking", cells: each(yes("keyword_tracking")) },
    { id: "ai_posts", label: "AI-written Google Post text", cells: each(yes("ai_posts")) },
    { id: "growth_agent", label: "AI Growth Agent (daily plan you approve)", cells: each(yes("growth_agent")) },
    { id: "locations", label: "Business locations", cells: each((p) => ({ kind: "value", text: n(p.max_locations) })) },
    { id: "staff", label: "Team members", cells: each((p) => ({ kind: "value", text: n(p.max_staff) })) },
  ];
  for (const c of COMING_SOON) rows.push({ id: c.id, label: c.label, cells: each((p) => (p.code === c.plan ? { kind: "soon" } : { kind: "no" })) });
  return rows;
}
