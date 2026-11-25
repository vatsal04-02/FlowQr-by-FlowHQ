import test from "node:test";
import assert from "node:assert/strict";
import { areaStep, approvalOutcome, fixHref, prepareHeadline, AREA_FOR_FIELD, MANUAL_EDITOR, countLabel } from "../src/lib/operator.ts";

const area = (key, state, mode) => ({ key, label: key, state, summary: "", fix: mode ? { mode, label: mode } : null });
const act = (id, field, status = "pending_approval") => ({ id, field, status });

test("an area that is fine offers nothing, and one not read yet offers nothing it cannot back up", () => {
  assert.equal(areaStep(area("description", "ok", null), []), null);
  assert.equal(areaStep(area("services", "unknown", null), []), null);
});

test("an area with a prepared change opens that exact change", () => {
  const s = areaStep(area("description", "improve", "owner_approved"), [act("a1", "description")]);
  assert.deepEqual(s, { kind: "open", href: "/ai/changes?focus=action:a1", label: "Review and approve" });
  const r = areaStep(area("services", "improve", "recommended_only"), [act("a2", "services", "recommended")]);
  assert.equal(r.kind, "open"); assert.match(r.label, /drafted/);
});

test("phone and website changes both belong to the contacts area", () => {
  assert.equal(AREA_FOR_FIELD.website, "contacts"); assert.equal(AREA_FOR_FIELD.phone, "contacts");
  assert.equal(areaStep(area("contacts", "improve", "owner_approved"), [act("c1", "phone")]).href, "/ai/changes?focus=action:c1");
});

test("an area with nothing prepared yet offers to have the AI prepare it, never a dead chip", () => {
  assert.deepEqual(areaStep(area("description", "missing", "owner_approved"), []), { kind: "prepare", area: "description", label: "Prepare the change" });
  assert.equal(areaStep(area("hours", "improve", "owner_approved"), []).kind, "prepare");
});

test("what only the owner knows jumps to the questions, and what Google or FlowQr cannot do says so in words", () => {
  assert.equal(areaStep(area("attributes", "improve", "owner_input_needed"), []).kind, "inputs");
  const g = areaStep(area("services", "improve", "unavailable_via_api"), []);
  assert.equal(g.kind, "info"); assert.match(g.text, /Google does not allow/); assert.ok(g.href);
  const n = areaStep(area("name", "improve", "edit_in_google"), []);
  assert.equal(n.kind, "info"); assert.match(n.text, /Edit it in Google/);
});

test("photos and posts lead to their own working screens", () => {
  assert.equal(areaStep(area("photos", "improve", "owner_approved"), []).href, "/gbp/photos");
  assert.equal(areaStep(area("posts", "improve", "owner_approved"), []).href, "/ai/studio");
});

test("a finished, rejected or failed change is not treated as an open one", () => {
  assert.equal(areaStep(area("description", "improve", "owner_approved"), [act("x", "description", "rejected")]).kind, "prepare");
});

test("checklist actions open the prepared change; a missing main category and a same-page anchor do not", () => {
  assert.equal(fixHref("description", "improve", "#description", "G1"), "/ai/changes?prepare=description&location=G1");
  assert.equal(fixHref("description", "missing", "#description", "G1"), "/ai/changes?prepare=description&location=G1");
  assert.equal(fixHref("category", "improve", "/gbp/info", "G1"), "/ai/changes?prepare=categories&location=G1");
  assert.equal(fixHref("category", "missing", "/gbp/info", "G1"), "/gbp/info");
  assert.equal(fixHref("photos", "improve", "/gbp/photos", "G1"), "/gbp/photos");
  assert.equal(fixHref("services", "ok", "#services", "G1"), null);
});

test("'applied' is claimed only when Google confirmed it by reading the profile back", () => {
  const item = { kind: "action", title: "Business description" };
  assert.equal(approvalOutcome(item, { status: "executed", verified_at: "2026-11-25T10:00:00Z" }).tone, "success");
  assert.equal(approvalOutcome(item, { status: "executed", verified_at: null }).tone, "warning");  // accepted but not confirmed: never a success
  const failed = approvalOutcome(item, { status: "failed", last_error: "Google did not show the new text." });
  assert.equal(failed.tone, "error"); assert.match(failed.text, /did not show/);
  assert.equal(approvalOutcome(item, { status: "approved" }).tone, "warning");
  assert.equal(approvalOutcome({ kind: "reply", title: "" }, { status: "published" }).tone, "success");
  assert.equal(approvalOutcome({ kind: "reply", title: "" }, { status: "failed" }).tone, "warning");
});

test("headlines and labels are plain words", () => {
  for (const k of ["prepared", "already_prepared", "needs_owner_input", "nothing_to_change", "cannot_prepare"]) assert.ok(prepareHeadline(k).length > 10);
  assert.equal(countLabel(1, "change", "changes"), "1 change"); assert.equal(countLabel(3, "change", "changes"), "3 changes");
  assert.ok(MANUAL_EDITOR.description.href.startsWith("/gbp/"));
});
