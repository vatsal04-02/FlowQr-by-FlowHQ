import test from "node:test";
import assert from "node:assert/strict";
import { LINK_CLICKED, linkClickWords, birthdayProblem, birthdayWords, greetingKindWords, MONTHS, categoryLabel, freeAllowanceWords, rateProblem, rateStatus, RATE_CATEGORIES, confirmWords, keywordProblem, OPTIN_PURPOSES, SOURCE_WORDS, currentStep, looksLikeMobile, setupPercent, setupProgress, stepOpen, STEP_STATE, HELPER_TITLES, audienceSentence, barPercent, fromIstInput, hourWords, offerChoices, percent, toIstInput, windowSentence, AUTOMATION_FIELDS, audienceWords, automationStatus, campaignBlockers, CAMPAIGN_STATUS, connectionWords, consentWords, csvPreview, MESSAGE_STATUS, nextStep, parseSignupMessage, reasonWords, rupees, RUN_STATUS, TEMPLATE_STATUS } from "../src/lib/whatsapp.ts";

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

test("money is shown in rupees with two decimals and never invented", () => {
  assert.equal(rupees("2.59"), "₹2.59");
  assert.equal(rupees("1234.5"), "₹1,234.50");
  assert.equal(rupees("0"), "₹0.00");
  for (const none of [null, undefined, "", "abc"]) assert.equal(rupees(none), "–");
});

test("every reason a message was not sent reads as a plain sentence", () => {
  for (const r of ["no_utility_consent", "no_marketing_consent", "opted_out", "too_soon", "template_not_approved", "not_connected", "sending_disabled", "emergency_stop", "contact_deleted", "responded", "no_review_link",
    "asked_recently", "automation_paused", "campaign_cancelled", "meta_rejected", "meta_unavailable", "rate_limited", "daily_cap", "invalid_variables", "token_expired", "internal_error"]) {
    const w = reasonWords(r);
    assert.ok(w.length > 10 && w.endsWith("."), r);
    assert.ok(!/[_]|meta|api|webhook|token|template/i.test(w), `${r}: ${w}`);
  }
  assert.match(reasonWords("gave_up:meta_unavailable"), /tried several times and gave up/);
  assert.equal(reasonWords("something_new"), "It was not sent.");
  assert.equal(reasonWords(null), "");
});

test("who an offer goes to is always limited to people who agreed", () => {
  for (const a of [undefined, { kind: "all" }, { kind: "tag", tag: "regular" }, { kind: "new", days: 30 }, { kind: "existing", days: 60 }]) assert.match(audienceWords(a), /agreed to receive offers/);
  assert.match(audienceWords({ kind: "tag", tag: "regular" }), /“regular”/);
});

test("an offer cannot be approved until everything it needs is in place, and the reasons are plain", () => {
  const all = { ready: { plan: true, connection: true, template_approved: true, has_recipients: true, sending_on: false } };
  assert.deepEqual(campaignBlockers(all), []);  // sending being off does not block approval: it just waits
  const none = campaignBlockers({ ready: { plan: false, connection: false, template_approved: false, has_recipients: false, sending_on: false } });
  assert.equal(none.length, 4);
  assert.ok(none.every((b) => b.endsWith(".") && !/api|token|webhook/i.test(b)));
});

test("every status the server can send has a label and a tone", () => {
  for (const s of ["draft", "scheduled", "sending", "paused", "done", "cancelled"]) assert.ok(CAMPAIGN_STATUS[s].label && CAMPAIGN_STATUS[s].tone, s);
  for (const s of ["scheduled", "sending", "sent", "skipped", "failed", "cancelled"]) assert.ok(RUN_STATUS[s].label, s);
  for (const s of ["queued", "sent", "delivered", "read", "failed"]) assert.ok(MESSAGE_STATUS[s].label, s);
  for (const s of ["approved", "pending", "rejected", "paused", "disabled"]) assert.ok(TEMPLATE_STATUS[s].label, s);
  assert.notEqual(MESSAGE_STATUS.delivered.label, MESSAGE_STATUS.read.label);  // delivered is never called read
});

test("the helper settings use the same limits the server enforces", () => {
  const r = AUTOMATION_FIELDS.review_followup[0];
  assert.deepEqual([r.key, r.min, r.max], ["delay_minutes", 5, 10080]);
  const e = AUTOMATION_FIELDS.enquiry_followup;
  assert.equal(e.find((f) => f.key === "send_ack").bool, true);
  const h = e.find((f) => f.key === "follow_up_hours");
  assert.deepEqual([h.min, h.max], [1, 168]);
});

test("who an offer goes to is described in full, including the Pro choices", () => {
  assert.equal(audienceSentence({ kind: "all" }), "Everyone who agreed to receive offers");
  const s = audienceSentence({ kind: "all", tags_any: ["vip"], exclude_tags: ["staff"], location_id: "L1", not_messaged_days: 30, never_messaged: true }, (id) => (id === "L1" ? "Agra branch" : undefined));
  assert.match(s, /agreed to receive offers/);
  for (const part of ["“vip”", "not in “staff”", "at Agra branch", "last 30 days", "never had an offer"]) assert.ok(s.includes(part), part);
  assert.match(audienceSentence({ kind: "all", location_id: "L9" }), /at one location/);
});

test("only approved, text-only messages that WhatsApp treats as offers can be chosen", () => {
  const t = (o) => ({ id: "x", name: "n", key: null, language: "en", category: "marketing", status: "approved", body: "b", variables: [], rejection_reason: null, synced_at: null, simple: true, ...o });
  const all = [t({ id: "1" }), t({ id: "2", status: "pending" }), t({ id: "3", category: "utility" }), t({ id: "4", simple: false }), t({ id: "5", status: "rejected" }), t({ id: "6", simple: undefined })];
  assert.deepEqual(offerChoices(all).map((x) => x.id), ["1", "6"]);
});

test("sending hours read as a plain sentence", () => {
  assert.deepEqual([0, 9, 12, 13, 21, 24].map(hourWords), ["12 am", "9 am", "12 pm", "1 pm", "9 pm", "midnight"]);
  assert.equal(windowSentence({ start: 9, end: 21, timezone: "Asia/Kolkata", open_now: true, always: false }), "Offers go out between 9 am and 9 pm (India time). Outside those hours they wait.");
  assert.equal(windowSentence({ start: 0, end: 24, timezone: "Asia/Kolkata", open_now: true, always: true }), "Offers can go out at any time of day.");
});

test("India-time inputs round-trip to the instant the server stores", () => {
  assert.equal(fromIstInput("2026-12-05T11:30"), "2026-12-05T11:30:00+05:30");
  assert.equal(fromIstInput(""), null);
  assert.equal(toIstInput("2026-12-05T06:00:00Z"), "2026-12-05T11:30");
  assert.equal(toIstInput(null), "");
  assert.equal(new Date(fromIstInput(toIstInput("2026-12-05T06:00:00Z"))).toISOString(), "2026-12-05T06:00:00.000Z");
});

test("chart bars and rates never invent a number", () => {
  assert.equal(barPercent(0, 10), 0);
  assert.equal(barPercent(10, 10), 100);
  assert.equal(barPercent(1, 1000), 4);
  assert.equal(barPercent(5, 0), 0);
  assert.equal(percent(null), "–");
  assert.equal(percent(undefined), "–");
  assert.equal(percent(0), "0%");
  assert.equal(percent(75), "75%");
});

const mkStep = (key, state) => ({ key, title: key, body: "b", state, action: "x" });
const mkSetup = (states) => ({ steps: ["plan", "connect", "messages", "customers", "test", "helper"].map((k, i) => mkStep(k, states[i])), done: states.filter((x) => x === "done").length, total: 6, complete: states.every((x) => x === "done") });

test("progress is told in words and a bar that never lies", () => {
  assert.equal(setupProgress(mkSetup(["done", "done", "todo", "todo", "blocked", "blocked"])), "2 of 6 steps done");
  assert.equal(setupProgress(mkSetup(Array(6).fill("done"))), "You are all set up.");
  assert.equal(setupPercent(mkSetup(["done", "done", "done", "todo", "todo", "todo"])), 50);
  assert.equal(setupPercent({ done: 0, total: 0 }), 0);
  assert.equal(setupPercent(mkSetup(Array(6).fill("done"))), 100);
});

test("the step to work on is the first one that is not done, even when it has to wait", () => {
  assert.equal(currentStep(mkSetup(["done", "done", "waiting", "todo", "blocked", "blocked"])).key, "messages");
  assert.equal(currentStep(mkSetup(["blocked", "blocked", "blocked", "todo", "blocked", "blocked"])).key, "plan");
  assert.equal(currentStep(mkSetup(Array(6).fill("done"))), null);
});

test("a step opens when it is the current one or the owner opened it, but a not-yet step stays closed", () => {
  const s = mkSetup(["done", "todo", "blocked", "todo", "blocked", "blocked"]);
  const cur = currentStep(s);
  assert.equal(stepOpen(s.steps[1], cur, null), true);   // the current step
  assert.equal(stepOpen(s.steps[0], cur, null), false);  // a finished step is closed
  assert.equal(stepOpen(s.steps[3], cur, null), false);  // a later step is closed
  assert.equal(stepOpen(s.steps[0], cur, "plan"), true); // the owner opened it
  const blockedCurrent = mkSetup(["blocked", "blocked", "blocked", "todo", "blocked", "blocked"]);
  assert.equal(stepOpen(blockedCurrent.steps[0], currentStep(blockedCurrent), null), false); // a blocked step does not open by itself
});

test("every set-up state has a plain label", () => {
  for (const k of ["done", "todo", "waiting", "blocked"]) assert.ok(STEP_STATE[k].label && STEP_STATE[k].tone, k);
  assert.deepEqual(Object.keys(HELPER_TITLES).sort(), ["enquiry_followup", "offers", "review_followup"]);
});

test("a number worth sending to the server looks like an Indian mobile number or an international one", () => {
  for (const ok of ["98765 43210", "9876543210", "+91 98765 43210", "919876543210", "+44 7911 123456"]) assert.equal(looksLikeMobile(ok), true, ok);
  for (const bad of ["", "12345", "abcdefghij", "98765", "0000", "123456789"]) assert.equal(looksLikeMobile(bad), false, bad);
});

test("a keyword is checked the way the server checks it", () => {
  for (const ok of ["joinus", "JoinUs", " welcome ", "abc", "a".repeat(20)]) assert.equal(keywordProblem(ok), null, ok);
  for (const bad of ["", "ab", "hello world", "join!", "a".repeat(21), "yes", "OK", "Stop", "stopall", "opt-out", "unsubscribe"]) assert.notEqual(keywordProblem(bad), null, bad);
});

test("each way of joining is named for the owner and every purpose has plain words", () => {
  assert.equal(SOURCE_WORDS.qr_click_to_chat, "Joined from your QR page");
  assert.equal(SOURCE_WORDS.keyword_opt_in, "Joined by texting a keyword");
  assert.deepEqual(OPTIN_PURPOSES.map((p) => p.value), ["utility", "marketing", "both"]);
  assert.ok(OPTIN_PURPOSES[0].hint.includes("do not agree to offers"));
});

test("the thank-you message state is told plainly", () => {
  assert.deepEqual(confirmWords(null), { label: "Not sent to WhatsApp yet", tone: "gray" });
  assert.equal(confirmWords("approved").tone, "green");
  assert.equal(confirmWords("pending").tone, "amber");
  assert.equal(confirmWords("rejected").tone, "red");
});

test("a price is Verified only when its latest check says so, and otherwise it is plainly UNVERIFIED", () => {
  assert.deepEqual(rateStatus({ verified: true }), { label: "Verified", tone: "green" });
  assert.deepEqual(rateStatus({ verified: false }), { label: "UNVERIFIED", tone: "amber" });
});

test("a typed price is a plain rupee amount", () => {
  for (const ok of ["1.09", "0.145", "0", "999.9999", " 0.8631 "]) assert.equal(rateProblem(ok), null, ok);
  for (const bad of ["", "abc", "-1", "1,09", "1.23456", "10000", "1e3", "Rs 1"]) assert.notEqual(rateProblem(bad), null, bad);
});

test("the four Meta categories and the free allowance have plain words", () => {
  assert.deepEqual(RATE_CATEGORIES.map((c) => c.value), ["marketing", "utility", "authentication", "service"]);
  assert.equal(categoryLabel("service"), "Service (replies inside 24 hours)");
  assert.equal(categoryLabel("other"), "other");
  assert.equal(freeAllowanceWords(1000), "First 1,000 free per number each month");
  assert.equal(freeAllowanceWords(0), "No free allowance");
});

test("a birthday is a day and a month that exist, and 29 February is allowed", () => {
  for (const [d, m] of [[14, 3], [29, 2], [31, 1], [30, 4], [1, 12]]) assert.equal(birthdayProblem(d, m), null, `${d}/${m}`);
  for (const [d, m] of [[30, 2], [31, 4], [31, 6], [31, 9], [31, 11], [0, 5], [5, 13], [5, 0], [1.5, 3]]) assert.notEqual(birthdayProblem(d, m), null, `${d}/${m}`);
  assert.equal(birthdayWords(14, 3), "14 March");
  assert.equal(birthdayWords(null, 3), "");
  assert.equal(MONTHS.length, 12);
});

test("what kind a greeting is says unknown until WhatsApp has reported it", () => {
  assert.deepEqual(greetingKindWords({ submitted: false, category: null, category_known: false }), { label: "Not sent to WhatsApp yet", tone: "gray" });
  assert.deepEqual(greetingKindWords({ submitted: true, category: null, category_known: false }), { label: "Category not confirmed yet", tone: "amber" });
  assert.deepEqual(greetingKindWords({ submitted: true, category: "marketing", category_known: true }), { label: "Marketing message", tone: "amber" });
  assert.deepEqual(greetingKindWords({ submitted: true, category: "utility", category_known: true }), { label: "Update message", tone: "green" });
});

test("greeting helpers choose an hour from 9 to 20 and refusals read as plain sentences", () => {
  for (const k of ["birthday", "festival"]) {
    const f = AUTOMATION_FIELDS[k][0];
    assert.equal(f.key, "send_hour");
    assert.equal(f.min, 9);
    assert.equal(f.max, 20);
  }
  for (const code of ["no_occasion_consent", "greeting_too_soon", "outside_hours", "day_passed", "plan_required"]) assert.match(reasonWords(code), /[a-z]{4,}/, code);
  assert.match(reasonWords("outside_hours"), /9 am and 9 pm/);
});

test("a link click is only ever called link clicked", () => {
  assert.equal(LINK_CLICKED, "Link clicked");
  assert.equal(linkClickWords("2026-11-19T10:00:00Z"), "Link clicked");
  assert.equal(linkClickWords(null), "");
  assert.equal(linkClickWords(undefined), "");
  assert.doesNotMatch(LINK_CLICKED + linkClickWords("x"), /review|rating|star|left|sale/i);
});

test("the review helper offers to count link clicks as a yes or no setting", () => {
  const f = AUTOMATION_FIELDS.review_followup.find((x) => x.key === "track_clicks");
  assert.ok(f && f.bool === true);
  assert.match(f.label, /Pro/);
});
