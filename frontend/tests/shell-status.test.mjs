// Run with: npm test   (Node's built-in runner; Node 22.6+ strips the TypeScript types itself, so there is no new dependency)
import test from "node:test";
import assert from "node:assert/strict";
import { googleLine, syncChip, crumbParts, showTrialChip } from "../src/lib/shell-status.ts";

test("googleLine: unknown while loading, never a guess", () => {
  assert.equal(googleLine(undefined), null);
  assert.equal(googleLine(null), null);
});
test("googleLine: connected only when a connection is active", () => {
  assert.deepEqual(googleLine([{ status: "active" }])?.label, "Google connected");
  assert.equal(googleLine([{ status: "active" }])?.tone, "ok");
  assert.equal(googleLine([{ status: "disconnected" }, { status: "active" }])?.label, "Google connected");
});
test("googleLine: needs-attention and not-connected states are honest", () => {
  assert.equal(googleLine([{ status: "error" }])?.label, "Reconnect Google");
  assert.equal(googleLine([{ status: "revoked" }])?.tone, "warn");
  assert.equal(googleLine([{ status: "pending_selection" }])?.label, "Choose your Google locations");
  assert.equal(googleLine([])?.label, "Google not connected");
  assert.equal(googleLine([{ status: "disconnected" }])?.tone, "idle");
});

test("syncChip: nothing to sync means no chip", () => {
  assert.equal(syncChip(undefined), null);
  assert.equal(syncChip([]), null);
  assert.equal(syncChip([{ selected: false, last_synced_at: "2026-11-17T08:00:00Z", last_sync_status: "ok" }]), null);
});
test("syncChip: newest successful time across selected locations", () => {
  const c = syncChip([
    { selected: true, last_synced_at: "2026-11-17T08:00:00Z", last_sync_status: "ok" },
    { selected: true, last_synced_at: "2026-11-17T09:30:00Z", last_sync_status: "ok" },
    { selected: false, last_synced_at: "2026-11-17T11:00:00Z", last_sync_status: "ok" },
  ]);
  assert.equal(c?.kind, "ok");
  assert.equal(c?.lastSyncedAt, "2026-11-17T09:30:00Z");
});
test("syncChip: first sync not done yet", () => {
  const c = syncChip([{ selected: true, last_synced_at: null, last_sync_status: null }]);
  assert.equal(c?.kind, "waiting");
  assert.equal(c?.label, "Waiting for first sync");
});
test("syncChip: Google asking us to wait is a warning, a failure is a problem", () => {
  const paused = syncChip([{ selected: true, last_synced_at: "2026-11-17T08:00:00Z", last_sync_status: "rate_limited" }]);
  assert.equal(paused?.kind, "paused"); assert.equal(paused?.tone, "warn");
  const failed = syncChip([{ selected: true, last_synced_at: null, last_sync_status: "rate_limited" }, { selected: true, last_synced_at: null, last_sync_status: "error" }]);
  assert.equal(failed?.kind, "failed"); assert.equal(failed?.tone, "bad");
  assert.equal(failed?.lastSyncedAt, null);
});

test("crumbParts: destination, page, tab, without repeats", () => {
  assert.deepEqual(crumbParts(null), []);
  assert.deepEqual(crumbParts({ dest: { label: "Home" }, child: null, tab: null }), ["Home"]);
  assert.deepEqual(crumbParts({ dest: { label: "GBP" }, child: { label: "Rankings" }, tab: null }), ["GBP", "Rankings"]);
  assert.deepEqual(crumbParts({ dest: { label: "GBP" }, child: { label: "Profile" }, tab: { label: "Photos" } }), ["GBP", "Profile", "Photos"]);
  assert.deepEqual(crumbParts({ dest: { label: "Activity" }, child: { label: "Activity" }, tab: null }), ["Activity"]);
  assert.deepEqual(crumbParts({ dest: { label: "GBP" }, child: { label: "Profile" }, tab: { label: "Profile" } }), ["GBP", "Profile"]);
});

test("showTrialChip: last five days of a trial, never on billing", () => {
  assert.equal(showTrialChip(null, "/overview"), false);
  assert.equal(showTrialChip({ status: "active", trial_days_left: null }, "/overview"), false);
  assert.equal(showTrialChip({ status: "trialing", trial_days_left: 12 }, "/overview"), false);
  assert.equal(showTrialChip({ status: "trialing", trial_days_left: 5 }, "/overview"), true);
  assert.equal(showTrialChip({ status: "trialing", trial_days_left: 0 }, "/seo"), true);
  assert.equal(showTrialChip({ status: "trialing", trial_days_left: 2 }, "/settings/billing"), false);
  assert.equal(showTrialChip({ status: "trialing", trial_days_left: 2 }, "/settings/billing/payments"), false);
});
