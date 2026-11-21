// Agency manager account (services/google/agency.py): what the client sees. Pure functions, so they are tested without a browser.

export type AgencyTone = "ok" | "info" | "warn" | "bad" | "idle";

/** One tone per backend status. Anything unknown is shown as neutral rather than guessed. */
export const AGENCY_TONE: Record<string, AgencyTone> = {
  consented: "info", invited: "info", accepted: "info", verified: "info", active: "ok", needs_attention: "warn", stopping: "warn", stopped: "idle", lost: "bad", cancelled: "idle", failed: "bad",
};
export const agencyTone = (status: string): AgencyTone => AGENCY_TONE[status] ?? "idle";

/** States where "Check again" can move things forward. Not offered once the client stopped, or after access was lost (the client must act in Google). */
export const canCheckAgain = (status: string): boolean => ["consented", "invited", "accepted", "verified", "needs_attention"].includes(status);

/** Stopping is offered while FlowQR is, or is about to be, a manager. */
export const canStop = (status: string): boolean => ["invited", "accepted", "verified", "active", "needs_attention"].includes(status);

export interface ConsentBlock { lead: string; bullets: string[] }

/** The consent text arrives as plain text ("lead\n\nWhat this means:\n- a\n- b"). It is shown exactly as sent, split into a lead line and bullets; nothing is added or removed. */
export function parseConsent(text: string): ConsentBlock {
  const lines = text.split("\n").map((l) => l.trim());
  const bullets = lines.filter((l) => l.startsWith("- ")).map((l) => l.slice(2));
  const lead = lines.filter((l) => l && !l.startsWith("- ")).join(" ");
  return { lead, bullets };
}

export interface AgencyLoc { status: string; accepted_at: string | null; removal_deadline_at: string | null }

/** One calm sentence about a location's date story, or null when there is nothing to add. */
export function dateLine(l: AgencyLoc, fmt: (iso: string) => string): string | null {
  if (l.status === "active" && l.accepted_at) return `FlowQR became your Manager on ${fmt(l.accepted_at)}.`;
  if (l.status === "stopping" && l.removal_deadline_at) return `FlowQR stopped work and will have removed itself by ${fmt(l.removal_deadline_at)}.`;
  return null;
}

// ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
// The guided onboarding (services/google/agency.py: dashboard_state, available_routes). Pure functions, so every sentence and every button rule is tested without a browser.

export type DashboardState = "google_connected" | "invitation_pending" | "client_action_required" | "access_verified" | "connection_lost" | "disconnected";
export const DASHBOARD_STATES: readonly DashboardState[] = ["google_connected", "invitation_pending", "client_action_required", "access_verified", "connection_lost", "disconnected"];

export const STATE_TONE: Record<DashboardState, AgencyTone> = {
  google_connected: "info", invitation_pending: "info", client_action_required: "warn", access_verified: "ok", connection_lost: "bad", disconnected: "idle",
};
/** An unknown state from a newer server is shown neutrally, never guessed. */
export const stateTone = (state: string): AgencyTone => STATE_TONE[state as DashboardState] ?? "idle";

export type AgencyAction = "retry" | "reconnect" | "disconnect" | "restart" | "start";
export const ACTION_LABEL: Record<AgencyAction, string> = {
  retry: "Check again", reconnect: "Reconnect Google", disconnect: "Stop FlowQR managing my profile", restart: "Start again", start: "Begin",
};
export const actionLabel = (a: string): string => ACTION_LABEL[a as AgencyAction] ?? a;

export type Route = "location" | "business_group";
export interface RoutesInfo { selected: number; available: Route[]; reason: string }
export interface RouteChoice { id: Route; title: string; body: string; enabled: boolean; why: string }

/** The two routes, always both shown, with the one that does not fit the client's selection disabled and the reason said plainly. */
export function routeChoices(r: RoutesInfo): RouteChoice[] {
  const off = (id: Route) => (r.available.includes(id) ? "" : r.selected === 0 ? "Select a profile first." : r.reason || (id === "location" ? "This route is for exactly one selected profile." : "This route is for two or more profiles of one business group."));
  return [
    { id: "location", title: "One profile", body: "Invite FlowQR to the one profile you selected.", enabled: r.available.includes("location"), why: off("location") },
    { id: "business_group", title: "My business group", body: "Invite FlowQR to several profiles that sit in the same Google business group. One invitation per profile, and you choose which.", enabled: r.available.includes("business_group"), why: off("business_group") },
  ];
}

export const defaultRoute = (r: RoutesInfo): Route | null => r.available[0] ?? null;

export const STEPS = ["Google connected", "Choose your profile", "Approve access", "Access verified"] as const;

/** The step the client is on (0 to 3), or 4 when everything is done. It never moves ahead of what the server has recorded. */
export function stepIndex(state: string, hasSelection: boolean): number {
  switch (state) {
    case "google_connected": return hasSelection ? 2 : 1;
    case "invitation_pending": return 3;
    case "access_verified": return 4;
    default: return 2; // client action required, lost, disconnected: back to approving access
  }
}

/** What this is, in the order a client wonders about it. Plain words, no promises beyond what the product does. */
export const HOW_IT_WORKS: readonly string[] = [
  "You stay the owner of your Google Business Profile. FlowQR is only ever added as a Manager, never as an Owner, and can't remove you or change who owns the profile.",
  "Nothing happens until you approve it here. We then send the invitation through Google, using the Google sign-in you already connected.",
  "In Google, open Business Profile, then People and access: you will see FlowQR's business group listed as a Manager, first pending and then accepted. You don't have to accept anything: FlowQR's team accepts it on its side.",
  "You can stop at any time here, or remove FlowQR yourself in Google. FlowQR stops work at once and removes itself.",
];

export const POLICY_FOOTNOTE = "An accepted invitation is not Google's approval of FlowQR's API access. Reviews, replies and posts stay off until that approval and Google's rules for this kind of access are confirmed.";

/** A fresh id for each attempt to approve, so a double click or a replayed request can never send a second invitation. */
export function newRequestId(): string {
  const c = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
  return c?.randomUUID ? c.randomUUID() : `req-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export interface AgencyView {
  state: string; headline: string; detail: string; waiting_on: string | null; client_action: boolean; actions: string[];
  routes: RoutesInfo; operations_enabled: boolean; policy_note: string;
}

/** The buttons to show for a view: only those the server offered, in a fixed, calm order. Unknown actions are dropped. */
export function visibleActions(v: Pick<AgencyView, "actions">): AgencyAction[] {
  const order: AgencyAction[] = ["start", "retry", "reconnect", "restart", "disconnect"];
  return order.filter((a) => v.actions.includes(a));
}
