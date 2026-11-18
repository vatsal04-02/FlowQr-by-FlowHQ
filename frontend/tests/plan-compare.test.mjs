import test from "node:test";
import assert from "node:assert/strict";
import { termPrice, termSaving } from "../src/lib/pricing.ts";
import { periodPrice, yearlySaving, sellablePlans, cardPoints, comparisonRows, COMING_SOON, BILLING_SUFFIX, BILLING_MONTHS } from "../src/lib/plan-compare.ts";

// A fixture shaped like GET /billing/plans (the real numbers live only in backend/app/services/plans.py; the page reads them from the server).
const R = (o) => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, v * 100]));
const terms = { months: [1, 3, 6, 12], checkout_open: false, prices_paise: { starter: R({ 1: 499, 3: 1399, 6: 2699, 12: 4999 }), growth: R({ 1: 799, 3: 2299, 6: 4299, 12: 7999 }), pro: R({ 1: 1299, 3: 3699, 6: 6999, 12: 12999 }) } };
const CORE = ["review_sync", "ai_replies", "review_generation", "qr_campaigns", "review_analytics", "gbp_connection", "gbp_info"];
const GROWTH = [...CORE, "gbp_posts", "gbp_media", "gbp_performance", "insights", "local_seo", "keyword_tracking", "geo_ranking", "autonomy", "ai_posts", "profile_optimizer", "growth_agent"];
const plan = (code, name, gens, reps, locs, staff, features) => ({ code, name, price_paise: 0, currency: "INR", interval: "monthly", max_locations: locs, monthly_ai_generations: gens + reps, review_generations: gens, review_replies: reps, max_staff: staff, features });
const plans = [plan("starter", "Launch", 200, 200, 1, 3, CORE), plan("growth", "Growth", 400, 400, 1, 10, GROWTH), plan("pro", "Scale", 800, 800, 10, 50, [...GROWTH, "multi_location"])];

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
  assert.deepEqual(sellablePlans(plans, partial).map((p) => p.code), ["starter", "pro"]);  // a plan missing its yearly price is left out whole
  assert.deepEqual(sellablePlans(plans, undefined), []);
});

test("the yearly saving is arithmetic against the plan's own monthly price, nothing else", () => {
  assert.equal(yearlySaving(terms, "starter").paise, 499 * 12 * 100 - 4999 * 100);
  assert.equal(yearlySaving(terms, "growth").paise, 799 * 12 * 100 - 7999 * 100);
  assert.equal(yearlySaving(terms, "pro").paise, 1299 * 12 * 100 - 12999 * 100);
  assert.equal(yearlySaving(undefined, "growth"), null);
});

test("allowances shown are the plan rows' own numbers, monthly, never multiplied for yearly", () => {
  const rows = comparisonRows(plans);
  const gen = rows.find((r) => r.id === "review_generations"), rep = rows.find((r) => r.id === "review_replies");
  assert.deepEqual(plans.map((p) => gen.cells[p.code].text), ["200 a month", "400 a month", "800 a month"]);   // Scale shows what the backend enforces
  assert.deepEqual(plans.map((p) => rep.cells[p.code].text), ["200 a month", "400 a month", "800 a month"]);
  assert.match(gen.note, /Resets every month, including on yearly plans/);
  for (const p of plans) assert.ok(!JSON.stringify(cardPoints(p)).match(/year|12/i), "no yearly credit totals on a card");
});

test("a feature appears for a plan only if its entitlement does", () => {
  const rows = Object.fromEntries(comparisonRows(plans).map((r) => [r.id, r]));
  assert.deepEqual(plans.map((p) => rows.local_seo.cells[p.code].kind), ["no", "yes", "yes"]);
  assert.deepEqual(plans.map((p) => rows.keyword_tracking.cells[p.code].kind), ["no", "yes", "yes"]);
  assert.deepEqual(plans.map((p) => rows.ai_posts.cells[p.code].kind), ["no", "yes", "yes"]);
  assert.deepEqual(plans.map((p) => rows.analytics.cells[p.code].text), ["Basic review analytics", "Review analytics + Google profile insights", "Review analytics + Google profile insights"]);
  assert.deepEqual(plans.map((p) => rows.locations.cells[p.code].text), ["1", "1", "10"]);
  const launch = cardPoints(plans[0]).map((x) => x.text).join("|");
  assert.ok(!/SEO|ranking|Growth Agent|Google Post/.test(launch), "Launch has none of the Growth features");
  // if the backend later removes a feature from a plan, the page follows with no code change
  const trimmed = plans.map((p) => (p.code === "growth" ? { ...p, features: p.features.filter((f) => f !== "local_seo") } : p));
  assert.equal(comparisonRows(trimmed).find((r) => r.id === "local_seo").cells.growth.kind, "no");
});

test("specified-but-not-built items are labelled Coming soon, carry no number and are never 'included'", () => {
  assert.deepEqual(COMING_SOON.map((c) => [c.id, c.plan]), [["campaigns", "pro"]]);
  const row = comparisonRows(plans).find((r) => r.id === "campaigns");
  assert.deepEqual(plans.map((p) => row.cells[p.code].kind), ["no", "no", "soon"]);
  const pts = cardPoints(plans[2]).filter((x) => x.soon);
  assert.deepEqual(pts, [{ text: "AI marketing campaigns", soon: true }]);
  assert.ok(!/\d/.test(pts[0].text));
  for (const p of [plans[0], plans[1]]) assert.ok(!cardPoints(p).some((x) => /campaign/i.test(x.text) && !/QR/.test(x.text)));
});

test("the two lookups agree with lib/pricing.ts for every plan and term", () => {
  for (const code of ["starter", "growth", "pro"]) {
    assert.equal(periodPrice(terms, code, "monthly"), termPrice(terms, code, 1));
    assert.equal(periodPrice(terms, code, "yearly"), termPrice(terms, code, 12));
    assert.deepEqual(yearlySaving(terms, code), termSaving(terms, code, 12));
  }
});
