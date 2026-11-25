import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (f) => readFileSync(new URL(`../src/${f}`, import.meta.url), "utf8");
const lib = read("lib/sites.ts");
const settable = JSON.parse(/SETTABLE_COMMERCIAL = (\[[^\]]*\])/.exec(lib)[1]);

test("every hosting status the database allows has a label, and only the server's accepted ones can be chosen", () => {
  const model = readFileSync(new URL("../../backend/app/models/sites.py", import.meta.url), "utf8");
  const all = [.../^COMMERCIAL_STATUSES = \(([^)]*)\)/m.exec(model)[1].matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
  const labels = /COMMERCIAL_LABEL[^=]*= \{([^}]*)\}/.exec(lib)[1];
  for (const s of all) assert.ok(labels.includes(`${s}:`), `no label for ${s}`);
  assert.deepEqual(settable, all.filter((s) => s !== "not_activated"));
});

test("the admin form starts on a status that can be recorded, not on the stored one", () => {
  const panel = read("components/admin/site/SiteAdminPanels.tsx");
  assert.match(panel, /useState\(commercialChoice\(site\.commercial\.status\)\)/);
  assert.match(panel, /SETTABLE_COMMERCIAL\.map/);
});
