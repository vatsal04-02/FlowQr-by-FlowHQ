import test from "node:test";
import assert from "node:assert/strict";
import {
  JOURNEY_STATES, STATE_TONE, stateTone, stateLabel, isWorking, isEnded, pollDelay, stepTone, stepWord, progressSummary, initialActions, toggleAction, actionsToSend, canApprove,
  visibleActions, actionLabel, OPERATOR_FILTERS, stateCounts, WORKING_STATES,
} from "../src/lib/agency-journey.ts";

const CATALOG = [
  { id: "read_reviews", label: "Read", description: "", required: true }, { id: "reply_to_reviews", label: "Reply", description: "", required: false },
  { id: "publish_posts", label: "Post", description: "", required: false }, { id: "edit_profile", label: "Edit", description: "", required: false },
];

test("there are exactly the thirteen journey states, each with a tone and a label, and an unknown one is neutral", () => {
  assert.deepEqual([...JOURNEY_STATES], ["NOT_STARTED", "CUSTOMER_OAUTH_PENDING", "CUSTOMER_CONSENT_PENDING", "LOCATION_SELECTION_PENDING", "MANAGER_INVITE_CREATING", "MANAGER_INVITE_PENDING",
    "AGENCY_ACCEPTANCE_PENDING", "ACCESS_VERIFICATION_PENDING", "CONNECTED", "FAILED", "REVOKED", "EXPIRED", "BLOCKED"]);
  for (const s of JOURNEY_STATES) { assert.ok(STATE_TONE[s], s); assert.notEqual(stateLabel(s), s); }
  assert.equal(stateTone("CONNECTED"), "ok");
  assert.equal(stateTone("FAILED"), "bad");
  assert.equal(stateTone("BLOCKED"), "warn");
  assert.equal(stateTone("SOMETHING_NEW"), "idle");
  assert.equal(stateLabel("SOMETHING_NEW"), "SOMETHING_NEW");
});

test("only states where FlowQR or Google is working are polled, and the pauses grow", () => {
  assert.deepEqual([...WORKING_STATES], ["MANAGER_INVITE_CREATING", "MANAGER_INVITE_PENDING", "AGENCY_ACCEPTANCE_PENDING", "ACCESS_VERIFICATION_PENDING"]);
  for (const s of JOURNEY_STATES) assert.equal(pollDelay(s, 0) !== null, isWorking(s), s);
  assert.equal(pollDelay("CONNECTED", 0), null);
  assert.equal(pollDelay("BLOCKED", 0), null);
  assert.equal(pollDelay("CUSTOMER_CONSENT_PENDING", 0), null); // waiting for a person: no polling
  assert.ok(pollDelay("AGENCY_ACCEPTANCE_PENDING", 0) < pollDelay("AGENCY_ACCEPTANCE_PENDING", 5 * 60_000));
  assert.ok(pollDelay("AGENCY_ACCEPTANCE_PENDING", 5 * 60_000) < pollDelay("AGENCY_ACCEPTANCE_PENDING", 60 * 60_000));
  assert.ok(isEnded("REVOKED") && isEnded("EXPIRED") && isEnded("FAILED") && !isEnded("CONNECTED") && !isEnded("BLOCKED"));
});

test("a step is described in words as well as colour, and an unknown status is shown neutrally", () => {
  for (const s of ["done", "current", "waiting", "pending", "blocked", "failed"]) { assert.ok(stepTone(s)); assert.ok(stepWord(s)); }
  assert.equal(stepTone("done"), "ok");
  assert.equal(stepTone("blocked"), "warn");
  assert.equal(stepWord("waiting"), "In progress");
  assert.equal(stepTone("mystery"), "idle");
});

test("progress counts only the steps the server reported as done, never a step that is merely waiting", () => {
  const steps = [{ key: "a", label: "A", status: "done" }, { key: "b", label: "B", status: "done" }, { key: "c", label: "C", status: "waiting" }, { key: "d", label: "D", status: "pending" }];
  assert.deepEqual(progressSummary(steps), { done: 2, total: 4, next: steps[2] });
  assert.equal(progressSummary(steps.map((s) => ({ ...s, status: "done" }))).next, null);
  assert.equal(progressSummary([{ key: "a", label: "A", status: "blocked" }]).done, 0);
});

test("nothing is pre-approved beyond reading, a required category cannot be unticked, an unknown one cannot be added", () => {
  assert.deepEqual(initialActions(CATALOG), ["read_reviews"]);
  let chosen = initialActions(CATALOG);
  chosen = toggleAction(chosen, "reply_to_reviews", CATALOG);
  assert.deepEqual(chosen, ["read_reviews", "reply_to_reviews"]);
  assert.deepEqual(toggleAction(chosen, "reply_to_reviews", CATALOG), ["read_reviews"]); // untick
  assert.deepEqual(toggleAction(chosen, "read_reviews", CATALOG), chosen); // reading stays
  assert.deepEqual(toggleAction(chosen, "take_over_my_account", CATALOG), chosen); // unknown: ignored
});

test("what is sent is the ticked categories plus reading, in the catalog's order, whatever the tick order was", () => {
  assert.deepEqual(actionsToSend(["edit_profile", "reply_to_reviews"], CATALOG), ["read_reviews", "reply_to_reviews", "edit_profile"]);
  assert.deepEqual(actionsToSend([], CATALOG), ["read_reviews"]);
  assert.deepEqual(actionsToSend(["nonsense"], CATALOG), ["read_reviews"]);
});

test("approve is enabled only with the agreement, an admin, a location, and the server offering it", () => {
  const ok = { agreed: true, canAct: true, offered: ["approve", "disconnect"], locations: 1 };
  assert.equal(canApprove(ok), true);
  assert.equal(canApprove({ ...ok, agreed: false }), false);
  assert.equal(canApprove({ ...ok, canAct: false }), false);
  assert.equal(canApprove({ ...ok, offered: ["disconnect"] }), false); // e.g. blocked: the server did not offer it
  assert.equal(canApprove({ ...ok, locations: 0 }), false);
});

test("buttons: only what the server offered, only to someone who may act, in a fixed order", () => {
  assert.deepEqual(visibleActions(["disconnect", "check_again", "connect", "approve", "select_location"], true), ["connect", "check_again", "disconnect"]);
  assert.deepEqual(visibleActions(["disconnect", "check_again"], false), []);
  assert.deepEqual(visibleActions([], true), []);
  assert.deepEqual(visibleActions(["made_up", "restart"], true), ["restart"]);
  assert.equal(actionLabel("disconnect"), "Stop FlowQR managing my profile");
  assert.equal(actionLabel("made_up"), "made_up");
});

test("the operator can filter by every state and see counts only for states that have businesses", () => {
  assert.equal(OPERATOR_FILTERS.length, JOURNEY_STATES.length + 1);
  assert.deepEqual(OPERATOR_FILTERS[0], ["", "All"]);
  assert.deepEqual(stateCounts({ CONNECTED: 2, BLOCKED: 1, FAILED: 0 }), [{ state: "CONNECTED", n: 2 }, { state: "BLOCKED", n: 1 }]);
  assert.deepEqual(stateCounts({}), []);
});

import { extraNote } from "../src/lib/agency-journey.ts";
test("an extra note is never a repeat of the server's own detail (the page once printed the same sentence twice)", () => {
  const same = "FlowQR is a Manager of your profile and its access was checked against Google.";
  assert.equal(extraNote("CONNECTED", same), null);
  assert.equal(extraNote("CONNECTED", "FlowQR is a Manager of your profile and its access was checked against Google"), null);
  assert.ok(extraNote("CONNECTED", "Something else entirely."));
  assert.equal(extraNote("CUSTOMER_CONSENT_PENDING", "anything"), null); // no note defined for this state
});

import { journeyOffered } from "../src/lib/agency-journey.ts";
test("the guided-setup entry is shown only when the server says the path is open for this business", () => {
  assert.equal(journeyOffered({ offered: true }), true);
  assert.equal(journeyOffered({ offered: false }), false);
  assert.equal(journeyOffered({}), false); // an older server that does not say is treated as closed, never as open
  assert.equal(journeyOffered(null), false);
  assert.equal(journeyOffered(undefined), false);
});
