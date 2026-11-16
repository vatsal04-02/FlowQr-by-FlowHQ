// Shapes returned by GET /agent/control-centre and the action endpoints (backend/app/api/v1/autonomy_actions.py). The level of an action is decided by the
// server from its type and values; nothing here can set one.

export type ActionStatus = "pending_approval" | "approved" | "executing" | "executed" | "failed" | "rejected" | "expired" | "invalidated" | "blocked" | "canceled";
export type Mode = "auto" | "ask" | "off";

export interface HistoryEvent { seq: number; type: string; actor: string; at: string; data?: Record<string, unknown> }
export interface ActionRow {
  id: string; google_location_id: string; action_type: string; effective_type: string; label: string; field: string; status: ActionStatus;
  policy_level: 1 | 2 | 3; policy: string; risk: "low" | "medium" | "high"; authorization: "policy" | "preauthorized" | "owner";
  trigger: string; problem: string; reason: string; expected_outcome: string; before: unknown; after: unknown; source: { kind?: string; refs?: string[] };
  evidence: Record<string, unknown>; policy_reasons: string[]; proposed_by: "agent" | "user"; expires_at: string | null; attempts: number; last_error: string | null;
  executed_at: string | null; verified_at: string | null; verification: { matched?: boolean; detail?: string; actual?: unknown } | null; created_at: string;
  subject_type?: string | null;
}
export interface ActionDetail extends ActionRow {
  approvals: { decision: string; basis: string; by: string | null; at: string; expires_at: string | null; reason: string | null; invalidated_at: string | null; invalidated_reason: string | null }[];
  history: HistoryEvent[]; history_integrity: { ok: boolean; events: number; reason: string | null }; baseline: Record<string, unknown> | null; outcome: { label?: string; note?: string } | null;
}
export interface PermissionRow { type: string; label: string; level: 1 | 2 | 3; mode: Mode; can_be_auto: boolean }
export interface AutonomySettings {
  enabled: boolean; suspended: boolean; suspended_at: string | null; suspended_reason: string | null; failure_streak: number; daily_limit: number; permissions_set_at: string | null;
  permissions: PermissionRow[]; executing_now: boolean; platform_emergency_stop: boolean; platform_emergency_stop_reason: string | null; note: string;
}
export interface Usage {
  month_resets_on: string;
  ai: { generations_used: number; generations_cap: number; review_generations_used: number; review_generations_cap: number; review_replies_used: number; review_replies_cap: number; usd_spent: number | null; usd_budget: number | null; tokens_used: number; tokens_budget: number | null; priced: boolean; calls: number; note: string | null; blocked: boolean };
  places: { search_checks_used: number; search_checks_cap: number; grid_points_used: number; grid_points_cap: number; grid_points_left: number; grid_enabled: boolean; grid_reason: "not_in_plan" | "not_configured" | null; business_cap: number | null; units_this_month: number; platform_capped: boolean; estimated_usd: number | null; priced: boolean };
  autonomy: { daily_limit: number; executed_last_24h: number };
}
export interface ControlCentre {
  settings: AutonomySettings; waiting: ActionRow[]; running: ActionRow[]; recent: ActionRow[]; problems: ActionRow[]; usage: Usage; can_decide: boolean; is_owner: boolean;
}

const DAY: Record<string, string> = { MONDAY: "Mon", TUESDAY: "Tue", WEDNESDAY: "Wed", THURSDAY: "Thu", FRIDAY: "Fri", SATURDAY: "Sat", SUNDAY: "Sun" };

/** A value as a person would read it: hours as "Mon 09:00-18:00", lists as lines, nothing as "nothing". */
export function showValue(v: unknown): string {
  if (v === null || v === undefined || v === "" || (Array.isArray(v) && v.length === 0)) return "Nothing";
  if (typeof v === "string") return v;
  if (Array.isArray(v)) {
    if (v.every((h) => Array.isArray(h) && h.length === 3)) return (v as string[][]).map(([d, o, c]) => `${DAY[d] ?? d} ${o}-${c}`).join("\n");
    return v.map((x) => (typeof x === "string" ? x.replace(/^categories\/gcid:/, "") : JSON.stringify(x))).join("\n");
  }
  if (typeof v === "object") {
    const o = v as Record<string, unknown>;
    if (typeof o.summary === "string") return o.summary;
    if (typeof o.body === "string") return o.body;
    return Object.entries(o).filter(([, x]) => x !== null && x !== "").map(([k, x]) => `${k.replace(/_/g, " ")}: ${String(x)}`).join("\n");
  }
  return String(v);
}

export const STATUS_WORDS: Record<ActionStatus, { label: string; tone: "ok" | "warn" | "bad" | "info" | "idle" }> = {
  pending_approval: { label: "Waiting for you", tone: "warn" }, approved: { label: "Approved, about to run", tone: "info" }, executing: { label: "Sending to Google", tone: "info" },
  executed: { label: "Confirmed on Google", tone: "ok" }, failed: { label: "Failed", tone: "bad" }, rejected: { label: "Rejected", tone: "idle" }, expired: { label: "Expired", tone: "idle" },
  invalidated: { label: "Stopped: things changed", tone: "warn" }, blocked: { label: "Blocked: not enough evidence", tone: "warn" }, canceled: { label: "Cancelled", tone: "idle" },
};

export const EVENT_WORDS: Record<string, string> = {
  proposed: "Proposed", policy_classified: "Classified by policy", approved: "Approved", auto_authorized: "Authorised by your autonomy settings", rejected: "Rejected", baseline_measured: "Ranking measured before the change",
  executing: "Started sending to Google", google_write: "Google accepted the request", read_back: "Read the profile back from Google", verified: "Confirmed: Google shows the change", failed: "Failed",
  retry_scheduled: "Temporary problem, will retry", google_value_changed: "Stopped: the value on Google changed", facts_changed: "Stopped: your business facts changed", expired: "Expired",
  invalidated: "Stopped", autonomy_withdrawn: "Autonomy was switched off before it ran", autonomy_suspended: "Autonomy suspended after repeated failures", held: "Held", blocked: "Blocked",
  followups_scheduled: "Ranking follow-ups scheduled", followup_measured: "Ranking re-measured", evaluated: "Outcome evaluated", canceled: "Cancelled", recovered_requeued: "Recovered after an interruption",
};
