import test from "node:test";
import assert from "node:assert/strict";
import { dailyStack, runs, canDrawArea, shares, ratingMix, pctChange, reviewTimeline, dayGap, scoreIf, scoreVerdict, liftOf, reviewInsight, newReviewsVerdict, ratingVerdict } from "../src/lib/charts.ts";

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

const W = { rating: 20, reviews: 25, replies: 15, profile: 15, rank: 25 };
const mk = (vals) => Object.keys(W).map((k) => ({ key: k, weight: W[k], available: vals[k] !== undefined, value: vals[k] ?? null }));
test("scoreIf reproduces the backend formula (re-weighted over measured parts)", () => {
  const parts = mk({ rating: 1, reviews: 0.7, replies: 0.5, profile: 1 });          // rank not measured: covered 75
  assert.equal(scoreIf(parts), Math.round((100 * (20 * 1 + 25 * 0.7 + 15 * 0.5 + 15 * 1)) / 75));
});
test("scoreIf: under the coverage floor there is no score", () => {
  assert.equal(scoreIf(mk({ rating: 1 })), null);                                    // 20 covered < 30
  assert.notEqual(scoreIf(mk({ rating: 1, profile: 0.5 })), null);                   // 35 covered
});
test("scoreVerdict names the fixes and what full marks on them would give; never claims more", () => {
  const parts = mk({ rating: 1, reviews: 0.7, replies: 0.5, profile: 1 });
  const score = scoreIf(parts);
  const v = scoreVerdict(score, parts);
  assert.deepEqual(v.fixes.sort(), ["replies", "reviews"]);
  assert.equal(v.reach, scoreIf(parts, ["replies", "reviews"]));
  assert.ok(v.reach > score);
  assert.equal(v.word, score >= 75 ? "Good" : score >= 50 ? "Fair" : "Needs work");
  const clean = scoreVerdict(100, mk({ rating: 1, reviews: 1, replies: 1, profile: 1 }));
  assert.deepEqual([clean.fixes, clean.reach], [[], null]);
  assert.equal(scoreVerdict(null, parts), null);
});
test("liftOf is an upper bound and zero for unmeasured or full parts", () => {
  const parts = mk({ rating: 1, reviews: 0.7, replies: 0.5, profile: 1 }), score = scoreIf(parts);
  assert.equal(liftOf(score, parts, "rating"), 0);
  assert.equal(liftOf(score, parts, "rank"), 0);
  assert.ok(liftOf(score, parts, "replies") > 0);
});
test("reviewInsight is built from the two counts only", () => {
  assert.equal(reviewInsight(0, 0, 30), null);
  assert.equal(reviewInsight(24, 12, 30), "24 new reviews in the last 30 days, 2× as many as the 30 before.");
  assert.equal(reviewInsight(24, 18, 30), "24 new reviews in the last 30 days, 1.3× as many as the 30 before.");
  assert.equal(reviewInsight(20, 18, 30), "20 new reviews in the last 30 days, about the same as the 30 before.");
  assert.equal(reviewInsight(10, 20, 7), "10 new reviews in the last 7 days, down 50% from the 7 before.");
  assert.equal(reviewInsight(5, 0, 30), "5 new reviews in the last 30 days, none in the 30 before.");
  assert.equal(reviewInsight(1, null, 30), "1 new review in the last 30 days.");
});
test("verdict chips: no number, no chip", () => {
  assert.equal(ratingVerdict(null), null);
  assert.equal(ratingVerdict(4.6), "good");
  assert.equal(ratingVerdict(4.3), "attention");   // the Growth score also treats 4.3 as something to improve
  assert.equal(newReviewsVerdict(10, null), null);
  assert.equal(newReviewsVerdict(10, 10), "good");
  assert.equal(newReviewsVerdict(9, 10), "attention");
  assert.equal(newReviewsVerdict(0, 0), "attention");
});
