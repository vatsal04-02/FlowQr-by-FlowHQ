/** Shapes and pure helpers for the AI Business Operator screens (backend/app/api/v1/operator.py, services/operator/*). Nothing here decides policy: the server says which operations exist and
 * why one is unavailable; this file only turns that into what a person sees, and never offers an action the server did not offer. */
import type { V2Action, V2Area } from "./seo-v2";

export type Category = "profile" | "business_info" | "reviews" | "posts" | "other";
export interface Op { available: boolean; method: "POST" | "PATCH" | "DELETE" | null; path: string | null; body: Record<string, unknown>; then: Op | null; reason: string | null }
export interface PendingItem {
  key: string; kind: "action" | "reply" | "post" | "profile_task"; id: string; category: Category; title: string; field: string | null; status: string; status_label: string; risk: string; level: number;
  google_location_id: string | null; location_title: string | null; before: string; before_label?: string; after: string; diff: { before: string[]; after: string[]; added: string[]; removed: string[] } | null;
  problem: string | null; reason: string | null; expected_outcome: string | null; source: string | null; quality_score: number | null; model: string | null; last_error: string | null;
  created_at: string | null; verified_at: string | null; blocked_note?: string | null; flags?: string[]; violations?: { message?: string; detail?: string }[]; needs_acknowledgement?: boolean;
  operations: Record<"approve" | "reject" | "edit" | "regenerate", Op>;
}
export interface PendingResponse { items: PendingItem[]; counts: Record<Category, number>; total: number; categories: { key: Category; label: string }[] }
export type PrepareStatus = "prepared" | "already_prepared" | "needs_owner_input" | "nothing_to_change" | "cannot_prepare";
export interface PrepareResponse { status: PrepareStatus; action_id: string | null; message: string; reasons: string[]; change: PendingItem | null }
export interface AskStep { tool: string; args: Record<string, unknown> | null; ok: boolean; summary: string; prepares: boolean }
export interface AskResponse { status: "completed" | "stopped" | "unavailable"; answer: string | null; reason: string | null; reason_text: string | null; steps: AskStep[]; changes: PendingItem[] }

export const AREA_FOR_FIELD: Record<string, string> = { description: "description", categories: "categories", services: "services", hours: "hours", special_hours: "special_hours", attributes: "attributes", service_area: "service_area", website: "contacts", phone: "contacts" };
/** Where the owner can still make a change by hand when FlowQr has nothing to prepare for it. Shown as a plain alternative, never as the main action. */
export const MANUAL_EDITOR: Record<string, { href: string; label: string }> = {
  description: { href: "/gbp/info", label: "Edit the description yourself" }, contacts: { href: "/gbp/info", label: "Edit phone and website yourself" }, hours: { href: "/gbp/hours", label: "Edit opening hours yourself" },
  categories: { href: "/gbp/info", label: "Edit categories yourself" }, services: { href: "/gbp/info", label: "Open the profile editor" },
};

export const operationLabel = { approve: "Approve & apply", reject: "Reject", edit: "Edit", regenerate: "Regenerate" } as const;

/** What the owner is told after approving, from the server's own answer. "Applied" is claimed only when Google's profile was read back and matched. */
export function approvalOutcome(item: PendingItem, result: unknown): { tone: "success" | "warning" | "error"; text: string } {
  const r = (result ?? {}) as { status?: string; verified_at?: string | null; execution?: { status?: string; reason?: string; detail?: string }; last_error?: string | null; published_at?: string | null };
  if (item.kind === "action") {
    if (r.status === "executed" && r.verified_at) return { tone: "success", text: `${item.title} updated on Google and confirmed by reading the profile back.` };
    if (r.status === "failed" || r.status === "blocked") return { tone: "error", text: r.last_error || r.execution?.detail || "Google did not accept this change. Nothing was changed on your profile." };
    if (r.status === "approved" || r.status === "executing") return { tone: "warning", text: "Approved. It is being applied now. This page shows it as done only after Google confirms." };
    return { tone: "warning", text: `Status: ${(r.status ?? "unknown").replaceAll("_", " ")}.` };
  }
  if (item.kind === "reply") return r.status === "published" || r.published_at ? { tone: "success", text: "Reply published on Google." } : { tone: "warning", text: `Reply status: ${String(r.status ?? "pending").replaceAll("_", " ")}.` };
  if (item.kind === "post") return { tone: "success", text: "Approved. The post's own status shows whether Google has published it." };
  return { tone: "success", text: "Approved." };
}

/** The next step an area's card offers. Every area that offers an action leads to a working change preview, or says in words why it cannot. */
export type AreaStep =
  | { kind: "open"; href: string; label: string }
  | { kind: "prepare"; area: string; label: string }
  | { kind: "inputs"; label: string }
  | { kind: "info"; text: string; href?: string; linkLabel?: string };

const OPEN_ELSEWHERE: Record<string, { href: string; label: string }> = { photos: { href: "/gbp/photos", label: "Open photos" }, posts: { href: "/ai/studio", label: "Write a post" } };

export function areaStep(area: V2Area, actions: Pick<V2Action, "id" | "field" | "status">[]): AreaStep | null {
  if (area.state === "ok" || area.state === "unknown") return null;
  const found = actions.find((a) => AREA_FOR_FIELD[a.field ?? ""] === area.key && ["pending_approval", "recommended", "approved", "executing"].includes(a.status));
  if (found) return { kind: "open", href: `/ai/changes?focus=action:${found.id}`, label: found.status === "recommended" ? "See the drafted change" : "Review and approve" };
  const mode = area.fix?.mode;
  if (mode === "edit_in_google") return { kind: "info", text: "FlowQr does not change this for you. Edit it in Google Business Profile.", href: "https://business.google.com/", linkLabel: "Open Google Business Profile" };
  if (mode === "unavailable_via_api") return { kind: "info", text: "Google does not allow this part of the profile to be changed through FlowQr. Make it in Google Business Profile.", href: "https://business.google.com/", linkLabel: "Open Google Business Profile" };
  if (mode === "owner_input_needed") return { kind: "inputs", label: "Answer below" };
  if (OPEN_ELSEWHERE[area.key]) return { kind: "open", ...OPEN_ELSEWHERE[area.key] };
  if (["description", "categories", "services", "hours", "contacts"].includes(area.key)) return { kind: "prepare", area: area.key, label: "Prepare the change" };
  return null;
}

/** The first line of the page when a link brought the owner here to have something prepared. */
export function prepareHeadline(s: PrepareStatus): string {
  return { prepared: "The change is ready for your approval.", already_prepared: "This change is already prepared.", needs_owner_input: "FlowQr needs your answer first.", nothing_to_change: "Nothing to change right now.", cannot_prepare: "FlowQr could not prepare this." }[s];
}

export function countLabel(n: number, one: string, many: string): string { return `${n} ${n === 1 ? one : many}`; }

/** Where an optimizer check's action leads. A check the engine can prepare a change for opens that prepared change (it is drafted on arrival); a main category that is missing, hours, photos and the
 * rest keep their own editor, because only the owner can supply those. Never a same-page anchor that may not exist on the page the card is shown on. */
export function fixHref(key: string, state: string, href: string | null, gid: string): string | null {
  const prepare = (area: string) => `/ai/changes?prepare=${area}&location=${gid}`;
  if (key === "description" && (state === "missing" || state === "improve")) return prepare("description");
  if (key === "category" && state === "improve") return prepare("categories");
  if (key === "services" && state === "improve") return prepare("services");
  if (href && href.startsWith("#")) return null;  // an anchor on another page is a dead end
  return href;
}
