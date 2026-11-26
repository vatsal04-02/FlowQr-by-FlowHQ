import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { LEGACY_ROUTES } from "../src/lib/legacy-routes.mjs";
import { ROWS } from "../src/components/settings/model.ts";

// nav.ts draws React icons, so it is read as text: the structure it declares is what these tests pin down.
const nav = readFileSync(new URL("../src/lib/nav.ts", import.meta.url), "utf8");
const dests = nav.slice(nav.indexOf("export const DESTS"), nav.indexOf("export const BOTTOM_IDS"));
const hrefs = new Set([...dests.matchAll(/href: "(\/[a-z0-9/_-]*)"/g)].map((m) => m[1]).concat([...dests.matchAll(/"(\/[a-z0-9/_-]+)"/g)].map((m) => m[1])));

test("the app has exactly four places: Home, AI, Google and Settings", () => {
  assert.deepEqual([...dests.matchAll(/^\s{2}\{ id: "([a-z]+)"/gm)].map((m) => m[1]), ["home", "ai", "google", "settings"]);
  assert.match(nav, /BOTTOM_IDS = \["home", "ai", "google", "settings"\] as const/);
});

test("every page of the signed-in app is reachable from one of the four places", () => {
  const root = new URL("../src/app/(app)", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
  const pages = [];
  const walk = (dir, url) => {
    for (const name of readdirSync(dir)) {
      const p = join(dir, name);
      if (statSync(p).isDirectory()) walk(p, `${url}/${name}`);
      else if (name === "page.tsx") pages.push(url || "/");
    }
  };
  walk(root, "");
  assert.ok(pages.length > 40, `found ${pages.length} pages`);
  const settingsHrefs = new Set(ROWS.map((r) => r.href));
  const covered = (page) => [...hrefs, ...settingsHrefs].some((h) => page === h || page.startsWith(h + "/"));
  // pages of unfinished integrations are deliberately not listed (see nav.ts)
  const unlisted = (page) => /^\/(ai\/studio\/(assets|brand|calendar|social)|website|gbp\/(connect|hours|inbox))/.test(page) || page === "/";
  const orphans = pages.filter((p) => !p.includes("[") && !unlisted(p) && !covered(p));
  assert.deepEqual(orphans, []);
});

test("the AI settings live inside AI, and nothing is left behind under Settings", () => {
  for (const tab of ["voice", "brain", "autonomy", "usage"]) assert.ok(hrefs.has(`/ai/settings/${tab}`), tab);
  assert.ok(!ROWS.some((r) => r.href.startsWith("/settings/ai") || r.href.startsWith("/ai/settings")));
  assert.ok(![...hrefs].some((h) => h.startsWith("/settings/ai")));
  for (const tab of ["voice", "brain", "autonomy", "usage"]) assert.ok(LEGACY_ROUTES.some(([from, to]) => from === `/settings/ai/${tab}` && to === `/ai/settings/${tab}`), `old /settings/ai/${tab} redirects`);
});

test("Google holds reviews, search, profile, posts, photos, review growth and locations; AI holds the assistant, studio, WhatsApp and its settings", () => {
  const google = dests.slice(dests.indexOf('id: "google"'), dests.indexOf('id: "settings"'));
  for (const h of ["/gbp/reviews", "/reputation/drafts", "/seo/rankings", "/seo/performance", "/seo/profile", "/gbp/posts", "/gbp/photos", "/growth", "/gbp/cards", "/gbp/campaigns", "/growth/reports", "/gbp/locations"]) assert.ok(google.includes(`"${h}"`), h);
  const ai = dests.slice(dests.indexOf('id: "ai"'), dests.indexOf('id: "google"'));
  for (const h of ["/ai/today", "/ai/automations", "/ai/operator", "/gbp/studio", "/ai/studio", "/ai/tasks", "/ai/approvals", "/ai/changes", "/ai/activity", "/whatsapp", "/ai/settings/voice"]) assert.ok(ai.includes(`"${h}"`), h);
});

test("no redirect points at a page that has itself moved (one hop only)", () => {
  const from = new Set(LEGACY_ROUTES.map(([f]) => f));
  for (const [f, to] of LEGACY_ROUTES) assert.ok(!from.has(to.replace(/\?.*$/, "")), `${f} -> ${to} chains`);
});
