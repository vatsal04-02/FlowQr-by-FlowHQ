import test from "node:test";
import assert from "node:assert/strict";
import { dailyStack, runs, canDrawArea, shares, ratingMix, pctChange, reviewTimeline, dayGap } from "../src/lib/charts.ts";

const p = (date, value) => ({ date, value });

test("dayGap counts whole days across month ends", () => {
  assert.equal(dayGap("2026-10-31", "2026-11-01"), 1);
  assert.equal(dayGap("2026-11-01", "2026-11-17"), 16);
});

test("dailyStack: sums metrics inside a group and keeps only days every group reported", () => {
  const series = {
    CALL_CLICKS: [p("2026-11-01", 2), p("2026-11-02", 0), p("2026-11-03", 1)],
    DIR: [p("2026-11-01", 5), p("2026-11-03", 4)], // no row for 11-02
    V_A: [p("2026-11-01", 10), p("2026-11-03", 7)], V_B: [p("2026-11-01", 1), p("2026-11-03", 2)],
  };
  const days = dailyStack(series, [["CALL_CLICKS"], ["DIR"], ["V_A", "V_B"]]);
  assert.deepEqual(days, [{ date: "2026-11-01", values: [2, 5, 11] }, { date: "2026-11-03", values: [1, 4, 9] }]);
});
test("dailyStack never invents a day or a value", () => {
  assert.deepEqual(dailyStack({}, [["A"]]), []);
  assert.deepEqual(dailyStack({ A: [p("2026-11-01", 1)] }, [["A"], ["B"]]), []); // B never reported: nothing is drawn
  assert.deepEqual(dailyStack({ A: [p("2026-11-01", 1)] }, []), []);
});

test("runs splits at gaps; an area needs three days in a row", () => {
  const d = (date) => ({ date, values: [1] });
  const days = [d("2026-11-01"), d("2026-11-02"), d("2026-11-04"), d("2026-11-05"), d("2026-11-06")];
  assert.deepEqual(runs(days).map((r) => r.length), [2, 3]);
  assert.equal(canDrawArea(days), true);
  assert.equal(canDrawArea([d("2026-11-01"), d("2026-11-02"), d("2026-11-04")]), false);
  assert.equal(canDrawArea([]), false);
});

test("shares always add up to 100 and zeros stay zero", () => {
  for (const v of [[21, 58, 18], [1, 1, 1], [467, 12, 2, 0, 1], [5, 0, 0]]) assert.equal(shares(v).reduce((a, b) => a + b, 0), 100);
  assert.deepEqual(shares([0, 0, 0]), [0, 0, 0]);
  assert.deepEqual(shares([5, 0, 0]), [100, 0, 0]);
  assert.deepEqual(shares([1, 1]), [50, 50]);
});

test("ratingMix lists five stars first and reads missing keys as zero", () => {
  assert.deepEqual(ratingMix({ 5: 467, 4: 12, 3: 2, 1: 1 }).map((x) => [x.star, x.count]), [[5, 467], [4, 12], [3, 2], [2, 0], [1, 1]]);
  assert.equal(ratingMix(null).every((x) => x.count === 0), true);
});

test("pctChange is null when there is nothing honest to compare", () => {
  assert.equal(pctChange(10, null), null);
  assert.equal(pctChange(10, 0), null);
  assert.equal(pctChange(null, 5), null);
  assert.equal(pctChange(13, 10), 30);
  assert.equal(pctChange(8, 10), -20);
});

test("reviewTimeline uses only timestamps the API returned, in time order", () => {
  const base = { review_created_at: "2026-11-10T08:00:00Z" };
  assert.deepEqual(reviewTimeline(base).map((s) => s.key), ["received"]);
  const full = reviewTimeline({ ...base, google_reply_at: "2026-11-10T12:00:00Z", latest_draft: { created_at: "2026-11-10T09:00:00+00:00", approved_at: "2026-11-10T10:00:00Z", published_at: "2026-11-10T11:00:00Z", status: "published", generated_by_ai: true } });
  assert.deepEqual(full.map((s) => s.key), ["received", "drafted", "approved", "published"]);
  assert.equal(full[1].label, "Reply drafted by FlowQR");
  // a reply that exists on Google with no draft of ours (the owner replied on Google) is shown as exactly that
  assert.deepEqual(reviewTimeline({ ...base, google_reply_at: "2026-11-11T08:00:00Z" }).map((s) => s.key), ["received", "replied"]);
  // a draft that was never approved has no approved/sent steps
  assert.deepEqual(reviewTimeline({ ...base, latest_draft: { created_at: "2026-11-10T09:00:00Z", approved_at: null, published_at: null, status: "draft" } }).map((s) => s.key), ["received", "drafted"]);
});
