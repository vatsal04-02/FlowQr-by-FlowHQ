/**
 * The short words and the small calculations behind the WhatsApp screens' visual pieces (rings, rails, bars, indicators). Pure functions, so they can be tested without a browser.
 * The screens show a state with a picture and about four words; the long explanations in lib/whatsapp.ts stay available for screen readers and for the "more" parts.
 */
import type { WaConnection, WaStep, WaStatus, WaUsage } from "./whatsapp";

export const STEP_ORDER = ["plan", "connect", "messages", "customers", "test", "helper"] as const;
export type StepKey = (typeof STEP_ORDER)[number];

/** One word for each step, shown under its icon. */
export const STEP_LABEL: Record<StepKey, string> = { plan: "Plan", connect: "Number", messages: "Approve", customers: "People", test: "Test", helper: "Helper" };

/** What to do at this step, as a short instruction. */
export const STEP_ACTION: Record<StepKey, string> = { plan: "Get WhatsApp switched on", connect: "Connect your number", messages: "Get your messages approved", customers: "Add a customer", test: "Send yourself a test", helper: "Switch on a helper" };

/** Four words or fewer: where this step stands. */
export function stepLine(s: Pick<WaStep, "key" | "state"> & { refused?: string[] }): string {
  const t: Record<StepKey, Partial<Record<WaStep["state"], string>>> = {
    plan: { done: "Switched on", todo: "FlowQR switches it on", blocked: "Not yet" },
    connect: { done: "Connected", todo: "Connect your number", waiting: "Not available yet", blocked: "Needs the plan first" },
    messages: { done: "Approved", todo: "Send for approval", waiting: "WhatsApp is reviewing", blocked: "Needs a number first" },
    customers: { done: "Customers added", todo: "Add your first customer", blocked: "Needs a number first" },
    test: { done: "Test arrived", todo: "Send yourself a test", waiting: "Waiting to send", blocked: "Needs approved messages" },
    helper: { done: "A helper is on", todo: "Switch one on", blocked: "Needs a number first" },
  };
  if (s.key === "messages" && s.state === "todo" && s.refused?.length) return "Fix a message";
  return t[s.key as StepKey]?.[s.state] ?? "";
}

/** The step to show first: the first one that is not finished, else null. */
export function firstOpen(steps: Pick<WaStep, "state">[]): number {
  const i = steps.findIndex((s) => s.state !== "done");
  return i < 0 ? -1 : i;
}

/** 0 to 100, whole numbers, safe for a zero total. */
export function pct(n: number, total: number): number {
  if (!(total > 0) || !(n > 0)) return 0;
  return Math.min(100, Math.round((n * 100) / total));
}

/** Geometry for a circular progress ring: the stroke length of the whole circle and how much of it to hide. */
export function ringGeometry(done: number, total: number, radius: number): { circumference: number; offset: number } {
  const circumference = 2 * Math.PI * radius;
  const share = total > 0 ? Math.min(1, Math.max(0, done / total)) : 0;
  return { circumference, offset: circumference * (1 - share) };
}

export type Health = "ok" | "warn" | "bad" | "off";
export interface HealthItem { key: "number" | "updates" | "quality"; label: string; value: string; state: Health }

export function qualityWords(r: string | null | undefined): { value: string; state: Health } {
  if (r === "GREEN") return { value: "Good", state: "ok" };
  if (r === "YELLOW") return { value: "Medium", state: "warn" };
  if (r === "RED") return { value: "Low", state: "bad" };
  return { value: "Not shown yet", state: "off" };
}

/** Three indicators for a connection: the number, delivery updates, and the number's quality. Colour is never the only signal: each has a word. */
export function connectionHealth(c: WaConnection | null): HealthItem[] {
  const live = !!c && c.status !== "disconnected" && c.status !== "pending";
  const number: HealthItem = !c || c.status === "disconnected" ? { key: "number", label: "Number", value: "Not connected", state: "off" }
    : c.status === "pending" ? { key: "number", label: "Number", value: "Connecting", state: "warn" }
    : c.status === "needs_attention" ? { key: "number", label: "Number", value: "Needs attention", state: "bad" }
    : c.token_state === "expiring" ? { key: "number", label: "Number", value: "Renew soon", state: "warn" }
    : c.token_state === "expired" ? { key: "number", label: "Number", value: "Expired", state: "bad" }
    : { key: "number", label: "Number", value: "Connected", state: "ok" };
  const updates: HealthItem = !live ? { key: "updates", label: "Updates", value: "Off", state: "off" }
    : c?.webhook_status === "subscribed" ? { key: "updates", label: "Updates", value: "On", state: "ok" }
    : c?.webhook_status === "failed" ? { key: "updates", label: "Updates", value: "Not working", state: "bad" }
    : { key: "updates", label: "Updates", value: "Not yet", state: "warn" };
  const q = live ? qualityWords(c?.quality_rating) : { value: "Not shown yet", state: "off" as Health };
  return [number, updates, { key: "quality", label: "Quality", value: q.value, state: q.state }];
}

export interface ConsentRow { key: "offers" | "updates" | "greetings" | "stopped"; label: string; value: number; share: number; tone: "brand" | "pos" | "accent" | "neg" }

/** Who agreed to what, as shares of all customers. A customer can agree to several things, so these are separate bars, not slices of one. */
export function consentRows(c: WaStatus["counts"]): ConsentRow[] {
  const total = c.contacts;
  return [
    { key: "offers", label: "Offers", value: c.marketing, share: pct(c.marketing, total), tone: "brand" },
    { key: "updates", label: "Visit updates", value: c.utility, share: pct(c.utility, total), tone: "pos" },
    { key: "greetings", label: "Greetings", value: c.occasion ?? 0, share: pct(c.occasion ?? 0, total), tone: "accent" },
    { key: "stopped", label: "Stopped", value: c.opted_out, share: pct(c.opted_out, total), tone: "neg" },
  ];
}

export interface FunnelStep { key: "sent" | "delivered" | "read"; label: string; value: number; share: number }

/** Sent, delivered and read as bars against the biggest of them (delivered is never the same as read). */
export function funnel(t: WaUsage["totals"]): FunnelStep[] {
  const top = Math.max(t.sent, t.delivered, t.read, 0);
  return [
    { key: "sent", label: "Sent", value: t.sent, share: pct(t.sent, top) },
    { key: "delivered", label: "Delivered", value: t.delivered, share: pct(t.delivered, top) },
    { key: "read", label: "Read", value: t.read, share: pct(t.read, top) },
  ];
}

/** "AV" for Asha Verma, "A" for Asha, and the last two digits for a number with no name. */
export function initials(name: string | null | undefined, phone?: string): string {
  const parts = (name ?? "").trim().split(/\s+/).filter((p) => /^[\p{L}\p{N}]/u.test(p));
  if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  if (parts.length === 1) return parts[0][0].toUpperCase();
  const d = (phone ?? "").replace(/\D/g, "");
  return d ? d.slice(-2) : "?";
}

/** "…2345": the last four digits, which is all a list needs to tell people apart. */
export function lastFour(phone: string | null | undefined): string {
  const d = (phone ?? "").replace(/\D/g, "");
  return d ? `…${d.slice(-4)}` : "";
}
