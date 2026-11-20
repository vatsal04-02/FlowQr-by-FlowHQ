import test from "node:test";
import assert from "node:assert/strict";
import { STEP_ORDER, STEP_LABEL, STEP_ACTION, stepLine, firstOpen, pct, ringGeometry, connectionHealth, qualityWords, consentRows, funnel, initials, lastFour } from "../src/lib/whatsapp-ui.ts";

test("every step has a one-word label and a short instruction", () => {
  for (const k of STEP_ORDER) {
    assert.ok(STEP_LABEL[k] && !STEP_LABEL[k].includes(" "), k);
    assert.ok(STEP_ACTION[k].split(" ").length <= 5, k);
  }
});

test("the status line under a step is four words or fewer and never empty for a real state", () => {
  for (const key of STEP_ORDER) {
    for (const state of ["done", "todo", "waiting", "blocked"]) {
      const line = stepLine({ key, state });
      if (line) assert.ok(line.split(" ").length <= 4, `${key}/${state}: ${line}`);
    }
  }
  assert.equal(stepLine({ key: "connect", state: "done" }), "Connected");
  assert.equal(stepLine({ key: "messages", state: "waiting" }), "WhatsApp is reviewing");
  assert.equal(stepLine({ key: "messages", state: "todo", refused: ["offer"] }), "Fix a message");
});

test("the step to do now is the first one that is not done", () => {
  assert.equal(firstOpen([{ state: "done" }, { state: "done" }, { state: "waiting" }, { state: "todo" }]), 2);
  assert.equal(firstOpen([{ state: "done" }, { state: "done" }]), -1);
  assert.equal(firstOpen([]), -1);
});

test("percentages are whole numbers and safe for zero", () => {
  assert.equal(pct(1, 3), 33);
  assert.equal(pct(3, 3), 100);
  assert.equal(pct(5, 3), 100);
  assert.equal(pct(0, 0), 0);
  assert.equal(pct(2, 0), 0);
  assert.equal(pct(-1, 4), 0);
});

test("the progress ring hides the right amount of the circle", () => {
  const r = 50;
  const c = 2 * Math.PI * r;
  assert.equal(ringGeometry(0, 6, r).offset, c);
  assert.ok(Math.abs(ringGeometry(3, 6, r).offset - c / 2) < 1e-9);
  assert.equal(ringGeometry(6, 6, r).offset, 0);
  assert.equal(ringGeometry(9, 6, r).offset, 0);
  assert.equal(ringGeometry(1, 0, r).offset, c);
});

test("connection health always has a word, never colour alone", () => {
  assert.deepEqual(connectionHealth(null).map((h) => h.value), ["Not connected", "Off", "Not shown yet"]);
  const live = { status: "active", token_state: "ok", webhook_status: "subscribed", quality_rating: "GREEN" };
  assert.deepEqual(connectionHealth(live).map((h) => [h.value, h.state]), [["Connected", "ok"], ["On", "ok"], ["Good", "ok"]]);
  assert.equal(connectionHealth({ ...live, status: "needs_attention" })[0].state, "bad");
  assert.equal(connectionHealth({ ...live, token_state: "expiring" })[0].value, "Renew soon");
  assert.equal(connectionHealth({ ...live, webhook_status: "failed" })[1].value, "Not working");
  assert.equal(connectionHealth({ ...live, status: "pending" })[0].value, "Connecting");
  assert.deepEqual(qualityWords("RED"), { value: "Low", state: "bad" });
  assert.deepEqual(qualityWords(undefined), { value: "Not shown yet", state: "off" });
});

test("who agreed to what is shown as separate shares of all customers", () => {
  const rows = consentRows({ contacts: 4, marketing: 1, utility: 4, occasion: 2, opted_out: 1 });
  assert.deepEqual(rows.map((r) => [r.key, r.value, r.share]), [["offers", 1, 25], ["updates", 4, 100], ["greetings", 2, 50], ["stopped", 1, 25]]);
  assert.deepEqual(consentRows({ contacts: 0, marketing: 0, utility: 0, opted_out: 0 }).map((r) => r.share), [0, 0, 0, 0]);
});

test("sent, delivered and read are bars against the biggest of them", () => {
  const f = funnel({ attempted: 12, sent: 10, delivered: 8, read: 4, failed: 2 });
  assert.deepEqual(f.map((x) => [x.key, x.share]), [["sent", 100], ["delivered", 80], ["read", 40]]);
  assert.deepEqual(funnel({ attempted: 0, sent: 0, delivered: 0, read: 0, failed: 0 }).map((x) => x.share), [0, 0, 0]);
});

test("initials and the last four digits of a number", () => {
  assert.equal(initials("Asha Verma"), "AV");
  assert.equal(initials("asha"), "A");
  assert.equal(initials("Geeta (you)"), "G");
  assert.equal(initials("Mary Ann Smith"), "MS");
  assert.equal(initials(null, "+91 98765 43210"), "10");
  assert.equal(initials("", ""), "?");
  assert.equal(lastFour("+91 98765 43210"), "…3210");
  assert.equal(lastFour(null), "");
});
