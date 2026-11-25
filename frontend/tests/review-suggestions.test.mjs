import test from "node:test";
import assert from "node:assert/strict";
import { COPY, optionsOf } from "../src/lib/review-growth.ts";

test("a round shows its two or three suggestions, first one first, never more than three", () => {
  assert.deepEqual(optionsOf({ draft: "A", suggestions: ["A", "B", "C"] }), ["A", "B", "C"]);
  assert.deepEqual(optionsOf({ draft: "A", suggestions: ["A", "B", "C", "D"] }), ["A", "B", "C"]);
  assert.deepEqual(optionsOf({ draft: "A", suggestions: ["A", "B"] }), ["A", "B"]);
});

test("blanks and repeats are dropped, and whitespace is trimmed", () => {
  assert.deepEqual(optionsOf({ draft: "A", suggestions: [" A ", "", "  ", "B", "B"] }), ["A", "B"]);
});

test("an older server that sends only the single draft still works (one option, so no chooser is shown)", () => {
  assert.deepEqual(optionsOf({ draft: "Only one.", suggestions: undefined }), ["Only one."]);
  assert.deepEqual(optionsOf({ draft: null, suggestions: [] }), []);
});

test("the chooser has words in English and Hindi, and says these are only suggestions", () => {
  for (const lang of ["en", "hi"]) {
    const t = COPY[lang];
    assert.ok(t.pickTitle.length > 3 && t.optionN.length > 1 && t.pickHint.length > 20, lang);
  }
  assert.match(COPY.en.pickHint, /only suggestions/i);
});
