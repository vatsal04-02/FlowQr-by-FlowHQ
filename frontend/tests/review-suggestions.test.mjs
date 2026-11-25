import test from "node:test";
import assert from "node:assert/strict";
import { COPY, optionsOf } from "../src/lib/review-growth.ts";

const texts = (r) => optionsOf(r).map((o) => o.text);

test("a round shows its one or two suggestions, first one first, never more than two", () => {
  assert.deepEqual(texts({ draft: "A", suggestions: ["A", "B"] }), ["A", "B"]);
  assert.deepEqual(texts({ draft: "A", suggestions: ["A", "B", "C"] }), ["A", "B"]);
  assert.deepEqual(texts({ draft: "A", suggestions: ["A"] }), ["A"]);
});

test("each option keeps its language, so a Hinglish one can be labelled", () => {
  assert.deepEqual(optionsOf({ draft: "A", suggestions: ["A", "B"], suggestion_languages: ["en", "hinglish"] }), [{ text: "A", lang: "en" }, { text: "B", lang: "hinglish" }]);
});

test("blanks and repeats are dropped, and whitespace is trimmed", () => {
  assert.deepEqual(texts({ draft: "A", suggestions: [" A ", "", "  ", "B", "B"] }), ["A", "B"]);
});

test("an older server that sends only the single draft still works (one option, so no chooser is shown)", () => {
  assert.deepEqual(texts({ draft: "Only one.", suggestions: undefined }), ["Only one."]);
  assert.deepEqual(texts({ draft: null, suggestions: [] }), []);
});

test("the chooser has words in English and Hindi, says these are only suggestions, and names Hinglish", () => {
  for (const lang of ["en", "hi"]) {
    const t = COPY[lang];
    assert.ok(t.pickTitle.length > 3 && t.optionN.length > 1 && t.pickHint.length > 20 && t.hinglishTag.length > 3, lang);
  }
  assert.match(COPY.en.pickHint, /only suggestions/i);
});
