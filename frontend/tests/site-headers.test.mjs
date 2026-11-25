import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import config from "../next.config.mjs";

const rules = await config.headers();
// Next's source syntax, reduced to what this config uses
const matches = (source, path) => source === "/((?!site/).*)" ? !path.startsWith("/site/") : source === "/site/:path*" ? path.startsWith("/site/") : false;
const headersFor = (path) => rules.filter((r) => matches(r.source, path)).flatMap((r) => r.headers);

test("only the two known header rules exist, so this test covers them all", () => {
  assert.deepEqual(rules.map((r) => r.source), ["/((?!site/).*)", "/site/:path*"]);
});

test("a business website gets the sandbox policy and never the app's own policy", () => {
  for (const path of ["/site/gomti-physio", "/site/gomti-physio/privacy"]) {
    const csp = headersFor(path).filter((h) => h.key === "Content-Security-Policy");
    assert.equal(csp.length, 1);
    assert.match(csp[0].value, /sandbox /);
    assert.doesNotMatch(csp[0].value, /allow-scripts|allow-same-origin/);
    assert.match(csp[0].value, /script-src 'none'/);
  }
});

test("the frontend's copy of the policy is the backend's", () => {
  const py = readFileSync(new URL("../../backend/app/services/sites/hosting.py", import.meta.url), "utf8");
  const base = /^CSP = "([^"]+)"/m.exec(py)[1];
  const extra = /^APP_CSP = CSP \+ "([^"]+)"/m.exec(py)[1];
  assert.equal(headersFor("/site/x").find((h) => h.key === "Content-Security-Policy").value, base + extra);
});

test("the app's pages keep their own headers", () => {
  const app = headersFor("/settings").map((h) => h.key);
  assert.ok(app.includes("Content-Security-Policy") && app.includes("X-Frame-Options"));
});
