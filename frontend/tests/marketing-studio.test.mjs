import test from "node:test";
import assert from "node:assert/strict";
import { OBJECTIVES, DURATIONS, STUDIO_STATUS, toLocalInput } from "../src/lib/marketing.ts";

test("the six goals and three lengths match what the server accepts", () => {
  assert.deepEqual(OBJECTIVES.map((o) => o.value), ["keep_active", "products", "offers", "enquiries", "events", "awareness"]);
  assert.deepEqual(DURATIONS.map((d) => [d.value, d.posts]), [[7, 3], [15, 5], [30, 8]]);
});

test("every post state the server can send has an owner-facing label, and a generated post reads as Generated", () => {
  for (const s of ["draft", "awaiting_approval", "approved", "scheduled", "publishing", "published", "failed", "canceled"]) assert.ok(STUDIO_STATUS[s], s);
  assert.equal(STUDIO_STATUS.awaiting_approval.label, "Generated");
  assert.equal(STUDIO_STATUS.published.tone, "ok");
  assert.equal(STUDIO_STATUS.failed.tone, "bad");
});

test("a suggested time is shown on the business's own clock, not the browser's", () => {
  assert.equal(toLocalInput("2026-11-25T04:30:00+00:00", "Asia/Kolkata"), "2026-11-25T10:00");
  assert.equal(toLocalInput("2026-11-25T04:30:00+00:00", "UTC"), "2026-11-25T04:30");
  assert.equal(toLocalInput(null, "Asia/Kolkata"), "");
  assert.equal(toLocalInput("not a date", "Asia/Kolkata"), "");
});
