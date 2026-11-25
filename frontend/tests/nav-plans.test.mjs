import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { PAGE_FEATURE, allows, featureFor } from "../src/lib/nav-features.ts";

// the real plan feature lists, read from the backend source of truth
const py = readFileSync(new URL("../../backend/app/services/plans.py", import.meta.url), "utf8");
const tuple = (name) => [...new RegExp(`^${name} = \\(([^)]*)\\)`, "m").exec(py)[1].matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
const CORE = tuple("CORE"), GROWTH_ADD = tuple("GROWTH_ADD"), PRO_ADD = tuple("PRO_ADD");
const plan = { launch: new Set(CORE), growth: new Set([...CORE, ...GROWTH_ADD]), scale: new Set([...CORE, ...GROWTH_ADD, ...PRO_ADD]) };
const hidden = (p) => Object.keys(PAGE_FEATURE).filter((h) => !allows(plan[p], h)).sort();

test("every page feature is a real plan feature (a typo would hide a page from everyone)", () => {
  const all = new Set([...CORE, ...GROWTH_ADD, ...PRO_ADD]);
  for (const [href, f] of Object.entries(PAGE_FEATURE)) assert.ok(all.has(f), `${href} needs "${f}", which no plan has`);
});

test("Launch sees reviews, the Google profile and QR growth, and none of the marketing, ranking or assistant pages", () => {
  assert.deepEqual(hidden("launch"), ["/ai/activity", "/ai/approvals", "/ai/automations", "/ai/changes", "/ai/operator", "/ai/studio", "/ai/tasks", "/ai/today", "/gbp/photos", "/gbp/posts", "/gbp/studio", "/seo/performance", "/seo/rankings"]);
  for (const kept of ["/overview", "/seo", "/seo/profile", "/gbp/info", "/gbp/reviews", "/reputation/drafts", "/reputation/insights", "/growth", "/gbp/cards", "/gbp/campaigns", "/growth/reports", "/settings", "/settings/billing"]) assert.ok(allows(plan.launch, kept), kept);
});

test("Growth and Scale see every page", () => {
  assert.deepEqual(hidden("growth"), []);
  assert.deepEqual(hidden("scale"), []);
});

test("nothing is hidden while the plan is not known yet, and an unlisted page is open to every plan", () => {
  for (const unknown of [null, undefined]) for (const h of Object.keys(PAGE_FEATURE)) assert.ok(allows(unknown, h));
  assert.ok(allows(plan.launch, "/some/new/page"));
});

test("the most specific listed page decides which feature a located page needs", () => {
  assert.equal(featureFor("/seo/profile", "/seo/profile", "/seo"), null);
  assert.equal(featureFor(undefined, "/seo/rankings", "/seo"), "keyword_tracking");
  assert.equal(featureFor(undefined, undefined, "/ai/activity"), "growth_agent");
});
