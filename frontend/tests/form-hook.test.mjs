// Regression guard for production-readiness finding F-03: the New campaign dialog (and any form using useForm with blur validation) threw React error #185
// "Maximum update depth exceeded" while it was being filled, because `blur` called setErrors from INSIDE a setValues updater function. A state updater must be pure.
// The behaviour itself is proved in a real browser by e2e/production-audit-journeys.js (no page error while filling and submitting the dialog); this guards the cause in CI without a browser.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const withComments = readFileSync(new URL("../src/lib/form.ts", import.meta.url), "utf8");
const src = withComments.replace(/\/\/.*$/gm, ""); // code only: the explanation above may mention the old pattern

function functionBody(name) {
  const start = src.indexOf(`const ${name} = useCallback`);
  assert.ok(start >= 0, `${name} not found in form.ts`);
  const open = src.indexOf("=> {", start);
  let depth = 0;
  for (let i = open + 3; i < src.length; i++) {
    if (src[i] === "{") depth++;
    if (src[i] === "}" && --depth === 0) return src.slice(open, i + 1);
  }
  throw new Error("unbalanced braces");
}

test("blur validates outside any state updater", () => {
  const body = functionBody("blur");
  assert.ok(!/setValues\s*\(/.test(body), "blur must not use a setValues updater (it ran setErrors inside it)");
  assert.ok(/setErrors\s*\(\s*\(?e\)?\s*=>/.test(body), "blur sets the error with a functional update");
});

test("blur leaves the errors object alone when the message did not change", () => {
  // returning the same object lets React skip the re-render, so blurring a valid field repeatedly causes no work
  const body = functionBody("blur");
  assert.match(body, /e\[key\]\s*===\s*msg\s*\?\s*e\s*:/);
});

test("no state updater function in form.ts calls another setter", () => {
  for (const m of src.matchAll(/\bset(Values|Errors|ServerError)\(\s*\(\w+\)\s*=>\s*\{?([^;]*)/g)) {
    assert.ok(!/\bset[A-Z]\w*\(/.test(m[2]), `an updater calls another setter: ${m[0].slice(0, 80)}`);
  }
});
