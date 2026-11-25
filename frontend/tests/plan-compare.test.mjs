import test from "node:test";
import assert from "node:assert/strict";
import { termPrice, termSaving } from "../src/lib/pricing.ts";
import { periodPrice, yearlySaving, sellablePlans, cardPoints, comparisonRows, discrepancies, SPEC, NOT_YET_BUILT, BILLING_SUFFIX, BILLING_MONTHS } from "../src/lib/plan-compare.ts";

// A fixture shaped like GET /billing/plans as production serves it today (the amounts and entitlements live in backend/app/services/plans.py).
const R = (o) => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, v * 100]));
const terms = { months: [1, 3, 6, 12], checkout_open: true, prices_paise: { starter: R({ 1: 499, 3: 1399, 6: 2699, 12: 4999 }), growth: R({ 1: 799, 3: 2299, 6: 4299, 12: 7999 }), pro: R({ 1: 1299, 3: 3699, 6: 6999, 12: 12999 }) } };
const CORE = ["review_sync", "ai_replies", "review_generation", "qr_campaigns", "review_analytics", "gbp_connection", "gbp_info"];
const GROWTH = [...CORE, "gbp_posts", "gbp_media", "gbp_performance", "insights", "local_seo", "keyword_tracking", "geo_ranking", "autonomy", "ai_posts", "profile_optimizer", "growth_agent"];
const plan = (code, name, gens, reps, locs, staff, features) => ({ code, name, price_paise: 0, currency: "INR", interval: "monthly", max_locations: locs, monthly_ai_generations: gens + reps, review_generations: gens, review_replies: reps, max_staff: staff, features });
const plans = [plan("starter", "Launch", 150, 150, 1, 3, CORE), plan("growth", "Growth", 300, 300, 1, 10, GROWTH), plan("pro", "Scale", 500, 500, 10, 50, [...GROWTH, "multi_location"])];

test("the two billing options take the monthly and the 12-month price from the served list", () => {
  assert.deepEqual(BILLING_MONTHS, { monthly: 1, yearly: 12 });
  assert.deepEqual(BILLING_SUFFIX, { monthly: "/month", yearly: "/year" });
  const want = { starter: [499, 4999], growth: [799, 7999], pro: [1299, 12999] };
  for (const [code, [m, y]] of Object.entries(want)) {
    assert.equal(periodPrice(terms, code, "monthly"), m * 100, code + " monthly");
    assert.equal(periodPrice(terms, code, "yearly"), y * 100, code + " yearly");
  }
});

test("no price in the list means no price on the page: never a guess", () => {
  assert.equal(periodPrice(undefined, "growth", "monthly"), null);
  assert.equal(periodPrice(terms, "nope", "yearly"), null);
  const partial = { ...terms, prices_paise: { ...terms.prices_paise, growth: { 1: 79900 } } };
  assert.deepEqual(sellablePlans(plans, partial).map((p) => p.code), ["starter", "pro"]);
  assert.deepEqual(sellablePlans(plans, undefined), []);
});

test("the yearly saving is arithmetic against the plan's own monthly price, nothing else", () => {
  assert.equal(yearlySaving(terms, "starter").paise, 499 * 12 * 100 - 4999 * 100);
  assert.equal(yearlySaving(terms, "growth").paise, 799 * 12 * 100 - 7999 * 100);
  assert.equal(yearlySaving(terms, "pro").paise, 1299 * 12 * 100 - 12999 * 100);
  assert.equal(yearlySaving(undefined, "growth"), null);
});

test("the two lookups agree with lib/pricing.ts for every plan and term", () => {
  for (const code of ["starter", "growth", "pro"]) {
    assert.equal(periodPrice(terms, code, "monthly"), termPrice(terms, code, 1));
    assert.equal(periodPrice(terms, code, "yearly"), termPrice(terms, code, 12));
    assert.deepEqual(yearlySaving(terms, code), termSaving(terms, code, 12));
  }
});

test("the comparison table is the specification's seven rows with its exact values", () => {
  const rows = comparisonRows(plans);
  assert.deepEqual(rows.map((r) => r.label), ["AI review writing allowance", "AI review reply allowance", "Analytics", "Local SEO", "Advanced SEO and ranking insights", "AI post generation", "AI marketing campaigns"]);
  const text = (id) => plans.map((p) => { const c = rows.find((r) => r.id === id).cells[p.code]; return c.kind === "value" ? c.text : c.kind; });
  assert.deepEqual(text("writing"), ["150 a month", "300 a month", "500 a month"]);
  assert.deepEqual(text("replies"), ["150 a month", "300 a month", "500 a month"]);
  assert.deepEqual(text("analytics"), ["Basic", "Advanced", "Advanced, with ranking insights"]);
  assert.deepEqual(text("local_seo"), ["no", "Included", "Advanced"]);
  assert.deepEqual(text("advanced_seo"), ["no", "Included", "Advanced"]);
  assert.deepEqual(text("posts"), ["no", "no", "30 post texts a month"]);
  assert.deepEqual(text("campaigns"), ["no", "no", "5 a month"]);
});

test("allowances are monthly and say so; nothing is multiplied for yearly or called unlimited", () => {
  const rows = comparisonRows(plans);
  for (const id of ["writing", "replies", "posts", "campaigns"]) assert.match(rows.find((r) => r.id === id).note, /Resets every month, including on yearly plans/);
  const all = JSON.stringify([rows, plans.map(cardPoints)]);
  assert.ok(!/unlimited|\b(2,400|4,800|7,200|360)\b/i.test(all), "no yearly totals, no unlimited");
});

test("a campaign that is not built is shown with its number and a Coming soon mark, never as live", () => {
  assert.ok(NOT_YET_BUILT.has("campaigns"));
  const c = comparisonRows(plans).find((r) => r.id === "campaigns").cells.pro;
  assert.deepEqual(c, { kind: "value", text: "5 a month", soon: true });
  assert.deepEqual(cardPoints(plans[2]).find((x) => /campaigns/.test(x.text)), { text: "5 AI marketing campaigns a month", soon: true });
  assert.ok(!cardPoints(plans[0]).concat(cardPoints(plans[1])).some((x) => /AI marketing campaigns/.test(x.text)));
});

test("card bullets follow the specification, and Launch has no SEO", () => {
  const t = (p) => cardPoints(p).map((x) => x.text);
  assert.deepEqual(t(plans[0]), ["150 AI-assisted review-writing operations a month", "150 AI-generated review replies a month", "Basic analytics", "Core review management", "QR-based review collection"]);
  assert.deepEqual(t(plans[1]).slice(0, 6), ["300 AI-assisted review-writing operations a month", "300 AI-generated review replies a month", "Advanced analytics", "Core review management", "QR-based review collection", "Local SEO features"]);
  assert.ok(t(plans[1]).includes("Business profile optimisation") && t(plans[1]).includes("Keyword and local ranking insights"));
  assert.ok(t(plans[2]).includes("500 AI-assisted review-writing operations a month") && t(plans[2]).includes("30 AI-generated post texts a month") && t(plans[2]).includes("Advanced local SEO"));
  // an item that maps to a real entitlement disappears if the plan row lacks it
  const bare = { ...plans[1], features: plans[1].features.filter((f) => f !== "local_seo") };
  assert.ok(!t(bare).includes("Local SEO features"));
});

test("every difference between the specification and the entitlement system is reported (and nothing is changed)", () => {
  const d = discrepancies(plans);
  assert.deepEqual(d, [
    "Growth: has the AI post-text entitlement, the specification says none",
    "Scale: AI post text is an entitlement without a monthly count, the specification says 30 a month (nothing enforces 30)",
    "Scale: \"AI marketing campaigns, 5 a month\" is not an entitlement in the backend at all",
    "Scale: \"Advanced\" local SEO and ranking insights are the same entitlements as Growth's (there is no separate advanced tier in the backend)",
  ]);
  const drifted = plans.map((p) => (p.code === "pro" ? { ...p, review_generations: 600, review_replies: 600 } : p));
  assert.ok(discrepancies(drifted).length > d.length, "a plan row that drifts from the specification is reported");
  assert.equal(SPEC.pro.writing, 500);
});
