import test from "node:test";
import assert from "node:assert/strict";
import {
  DASHBOARD_STATES, STATE_TONE, stateTone, ACTION_LABEL, actionLabel, routeChoices, defaultRoute, STEPS, stepIndex, HOW_IT_WORKS, POLICY_FOOTNOTE, newRequestId, visibleActions,
} from "../src/lib/agency-ui.ts";

test("there are exactly the six dashboard states, each with a tone, and an unknown one is neutral", () => {
  assert.deepEqual([...DASHBOARD_STATES], ["google_connected", "invitation_pending", "client_action_required", "access_verified", "connection_lost", "disconnected"]);
  for (const s of DASHBOARD_STATES) assert.ok(STATE_TONE[s], s);
  assert.equal(stateTone("access_verified"), "ok");
  assert.equal(stateTone("connection_lost"), "bad");
  assert.equal(stateTone("client_action_required"), "warn");
  assert.equal(stateTone("something-new"), "idle");
});

test("every action has a plain label and an unknown action is shown as sent, never guessed", () => {
  for (const a of Object.keys(ACTION_LABEL)) assert.ok(actionLabel(a).length > 2);
  assert.equal(actionLabel("retry"), "Check again");
  assert.equal(actionLabel("reconnect"), "Reconnect Google");
  assert.equal(actionLabel("disconnect"), "Stop FlowQR managing my profile");
  assert.equal(actionLabel("mystery"), "mystery");
});

test("both routes are always shown, and the one that does not fit the selection is disabled with the reason said", () => {
  const one = routeChoices({ selected: 1, available: ["location"], reason: "" });
  assert.deepEqual(one.map((c) => [c.id, c.enabled]), [["location", true], ["business_group", false]]);
  assert.match(one[1].why, /two or more/i);
  const group = routeChoices({ selected: 3, available: ["business_group"], reason: "" });
  assert.deepEqual(group.map((c) => c.enabled), [false, true]);
  const none = routeChoices({ selected: 0, available: [], reason: "Select the profile you want FlowQR to manage first." });
  assert.ok(none.every((c) => !c.enabled && c.why === "Select a profile first."));
  const mixed = routeChoices({ selected: 2, available: [], reason: "The profiles you selected belong to different Google business groups." });
  assert.ok(mixed.every((c) => !c.enabled && /different Google business groups/.test(c.why)));
  assert.equal(defaultRoute({ selected: 1, available: ["location"], reason: "" }), "location");
  assert.equal(defaultRoute({ selected: 2, available: [], reason: "x" }), null);
});

test("the step tracker never moves ahead of what the server recorded", () => {
  assert.equal(STEPS.length, 4);
  assert.equal(stepIndex("google_connected", false), 1);
  assert.equal(stepIndex("google_connected", true), 2);
  assert.equal(stepIndex("invitation_pending", true), 3);
  assert.equal(stepIndex("access_verified", true), 4);
  for (const s of ["client_action_required", "connection_lost", "disconnected", "unknown"]) assert.equal(stepIndex(s, true), 2, s);
});

test("the explanation says the client stays the owner, FlowQR is a Manager, the client approves, what Google shows, and that it can be stopped", () => {
  const text = HOW_IT_WORKS.join(" ");
  assert.match(text, /stay the owner/i);
  assert.match(text, /never as an Owner/i);
  assert.match(text, /Nothing happens until you approve/i);
  assert.match(text, /People and access/);
  assert.match(text, /stop at any time/i);
  assert.ok(HOW_IT_WORKS.every((t) => !/guarantee|automatic(ally)? (reply|post)/i.test(t)));
});

test("the footnote never lets an accepted invitation pass for Google's approval", () => {
  assert.match(POLICY_FOOTNOTE, /not Google's approval/);
  assert.match(POLICY_FOOTNOTE, /stay off/);
});

test("each attempt gets its own request id", () => {
  const a = newRequestId(), b = newRequestId();
  assert.notEqual(a, b);
  assert.ok(a.length >= 8 && a.length <= 64);
});

test("only the buttons the server offered are shown, in a calm fixed order, and unknown ones are dropped", () => {
  assert.deepEqual(visibleActions({ actions: ["disconnect", "retry"] }), ["retry", "disconnect"]);
  assert.deepEqual(visibleActions({ actions: ["restart", "reconnect"] }), ["reconnect", "restart"]);
  assert.deepEqual(visibleActions({ actions: ["start"] }), ["start"]);
  assert.deepEqual(visibleActions({ actions: ["fly-to-moon"] }), []);
  assert.deepEqual(visibleActions({ actions: [] }), []);
});
