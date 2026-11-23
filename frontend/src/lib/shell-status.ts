/**
 * What the top bar says about Google, the sync and where you are. Pure functions (no imports) so they are unit-tested with `node --test` (frontend/tests).
 * Every sentence here is derived from what the API returned; when the API has not answered yet the answer is `null` and the bar shows nothing rather than a guess.
 */

type Conn = { status: string };
type Loc = { selected: boolean; last_synced_at: string | null; last_sync_status: string | null };

export type Tone = "ok" | "warn" | "bad" | "idle";

/** The line under the business name: is Google connected? `null` = not known yet (still loading). */
export function googleLine(conns: Conn[] | null | undefined): { label: string; tone: Tone; href: string } | null {
  if (!conns) return null;
  const live = conns.filter((c) => c.status !== "disconnected");
  if (live.some((c) => c.status === "active")) return { label: "Google connected", tone: "ok", href: "/settings/connections/google" };
  if (live.some((c) => c.status === "pending_selection")) return { label: "Choose your Google locations", tone: "warn", href: "/settings/connections/google" };
  if (live.some((c) => c.status === "error" || c.status === "revoked")) return { label: "Reconnect Google", tone: "warn", href: "/settings/connections/google" };
  return { label: "Google not connected", tone: "idle", href: "/settings/connections/google" };
}

/** Statuses that mean "Google asked us to wait", not "something broke". */
const PAUSED = new Set(["rate_limited", "awaiting_approval"]);

export type SyncChip =
  | { kind: "waiting"; tone: "idle"; label: string; lastSyncedAt: null }
  | { kind: "ok"; tone: "ok"; label: string; lastSyncedAt: string }
  | { kind: "paused" | "failed"; tone: "warn" | "bad"; label: string; lastSyncedAt: string | null };

/**
 * The sync chip. Looks only at the locations being synced. `null` means there is nothing to sync (no connection or none chosen), so the chip is not shown.
 * "ok" carries the newest successful time; the component turns it into "13m ago" so the text stays fresh.
 */
export function syncChip(locs: Loc[] | null | undefined): SyncChip | null {
  const on = (locs ?? []).filter((l) => l.selected);
  if (!on.length) return null;
  const last = on.map((l) => l.last_synced_at).filter((x): x is string => !!x).sort().pop() ?? null;
  const bad = on.filter((l) => l.last_sync_status && l.last_sync_status !== "ok");
  if (bad.length) {
    const paused = bad.every((l) => PAUSED.has(l.last_sync_status ?? ""));
    return paused ? { kind: "paused", tone: "warn", label: "Sync paused by Google", lastSyncedAt: last } : { kind: "failed", tone: "bad", label: "Sync problem", lastSyncedAt: last };
  }
  if (!last) return { kind: "waiting", tone: "idle", label: "Waiting for first sync", lastSyncedAt: null };
  return { kind: "ok", tone: "ok", label: "Synced", lastSyncedAt: last };
}

type Located = { dest: { label: string }; child: { label: string } | null; tab: { label: string } | null } | null;

/** Breadcrumb parts from the navigation file's own answer: "GBP › Profile › Photos". The Home destination is a single crumb. Unknown pages show no crumb. */
export function crumbParts(l: Located): string[] {
  if (!l) return [];
  const parts = [l.dest.label];
  if (l.child && l.child.label !== l.dest.label) parts.push(l.child.label);
  if (l.tab && l.tab.label !== parts[parts.length - 1]) parts.push(l.tab.label);
  return parts;
}

/** The trial chip in the top bar: only while trialing, in the last five days, and not on the billing pages themselves. */
export function showTrialChip(s: { status: string; trial_days_left: number | null } | null | undefined, path: string): boolean {
  if (!s || s.status !== "trialing") return false;
  if (path.startsWith("/settings/billing")) return false;
  return (s.trial_days_left ?? 99) <= 5;
}
