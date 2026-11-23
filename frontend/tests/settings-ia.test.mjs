import test from "node:test";
import assert from "node:assert/strict";
import { GROUPS, ROWS, rowsFor, rowAt, searchRows } from "../src/components/settings/model.ts";
import { describeAudit, whenText } from "../src/lib/audit-text.ts";
import { LEGACY_ROUTES } from "../src/lib/legacy-routes.mjs";

test("settings has the six groups from the brief, in order, and every row belongs to one", () => {
  assert.deepEqual(GROUPS.map((g) => g.label), ["Your account", "Business", "Connected accounts", "Preferences", "Billing", "Security & activity"]);
  for (const r of ROWS) assert.ok(GROUPS.some((g) => g.id === r.group), r.id);
});

test("row subtitles are short plain language (under 40 characters)", () => {
  for (const r of ROWS) assert.ok(r.sub.length < 40, `${r.id}: ${r.sub.length}`);
});

test("Google has exactly one home and every address is unique", () => {
  const google = ROWS.filter((r) => r.href.includes("connections/google"));
  assert.equal(google.length, 1);
  const hrefs = ROWS.map((r) => r.href);
  assert.equal(new Set(hrefs).size, hrefs.length);
});

test("staff do not see billing or the audit log; owners and admins do", () => {
  const ids = (role) => rowsFor(role).map((r) => r.id);
  for (const id of ["plan", "payments", "audit"]) { assert.ok(!ids("staff").includes(id), id); assert.ok(ids("owner").includes(id), id); assert.ok(ids("admin").includes(id), id); }
  assert.ok(ids("staff").includes("notifications"));
});

test("the longest matching address wins, so Payments is not Plan and AI tabs stay on one row", () => {
  assert.equal(rowAt("/settings/billing/payments")?.id, "payments");
  assert.equal(rowAt("/settings/billing")?.id, "plan");
  assert.equal(rowAt("/settings/ai/brain")?.id, "ai");
  assert.equal(rowAt("/settings/connections/google")?.id, "google");
  assert.equal(rowAt("/settings/connections")?.id, "connections");
  assert.equal(rowAt("/overview"), null);
});

test("search matches titles, subtitles and group names, and nothing for an empty box", () => {
  assert.deepEqual(searchRows(ROWS, ""), []);
  assert.ok(searchRows(ROWS, "notif").some((r) => r.id === "notifications"));
  assert.ok(searchRows(ROWS, "time zone").some((r) => r.id === "region"));
  assert.ok(searchRows(ROWS, "billing").some((r) => r.id === "plan"));
  assert.deepEqual(searchRows(ROWS, "zzzz"), []);
});

test("the old guided-setup address still reaches the Google page", () => {
  assert.ok(LEGACY_ROUTES.some(([from, to]) => from === "/gbp/connect" && to === "/settings/connections/google"));
});

test("audit entries read as sentences, with a readable fallback and no raw JSON", () => {
  assert.equal(describeAudit("reply.approve", "me@x.com", "ME@x.com"), "You approved a reply");
  assert.equal(describeAudit("staff.invite", "priya@x.com", "me@x.com"), "priya@x.com invited a team member");
  assert.equal(describeAudit("post.approve", null), "FlowQR approved a post");
  assert.equal(describeAudit("rank.grid_scan", null), "Rank grid scan");
  assert.equal(describeAudit("rank.grid_scan", "a@x.com"), "a@x.com: rank grid scan");
});

test("the date reads like '21 Nov, 8:37 pm' and a bad date reads as nothing", () => {
  assert.match(whenText("2026-11-21T15:07:00Z", "en-IN"), /^21 Nov, \d{1,2}:\d{2} (am|pm)$/);
  assert.equal(whenText("nonsense"), "");
});
