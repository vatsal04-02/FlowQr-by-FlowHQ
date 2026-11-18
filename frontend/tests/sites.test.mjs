import test from "node:test";
import assert from "node:assert/strict";
import { addableSections, blankItem, blankValue, charsLeft, daysUntil, errorMap, fitScale, hasErrorUnder, moveItem, newSectionId, nextStep, setPath, DEVICES } from "../src/lib/sites.ts";

test("moveItem reorders without changing the original and clamps", () => {
  const a = ["a", "b", "c", "d"];
  assert.deepEqual(moveItem(a, 0, 2), ["b", "c", "a", "d"]);
  assert.deepEqual(moveItem(a, 3, 0), ["d", "a", "b", "c"]);
  assert.deepEqual(moveItem(a, 1, 99), ["a", "c", "d", "b"]);
  assert.deepEqual(moveItem(a, 2, -5), ["c", "a", "b", "d"]);
  assert.deepEqual(moveItem(a, 9, 0), a);
  assert.deepEqual(a, ["a", "b", "c", "d"]);
});

test("blank values match the field kind", () => {
  assert.equal(blankValue({ key: "x", label: "x", kind: "bool" }), false);
  assert.equal(blankValue({ key: "x", label: "x", kind: "asset" }), null);
  assert.deepEqual(blankValue({ key: "x", label: "x", kind: "list", fields: [] }), []);
  assert.deepEqual(blankValue({ key: "x", label: "x", kind: "strings" }), []);
  assert.equal(blankValue({ key: "x", label: "x", kind: "select", options: ["", "veg"] }), "");
  assert.equal(blankValue({ key: "x", label: "x", kind: "text" }), "");
  assert.deepEqual(blankItem([{ key: "name", label: "n", kind: "text" }, { key: "image", label: "i", kind: "asset" }, { key: "veg", label: "v", kind: "select", options: ["", "veg"] }]), { name: "", image: null, veg: "" });
});

test("a new section id follows the server's rule and is never a repeat", () => {
  const re = /^[a-z][a-z0-9]{1,11}$/;
  const used = ["s000", "s001"];
  let n = 0;
  const id = newSectionId(used, () => (n++ < 2 ? 0 : 0.5));
  assert.match(id, re);
  assert.ok(!used.includes(id));
  for (let i = 0; i < 200; i++) assert.match(newSectionId([], Math.random), re);
});

test("sections that may appear once are not offered again, and the cap holds", () => {
  const allowed = ["hero", "about", "faqs", "contact", "gallery"];
  assert.deepEqual(addableSections(allowed, [{ type: "hero" }, { type: "contact" }]), ["about", "faqs", "gallery"]);
  assert.deepEqual(addableSections(allowed, [{ type: "about" }]), allowed.filter((t) => t !== "x"));
  assert.deepEqual(addableSections(allowed, Array.from({ length: 20 }, () => ({ type: "about" }))), []);
});

test("server errors map to fields and prefixes", () => {
  const m = errorMap([{ path: "sections[2].data.items[0].title", message: "Use at most 80 characters." }, { path: "business.email", message: "Enter a valid email address." }]);
  assert.equal(m["business.email"], "Enter a valid email address.");
  assert.ok(hasErrorUnder(m, "sections[2]") && hasErrorUnder(m, "sections[2].data.items") && hasErrorUnder(m, "business"));
  assert.ok(!hasErrorUnder(m, "sections[1]") && !hasErrorUnder(m, "sections[20]") && !hasErrorUnder(m, "busines"));
  assert.deepEqual(errorMap(undefined), {});
});

test("setPath is immutable and handles arrays", () => {
  const c = { business: { phone: "1", hours: [{ open: "09:00" }, { open: "10:00" }] }, sections: [{ data: { items: [{ title: "a" }] } }] };
  const d = setPath(c, "business.hours[1].open", "11:30");
  assert.equal(d.business.hours[1].open, "11:30");
  assert.equal(c.business.hours[1].open, "10:00");
  assert.equal(d.business.hours[0], c.business.hours[0]);
  assert.equal(setPath(c, "sections[0].data.items[0].title", "b").sections[0].data.items[0].title, "b");
  assert.equal(setPath(c, "business.phone", "").business.phone, "");
});

test("counters and dates", () => {
  assert.equal(charsLeft("abc", 10), 7);
  assert.equal(charsLeft(null, 10), 10);
  assert.equal(charsLeft("x".repeat(12), 10), -2);
  const now = new Date("2026-11-19T00:00:00Z");
  assert.equal(daysUntil("2026-11-29T00:00:00Z", now), 10);
  assert.equal(daysUntil("2026-11-18T00:00:00Z", now), -1);
  assert.equal(daysUntil(null, now), null);
  assert.equal(daysUntil("not a date", now), null);
});

test("preview scale fits the pane and never enlarges", () => {
  assert.equal(fitScale("desktop", 640), 0.5);
  assert.equal(fitScale("mobile", 390), 1);
  assert.equal(fitScale("mobile", 900), 1);
  assert.equal(fitScale("desktop", 10), 0.2);
  assert.equal(DEVICES.mobile.width, 390);
});

test("the status line tells the administrator what to do next", () => {
  const live = { status: "published", live_version: 1, publish_state: "idle", commercial: { status: "paid_offline" } };
  assert.match(nextStep({ ...live, status: "suspended" }, 0, false), /suspended/i);
  assert.match(nextStep({ ...live, publish_state: "failed" }, 0, false), /failed.*unchanged/i);
  assert.match(nextStep({ ...live, commercial: { status: "expired" } }, 0, false), /not active/i);
  assert.match(nextStep(live, 0, true), /unsaved/i);
  assert.match(nextStep(live, 3, false), /3 things to fix/);
  assert.match(nextStep(live, 1, false), /1 thing to fix/);
  assert.match(nextStep(live, 0, false), /Live/);
  assert.match(nextStep({ ...live, status: "draft" }, 0, false), /Ready to publish/);
});
