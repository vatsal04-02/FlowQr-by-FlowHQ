"use client";
import { Button } from "@/components/ui/Button";
import { Alert, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { Meter, Panel, Status } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import type { Activity } from "@/lib/agent";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, fmtNum, timeAgo } from "@/lib/format";
import { useFetch } from "@/lib/use-api";

const KIND: Record<string, string> = { daily_plan: "Daily plan", refresh_google: "Google refresh", publish_posts: "Publishing", draft_replies: "Reply drafts" };
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "–");

export default function ActivityPage() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const { data: a, error, loading, reload } = useFetch<Activity>("/agent/activity");
  const retry = async (id: string) => { try { const r = await api<{ status: string; failure_reason: string | null }>(`/posts/${id}/retry`, { method: "POST" }); toast(r.status === "published" ? "Published on Google." : r.failure_reason ?? "Will retry.", r.status === "published" ? "success" : "error"); await reload(); } catch (e) { toast(errorMessage(e), "error"); } };
  if (error) return <Alert tone="error">{error}</Alert>;
  if (loading || !a) return <Skeleton className="h-64" />;
  return (
    <>
      <PageHeader eyebrow="AI Growth Agent" title="Activity" subtitle="What the agent did, what is queued, what failed and why, and how much AI you have used." />
      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title="Status">
          <dl className="space-y-2 text-sm"><div className="flex justify-between"><dt className="text-ink-500">Last plan</dt><dd>{a.last_plan_run ? <Status tone={a.last_plan_run.status === "ok" ? "ok" : "bad"}>{a.last_plan_run.status === "ok" ? "Ran" : "Failed"} {timeAgo(a.last_plan_run.at)}</Status> : "Not run yet"}</dd></div>
            <div className="flex justify-between"><dt className="text-ink-500">Plan date</dt><dd>{a.last_plan_date ? fmtDate(a.last_plan_date) : "–"}</dd></div>
            <div className="flex justify-between"><dt className="text-ink-500">Waiting for approval</dt><dd className="num font-semibold">{a.pending_approvals}</dd></div></dl>
          {a.last_plan_run?.error && <p className="mt-2 text-[13px] text-red-700">{a.last_plan_run.error}</p>}
        </Panel>
        <Panel title="AI usage this month" action={<a className="text-[13px] font-medium text-brand-700 hover:underline" href="/ai/usage">Details</a>}>
          <p className="num text-2xl font-bold">{fmtNum(a.ai.used_this_month)} <span className="text-base font-medium text-ink-400">/ {fmtNum(a.ai.monthly_limit)}</span></p>
          <div className="mt-2"><Meter value={a.ai.used_this_month} max={a.ai.monthly_limit} label="AI uses this month" tone={a.ai.used_this_month >= a.ai.monthly_limit ? "bad" : "info"} /></div>
        </Panel>
        <Panel title="Queued posts">{a.queued_posts.length === 0 ? <p className="text-sm text-ink-500">Nothing is queued.</p> : <ul className="space-y-2 text-sm">{a.queued_posts.map((p) => (
          <li key={p.id}><p className="truncate">{p.summary}</p><p className="text-[13px] text-ink-500">due {when(p.scheduled_for)}{p.attempts > 0 ? ` · attempt ${p.attempts} failed; next try ${when(p.next_attempt_at)}` : ""}</p>{p.last_error && <p className="text-[13px] text-amber-800">{p.last_error}</p>}</li>))}</ul>}</Panel>
      </div>
      {a.failed_posts.length > 0 && <div className="mt-4"><Panel title={`Failed posts (${a.failed_posts.length})`}><ul className="divide-y divide-ink-100">{a.failed_posts.map((p) => (
        <li key={p.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-sm"><div className="min-w-0 flex-1"><p className="truncate font-medium">{p.summary}</p><p className="text-[13px] text-red-700">{p.reason}</p></div>{isAdmin && <Button size="sm" variant="secondary" onClick={() => void retry(p.id)}>Retry</Button>}</li>))}</ul></Panel></div>}
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Panel title="Runs" flush>{a.runs.length === 0 ? <div className="p-4"><EmptyState title="No runs yet">The agent runs once a day, or when you press Update plan.</EmptyState></div> : (
          <div className="overflow-x-auto"><table className="dt min-w-[420px]"><thead><tr><th>What</th><th>When</th><th>Result</th></tr></thead><tbody>{a.runs.map((r) => (
            <tr key={r.id}><td>{KIND[r.kind] ?? r.kind}</td><td className="whitespace-nowrap text-ink-500">{when(r.started_at)}</td><td><Status tone={r.status === "ok" ? "ok" : r.status === "running" ? "info" : "bad"}>{r.status === "ok" ? "OK" : r.status}</Status>{r.error && <p className="max-w-[220px] text-xs text-red-700">{r.error}</p>}</td></tr>))}</tbody></table></div>)}</Panel>
        <Panel title="Task history" flush>{a.events.length === 0 ? <p className="p-4 text-sm text-ink-500">No task activity yet.</p> : <ul className="max-h-[480px] divide-y divide-ink-100 overflow-y-auto">{a.events.map((e, i) => (
          <li key={i} className="px-4 py-2.5 text-sm"><p className="font-medium">{e.task}</p><p className="text-[13px] text-ink-500">{e.from ? `${e.from.replace(/_/g, " ")} → ` : ""}{e.to.replace(/_/g, " ")} · by {e.actor} · {when(e.at)}{e.note ? ` · ${e.note}` : ""}</p></li>))}</ul>}</Panel>
      </div>
    </>
  );
}
