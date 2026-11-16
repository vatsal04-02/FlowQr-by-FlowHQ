// Pure helpers for the Overview dashboard: comparisons, the "things to do" list and the activity timeline.
// Everything here is derived from real API responses. Nothing is estimated, padded or invented.
import type { Activity, ReportSummary, Task } from "./agent";
import type { Card, GoogleConnection, Location, Overview, Review } from "./types";

export type Days = 7 | 30 | 90;
export const DAY_OPTIONS = [[7, "7 days"], [30, "30 days"], [90, "90 days"]] as const;

/** A change against the previous period of the same length. `null` when there is nothing real to compare with. */
export interface Delta { diff: number; hadPrevious: boolean }
export function delta(current: number | null | undefined, previous: number | null | undefined): Delta | null {
  if (current === null || current === undefined || previous === null || previous === undefined) return null;
  return { diff: current - previous, hadPrevious: previous > 0 };
}

const plural = (n: number, one: string, many: string) => (n === 1 ? one : many);

/** "3 more than the previous 30 days": words as well as an arrow, never colour alone. */
export function deltaText(d: Delta | null, days: number, unit: [string, string] = ["", ""], decimals = 0): { text: string; dir: "up" | "down" | "flat" | "none" } {
  if (!d) return { text: "Nothing earlier to compare with", dir: "none" };
  if (!d.hadPrevious && d.diff <= 0) return { text: `Nothing earlier to compare with`, dir: "none" };
  const n = Math.abs(d.diff), shown = decimals ? n.toFixed(decimals) : String(Math.round(n));
  const u = unit[0] ? ` ${plural(Math.round(n), unit[0], unit[1])}` : "";
  const since = `than the previous ${days} days`;
  if (n < (decimals ? 0.05 : 0.5)) return { text: `Same as the previous ${days} days`, dir: "flat" };
  if (!d.hadPrevious) return { text: `${shown}${u} (none in the previous ${days} days)`, dir: "up" };
  return d.diff > 0 ? { text: `${shown}${u} more ${since}`, dir: "up" } : { text: `${shown}${u} fewer ${since}`, dir: "down" };
}

/** The same dates one period earlier, for the second fetch that powers every comparison. */
export function previousRange(from: string, days: number) {
  const f = new Date(from + "T00:00:00");
  const to = new Date(f); to.setDate(to.getDate() - 1);
  const start = new Date(to); start.setDate(start.getDate() - (days - 1));
  const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  return { from: iso(start), to: iso(to) };
}

export function greeting(now = new Date()) {
  const h = now.getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

// ------------------------------------------------------------------------------------------ Google numbers FlowQR already stores

/**
 * "People who used your Google profile", read from the numbers FlowQR's own daily job stored from Google (28 days and the 28 before).
 * Reading these makes no call to Google, so opening the dashboard never spends Google quota or touches the connection.
 */
export type GoogleStored =
  | { state: "loading" }
  | { state: "not-connected" }
  | { state: "unavailable"; note: string }
  | { state: "ready"; current: number; previous: number; fetchedAt: string };
export function googleStored(rep: ReportSummary | null, error: string | null, connected: boolean, loading: boolean): GoogleStored {
  if (!connected) return loading ? { state: "loading" } : { state: "not-connected" };
  if (error) return { state: "unavailable", note: "We couldn't load Google's numbers just now." };
  if (!rep) return { state: "loading" };
  const g = rep.google_performance;
  if (!g.available || g.locations.length === 0) return { state: "unavailable", note: g.note || "Google hasn't shared numbers for this profile yet." };
  return {
    state: "ready", current: g.locations.reduce((a, l) => a + l.last_28_days, 0), previous: g.locations.reduce((a, l) => a + l.previous_28_days, 0),
    fetchedAt: g.locations.map((l) => l.fetched_at).sort().pop()!,
  };
}

// ------------------------------------------------------------------------------------------ things to do

export interface Todo { id: string; tone: "bad" | "warn" | "info"; title: string; detail: string; href: string; cta: string }
const n = (v: number, one: string, many: string) => `${v} ${plural(v, one, many)}`;

const TASK_ACTION: Partial<Record<Task["kind"], [string, string]>> = {
  profile_fix: ["/gbp/info", "Fix it"], add_photo: ["/gbp/photos", "Add photos"], connect_google: ["/gbp/locations", "Connect Google"],
  complete_knowledge: ["/settings/ai/brain", "Add details"], create_post: ["/ai/tasks", "Write the post"],
};

/**
 * What needs a person today, in plain words, most urgent first. Counts come straight from the data (reviews, approvals, failures,
 * the agent's own tasks); one row per kind of thing so the list stays short.
 */
export function buildTodos(a: {
  overview: Overview | null; tasks: Task[]; pendingApprovals: number; failedReplies: number; sensitiveWaiting: number;
  locations: Location[]; connections: GoogleConnection[]; googleConfigured: boolean | undefined;
}): Todo[] {
  const out: Todo[] = [];
  const o = a.overview;
  if (a.failedReplies > 0) out.push({ id: "failed-replies", tone: "bad", title: `Resend ${n(a.failedReplies, "reply", "replies")}`, detail: "Google didn't accept them. Open each one to try again or change the wording.", href: "/gbp/reviews?state=failed", cta: "Fix and resend" });
  if (a.sensitiveWaiting > 0) out.push({ id: "sensitive", tone: "bad", title: `${n(a.sensitiveWaiting, "review needs", "reviews need")} you`, detail: "They mention things like refunds or safety, so the AI won't answer without your okay.", href: "/gbp/reviews?state=none", cta: "Read them" });
  for (const s of o?.sync ?? []) {
    if (s.status && s.status !== "ok" && s.status !== "running") out.push({ id: `sync-${s.location}`, tone: "bad", title: `Fix review sync`, detail: s.error ?? "Google didn't let FlowQR read this location.", href: "/gbp/locations", cta: "Check connection" });
  }
  const broken = a.connections.find((c) => c.status === "revoked" || c.status === "error");
  if (broken) out.push({ id: "google-broken", tone: "bad", title: "Reconnect Google", detail: broken.last_error ?? "Access was removed or expired. Reconnect to keep reviews coming in.", href: "/gbp/locations", cta: "Reconnect" });
  if (a.pendingApprovals > 0) out.push({ id: "approvals", tone: "warn", title: `Approve ${n(a.pendingApprovals, "draft", "drafts")}`, detail: "Your AI assistant wrote them. Nothing goes live until you say yes.", href: "/ai/approvals", cta: "Review and approve" });
  const needReply = o?.reviews.awaiting_reply ?? 0;
  if (needReply > 0) out.push({ id: "need-reply", tone: "warn", title: `Reply to ${n(needReply, "review", "reviews")}`, detail: o && o.reviews.drafts_pending_approval ? `${o.reviews.drafts_pending_approval} already have a draft ready for you.` : "Let the AI write a reply, then you check it and send.", href: "/gbp/reviews?state=none", cta: "Reply to reviews" });
  for (const t of a.tasks) {
    const act = TASK_ACTION[t.kind];
    if (!act || ["published", "done", "dismissed", "snoozed", "awaiting_approval"].includes(t.status)) continue;
    out.push({ id: `task-${t.id}`, tone: "info", title: t.title, detail: t.why, href: act[0], cta: act[1] });
  }
  const noLink = a.locations.filter((l) => l.is_active && !l.review_url);
  if (noLink.length) out.push({ id: "no-link", tone: "warn", title: `${noLink.map((l) => l.name).join(", ")} can't send customers to Google yet`, detail: "Add your Google review link so customers who scan a card can leave a review.", href: "/gbp/locations", cta: "Add the link" });
  if (!a.connections.some((c) => c.status === "active") && (o?.reviews.total_synced ?? 0) === 0 && !out.some((x) => x.id.startsWith("task-") && x.cta === "Connect Google")) {
    out.push({ id: "connect", tone: "info", title: "Connect Google", detail: a.googleConfigured === false ? "Google sign-in isn't switched on for this server yet. Cards and the review helper still work." : "Then your reviews appear here and the AI can help you reply.", href: "/gbp/locations", cta: "Connect Google" });
  }
  const rank = { bad: 0, warn: 1, info: 2 };
  return out.sort((x, y) => rank[x.tone] - rank[y.tone]);
}

// ------------------------------------------------------------------------------------------ recent activity

export type TimelineState = "done" | "pending" | "failed";
export interface TimelineItem { id: string; at: string | null; state: TimelineState; title: string; detail?: string; tag?: string; href?: string }

const REPLY_TAG: Record<Review["reply_state"], [string, TimelineState]> = {
  none: ["Needs a reply", "pending"], draft: ["Reply drafted", "pending"], approved: ["Reply approved", "pending"], publishing: ["Sending to Google", "pending"], published: ["Replied", "done"], failed: ["Reply didn't send", "failed"],
};

/**
 * One readable list from real events: reviews that arrived, what the AI assistant prepared or finished, failed posts and card scans.
 * For tasks only the latest step is shown, so a reply that was drafted, approved and published appears once, as finished.
 */
export function buildTimeline(reviews: Review[], activity: Activity | null, cards: Card[], limit = 8): TimelineItem[] {
  const items: TimelineItem[] = [];
  for (const r of reviews) {
    const [tag, st] = REPLY_TAG[r.reply_state];
    items.push({ id: `review-${r.id}`, at: r.review_created_at, state: st === "failed" ? "failed" : "done", title: `New ${r.rating}-star review${r.location_name ? ` at ${r.location_name}` : ""}`, detail: r.text ? `“${r.text}”` : "Rating only, no comment", tag, href: `/gbp/reviews/${r.id}` });
  }
  const latest = new Map<string, Activity["events"][number]>();
  for (const e of activity?.events ?? []) { const cur = latest.get(e.task); if (!cur || e.at > cur.at) latest.set(e.task, e); }
  for (const e of latest.values()) {
    const to = e.to;
    if (to === "drafted" || to === "awaiting_approval") items.push({ id: `ev-${e.task}-${e.at}`, at: e.at, state: "pending", title: `Your AI assistant prepared: ${e.task}`, tag: "Waiting for your approval", href: "/ai/approvals" });
    else if (to === "approved" || to === "scheduled") items.push({ id: `ev-${e.task}-${e.at}`, at: e.at, state: "pending", title: `You approved: ${e.task}`, tag: "Going out to Google", href: "/ai/activity" });
    else if (to === "published" || to === "done") items.push({ id: `ev-${e.task}-${e.at}`, at: e.at, state: "done", title: e.task, tag: to === "published" ? "Published on Google" : "Done", href: "/ai/activity" });
    else if (to === "failed") items.push({ id: `ev-${e.task}-${e.at}`, at: e.at, state: "failed", title: `Didn't work: ${e.task}`, detail: e.note ?? undefined, tag: "Needs a look", href: "/ai/activity" });
  }
  for (const p of activity?.failed_posts ?? []) items.push({ id: `post-${p.id}`, at: null, state: "failed", title: "A Google post didn't publish", detail: p.reason ?? p.summary, tag: "Needs a look", href: "/gbp/posts" });
  for (const c of [...cards].filter((x) => x.last_scan_at).sort((x, y) => (y.last_scan_at ?? "").localeCompare(x.last_scan_at ?? "")).slice(0, 3))
    items.push({ id: `card-${c.id}`, at: c.last_scan_at ?? null, state: "done", title: `${c.label ?? "A card"} was scanned`, detail: [c.card_code, c.location_name].filter(Boolean).join(" · "), tag: "Card scanned", href: `/gbp/cards/${c.id}` });
  // failures with no time first (they are still open), then newest first
  return items.sort((a, b) => (a.at === null ? -1 : b.at === null ? 1 : b.at.localeCompare(a.at))).slice(0, limit);
}
