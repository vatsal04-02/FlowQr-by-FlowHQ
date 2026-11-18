// The public pricing section's content: the plans exactly as the owner specified them (SPEC below), with the PRICES read from the prepaid price list the server serves
// (GET /billing/plans `terms`, which has these same amounts) so a price can never be typed wrong here.
//
// SPEC is the commercial specification. The backend's entitlement system (backend/app/services/plans.py) does not match it everywhere; `discrepancies()` lists every mismatch, a test pins
// the list, and nothing here changes what the backend gives a plan. A bullet that maps to a real entitlement key (local SEO, keyword tracking, profile optimiser, ...) is shown only
// if the plan row has that key.
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

// ----------------------------------------------------------------------------------------------------------------------------------- the specification
export interface Spec {
  position: string;
  /** monthly allowances (they reset every month, on yearly plans too; never multiplied) */
  writing: number; replies: number;
  analytics: string;
  localSeo: "Included" | "Advanced" | null;
  advancedSeo: "Included" | "Advanced" | null;
  /** AI-generated post texts a month, null = not included */
  posts: number | null;
  /** AI marketing campaigns a month, null = not included */
  campaigns: number | null;
}
export const SPEC: Record<string, Spec> = {
  starter: { position: "Essential review management for small businesses.", writing: 200, replies: 200, analytics: "Basic", localSeo: null, advancedSeo: null, posts: null, campaigns: null },
  growth: { position: "Review management with local SEO and business growth capabilities.", writing: 400, replies: 400, analytics: "Advanced", localSeo: "Included", advancedSeo: "Included", posts: null, campaigns: null },
  pro: { position: "Advanced local SEO, AI-powered growth and marketing.", writing: 600, replies: 600, analytics: "Advanced, with ranking insights", localSeo: "Advanced", advancedSeo: "Advanced", posts: 30, campaigns: 5 },
};
/** Specified but not yet an entitlement in the backend: shown with its number AND a "Coming soon" tag, so the page never says it is live. */
export const NOT_YET_BUILT = new Set(["campaigns"]);

/** Everything on the specification that the entitlement system does not match, in plain words. Reported, never "fixed": this module changes nothing about what a plan gets. */
export function discrepancies(plans: Plan[]): string[] {
  const out: string[] = [];
  const by = Object.fromEntries(plans.map((p) => [p.code, p]));
  for (const [code, s] of Object.entries(SPEC)) {
    const p = by[code];
    if (!p) { out.push(`${code}: no plan row`); continue; }
    if (p.review_generations !== s.writing) out.push(`${p.name}: AI review writing is ${n(p.review_generations)} a month in the plan row, ${n(s.writing)} in the specification`);
    if (p.review_replies !== s.replies) out.push(`${p.name}: AI review replies are ${n(p.review_replies)} a month in the plan row, ${n(s.replies)} in the specification`);
    if (s.posts === null && has(p, "ai_posts")) out.push(`${p.name}: has the AI post-text entitlement, the specification says none`);
    if (s.posts !== null && has(p, "ai_posts")) out.push(`${p.name}: AI post text is an entitlement without a monthly count, the specification says ${s.posts} a month (nothing enforces ${s.posts})`);
    if (s.posts !== null && !has(p, "ai_posts")) out.push(`${p.name}: the specification gives AI post text, the plan has no such entitlement`);
    if (s.campaigns !== null) out.push(`${p.name}: "AI marketing campaigns, ${s.campaigns} a month" is not an entitlement in the backend at all`);
    if ((s.localSeo === null) === has(p, "local_seo")) out.push(`${p.name}: local SEO is ${has(p, "local_seo") ? "included" : "not included"} in the plan row, the specification says ${s.localSeo ?? "none"}`);
  }
  const seo = (p?: Plan) => ["local_seo", "keyword_tracking", "geo_ranking", "autonomy", "profile_optimizer"].filter((k) => p && has(p, k)).join(",");
  if (by.growth && by.pro && SPEC.pro.localSeo === "Advanced" && seo(by.growth) === seo(by.pro)) out.push("Scale: \"Advanced\" local SEO and ranking insights are the same entitlements as Growth's (there is no separate advanced tier in the backend)");
  return out;
}

// ----------------------------------------------------------------------------------------------------------------------------------- what the page shows
export const POSITION = Object.fromEntries(Object.entries(SPEC).map(([k, v]) => [k, v.position])) as Record<string, string>;

/** The bullets on a plan card, in the specification's words. Ones that map to a real entitlement need the plan row to have it. */
export function cardPoints(p: Plan): { text: string; soon?: boolean }[] {
  const s = SPEC[p.code];
  if (!s) return [];
  const out: { text: string; soon?: boolean }[] = [];
  out.push({ text: `${n(s.writing)} AI-assisted review-writing operations a month` });
  out.push({ text: `${n(s.replies)} AI-generated review replies a month` });
  out.push({ text: `${s.analytics} analytics` });
  out.push({ text: "Core review management" });
  if (has(p, "qr_campaigns")) out.push({ text: "QR-based review collection" });
  if (s.localSeo && has(p, "local_seo")) out.push({ text: s.localSeo === "Advanced" ? "Advanced local SEO" : "Local SEO features" });
  if (s.advancedSeo && has(p, "keyword_tracking")) out.push({ text: p.code === "pro" ? "Advanced ranking insights" : "Keyword and local ranking insights" });
  if (p.code === "growth" && has(p, "profile_optimizer")) out.push({ text: "Business profile optimisation" });
  if (s.posts !== null) out.push({ text: `${n(s.posts)} AI-generated post texts a month` });
  if (s.campaigns !== null) out.push({ text: `${n(s.campaigns)} AI marketing campaigns a month`, soon: NOT_YET_BUILT.has("campaigns") });
  if (p.code === "pro") {
    if (has(p, "growth_agent")) out.push({ text: "AI Growth Agent: a daily plan you approve" });
    if (has(p, "profile_optimizer")) out.push({ text: "Business profile optimisation" });
    if (has(p, "multi_location")) out.push({ text: `Up to ${p.max_locations} business locations` });
  }
  return out;
}

export type Cell = { kind: "value"; text: string; soon?: boolean } | { kind: "yes" } | { kind: "no" };
export interface Row { id: string; label: string; note?: string; cells: Record<string, Cell> }

/** The comparison table: the seven things the specification compares. A dash means "not included". */
export function comparisonRows(plans: Plan[]): Row[] {
  const each = (f: (s: Spec, p: Plan) => Cell) => Object.fromEntries(plans.map((p) => [p.code, SPEC[p.code] ? f(SPEC[p.code], p) : ({ kind: "no" } as Cell)]));
  const text = (t: string | null): Cell => (t ? { kind: "value", text: t } : { kind: "no" });
  const num = (v: number | null, unit: string, soon = false): Cell => (v === null ? { kind: "no" } : { kind: "value", text: `${n(v)} ${unit}`, soon });
  const monthly = "Resets every month, including on yearly plans.";
  return [
    { id: "writing", label: "AI review writing allowance", note: monthly, cells: each((s) => num(s.writing, "a month")) },
    { id: "replies", label: "AI review reply allowance", note: monthly, cells: each((s) => num(s.replies, "a month")) },
    { id: "analytics", label: "Analytics", cells: each((s) => text(s.analytics)) },
    { id: "local_seo", label: "Local SEO", cells: each((s) => text(s.localSeo)) },
    { id: "advanced_seo", label: "Advanced SEO and ranking insights", cells: each((s) => text(s.advancedSeo)) },
    { id: "posts", label: "AI post generation", note: monthly, cells: each((s) => num(s.posts, "post texts a month")) },
    { id: "campaigns", label: "AI marketing campaigns", note: monthly, cells: each((s) => num(s.campaigns, "a month", NOT_YET_BUILT.has("campaigns"))) },
  ];
}
