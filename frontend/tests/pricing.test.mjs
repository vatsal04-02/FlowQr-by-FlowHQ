import test from "node:test";
import assert from "node:assert/strict";
import { termPrice, effectiveMonthlyPaise, termSaving, newFeatureGroups, FEATURE_GROUPS, HELD_BACK, LIMIT_ROWS, PLAN_ORDER } from "../src/lib/pricing.ts";

// Same numbers the server serves (backend/app/services/plans.py). The screen itself never contains these: this is a test fixture shaped like the /billing/plans answer.
const rupees = (o) => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, v * 100]));
const terms = { months: [1, 3, 6, 12], checkout_open: false, prices_paise: {
  starter: rupees({ 1: 499, 3: 1399, 6: 2699, 12: 4999 }), growth: rupees({ 1: 799, 3: 2299, 6: 4299, 12: 7999 }), pro: rupees({ 1: 1299, 3: 3699, 6: 6999, 12: 12999 }) } };

test("all twelve plan and duration prices come from the served list", () => {
  const want = { starter: [499, 1399, 2699, 4999], growth: [799, 2299, 4299, 7999], pro: [1299, 3699, 6999, 12999] };
  for (const [code, list] of Object.entries(want)) [1, 3, 6, 12].forEach((m, i) => assert.equal(termPrice(terms, code, m), list[i] * 100, `${code} ${m}`));
});

test("a missing price is null, never zero or a guess", () => {
  assert.equal(termPrice(null, "growth", 3), null);
  assert.equal(termPrice({ ...terms, prices_paise: {} }, "growth", 3), null);
  assert.equal(termPrice(terms, "growth", 2), null);
  assert.equal(termPrice(terms, "nope", 1), null);
});

test("effective monthly price is the term price over its months, in whole rupees", () => {
  assert.equal(effectiveMonthlyPaise(49900, 1), 49900);
  assert.equal(effectiveMonthlyPaise(139900, 3), 46600);   // 466.33
  assert.equal(effectiveMonthlyPaise(269900, 6), 45000);   // 449.83
  assert.equal(effectiveMonthlyPaise(499900, 12), 41700);  // 416.58
  assert.equal(effectiveMonthlyPaise(1299900, 12), 108300); // 1083.25
});

test("savings are computed against the plan's own monthly price and never hard-coded", () => {
  assert.equal(termSaving(terms, "starter", 1), null);
  assert.deepEqual(termSaving(terms, "starter", 3), { paise: 9800, percent: 7 });    // 1497 - 1399
  assert.deepEqual(termSaving(terms, "starter", 12), { paise: 98900, percent: 17 }); // 5988 - 4999
  assert.deepEqual(termSaving(terms, "growth", 6), { paise: 49500, percent: 10 });   // 4794 - 4299
  assert.deepEqual(termSaving(terms, "pro", 12), { paise: 258900, percent: 17 });    // 15588 - 12999
  // change the monthly price and the saving moves with it
  const changed = { ...terms, prices_paise: { ...terms.prices_paise, starter: { ...terms.prices_paise.starter, 1: 59900 } } };
  assert.deepEqual(termSaving(changed, "starter", 3), { paise: 39800, percent: 22 });
});

test("no saving is shown when a longer term costs the same or more", () => {
  const flat = { ...terms, prices_paise: { starter: { 1: 50000, 3: 150000 } } };
  assert.equal(termSaving(flat, "starter", 3), null);
  assert.equal(termSaving({ ...terms, prices_paise: { starter: { 3: 100000 } } }, "starter", 3), null); // no monthly price to compare with
});

test("every longer term is cheaper per month than the one before it", () => {
  for (const code of PLAN_ORDER) {
    const per = [1, 3, 6, 12].map((m) => termPrice(terms, code, m) / m);
    for (let i = 1; i < per.length; i++) assert.ok(per[i] < per[i - 1], `${code} term ${i}`);
  }
});

const plan = (code, features, o = {}) => ({ code, name: code, price_paise: 0, currency: "INR", interval: "monthly", max_locations: 1, monthly_ai_generations: 0, review_generations: 1, review_replies: 1, max_staff: 1, features, ...o });
const CORE = ["review_sync", "ai_replies", "review_generation", "qr_campaigns", "review_analytics", "gbp_connection", "gbp_info"];
const GROWTH = [...CORE, "gbp_posts", "gbp_media", "gbp_performance", "insights", "local_seo", "keyword_tracking", "geo_ranking", "autonomy", "ai_posts", "profile_optimizer", "growth_agent"];

test("a plan lists only the features its entitlements actually include", () => {
  const launch = newFeatureGroups(plan("starter", CORE), null).flatMap((g) => g.items);
  assert.ok(launch.includes("Google review sync") && launch.includes("AI reply drafts"));
  assert.ok(!launch.includes("Google Posts") && !launch.includes("Keyword tracking"));
});

test("a higher plan lists what it adds, not what the lower plan already had", () => {
  const launch = plan("starter", CORE), growth = plan("growth", GROWTH), scale = plan("pro", [...GROWTH, "multi_location"]);
  const added = newFeatureGroups(growth, launch).flatMap((g) => g.items);
  assert.ok(added.includes("Keyword tracking") && added.includes("AI-written Google Posts"));
  assert.ok(!added.includes("Google review sync"));
  assert.deepEqual(newFeatureGroups(scale, growth).flatMap((g) => g.items), ["Multi-location management"]);
});

test("held-back entitlements are never advertised and the claims we cannot back do not exist", () => {
  const labels = FEATURE_GROUPS.flatMap((g) => g.items.map(([k, l]) => [k, l.toLowerCase()]));
  for (const k of HELD_BACK) assert.ok(!labels.some(([key]) => key === k), k);
  for (const [, l] of labels) { assert.ok(!/campaigns? a month|posts? a month|30 post|5 campaign|geo|map pack|autonom/.test(l), l); }
  assert.deepEqual(LIMIT_ROWS.map((r) => r.id), ["locations", "staff", "review_generations", "review_replies"]);
});

test("limit rows read the plan row, they do not hold numbers of their own", () => {
  const p = plan("growth", GROWTH, { max_locations: 7, max_staff: 9, review_generations: 11, review_replies: 13 });
  assert.deepEqual(LIMIT_ROWS.map((r) => r.value(p)), [7, 9, 11, 13]);
});
