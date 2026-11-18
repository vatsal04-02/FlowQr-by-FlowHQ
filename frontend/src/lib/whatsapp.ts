/** WhatsApp automation (Phase 1): types for the API, the plain-language words the owner sees, and the Embedded Signup launcher. No access token ever reaches this code: the server keeps it. */

export type ConnStatus = "pending" | "connected" | "needs_attention" | "disconnected";
export interface WaConnection {
  id: string; status: ConnStatus; display_phone_number: string | null; verified_name: string | null; quality_rating: string | null; is_test_number: boolean;
  webhook_status: "unknown" | "subscribed" | "failed"; attention_reason: string | null; connected_at: string | null; token_state: "ok" | "expiring" | "expired" | "missing" | "no_expiry";
}
export interface WaTier { key: string; label: string; price_inr_month: number; automation_limit: number; summary: string; campaigns: boolean; segmentation: string }
export interface WaStatus {
  enabled: boolean; signup_available: boolean; addon_required: boolean; addon: (WaTier & { since: string }) | null; tiers: WaTier[]; connection: WaConnection | null;
  counts: { contacts: number; marketing: number; utility: number; opted_out: number }; messaging: { enabled: boolean; emergency_stop: boolean }; can_connect: boolean;
}
export interface WaConsentInfo { since: string; source: string; wording_version: string }
export interface WaContact {
  id: string; phone: string; customer_name: string | null; tags: string[]; source: string; created_at: string; marketing: WaConsentInfo | null; utility: WaConsentInfo | null; opted_out: boolean; opted_out_at: string | null;
}
export interface WaContacts { total: number; items: WaContact[]; counts: WaStatus["counts"]; wording: { marketing: string; utility: string } }
export interface WaAutomation { key: string; title: string; description: string; purpose: "marketing" | "utility"; needs: string[]; available: boolean; coming_soon: boolean; ready: { connection: boolean; addon: boolean; customers: boolean } }
export interface WaAutomations { items: WaAutomation[]; limit: number | null }
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
export function consentWords(c: Pick<WaContact, "marketing" | "utility" | "opted_out">): { label: string; tone: "green" | "blue" | "gray" | "red" } {
  if (c.opted_out) return { label: "Asked to stop offers", tone: "red" };
  if (c.marketing && c.utility) return { label: "Agreed to offers and visit updates", tone: "green" };
  if (c.marketing) return { label: "Agreed to offers", tone: "green" };
  if (c.utility) return { label: "Agreed to visit updates", tone: "blue" };
  return { label: "No agreement yet", tone: "gray" };
}

export const SOURCE_WORDS: Record<string, string> = {
  qr_page: "On your review page", website_form: "On your website", customer_message: "Messaged you", owner_entry: "Added by you", csv_import: "Imported by you", admin_entry: "Added by FlowQR",
};

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
