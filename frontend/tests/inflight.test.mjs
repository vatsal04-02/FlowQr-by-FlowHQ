import test from "node:test";
import assert from "node:assert/strict";
import { forgetInFlight, inFlightCount, shareGet } from "../src/lib/inflight.ts";

const answer = (text) => ({ status: 200, text, failed: false });
const later = (v, ms = 5) => new Promise((r) => setTimeout(() => r(v), ms));

test("identical reads made at the same moment send ONE request and all get its answer", async () => {
  let sent = 0;
  const send = () => { sent += 1; return later(answer("locations")); };
  const [a, b, c] = await Promise.all([shareGet("/locations", send), shareGet("/locations", send), shareGet("/locations", send)]);
  assert.equal(sent, 1);
  assert.deepEqual([a.text, b.text, c.text], ["locations", "locations", "locations"]);
});

test("different addresses are never joined", async () => {
  let sent = 0;
  const send = (t) => () => { sent += 1; return later(answer(t)); };
  const [a, b] = await Promise.all([shareGet("/reviews?limit=20", send("20")), shareGet("/reviews?limit=50", send("50"))]);
  assert.equal(sent, 2);
  assert.deepEqual([a.text, b.text], ["20", "50"]);
});

test("it is not a cache: once the request has ended, the next read is a new request", async () => {
  let sent = 0;
  const send = () => { sent += 1; return later(answer(`v${sent}`)); };
  const first = await shareGet("/google/status", send);
  assert.equal(inFlightCount(), 0);
  const second = await shareGet("/google/status", send);
  assert.deepEqual([first.text, second.text, sent], ["v1", "v2", 2]);
});

test("a write drops everything in flight, so a read after it is fresh", async () => {
  let sent = 0;
  const send = () => { sent += 1; return later(answer(`v${sent}`), 15); };
  const before = shareGet("/posts", send);
  forgetInFlight(); // a POST/PATCH/DELETE has started or finished
  const after = shareGet("/posts", send);
  assert.equal(sent, 2);
  assert.deepEqual([(await before).text, (await after).text], ["v1", "v2"]);
});

test("a failed request is shared by the readers that were waiting, then forgotten", async () => {
  let sent = 0;
  const send = () => { sent += 1; return later({ status: 0, text: "", failed: true }); };
  const [a, b] = await Promise.all([shareGet("/x", send), shareGet("/x", send)]);
  assert.equal(sent, 1);
  assert.ok(a.failed && b.failed);
  assert.equal(inFlightCount(), 0);
  await shareGet("/x", send);
  assert.equal(sent, 2); // an error is never remembered
});
