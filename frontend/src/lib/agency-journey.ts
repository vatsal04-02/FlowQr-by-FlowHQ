// The self-service agency onboarding journey (backend: services/google/agency_journey.py). Pure functions and types, so every rule about what the page may say or enable is tested without a browser.
// The page never decides what is true: it shows what the server derived from its records, and it refuses to enable an action the server did not offer.

export type JourneyState =
  | "NOT_STARTED" | "CUSTOMER_OAUTH_PENDING" | "CUSTOMER_CONSENT_PENDING" | "LOCATION_SELECTION_PENDING" | "MANAGER_INVITE_CREATING" | "MANAGER_INVITE_PENDING"
  | "AGENCY_ACCEPTANCE_PENDING" | "ACCESS_VERIFICATION_PENDING" | "CONNECTED" | "FAILED" | "REVOKED" | "EXPIRED" | "BLOCKED";

export const JOURNEY_STATES: readonly JourneyState[] = [
  "NOT_STARTED", "CUSTOMER_OAUTH_PENDING", "CUSTOMER_CONSENT_PENDING", "LOCATION_SELECTION_PENDING", "MANAGER_INVITE_CREATING", "MANAGER_INVITE_PENDING",
  "AGENCY_ACCEPTANCE_PENDING", "ACCESS_VERIFICATION_PENDING", "CONNECTED", "FAILED", "REVOKED", "EXPIRED", "BLOCKED",
];

export type StepStatus = "done" | "current" | "waiting" | "pending" | "blocked" | "failed";
export interface JourneyStep { key: string; label: string; status: StepStatus; message: string | null }
export interface MappingCheck { name: string; ok: boolean; detail: string }
export interface Blocked { code: string; who: string; message: string }
export interface TimelineEvent { at: string; event: string; code: string | null; action: string }
export interface ActionCategory { id: string; label: string; description: string; required: boolean }
export interface Authorization {
  id: string; status: string; target_type: string; consent_version: string; consented_at: string | null; consented_by_email: string | null; consent_actions: string[]; consent_actions_recorded: boolean;
  invite_sent_at: string | null; accepted_at: string | null; verified_at: string | null; last_verified_at: string | null; switched_at: string | null; notice_due_at: string | null; notice_sent_at: string | null;
  removal_requested_at: string | null; removal_deadline_at: string | null; removed_at: string | null; lost_at: string | null; notices_sent: Record<string, string>;
  failure_code?: string | null; last_error?: string | null; attempts?: number; next_attempt_at?: string | null; last_polled_at?: string | null; google_location_resource?: string | null;
}
export interface SyncInfo { mode: "owner_oauth" | "agency"; last_synced_at: string | null; last_status: string | null; last_error: string | null; consecutive_failures: number; initial_sync_queued_at: string | null }
export interface JourneyLocation {
  google_location_id: string; title: string | null; address: string | null; selected: boolean; flowqr_location_id: string | null; state: JourneyState; blocked: Blocked | null; reached: number;
  steps: JourneyStep[]; sync: SyncInfo; authorization: Authorization | null; mapping: MappingCheck[];
}
export interface AvailableLocation { google_location_id: string; title: string | null; address: string | null; selected: boolean; flowqr_location_id: string | null; taken: boolean }
export interface Journey {
  connection_id: string; state: JourneyState; headline: string; detail: string; steps: JourneyStep[]; blocked: Blocked | null; actions: string[]; operations_enabled: boolean;
  google: { email: string | null; connected_at: string | null; status: string; api_access: string; auth_mode: string; locations_found: number };
  locations: JourneyLocation[]; available_locations: AvailableLocation[]; timeline: TimelineEvent[];
  tenant_id?: string; tenant_name?: string | null; grant_open?: boolean;
}
export interface StartView { state: JourneyState; headline: string; detail: string; blocked: Blocked | null; actions: string[]; steps: JourneyStep[] }
export interface JourneyResponse {
  consent: { version: string; text: string; actions: ActionCategory[] }; can_act: boolean; notice_hours: number; removal_business_days: number; journeys: Journey[]; start?: StartView;
}

export type Tone = "ok" | "info" | "warn" | "bad" | "idle";
export const STATE_TONE: Record<JourneyState, Tone> = {
  NOT_STARTED: "idle", CUSTOMER_OAUTH_PENDING: "info", CUSTOMER_CONSENT_PENDING: "info", LOCATION_SELECTION_PENDING: "info", MANAGER_INVITE_CREATING: "info", MANAGER_INVITE_PENDING: "info",
  AGENCY_ACCEPTANCE_PENDING: "info", ACCESS_VERIFICATION_PENDING: "info", CONNECTED: "ok", FAILED: "bad", REVOKED: "idle", EXPIRED: "warn", BLOCKED: "warn",
};
/** An unknown state from a newer server is shown neutrally, never guessed. */
export const stateTone = (s: string): Tone => STATE_TONE[s as JourneyState] ?? "idle";

export const STATE_LABEL: Record<JourneyState, string> = {
  NOT_STARTED: "Not started", CUSTOMER_OAUTH_PENDING: "Google sign-in pending", CUSTOMER_CONSENT_PENDING: "Waiting for your approval", LOCATION_SELECTION_PENDING: "Choose a location",
  MANAGER_INVITE_CREATING: "Sending invitation", MANAGER_INVITE_PENDING: "Invitation pending", AGENCY_ACCEPTANCE_PENDING: "Being accepted", ACCESS_VERIFICATION_PENDING: "Verifying access",
  CONNECTED: "Connected", FAILED: "Failed", REVOKED: "Stopped", EXPIRED: "Expired", BLOCKED: "Blocked",
};
export const stateLabel = (s: string): string => STATE_LABEL[s as JourneyState] ?? s;

/** States in which FlowQR's own side is working and the page should keep looking. A person's action, a block or an end state is not polled. */
export const WORKING_STATES: readonly JourneyState[] = ["MANAGER_INVITE_CREATING", "MANAGER_INVITE_PENDING", "AGENCY_ACCEPTANCE_PENDING", "ACCESS_VERIFICATION_PENDING"];
export const isWorking = (s: string): boolean => (WORKING_STATES as readonly string[]).includes(s);
export const isEnded = (s: string): boolean => s === "REVOKED" || s === "FAILED" || s === "EXPIRED";

/** The next look, in ms: quick while something is being worked on (the first minutes), then slower, and none at all when nothing is waiting on FlowQR or Google. */
export function pollDelay(state: string, ageMs: number): number | null {
  if (!isWorking(state)) return null;
  return ageMs < 2 * 60_000 ? 4_000 : ageMs < 10 * 60_000 ? 15_000 : 60_000;
}

export const STEP_TONE: Record<StepStatus, Tone> = { done: "ok", current: "info", waiting: "info", pending: "idle", blocked: "warn", failed: "bad" };
export const stepTone = (s: string): Tone => STEP_TONE[s as StepStatus] ?? "idle";
const STEP_WORD: Record<StepStatus, string> = { done: "Done", current: "Your turn", waiting: "In progress", pending: "Not started", blocked: "On hold", failed: "Stopped" };
/** A step's status in words, so the stage never relies on colour alone. */
export const stepWord = (s: string): string => STEP_WORD[s as StepStatus] ?? s;

/** "3 of 8 steps done" and the label of the step that is not done yet, or null when all are. Only steps the server reports as `done` count. */
export function progressSummary(steps: JourneyStep[]): { done: number; total: number; next: JourneyStep | null } {
  const done = steps.filter((s) => s.status === "done").length;
  return { done, total: steps.length, next: steps.find((s) => s.status !== "done") ?? null };
}

// ---- consent: explicit, per category, nothing pre-approved beyond what reading needs
export function initialActions(catalog: ActionCategory[]): string[] { return catalog.filter((c) => c.required).map((c) => c.id); }
export function toggleAction(chosen: string[], id: string, catalog: ActionCategory[]): string[] {
  const cat = catalog.find((c) => c.id === id);
  if (!cat || cat.required) return chosen; // an unknown category is never added; a required one is never removed
  return chosen.includes(id) ? chosen.filter((x) => x !== id) : [...chosen, id];
}
/** What is sent: every ticked category plus the required ones, in the catalog's order. */
export function actionsToSend(chosen: string[], catalog: ActionCategory[]): string[] { return catalog.filter((c) => c.required || chosen.includes(c.id)).map((c) => c.id); }
/** The approve button is enabled only with the agreement ticked, a location, an admin, and the server offering `approve`. */
export function canApprove(o: { agreed: boolean; canAct: boolean; offered: string[]; locations: number }): boolean {
  return o.agreed && o.canAct && o.offered.includes("approve") && o.locations > 0;
}

export type JourneyAction = "connect" | "select_location" | "approve" | "check_again" | "restart" | "disconnect";
export const ACTION_LABEL: Record<JourneyAction, string> = {
  connect: "Connect Google", select_location: "Use this location", approve: "Approve and invite FlowQR", check_again: "Check again", restart: "Start again", disconnect: "Stop FlowQR managing my profile",
};
export const actionLabel = (a: string): string => ACTION_LABEL[a as JourneyAction] ?? a;
/** Buttons in a calm, fixed order, only those the server offered, and only to someone who may act. */
export function visibleActions(offered: string[], canAct: boolean): JourneyAction[] {
  if (!canAct) return [];
  const order: JourneyAction[] = ["connect", "check_again", "restart", "disconnect"];
  return order.filter((a) => offered.includes(a));
}

export const WHAT_HAPPENS_NEXT: Record<string, string> = {
  CONNECTED: "FlowQR is a Manager of your profile and its access was checked against Google. You can stop it at any time below.",
  BLOCKED: "Nothing is wrong with your account. A rule or a setting holds this back, and nothing was changed on your profile.",
};

/** An extra explanatory line for a state, or null when it would only repeat what the server's own detail already says (the page used to print the same sentence twice). */
export function extraNote(state: string, detail: string): string | null {
  const note = WHAT_HAPPENS_NEXT[state];
  if (!note) return null;
  const norm = (t: string) => t.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  return norm(detail).includes(norm(note)) || norm(note).includes(norm(detail)) ? null : note;
}

export const sinceLabel = (iso: string | null | undefined, fmt: (iso: string) => string): string | null => (iso ? fmt(iso) : null);

// ---- the operator's table
export const OPERATOR_FILTERS: readonly (readonly [string, string])[] = [["", "All"], ...JOURNEY_STATES.map((s) => [s, STATE_LABEL[s]] as const)];
export function stateCounts(counts: Record<string, number>): { state: JourneyState; n: number }[] {
  return JOURNEY_STATES.filter((s) => (counts[s] ?? 0) > 0).map((s) => ({ state: s, n: counts[s] }));
}
