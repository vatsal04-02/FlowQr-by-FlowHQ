import test from "node:test";
import assert from "node:assert/strict";
import { agencyTone, canCheckAgain, canStop, parseConsent, dateLine } from "../src/lib/agency-ui.ts";

test("every backend status has a tone and an unknown one is neutral, never a guess", () => {
  for (const s of ["consented", "invited", "accepted", "verified", "active", "needs_attention", "stopping", "stopped", "lost", "cancelled", "failed"]) assert.ok(agencyTone(s));
  assert.equal(agencyTone("active"), "ok");
  assert.equal(agencyTone("lost"), "bad");
  assert.equal(agencyTone("something-new"), "idle");
});

test("check again and stop are offered only where they make sense", () => {
  assert.ok(canCheckAgain("invited") && canCheckAgain("needs_attention"));
  assert.ok(!canCheckAgain("stopped") && !canCheckAgain("lost") && !canCheckAgain("active"));
  assert.ok(canStop("active") && canStop("invited"));
  assert.ok(!canStop("stopped") && !canStop("lost") && !canStop("consented"));
});

test("the consent text is shown exactly as sent: a lead and its bullets, nothing dropped or added", () => {
  const text = "FlowQR would like to join.\n\nWhat this means:\n- The role is Manager, never Owner.\n- You can stop at any time.";
  const c = parseConsent(text);
  assert.deepEqual(c.bullets, ["The role is Manager, never Owner.", "You can stop at any time."]);
  assert.equal(c.lead, "FlowQR would like to join. What this means:");
});

test("date lines say only what is recorded", () => {
  const fmt = (x) => `<${x}>`;
  assert.equal(dateLine({ status: "active", accepted_at: "2026-11-21", removal_deadline_at: null }, fmt), "FlowQR became your Manager on <2026-11-21>.");
  assert.match(dateLine({ status: "stopping", accepted_at: null, removal_deadline_at: "2026-12-02" }, fmt), /removed itself by <2026-12-02>/);
  assert.equal(dateLine({ status: "invited", accepted_at: null, removal_deadline_at: null }, fmt), null);
});
