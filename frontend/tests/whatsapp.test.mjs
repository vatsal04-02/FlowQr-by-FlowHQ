import test from "node:test";
import assert from "node:assert/strict";
import { automationStatus, connectionWords, consentWords, csvPreview, nextStep, parseSignupMessage } from "../src/lib/whatsapp.ts";

const FB = "https://www.facebook.com";
const finish = (o = {}) => JSON.stringify({ type: "WA_EMBEDDED_SIGNUP", event: "FINISH", data: { waba_id: "100000000000001", phone_number_id: "200000000000001", ...o } });

test("a finished sign-up is read only from Meta's own origins", () => {
  assert.deepEqual(parseSignupMessage(FB, finish()), { kind: "finish", waba_id: "100000000000001", phone_number_id: "200000000000001" });
  assert.deepEqual(parseSignupMessage("https://business.facebook.com", finish()), { kind: "finish", waba_id: "100000000000001", phone_number_id: "200000000000001" });
  for (const origin of ["https://evil.example", "https://www.facebook.com.evil.example", "http://www.facebook.com", "https://facebook.com.evil", ""]) {
    assert.equal(parseSignupMessage(origin, finish()), null, origin);
  }
});

test("a sign-up message is parsed from a string or an object and anything else is ignored", () => {
  const obj = { type: "WA_EMBEDDED_SIGNUP", event: "FINISH", data: { waba_id: "12345", phone_number_id: "67890" } };
  assert.equal(parseSignupMessage(FB, obj).kind, "finish");
  for (const junk of ["not json", "{", null, undefined, 5, [], {}, { type: "OTHER", event: "FINISH" }, JSON.stringify({ type: "WA_EMBEDDED_SIGNUP", event: "SOMETHING_ELSE" })]) {
    assert.equal(parseSignupMessage(FB, junk), null, String(junk));
  }
});

test("ids that are not plain digits are never passed on", () => {
  for (const bad of [{ waba_id: "abc" }, { phone_number_id: "1; drop" }, { waba_id: "" }, { phone_number_id: "../../x" }, { waba_id: "1".repeat(41) }]) {
    assert.equal(parseSignupMessage(FB, finish(bad)).kind, "error");
  }
});

test("closing the window is a cancel and the owner is told nothing alarming", () => {
  assert.deepEqual(parseSignupMessage(FB, JSON.stringify({ type: "WA_EMBEDDED_SIGNUP", event: "CANCEL", data: { current_step: "PHONE_NUMBER_SETUP" } })), { kind: "cancel" });
});

test("a connection is described in plain words with a tone and a next action", () => {
  const base = { id: "1", display_phone_number: "+91 98765 43210", verified_name: "Asha", quality_rating: "GREEN", is_test_number: false, webhook_status: "subscribed", attention_reason: null, connected_at: null, token_state: "no_expiry" };
  assert.deepEqual(connectionWords(null).label, "Not connected");
  assert.equal(connectionWords({ ...base, status: "disconnected" }).tone, "gray");
  assert.equal(connectionWords({ ...base, status: "pending" }).label, "Connecting");
  assert.equal(connectionWords({ ...base, status: "connected" }).tone, "green");
  assert.equal(connectionWords({ ...base, status: "connected", token_state: "expiring", attention_reason: "Your WhatsApp connection expires soon." }).tone, "amber");
  const bad = connectionWords({ ...base, status: "needs_attention", attention_reason: "Meta no longer accepts this connection." });
  assert.equal(bad.tone, "red");
  assert.equal(bad.hint, "Meta no longer accepts this connection.");
});

test("what a customer agreed to reads plainly, and an opt-out always wins", () => {
  const info = { since: "2026-11-19", source: "qr_page", wording_version: "v1" };
  assert.equal(consentWords({ marketing: null, utility: null, opted_out: false }).label, "No agreement yet");
  assert.equal(consentWords({ marketing: info, utility: null, opted_out: false }).label, "Agreed to offers");
  assert.equal(consentWords({ marketing: null, utility: info, opted_out: false }).label, "Agreed to visit updates");
  assert.equal(consentWords({ marketing: info, utility: info, opted_out: false }).label, "Agreed to offers and visit updates");
  const stopped = consentWords({ marketing: null, utility: info, opted_out: true });
  assert.equal(stopped.label, "Asked to stop offers");
  assert.equal(stopped.tone, "red");
  assert.equal(consentWords({ marketing: info, utility: info, opted_out: true }).label, "Asked to stop offers");
});

test("the next step follows where the set-up stands", () => {
  const counts = { contacts: 0, marketing: 0, utility: 0, opted_out: 0 };
  const conn = (status, extra = {}) => ({ id: "1", status, display_phone_number: "+91", verified_name: null, quality_rating: null, is_test_number: false, webhook_status: "subscribed", attention_reason: null, connected_at: null, token_state: "ok", ...extra });
  assert.match(nextStep({ addon: null, addon_required: true, connection: null, signup_available: true, counts }).title, /switch WhatsApp on/);
  const addon = { key: "whatsapp_starter" };
  assert.match(nextStep({ addon, addon_required: true, connection: null, signup_available: true, counts }).title, /Connect your WhatsApp/);
  assert.match(nextStep({ addon, addon_required: true, connection: null, signup_available: false, counts }).body, /not available yet/);
  assert.match(nextStep({ addon, addon_required: true, connection: conn("needs_attention", { attention_reason: "Meta reported a problem." }), signup_available: true, counts }).title, /Fix your connection/);
  assert.match(nextStep({ addon, addon_required: true, connection: conn("connected"), signup_available: true, counts }).title, /Add the customers/);
  assert.match(nextStep({ addon, addon_required: true, connection: conn("connected"), signup_available: true, counts: { ...counts, contacts: 3 } }).title, /set up/);
  assert.equal(nextStep({ addon: null, addon_required: false, connection: null, signup_available: true, counts }).href, "/whatsapp/connect");
});

test("the screens never use technical words for the owner", () => {
  const texts = [connectionWords(null), consentWords({ marketing: null, utility: null, opted_out: false }), nextStep({ addon: null, addon_required: true, connection: null, signup_available: true, counts: { contacts: 0, marketing: 0, utility: 0, opted_out: 0 } })];
  const blob = JSON.stringify(texts).toLowerCase();
  for (const jargon of ["webhook", "api", "waba", "token", "oauth", "payload", "phone_number_id"]) assert.ok(!blob.includes(jargon), jargon);
});

test("the CSV preview shows the first rows and counts the rest without sending anything", () => {
  const p = csvPreview("﻿phone,name,tags\n98765 10001,Anil,\"vip\"\r\n98765 10002,Bina,\n\n98765 10003,Chetan,new\n", 2);
  assert.deepEqual(p.header, ["phone", "name", "tags"]);
  assert.equal(p.total, 3);
  assert.deepEqual(p.rows, [["98765 10001", "Anil", "vip"], ["98765 10002", "Bina", ""]]);
  assert.deepEqual(csvPreview(""), { header: [], rows: [], total: 0 });
});

test("an automation that is not ready is labelled for what it is", () => {
  assert.equal(automationStatus({ coming_soon: true, available: false }), "Coming soon");
  assert.equal(automationStatus({ coming_soon: false, available: true }), "Ready");
  assert.equal(automationStatus({ coming_soon: false, available: false }), "Not available");
});
