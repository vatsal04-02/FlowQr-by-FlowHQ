/** WhatsApp automation (Phase 1): types for the API, the plain-language words the owner sees, and the Embedded Signup launcher. No access token ever reaches this code: the server keeps it. */

export type ConnStatus = "pending" | "connected" | "needs_attention" | "disconnected";
export interface WaConnection {
  id: string; status: ConnStatus; display_phone_number: string | null; verified_name: string | null; quality_rating: string | null; is_test_number: boolean;
  webhook_status: "unknown" | "subscribed" | "failed"; attention_reason: string | null; connected_at: string | null; token_state: "ok" | "expiring" | "expired" | "missing" | "no_expiry";
}
export interface WaTier { key: string; label: string; price_inr_month: number; automation_limit: number; summary: string; campaigns: boolean; segmentation: string }
export interface WaStatus {
  enabled: boolean; signup_available: boolean; addon_required: boolean; addon: (WaTier & { since: string }) | null; tiers: WaTier[]; connection: WaConnection | null;
  counts: { contacts: number; marketing: number; utility: number; occasion?: number; opted_out: number }; messaging: { enabled: boolean; emergency_stop: boolean }; can_connect: boolean;
}
export interface WaConsentInfo { since: string; source: string; wording_version: string }
export interface WaContact {
  id: string; phone: string; customer_name: string | null; tags: string[]; location_id?: string | null; source: string; created_at: string; marketing: WaConsentInfo | null; utility: WaConsentInfo | null; opted_out: boolean; opted_out_at: string | null;
  occasion?: WaConsentInfo | null; birth_day?: number | null; birth_month?: number | null; last_visit_at?: string | null; last_replied_at?: string | null; last_enquiry_at?: string | null; no_consent_contact?: boolean;
}
export interface WaContacts { total: number; items: WaContact[]; counts: WaStatus["counts"]; wording: { marketing: string; utility: string; occasion?: string } }
export interface WaChecklist { connected: boolean; templates_installed: boolean; templates_approved: boolean; missing: string[]; waiting: string[]; refused: string[] }
export interface WaAutomationState { key: string; status: "off" | "on" | "paused"; config: Record<string, number | boolean>; activated_at: string | null; last_run_at: string | null; runs: Record<string, number>; checklist: WaChecklist }
export interface WaAutomation {
  key: string; title: string; description: string; purpose: "marketing" | "utility" | "occasion"; needs: string[]; available: boolean; coming_soon: boolean; ready: { connection: boolean; addon: boolean; customers: boolean };
  state?: WaAutomationState; campaigns_allowed?: boolean;
}
export interface WaAutomations { items: WaAutomation[]; limit: number | null; active: number; sending: boolean }
export interface WaRun { id: string; step: string; status: string; reason: string | null; to: string | null; phone_last4: string | null; scheduled_at: string; executed_at: string | null; attempts: number }
export interface WaTemplate { id: string; name: string; key: string | null; language: string; category: string; status: string; body: string | null; variables: string[]; rejection_reason: string | null; synced_at: string | null; simple?: boolean }
export interface WaTemplates { items: WaTemplate[]; available: { key: string; category: string; body: string; installed: boolean }[] }
export interface WaEstimate { category: string; count: number; rate: string | null; currency: string | null; amount: string | null; verified: boolean; note: string; warning?: string | null; free_included?: number; billable?: number; effective_from?: string | null }
export type WaEngaged = "read" | "replied" | "clicked" | "delivered_not_read";
export type WaAudience = { kind: string; tag?: string; days?: number; tags_any?: string[]; tags_all?: string[]; exclude_tags?: string[]; location_id?: string; not_messaged_days?: number; never_messaged?: boolean;
  engaged?: WaEngaged; engaged_days?: number; no_engagement_last_offers?: number; winback_days?: number };
export type WaMapping = { source: "customer_name" | "business_name" | "text"; value?: string };
export type WaVariables = { offer_text?: string; mapping?: WaMapping[] };
export interface WaCampaign { id: string; name: string; status: "draft" | "scheduled" | "sending" | "paused" | "done" | "cancelled"; audience: WaAudience; variables: WaVariables; template_id: string | null;
  scheduled_at: string | null; approved_at: string | null; approved_recipients: number | null; approved_cost: string | null; started_at: string | null; finished_at: string | null; created_at: string }
export interface WaWindow { start: number; end: number; timezone: string; open_now: boolean; always: boolean }
export interface WaCampaignPreview { id: string; name: string; status: WaCampaign["status"]; audience: WaCampaign["audience"]; recipients: number; estimate: WaEstimate; message_preview: string | null; excluded_note: string;
  ready: { plan: boolean; connection: boolean; template_approved: boolean; has_recipients: boolean; sending_on: boolean }; approved_recipients: number | null; approved_cost: string | null;
  scheduled_at: string | null; variables: WaVariables; template_id: string | null; segmentation: "none" | "basic" | "advanced"; window: WaWindow; starts_at: string; waits_for_hours: boolean; estimated_minutes: number;
  matching?: number; excluded?: { no_consent: number; opted_out: number }; audience_notes?: { key: string; text: string; basis?: string }[] }
export interface WaDay { date: string; sent: number; delivered: number; read: number; failed: number }
export interface WaCompareRow { id: string; name: string; status: string; approved_recipients: number | null; sent: number; delivered: number; read: number; failed: number; delivery_rate: number | null; read_rate: number | null;
  opted_out_after: number; estimated_meta_cost: string; approved_estimate: string | null; started_at: string | null }
export interface WaCampaignResults { id: string; name: string; status: string; approved_recipients: number | null; approved_estimate: string | null; attempted: number; sent: number; delivered: number; read: number; failed: number;
  waiting: number; skipped: number; skipped_reasons: Record<string, number>; opted_out_after: number; estimated_meta_cost: string; note: string; delivery_rate: number | null; read_rate: number | null; timeline: WaDay[] }
export interface WaUsage { month: string; totals: { attempted: number; sent: number; delivered: number; read: number; failed: number }; by_category: Record<string, { attempted: number; sent: number; delivered: number; read: number; failed: number; estimated_cost: string }>;
  estimated_meta_cost: string; currency: string; note: string; delivery_rate: number | null; rates: { marketing: WaEstimate; utility: WaEstimate }; limits: { per_minute: number; per_day: number }; price_warning?: string | null; links?: WaLinkSummary }
export interface WaMessageRow { link_clicked_at?: string | null; id: string; to: string | null; phone_last4: string | null; category: string | null; status: string; error_code: string | null; sent_at: string | null; delivered_at: string | null; read_at: string | null; created_at: string }
export interface SignupStart { app_id: string; config_id: string; graph_version: string; state: string; expires_at: string }

/** How a connection is described to a shop owner: plain words, a tone for the badge, and what to do next. */
export function connectionWords(c: WaConnection | null): { label: string; tone: "green" | "amber" | "gray" | "red"; hint: string } {
  if (!c || c.status === "disconnected") return { label: "Not connected", tone: "gray", hint: "Connect your WhatsApp number to start." };
  if (c.status === "pending") return { label: "Connecting", tone: "amber", hint: "Finish the steps in the WhatsApp window, or start again." };
  if (c.status === "needs_attention") return { label: "Needs attention", tone: "red", hint: c.attention_reason ?? "Check your connection." };
  if (c.token_state === "expiring") return { label: "Connected, renew soon", tone: "amber", hint: c.attention_reason ?? "Your connection expires soon." };
  return { label: "Connected", tone: "green", hint: "Your WhatsApp number is connected." };
}

/** What a customer has agreed to, in words an owner understands. */
export function consentWords(c: Pick<WaContact, "marketing" | "utility" | "opted_out"> & { no_consent_contact?: boolean }): { label: string; tone: "green" | "blue" | "gray" | "red" } {
  if (c.opted_out) return { label: "Asked to stop offers", tone: "red" };
  if (c.no_consent_contact) return { label: "Contact, no consent", tone: "gray" };  // someone who wrote to you: kept so you can reply, never messaged first
  if (c.marketing && c.utility) return { label: "Agreed to offers and visit updates", tone: "green" };
  if (c.marketing) return { label: "Agreed to offers", tone: "green" };
  if (c.utility) return { label: "Agreed to visit updates", tone: "blue" };
  return { label: "No agreement yet", tone: "gray" };
}

export const SOURCE_WORDS: Record<string, string> = {
  qr_page: "On your review page", website_form: "On your website", customer_message: "Messaged you", owner_entry: "Added by you", csv_import: "Imported by you", admin_entry: "Added by FlowQR",
  qr_click_to_chat: "Joined from your QR page", keyword_opt_in: "Joined by texting a keyword",
};

/** Opt-in without a phone number: the QR page's WhatsApp button and opt-in keywords. */
export type OptinPurpose = "utility" | "marketing" | "both";
export interface WaOptinKeyword { id: string; keyword: string; purpose: OptinPurpose; enabled: boolean; confirm_reply: boolean; wording: string }
export interface WaOptin {
  settings: { code: string; qr_enabled: boolean; purpose: OptinPurpose; confirm_reply: boolean; prefill_text: string } | null;
  keywords: WaOptinKeyword[]; max_keywords: number; connected: boolean; link_live: boolean; link_example: string | null;
  confirm_templates: Record<"optin_confirm" | "optin_confirm_offers", string | null>; purpose_words: Record<OptinPurpose, string>;
}
export const OPTIN_PURPOSES: { value: OptinPurpose; label: string; hint: string }[] = [
  { value: "utility", label: "Updates about their visits and enquiries", hint: "The safest choice. Customers do not agree to offers." },
  { value: "marketing", label: "Offers and updates", hint: "Customers agree to receive your offers." },
  { value: "both", label: "Visit updates and offers", hint: "Customers agree to both, in one message." },
];
const RESERVED = new Set(["yes", "no", "ok", "okay", "hi", "hello", "hey", "thanks", "thank", "help", "start", "stop", "join", "cancel", "unsubscribe", "optout"]);
/** Mirrors the server's check so a bad word is caught before it is sent. The server decides. */
export function keywordProblem(raw: string): string | null {
  const k = raw.trim().toLowerCase();
  if (!/^[a-z0-9]{3,20}$/.test(k)) return "Use 3 to 20 letters or numbers, with no spaces.";
  if (RESERVED.has(k) || ["stop all", "stopall", "opt out", "opt-out"].includes(k)) return "That word is too common or already means something else. Choose a more specific word.";
  return null;
}
/** What the owner is told about the confirmation message, from the approval state WhatsApp reported. */
export function confirmWords(status: string | null | undefined): { label: string; tone: "green" | "amber" | "gray" | "red" } {
  if (!status) return { label: "Not sent to WhatsApp yet", tone: "gray" };
  if (status === "approved") return { label: "Approved", tone: "green" };
  if (status === "pending") return { label: "WhatsApp is reviewing it", tone: "amber" };
  return { label: "Not approved", tone: "red" };
}

/** Where a given automation stands, as one sentence. */
export function automationStatus(a: WaAutomation): string {
  if (a.coming_soon) return "Coming soon";
  return a.available ? "Ready" : "Not available";
}

/** The first thing an owner should do, given where their set-up stands. */
export function nextStep(s: Pick<WaStatus, "addon" | "addon_required" | "connection" | "signup_available" | "counts">): { title: string; body: string; href: string; cta: string } {
  if (s.addon_required && !s.addon) return { title: "Ask us to switch WhatsApp on", body: "WhatsApp automation is an add-on. Tell the FlowQR team and we will turn it on for your business.", href: "/settings", cta: "Open settings" };
  const c = s.connection;
  if (!c || c.status === "disconnected" || c.status === "pending") return { title: "Connect your WhatsApp", body: s.signup_available ? "It takes about ten minutes. You will need your WhatsApp number and a Facebook login." : "Connecting is not available yet. FlowQR is still completing its set-up with Meta.", href: "/whatsapp/connect", cta: "Connect WhatsApp" };
  if (c.status === "needs_attention") return { title: "Fix your connection", body: c.attention_reason ?? "Your WhatsApp connection needs attention.", href: "/whatsapp/connect", cta: "Open connection" };
  if (s.counts.contacts === 0) return { title: "Add the customers who agreed to hear from you", body: "Only customers who agreed can receive messages. Add them one by one or upload a list you have consent for.", href: "/whatsapp/contacts", cta: "Add customers" };
  return { title: "You are set up", body: "Your automations will appear here as they become available.", href: "/whatsapp/automations", cta: "See automations" };
}

// ---- Embedded Signup. Meta's popup reports the chosen account and number through a window message; the one-time `code` comes from FB.login. Both are untrusted until the server confirms them with Meta.
export type SignupMessage = { kind: "finish"; waba_id: string; phone_number_id: string } | { kind: "cancel" } | { kind: "error"; message: string };

const FB_ORIGINS = new Set(["https://www.facebook.com", "https://web.facebook.com", "https://business.facebook.com"]);

/** Reads a window `message` event from Meta's popup. Anything from another origin, or not shaped like an Embedded Signup event, is null. */
export function parseSignupMessage(origin: string, data: unknown): SignupMessage | null {
  if (!FB_ORIGINS.has(origin)) return null;
  let d: unknown = data;
  if (typeof d === "string") { try { d = JSON.parse(d); } catch { return null; } }
  if (!d || typeof d !== "object") return null;
  const o = d as { type?: unknown; event?: unknown; data?: Record<string, unknown> };
  if (o.type !== "WA_EMBEDDED_SIGNUP") return null;
  if (o.event === "FINISH" || o.event === "FINISH_ONLY_WABA" || o.event === "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING") {
    const waba = String(o.data?.waba_id ?? ""), phone = String(o.data?.phone_number_id ?? "");
    return /^\d{5,40}$/.test(waba) && /^\d{5,40}$/.test(phone) ? { kind: "finish", waba_id: waba, phone_number_id: phone } : { kind: "error", message: "WhatsApp did not share a phone number. Please try again and add a number." };
  }
  if (o.event === "CANCEL") return { kind: "cancel" };
  return null;
}

declare global { interface Window { FB?: { init: (o: Record<string, unknown>) => void; login: (cb: (r: { authResponse?: { code?: string } | null }) => void, o: Record<string, unknown>) => void }; fbAsyncInit?: () => void } }

function loadSdk(appId: string, version: string): Promise<void> {
  return new Promise((resolve, reject) => {
    if (window.FB) { window.FB.init({ appId, autoLogAppEvents: true, xfbml: false, version }); resolve(); return; }
    window.fbAsyncInit = () => { window.FB?.init({ appId, autoLogAppEvents: true, xfbml: false, version }); resolve(); };
    const s = document.createElement("script");
    s.src = "https://connect.facebook.net/en_US/sdk.js"; s.async = true; s.defer = true; s.crossOrigin = "anonymous";
    s.onerror = () => reject(new Error("We could not load WhatsApp's sign-up window. Check your connection and try again."));
    document.body.appendChild(s);
  });
}

/** Opens Meta's Embedded Signup. Resolves with what Meta returned (to be sent to FlowQR's server together with the `state` from /connect/start); rejects with a plain-words message. */
export async function launchEmbeddedSignup(cfg: Pick<SignupStart, "app_id" | "config_id" | "graph_version">): Promise<{ code: string; waba_id: string; phone_number_id: string }> {
  await loadSdk(cfg.app_id, cfg.graph_version);
  return new Promise((resolve, reject) => {
    let code: string | null = null, ids: { waba_id: string; phone_number_id: string } | null = null, done = false;
    const finish = (fn: () => void) => { if (done) return; done = true; window.removeEventListener("message", onMsg); clearTimeout(timer); fn(); };
    const maybe = () => { if (code && ids) finish(() => resolve({ code: code as string, ...(ids as { waba_id: string; phone_number_id: string }) })); };
    const onMsg = (e: MessageEvent) => {
      const m = parseSignupMessage(e.origin, e.data);
      if (!m) return;
      if (m.kind === "finish") { ids = { waba_id: m.waba_id, phone_number_id: m.phone_number_id }; maybe(); }
      else if (m.kind === "cancel") finish(() => reject(new Error("You closed the WhatsApp window before finishing. Press Connect WhatsApp to try again.")));
      else finish(() => reject(new Error(m.message)));
    };
    const timer = setTimeout(() => finish(() => reject(new Error("That took too long. Please try again."))), 10 * 60 * 1000);
    window.addEventListener("message", onMsg);
    window.FB?.login((r) => {
      const c = r.authResponse?.code;
      if (!c) { finish(() => reject(new Error("The connection was not completed. Press Connect WhatsApp to try again."))); return; }
      code = c; maybe();
    }, { config_id: cfg.config_id, response_type: "code", override_default_response_type: true, extras: { setup: {}, featureType: "", sessionInfoVersion: "3" } });
  });
}

/** A short CSV template an owner can download to fill in. */
export const CSV_TEMPLATE = "phone,name,tags\n98765 43210,Asha Verma,regular\n";

/** Reads the first lines of a CSV so the owner can check it before importing (nothing is sent anywhere). */
export function csvPreview(text: string, max = 5): { header: string[]; rows: string[][]; total: number } {
  const lines = text.replace(/^﻿/, "").split(/\r?\n/).filter((l) => l.trim());
  const cut = (l: string) => l.split(",").map((c) => c.trim().replace(/^"|"$/g, ""));
  return { header: lines[0] ? cut(lines[0]) : [], rows: lines.slice(1, 1 + max).map(cut), total: Math.max(0, lines.length - 1) };
}

// ---- Phase 2 and 3: plain words for the helpers, campaigns, costs and messages

/** Money as the owner sees it: rupees with two decimals, or a dash when no rate is known. Always an estimate; the screens say so. */
export function rupees(v: string | null | undefined): string {
  if (v === null || v === undefined || v === "") return "–";
  const n = Number(v);
  return Number.isFinite(n) ? `₹${n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : "–";
}

/** Why a message was not sent, in words an owner understands. Unknown codes read as a plain sentence, never a code. */
export function reasonWords(reason: string | null | undefined): string {
  const map: Record<string, string> = {
    no_utility_consent: "They have not agreed to updates about their visit.", no_marketing_consent: "They have not agreed to receive offers.", opted_out: "They asked to stop offers.",
    too_soon: "They already got an offer very recently.", template_not_approved: "WhatsApp has not approved the message yet.", not_connected: "WhatsApp is not connected.",
    sending_disabled: "Sending is not switched on yet.", emergency_stop: "Sending is paused for everyone for now.", no_addon: "The WhatsApp add-on is not on.",
    contact_deleted: "The customer was deleted.", responded: "Someone had already replied to them.", no_review_link: "Your Google review link is missing.", asked_recently: "They were asked recently.",
    automation_paused: "The helper was paused.", automation_off: "The helper was switched off.", campaign_cancelled: "The campaign was cancelled.", meta_rejected: "WhatsApp did not accept it.",
    meta_unavailable: "WhatsApp was not reachable. We will try again.", rate_limited: "Waiting for the sending limit.", daily_cap: "The daily limit was reached.", template_missing: "The message is not set up yet.",
    invalid_variables: "Something in the message was empty.", token_expired: "The WhatsApp connection needs renewing.", internal_error: "Something went wrong. We will try again.",
    no_occasion_consent: "They have not agreed to birthday and festival greetings.", greeting_too_soon: "They already got a greeting in the last 14 days.",
    outside_hours: "Greetings go out only between 9 am and 9 pm India time, and this was outside those hours.", day_passed: "Its day had already passed, so it was not sent late.",
    plan_required: "Greetings are part of the Growth and Pro plans.", kind_mismatch: "That message cannot be sent this way.",
  };
  if (!reason) return "";
  if (reason.startsWith("gave_up:")) return "We tried several times and gave up. " + (map[reason.slice(8)] ?? "");
  return map[reason] ?? "It was not sent.";
}

export const RUN_STATUS: Record<string, { label: string; tone: "green" | "amber" | "gray" | "red" }> = {
  scheduled: { label: "Waiting to send", tone: "amber" }, sending: { label: "Sending", tone: "amber" }, sent: { label: "Sent", tone: "green" }, skipped: { label: "Not sent", tone: "gray" },
  failed: { label: "Failed", tone: "red" }, cancelled: { label: "Cancelled", tone: "gray" },
};

export const CAMPAIGN_STATUS: Record<WaCampaign["status"], { label: string; tone: "green" | "amber" | "gray" | "red" | "blue" }> = {
  draft: { label: "Draft", tone: "gray" }, scheduled: { label: "Approved, waiting to start", tone: "blue" }, sending: { label: "Sending", tone: "amber" }, paused: { label: "Paused", tone: "amber" },
  done: { label: "Finished", tone: "green" }, cancelled: { label: "Cancelled", tone: "gray" },
};

/** Who a campaign goes to, in one line. */
export function audienceWords(a: WaCampaign["audience"] | undefined): string {
  if (!a || a.kind === "all") return "Everyone who agreed to receive offers";
  if (a.kind === "tag") return `Customers in the group “${a.tag}” who agreed to receive offers`;
  if (a.kind === "new") return `New customers from the last ${a.days} days who agreed to receive offers`;
  if (a.kind === "existing") return `Customers added more than ${a.days} days ago who agreed to receive offers`;
  return "Customers who agreed to receive offers";
}

/** What blocks a campaign from being approved, as a short list of plain sentences. Empty = ready. */
export function campaignBlockers(p: Pick<WaCampaignPreview, "ready">): string[] {
  const out: string[] = [];
  if (!p.ready.plan) out.push("Campaigns are part of the Growth and Pro add-ons.");
  if (!p.ready.connection) out.push("Connect your WhatsApp number.");
  if (!p.ready.template_approved) out.push("WhatsApp has not approved the offer message yet.");
  if (!p.ready.has_recipients) out.push("No customers who agreed to receive offers match this group.");
  return out;
}

export const MESSAGE_STATUS: Record<string, { label: string; tone: "green" | "blue" | "gray" | "red" | "amber" }> = {
  queued: { label: "Preparing", tone: "gray" }, sent: { label: "Sent", tone: "blue" }, delivered: { label: "Delivered", tone: "green" }, read: { label: "Read", tone: "green" }, failed: { label: "Not delivered", tone: "red" },
};

export const TEMPLATE_STATUS: Record<string, { label: string; tone: "green" | "amber" | "gray" | "red" }> = {
  approved: { label: "Approved", tone: "green" }, pending: { label: "WhatsApp is reviewing", tone: "amber" }, rejected: { label: "Not approved", tone: "red" }, paused: { label: "Paused by WhatsApp", tone: "amber" }, disabled: { label: "Not available", tone: "gray" },
};

export const TEMPLATE_TITLES: Record<string, string> = { review_followup: "Review request", enquiry_ack: "Thank you for your enquiry", enquiry_followup: "Enquiry follow-up", offer: "Offer" };

/** The helper's settings in words, with the limits the server enforces. */
export type AutomationField = { key: string; label: string; bool: true } | { key: string; label: string; unit: string; min: number; max: number };
export const AUTOMATION_FIELDS: Record<string, AutomationField[]> = {
  review_followup: [{ key: "delay_minutes", label: "Send the review request after", unit: "minutes", min: 5, max: 10080 }, { key: "track_clicks", label: "Count when a customer opens the review link (Pro plan)", bool: true }],
  enquiry_followup: [{ key: "send_ack", label: "Send a thank-you straight away", bool: true }, { key: "follow_up_hours", label: "Follow up if nobody has replied after", unit: "hours", min: 1, max: 168 }],
  birthday: [{ key: "send_hour", label: "Send the greeting at", unit: "o'clock, India time (9 to 20)", min: 9, max: 20 }],
  festival: [{ key: "send_hour", label: "Send the greeting at", unit: "o'clock, India time (9 to 20)", min: 9, max: 20 }],
};

// ---- Phase 4: the campaign manager

/** Who a campaign goes to, including the Pro choices, in one plain sentence. */
export function audienceSentence(a: WaAudience | undefined, locationName?: (id: string) => string | undefined): string {
  const base = audienceWords(a);
  if (!a) return base;
  const extra: string[] = [];
  if (a.tags_any?.length) extra.push(`in any of the groups ${a.tags_any.map((t) => `“${t}”`).join(", ")}`);
  if (a.tags_all?.length) extra.push(`in all of the groups ${a.tags_all.map((t) => `“${t}”`).join(", ")}`);
  if (a.exclude_tags?.length) extra.push(`not in ${a.exclude_tags.map((t) => `“${t}”`).join(", ")}`);
  if (a.location_id) extra.push(`at ${locationName?.(a.location_id) ?? "one location"}`);
  if (a.not_messaged_days) extra.push(`who have not had an offer in the last ${a.not_messaged_days} days`);
  if (a.never_messaged) extra.push("who have never had an offer");
  if (a.engaged) extra.push(`${ENGAGED_SENTENCE[a.engaged]} in the last ${a.engaged_days ?? 30} days`);
  if (a.no_engagement_last_offers) extra.push(`who did not read, reply to or click their last ${a.no_engagement_last_offers} offer${a.no_engagement_last_offers === 1 ? "" : "s"}`);
  if (a.winback_days) extra.push(`who have not visited or been messaged in the last ${a.winback_days} days`);
  return extra.length ? `${base}, ${extra.join(", ")}` : base;
}

/** The messages a business can use for an offer: approved, treated by WhatsApp as an offer, and text-only. */
export function offerChoices(items: WaTemplate[]): WaTemplate[] {
  return items.filter((t) => t.status === "approved" && t.category === "marketing" && t.simple !== false);
}

/** One blank of a message, described for the owner. Standard offers have fixed blanks; other messages are filled by the owner. */
export function blankLabel(i: number): string { return `Blank ${i + 1}`; }

/** An hour of the day (India time) as the owner reads it, for example 9 am or 9 pm. */
export function hourWords(h: number): string {
  const x = h % 24;
  const word = x === 0 ? "12 am" : x < 12 ? `${x} am` : x === 12 ? "12 pm" : `${x - 12} pm`;
  return h === 24 ? "midnight" : word;
}

/** The sending hours as one sentence. */
export function windowSentence(w: WaWindow): string {
  return w.always ? "Offers can go out at any time of day." : `Offers go out between ${hourWords(w.start)} and ${hourWords(w.end)} (India time). Outside those hours they wait.`;
}

/** The value for a datetime-local input (India time) from an ISO instant, and back. */
export function toIstInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(new Date(iso).getTime() + 5.5 * 3600 * 1000);
  return d.toISOString().slice(0, 16);
}
export function fromIstInput(v: string): string | null {
  return v ? `${v}:00+05:30` : null;
}

/** A bar's width (0 to 100) for a count against the largest count, never below a visible sliver for a non-zero count. */
export function barPercent(n: number, max: number): number {
  if (n <= 0 || max <= 0) return 0;
  return Math.max(4, Math.round((n * 100) / max));
}

/** A rate as the owner reads it: a whole percent, or a dash when nothing was measured. */
export function percent(v: number | null | undefined): string {
  return v === null || v === undefined ? "–" : `${v}%`;
}

// ---- Phase 5: first-run set-up

export type StepState = "done" | "todo" | "waiting" | "blocked";
export interface WaStep { key: "plan" | "connect" | "messages" | "customers" | "test" | "helper"; title: string; body: string; state: StepState; action: string;
  missing?: string[]; pending?: string[]; refused?: string[]; recommended?: string[]; test?: { status: string; sent_at: string | null; delivered_at: string | null } }
export interface WaSetup { steps: WaStep[]; done: number; total: number; complete: boolean; next: WaStep["key"] | null; sending: boolean; recommended: { helpers: string[]; why: string };
  last_test: { status: string; sent_at: string | null; delivered_at: string | null } | null }

export const STEP_STATE: Record<StepState, { label: string; tone: "green" | "amber" | "gray" | "blue" }> = {
  done: { label: "Done", tone: "green" }, todo: { label: "Your turn", tone: "blue" }, waiting: { label: "Waiting", tone: "amber" }, blocked: { label: "Not yet", tone: "gray" },
};

export const HELPER_TITLES: Record<string, string> = { review_followup: "Get more customer reviews", enquiry_followup: "Follow up with enquiries", offers: "Send offers to customers" };

/** "3 of 6 steps done", or a finished message. */
export function setupProgress(s: Pick<WaSetup, "done" | "total" | "complete">): string {
  return s.complete ? "You are all set up." : `${s.done} of ${s.total} steps done`;
}

/** A width for the progress bar, 0 to 100. */
export function setupPercent(s: Pick<WaSetup, "done" | "total">): number {
  return s.total <= 0 ? 0 : Math.round((s.done * 100) / s.total);
}

/** Whether a typed number looks like a mobile number worth sending to the server (the server decides for real). */
export function looksLikeMobile(v: string): boolean {
  const d = v.replace(/\D/g, "");
  return d.length === 10 || (d.length === 12 && d.startsWith("91")) || (d.length >= 11 && d.length <= 15 && v.trim().startsWith("+"));
}

/** The step the owner should work on now, or null when everything is done. */
export function currentStep(s: Pick<WaSetup, "steps">): WaStep | null {
  return s.steps.find((x) => x.state !== "done") ?? null;
}

/** A step is open (its controls are shown) when it is the one to work on, or when the owner opened it. Done and not-yet steps stay closed. */
export function stepOpen(step: WaStep, current: WaStep | null, openKey: string | null): boolean {
  if (openKey === step.key) return true;
  return current?.key === step.key && step.state !== "blocked";
}

/** Meta's per-message prices as an administrator sees them: dated rows that are never overwritten, each with its latest check. */
export type RateCategory = "marketing" | "utility" | "authentication" | "service";
export const RATE_CATEGORIES: { value: RateCategory; label: string }[] = [
  { value: "marketing", label: "Marketing (offers)" }, { value: "utility", label: "Utility (visit and enquiry updates)" },
  { value: "authentication", label: "Authentication (one-time codes)" }, { value: "service", label: "Service (replies inside 24 hours)" },
];
export interface WaRateCheck { verified: boolean; note: string; at: string; by: string | null }
export interface WaRate { id: string; country: string; category: RateCategory; rate: string; currency: string; effective_from: string; source: string; verified: boolean; free_per_number_month: number; verification: WaRateCheck | null; in_force?: boolean }
export interface WaRates { items: WaRate[]; note: string; unverified_in_use: RateCategory[] }
export const categoryLabel = (c: string) => RATE_CATEGORIES.find((x) => x.value === c)?.label ?? c;
/** The one word shown for a price: Verified only when the latest check says it matches Meta's own rate card. */
export function rateStatus(r: Pick<WaRate, "verified">): { label: string; tone: "green" | "amber" } {
  return r.verified ? { label: "Verified", tone: "green" } : { label: "UNVERIFIED", tone: "amber" };
}
/** The free allowance in words, or nothing when there is none. */
export function freeAllowanceWords(n: number): string {
  return n > 0 ? `First ${n.toLocaleString("en-IN")} free per number each month` : "No free allowance";
}
/** A rate typed by an administrator: a plain number from 0 to 1000 with up to four decimals. */
export function rateProblem(raw: string): string | null {
  if (!/^\d{1,4}(\.\d{1,4})?$/.test(raw.trim())) return "Enter the price in rupees, like 1.09 or 0.145.";
  return Number(raw) > 1000 ? "That price is not realistic." : null;
}

// ---- birthday and festival greetings
export interface WaGreetingKind {
  key: string; submitted: boolean; status: string | null; category: string | null; category_known: boolean; needs_offers_consent: boolean; warning: string | null; body: string | null;
  audience: { agreed: number; would_receive: number; with_birthday: number; left_out: number }; helper: WaAutomationState;
  estimate: { category_used: "marketing" | "utility"; per_greeting: WaEstimate; for_everyone_who_would_get_it: WaEstimate };
}
export interface WaOccasions {
  allowed: boolean; hours: { start: number; end: number; timezone: string }; gap_days: number; birthday: WaGreetingKind; festival: WaGreetingKind;
  festivals: { id: string; name: string; date: string; region: string; enabled: boolean }[]; wording: string; note: string;
}
export interface WaFestival { id: string; name: string; date: string; region: string; active: boolean }
export const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const DAYS_IN = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]; // February has 29: a 29 February birthday is real
/** A birth day and month, never a year. Mirrors the server's check; the server decides. */
export function birthdayProblem(day: number, month: number): string | null {
  if (!Number.isInteger(day) || !Number.isInteger(month) || month < 1 || month > 12 || day < 1) return "Choose a day and a month.";
  return day > DAYS_IN[month - 1] ? "That day does not exist in that month." : null;
}
export function birthdayWords(day?: number | null, month?: number | null): string {
  return day && month ? `${day} ${MONTHS[month - 1]}` : "";
}
/** What the owner is told about the kind of message a greeting is, from what WhatsApp reported. */
export function greetingKindWords(g: Pick<WaGreetingKind, "submitted" | "category" | "category_known">): { label: string; tone: "green" | "amber" | "gray" } {
  if (!g.submitted) return { label: "Not sent to WhatsApp yet", tone: "gray" };
  if (!g.category_known) return { label: "Category not confirmed yet", tone: "amber" };
  return g.category === "marketing" ? { label: "Marketing message", tone: "amber" } : { label: "Update message", tone: "green" };
}

// ---- tracked review links (Pro): "link clicked", never "review left"
export interface WaLinkSummary { enabled: boolean; link_clicked: number; messages_with_a_click: number; by_day: { date: string; clicks: number }[]; note: string }
/** What a link click is called on every screen. A click means the link was opened; it never means a review was left, and it carries no rating. */
export const LINK_CLICKED = "Link clicked";
export function linkClickWords(at: string | null | undefined): string {
  return at ? LINK_CLICKED : "";
}

// ---- engagement and win-back audiences (Pro). They only choose WHO an ordinary offer is for.
const ENGAGED_SENTENCE: Record<WaEngaged, string> = { read: "who read a message", replied: "who wrote to you", clicked: "who opened a tracked link", delivered_not_read: "who had a message delivered but not read" };
export const ENGAGED_CHOICES: { value: WaEngaged; label: string; note: string }[] = [
  { value: "read", label: "Read a message", note: "Only counts customers who have read receipts turned on." },
  { value: "replied", label: "Wrote to you", note: "A STOP is never counted as writing to you. Only the time is kept, never what they said." },
  { value: "clicked", label: "Opened a tracked link", note: "Only has data from the time link click counting was switched on (Pro). Before that, nobody can show up here." },
  { value: "delivered_not_read", label: "Delivered but not read (may include people with read receipts turned off)", note: "This does not show whether they saw the message." },
];
export const WINBACK_NOTE = "Not visited counts only visits you marked on the Customers page. If you have not marked any, this uses messages only: customers you have not messaged for that long. Any message counts, including greetings.";
/** The one-line limit shown beside an engagement choice. */
export function engagedNote(v: WaEngaged | ""): string {
  return ENGAGED_CHOICES.find((c) => c.value === v)?.note ?? "";
}
/** How many customers a preview left out, in a sentence for the owner. */
export function leftOutWords(x: { no_consent: number; opted_out: number } | undefined): string {
  if (!x || (x.no_consent === 0 && x.opted_out === 0)) return "";
  const bits: string[] = [];
  if (x.opted_out) bits.push(`${x.opted_out} asked to stop offers`);
  if (x.no_consent) bits.push(`${x.no_consent} never agreed to receive offers`);
  return `Left out: ${bits.join(" and ")}.`;
}

// ---- conversations and the inbox
export type ConvStatus = "open" | "needs_human" | "closed";
export interface WaConvSummary {
  id: string; contact: { id: string; name: string | null; phone: string; source: string; opted_out: boolean; no_consent: boolean } | null; status: ConvStatus; handoff_reason: string | null; handoff_words: string | null;
  unread: number; needs_reply: boolean; preview: string | null; preview_from: string | null; last_message_at: string | null; window_open: boolean; window_closes_at: string | null;
  ai_paused_until: string | null; assigned_to: string | null; source: string; ai_off?: boolean;
}
export interface WaConvMessage {
  id: string; direction: "inbound" | "outbound"; sender_type: "customer" | "ai" | "staff" | "system"; sender_label: string | null; text: string | null; msg_type: string; status: string; created_at: string;
  template_key: string | null; via_app: boolean; marketing_confirmed: boolean; error_code: string | null; feedback?: "up" | "down" | null; model_version?: string | null;
}
export interface WaConvThread extends WaConvSummary {
  messages: WaConvMessage[]; assigned_name: string | null; code: string; window_note: string | null;
  fallback_templates: { key: string; label: string; can_send: boolean; reason: string | null; text: string | null }[];
}
export interface WaConvList { total: number; unread_total: number; needs_you: number; items: WaConvSummary[] }
export interface WaConvSettings {
  settings: { enabled: boolean; retention_days: number; takeover_minutes: number; debounce_seconds: number; notify_email: boolean; limits: Record<string, [number, number]> };
  platform_on: boolean; addon_ok: boolean; active: boolean;
}
export const CONV_FILTERS: { value: "all" | "needs_you" | "unread" | "closed"; label: string }[] = [
  { value: "all", label: "All" }, { value: "needs_you", label: "Needs you" }, { value: "unread", label: "Unread" }, { value: "closed", label: "Closed" },
];
/** Who a message is from, in the words shown above it. A customer's own name, the assistant clearly marked as automated, or the named team member. */
export function senderTag(m: Pick<WaConvMessage, "sender_type" | "sender_label" | "via_app">): string {
  if (m.sender_type === "ai") return "Assistant (automated)";
  if (m.sender_type === "system") return "Automatic message";
  if (m.sender_type === "staff") return m.via_app ? "You, on the WhatsApp Business app" : m.sender_label ?? "A team member";
  return m.sender_label ?? "A customer";
}
/** What the customer's 24-hour window means for the owner right now. */
export function windowWords(open: boolean, closesAt: string | null, now: number = Date.now()): string {
  if (!closesAt) return "This customer has not written to you, so only an approved message can be sent.";
  if (!open) return "The 24-hour window has closed. WhatsApp only allows an approved message now.";
  const mins = Math.max(0, Math.round((new Date(closesAt).getTime() - now) / 60000));
  return mins >= 120 ? `You can reply freely for about ${Math.round(mins / 60)} more hours.` : mins >= 60 ? "You can reply freely for about an hour more." : `You can reply freely for ${mins} more minute${mins === 1 ? "" : "s"}.`;
}
export const RETENTION_NOTE = (days: number) => `Messages are kept for ${days} days, then deleted. They are also deleted when you delete the customer.`;

// ---- the assistant (auto-reply)
export type KnowledgeKind = "about" | "address" | "hours" | "service" | "faq" | "policy" | "booking_rule";
export interface WaKnowledgeItem { id: string; kind: KnowledgeKind; title: string | null; body: string; price_inr: number | null; active: boolean; position: number; updated_at: string }
export interface WaKnowledge {
  items: WaKnowledgeItem[]; readiness: { ready: boolean; missing: string[]; count: number }; max_items: number;
  suggestions: { business_type: string; questions: string[]; sections: { kind: KnowledgeKind; label: string; single: boolean }[]; warning: string; examples: Record<string, string> };
}
export interface WaAiStatus {
  available: boolean; reason: string | null; reason_words: string | null; platform: { on: boolean; reason: string | null; words: string | null; terms_verified: boolean };
  settings: { enabled: boolean; privacy_ack_at: string | null; tone: string | null }; readiness: { ready: boolean; missing: string[]; count: number };
  quota: { limit: number; used: number; remaining: number; month: string; near_limit: boolean; tier: string | null }; privacy_notice: string; unanswered: number;
}
export interface WaAiTestReply { reply: string; kind: "reply" | "refuse" | "handoff" | "holding"; reason: string | null; reason_words: string | null; sources: string[]; sent_to_whatsapp: false; model_version: string | null }
export interface WaUnanswered { question: string; count: number; last_asked_at: string | null; ids: string[] }
export const KNOWLEDGE_ORDER: KnowledgeKind[] = ["about", "address", "hours", "service", "faq", "policy", "booking_rule"];
/** How full the month's allowance is, in words an owner can act on. */
export function quotaWords(q: Pick<WaAiStatus["quota"], "limit" | "used" | "remaining">): string {
  if (q.limit <= 0) return "Your plan does not include assistant replies.";
  if (q.remaining <= 0) return "This month's replies are used up. Customers go to your team until next month.";
  if (q.used >= q.limit * 0.8) return `${q.remaining} of ${q.limit} replies left this month. Customers go to your team when they run out.`;
  return `${q.used} of ${q.limit} replies used this month.`;
}
export interface WaAiQuotas {
  items: { id: string; addon_key: string; monthly_replies: number; effective_from: string; note: string }[];
  platform: { on: boolean; reason: string | null; terms_verified: boolean; terms_provider: string | null; provider: string };
  this_month: { provider: string | null; model_version: string | null; runs: number; prompt_tokens: number; completion_tokens: number; avg_latency_ms: number }[]; note: string;
}
export const tierLabel = (k: string) => ({ whatsapp_starter: "Starter", whatsapp_growth: "Growth", whatsapp_pro: "Pro" } as Record<string, string>)[k] ?? k;

// ---- appointment booking
export type BookingStatus = "booked" | "done" | "no_show" | "cancelled";
export interface WaBooking {
  id: string; code: string; status: BookingStatus; source: "ai" | "staff" | "api"; service: string; service_id: string | null; duration_minutes: number; price_inr: number | null; starts_at: string; ends_at: string; when: string; note: string | null;
  contact_id: string; customer: { name: string | null; phone: string } | null; reminder_day: string | null; reminder_soon: string | null; done_at: string | null; cancel_reason: string | null; review?: { scheduled: boolean; reason: string } | null;
}
export interface WaBookingService { id: string; name: string; duration_minutes: number; buffer_minutes: number; price_inr: number | null; active: boolean }
export interface WaReminderTemplate { key: string; submitted: boolean; status: string | null; category: string | null; category_known: boolean; needs_offers_consent: boolean; body: string }
export interface WaBookingOverview {
  platform_on: boolean; plan_ok: boolean; active: boolean; timezone: string; setup_needed: string[]; reminder_note: string;
  settings: { enabled: boolean; capacity: number; slot_step_minutes: number; min_notice_minutes: number; max_days_ahead: number; reminders_enabled: boolean; reminder_day_hour: number; reminder_soon_hours: number; limits: Record<string, [number, number]> };
  services: WaBookingService[]; hours: { weekday: number; day: string; opens: string; closes: string }[]; closed: { id: string; day: string; reason: string | null }[]; reminder_templates: Record<string, WaReminderTemplate>;
}
export const WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
export const BOOKING_STATUS_WORDS: Record<BookingStatus, { label: string; tone: "green" | "gray" | "amber" | "red" | "blue" }> = {
  booked: { label: "Booked", tone: "blue" }, done: { label: "Visit done", tone: "green" }, no_show: { label: "Did not come", tone: "amber" }, cancelled: { label: "Cancelled", tone: "gray" },
};
const REMINDER_WORDS: Record<string, string> = {
  sent: "Reminder sent", no_utility_consent: "No reminder: the customer has not agreed to updates about their visit", opted_out: "No reminder: the customer replied STOP",
  no_marketing_consent: "No reminder: WhatsApp has not confirmed this is an update message, so the customer's agreement to offers is also needed", outside_hours: "No reminder: it would have gone out at night",
  template_not_approved: "Waiting: the reminder message is not approved yet", plan_required: "No reminder: not part of this plan", no_customer: "No reminder: customer not found",
};
/** What happened (or will not happen) with a booking's reminders, in plain words. */
export function reminderWords(result: string | null): string | null { return result ? REMINDER_WORDS[result] ?? `No reminder (${result.replace(/_/g, " ")})` : null; }
/** Where the reminder messages stand, so an owner is never surprised. */
export function reminderStateWords(t: WaReminderTemplate | undefined): string {
  if (!t || !t.submitted) return "Not submitted to WhatsApp yet.";
  if (t.status !== "approved") return t.status === "pending" ? "Waiting for WhatsApp to approve it." : `WhatsApp status: ${t.status}.`;
  if (!t.category_known) return "Approved. WhatsApp has not told us its category yet, so customers also need to have agreed to offers until it does.";
  return t.category === "utility" ? "Approved as an update message. Customers who agreed to visit updates get it." : "WhatsApp counts this as marketing, so customers also need to have agreed to offers.";
}
/** "Mon to Sat 9:00 to 18:00" style summary of the weekly hours. */
export function hoursSummary(rows: { weekday: number; opens: string; closes: string }[]): string {
  if (!rows.length) return "No opening hours set.";
  const same = rows.every((r) => r.opens === rows[0].opens && r.closes === rows[0].closes);
  const days = rows.map((r) => WEEKDAY_NAMES[r.weekday].slice(0, 3));
  return same ? `${days.join(", ")}: ${rows[0].opens} to ${rows[0].closes}` : rows.map((r) => `${WEEKDAY_NAMES[r.weekday].slice(0, 3)} ${r.opens} to ${r.closes}`).join("; ");
}
export const bookingDay = (iso: string) => new Date(iso).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: "Asia/Kolkata" });
export const bookingTime = (iso: string) => new Date(iso).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", hour12: true, timeZone: "Asia/Kolkata" });

// ---- integrations
export interface WaApiKey { id: string; name: string; prefix: string; scopes: string[]; rate_limit_per_min: number; created_at: string; last_used_at: string | null; expires_at: string | null; revoked_at: string | null; active: boolean; key?: string; note?: string }
export interface WaWebhookEndpoint { id: string; url: string; events: string[]; active: boolean; disabled_reason: string | null; secret_hint: string; failure_streak: number; last_success_at: string | null; last_failure_at: string | null; created_at: string; secret?: string; note?: string }
export interface WaDelivery { id: string; endpoint_id: string; event_id: string; event_type: string; status: "pending" | "delivered" | "dead"; attempts: number; next_attempt_at: string | null; last_status_code: number | null; last_error: string | null; created_at: string; delivered_at: string | null }
export interface WaIntegrations { platform_on: boolean; plan_ok: boolean; keys: WaApiKey[]; endpoints: WaWebhookEndpoint[]; scopes: Record<string, string>; events: Record<string, string>; api_version: string; base_path: string; limits: { keys: number; endpoints: number } }
/** One plain sentence for a delivery: what happened and what happens next. */
export function deliveryWords(d: Pick<WaDelivery, "status" | "attempts" | "last_status_code" | "last_error">): string {
  if (d.status === "delivered") return d.attempts > 1 ? `Delivered on attempt ${d.attempts}.` : "Delivered.";
  if (d.status === "dead") return `Gave up after ${d.attempts} attempts${d.last_error ? `: ${d.last_error}` : ""}.`;
  return d.attempts === 0 ? "Waiting to be sent." : `Will try again (attempt ${d.attempts} failed${d.last_error ? `: ${d.last_error}` : ""}).`;
}
/** A webhook address must be https; this is only a quick check before asking the server, which does the real one. */
export function webhookUrlProblem(url: string): string | null {
  const u = url.trim();
  if (!u) return "Enter the address that should receive events.";
  if (!/^https:\/\//i.test(u)) return "The address must start with https://";
  if (u.length > 500) return "That address is too long.";
  return null;
}
export const keyStatusWords = (k: Pick<WaApiKey, "active" | "revoked_at" | "expires_at">): string => (k.revoked_at ? "Revoked" : !k.active ? "Expired" : "Active");
