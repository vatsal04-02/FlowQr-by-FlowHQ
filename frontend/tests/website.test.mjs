import test from "node:test";
import assert from "node:assert/strict";
import { phaseOf, progress, previewKey, editableFields, emptyItem, STEP_WORD, DEVICES } from "../src/lib/website.ts";

const step = (status) => ({ key: status, label: status, detail: "", status, note: null });
const job = (status, steps = []) => ({ id: "j", status, stage: "", steps, notes: [], error: null, trigger: "owner" });

test("the screen follows the server's job, never its own idea of progress", () => {
  assert.equal(phaseOf({ enabled: true, job: null, site: null }), "start");
  assert.equal(phaseOf({ enabled: true, job: job("queued"), site: null }), "building");
  assert.equal(phaseOf({ enabled: true, job: job("running"), site: { version: 2 } }), "building");
  assert.equal(phaseOf({ enabled: true, job: job("failed"), site: null }), "failed");
  assert.equal(phaseOf({ enabled: true, job: job("completed"), site: { version: 9 } }), "review");
});

test("finished counts only done and skipped steps; waiting, running and failed are not done", () => {
  const p = progress([step("done"), step("skipped"), step("running"), step("waiting"), step("failed")]);
  assert.equal(p.finished, 2); assert.equal(p.total, 5); assert.equal(p.current.status, "running");
  assert.deepEqual(Object.values(STEP_WORD), ["Waiting", "In progress", "Completed", "Skipped", "Failed"]);
});

test("the preview is fetched again only when the server did more work", () => {
  const a = { enabled: true, site: { version: 3 }, job: job("running", [step("done"), step("running")]) };
  assert.equal(previewKey(a), previewKey({ ...a }));
  assert.notEqual(previewKey(a), previewKey({ ...a, site: { version: 4 } }));
  assert.notEqual(previewKey(a), previewKey({ ...a, job: job("running", [step("done"), step("done")]) }));
});

test("editors cover text fields and lists, and previews use real device widths", () => {
  assert.deepEqual(editableFields([{ key: "h", kind: "text" }, { key: "i", kind: "asset" }, { key: "l", kind: "list" }, { key: "b", kind: "bool" }]).map((f) => f.key), ["h", "l"]);
  assert.deepEqual(emptyItem([{ key: "title", kind: "text" }, { key: "image", kind: "asset" }]), { title: "", image: null });
  assert.deepEqual(Object.values(DEVICES), [1280, 820, 390]);
});
