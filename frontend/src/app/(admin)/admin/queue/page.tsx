"use client";
import { Alert, Badge, Card, CardHeader, PageHeader, Skeleton } from "@/components/ui/Card";
import { useFetch } from "@/lib/use-api";

interface FailedAction { id: string; tenant_id: string; business: string; location: string | null; field: string; action_type: string; status: string; attempts: number; error: string | null; policy_reasons: string[]; when: string; next_attempt_at: string | null }
interface FailedPost { id: string; tenant_id: string; business: string; location: string | null; attempts: number; error: string | null; scheduled_for: string | null; when: string }
interface Pending { id: string; tenant_id: string; business: string; location: string | null; field: string; action_type: string; level: number; risk: string; waiting_hours: number | null; expires_at: string | null }
interface Queue {
  generated_at: string; window_days: number;
  failed: { counts: Record<string, number>; actions: FailedAction[]; posts_total: number; posts: FailedPost[] };
  pending: { actions_total: number; actions: Pending[]; posts_waiting: number; oldest_post_waiting_hours: number | null };
  account_requests: {
    deletions_scheduled: { tenant_id: string; business: string; requested_at: string | null; scheduled_for: string | null; overdue: boolean; subscription_status: string | null }[];
    exports_recent: { tenant_id: string | null; business: string | null; when: string; files: number | null; bytes: number | null }[];
    deletions_completed: { when: string; business_slug: string | null; google_grants_revoked: number | null; users_removed: number | null; cards_returned: number | null }[];
  };
}

const when = (s: string | null) => (s ? new Date(s).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : "n/a");
const label = (s: string) => s.replace(/_/g, " ");
const hours = (h: number | null) => (h === null ? "n/a" : h < 48 ? `${Math.round(h)} h` : `${Math.round(h / 24)} days`);
const kb = (n: number | null) => (n === null ? "n/a" : n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`);
const STATUS_TONE = { failed: "red", blocked: "amber", invalidated: "amber" } as const;

function Empty({ children }: { children: React.ReactNode }) { return <p className="py-3 text-sm text-muted">{children}</p>; }

/** Platform admin: everything across all businesses that needs a person. Read from the real records; an empty list means nothing is waiting, not that nothing is being checked. */
export default function AdminQueue() {
  const { data, error } = useFetch<Queue>("/admin/work-queue");
  if (error) return <Alert tone="error">{error}</Alert>;
  if (!data) return <Skeleton className="h-64" />;
  const { failed, pending, account_requests: acct } = data;
  const overdue = acct.deletions_scheduled.filter((d) => d.overdue);
  const stuck = pending.actions.filter((a) => (a.waiting_hours ?? 0) >= 72).length;
  return (
    <>
      <PageHeader title="Work queue" subtitle={`What needs a person, across every business. Failures cover the last ${data.window_days} days. Read-only; as of ${when(data.generated_at)}.`} />
      <div className="mb-5 grid gap-3 sm:grid-cols-3">
        <Card><p className="text-xs text-muted">Failed, blocked or invalidated Google changes</p><p className="num mt-1 text-2xl font-semibold">{failed.counts.failed + failed.counts.blocked + failed.counts.invalidated}</p><p className="text-xs text-muted">{failed.counts.failed} failed · {failed.counts.blocked} blocked · {failed.counts.invalidated} invalidated</p></Card>
        <Card><p className="text-xs text-muted">Waiting for a business owner</p><p className="num mt-1 text-2xl font-semibold">{pending.actions_total + pending.posts_waiting}</p><p className="text-xs text-muted">{pending.actions_total} profile changes · {pending.posts_waiting} posts{stuck ? ` · ${stuck} waiting over 3 days` : ""}</p></Card>
        <Card><p className="text-xs text-muted">Deletion requests</p><p className="num mt-1 text-2xl font-semibold">{acct.deletions_scheduled.length}</p><p className="text-xs text-muted">{overdue.length ? `${overdue.length} overdue: the daily job has not run them` : "none overdue"}</p></Card>
      </div>
      {overdue.length > 0 && <div className="mb-5"><Alert tone="error" title="A scheduled deletion is overdue">The daily deletion job should have removed {overdue.map((d) => d.business).join(", ")}. Check Operations for the worker and scheduler, then the job's log. Until it runs, that business's data is still held.</Alert></div>}

      <div className="space-y-6">
        <Card><CardHeader title="Failed Google changes" subtitle="Profile changes that failed after retries, were stopped by a safety rule, or were dropped because Google's value had changed since they were proposed." />
          {failed.actions.length === 0 ? <Empty>No failed, blocked or invalidated changes in the last {data.window_days} days.</Empty> : (
            <ul className="divide-y divide-line text-sm">{failed.actions.map((a) => (
              <li key={a.id} className="py-3">
                <div className="flex flex-wrap items-center gap-2"><span className="font-medium">{a.business}</span><span className="text-muted">{a.location ?? "location removed"}</span><Badge tone={STATUS_TONE[a.status as keyof typeof STATUS_TONE] ?? "gray"}>{a.status}</Badge><span className="text-muted">{label(a.action_type)} · {label(a.field)} · {a.attempts} attempt{a.attempts === 1 ? "" : "s"} · {when(a.when)}</span></div>
                {a.error && <p className="mt-1 break-words text-muted">{a.error}</p>}
                {a.status === "failed" && a.next_attempt_at && <p className="text-xs text-muted">Will retry at {when(a.next_attempt_at)}</p>}
              </li>))}</ul>)}
        </Card>

        <Card><CardHeader title={`Failed posts (${failed.posts_total})`} subtitle="Google Posts that could not be published." />
          {failed.posts.length === 0 ? <Empty>No failed posts in the last {data.window_days} days.</Empty> : (
            <ul className="divide-y divide-line text-sm">{failed.posts.map((p) => (
              <li key={p.id} className="py-3"><div className="flex flex-wrap items-center gap-2"><span className="font-medium">{p.business}</span><span className="text-muted">{p.location ?? "location removed"}</span><Badge tone="red">failed</Badge><span className="text-muted">{p.attempts} attempt{p.attempts === 1 ? "" : "s"} · due {when(p.scheduled_for)}</span></div>{p.error && <p className="mt-1 break-words text-muted">{p.error}</p>}</li>))}</ul>)}
        </Card>

        <Card><CardHeader title="Waiting for approval" subtitle="Oldest first. These need the business owner; FlowQR never applies them on its own." />
          {pending.actions.length === 0 && pending.posts_waiting === 0 ? <Empty>Nothing is waiting for approval.</Empty> : (
            <>
              {pending.posts_waiting > 0 && <p className="mb-2 text-sm text-muted">{pending.posts_waiting} post{pending.posts_waiting === 1 ? "" : "s"} waiting; the oldest for {hours(pending.oldest_post_waiting_hours)}.</p>}
              <ul className="divide-y divide-line text-sm">{pending.actions.map((a) => (
                <li key={a.id} className="flex flex-wrap items-center gap-2 py-2.5"><span className="font-medium">{a.business}</span><span className="text-muted">{a.location ?? "location removed"} · {label(a.action_type)} · {label(a.field)}</span><Badge tone={a.risk === "high" ? "red" : a.risk === "medium" ? "amber" : "gray"}>{a.risk} risk</Badge><span className="ml-auto num text-muted">waiting {hours(a.waiting_hours)}</span></li>))}</ul>
            </>)}
        </Card>

        <Card><CardHeader title="Business deletions" subtitle="Scheduled by the owner; they can cancel until the date. The daily job then removes the business and revokes its Google access." />
          {acct.deletions_scheduled.length === 0 ? <Empty>No deletions are scheduled.</Empty> : (
            <ul className="divide-y divide-line text-sm">{acct.deletions_scheduled.map((d) => (
              <li key={d.tenant_id} className="flex flex-wrap items-center gap-2 py-2.5"><span className="font-medium">{d.business}</span>{d.overdue ? <Badge tone="red">overdue</Badge> : <Badge tone="amber">scheduled</Badge>}<span className="text-muted">asked {when(d.requested_at)} · runs {when(d.scheduled_for)}{d.subscription_status ? ` · subscription ${d.subscription_status}` : ""}</span></li>))}</ul>)}
          <h3 className="mb-1 mt-5 text-sm font-semibold">Completed in the last {data.window_days} days</h3>
          {acct.deletions_completed.length === 0 ? <Empty>None.</Empty> : (
            <ul className="divide-y divide-line text-sm">{acct.deletions_completed.map((d, i) => (
              <li key={i} className="py-2.5 text-muted"><span className="font-medium text-ink">{d.business_slug ?? "business"}</span> deleted {when(d.when)} · Google access revoked for {d.google_grants_revoked ?? 0} connection(s) · {d.users_removed ?? 0} account(s) removed · {d.cards_returned ?? 0} card(s) returned to stock</li>))}</ul>)}
        </Card>

        <Card><CardHeader title="Data exports" subtitle="Each owner download of their business's data in the last 30 days. The file itself is created on request and not kept." />
          {acct.exports_recent.length === 0 ? <Empty>No exports in the last {data.window_days} days.</Empty> : (
            <ul className="divide-y divide-line text-sm">{acct.exports_recent.map((e, i) => (
              <li key={i} className="flex flex-wrap items-center gap-2 py-2.5"><span className="font-medium">{e.business ?? "deleted business"}</span><span className="text-muted">{when(e.when)} · {e.files ?? "?"} files · {kb(e.bytes)}</span></li>))}</ul>)}
        </Card>
      </div>
    </>
  );
}
