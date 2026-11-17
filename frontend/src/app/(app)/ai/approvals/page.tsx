"use client";
import { useState } from "react";
import { Violations } from "@/components/agent/TaskCard";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, EmptyState, PageHeader, Skeleton, Stars } from "@/components/ui/Card";
import { Input, Textarea } from "@/components/ui/Form";
import { Panel } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import type { Approvals, Violation } from "@/lib/agent";
import { api, ApiError, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-api";

export default function ApprovalsPage() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const { data, error, loading, reload } = useFetch<Approvals>("/agent/approvals");
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<Record<string, string>>({});
  const [viol, setViol] = useState<Record<string, Violation[]>>({});
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [when, setWhen] = useState<Record<string, string>>({});
  const [ack, setAck] = useState<Record<string, boolean>>({});

  async function run(id: string, fn: () => Promise<unknown>, ok: string) {
    setBusy(id); setErr((e) => ({ ...e, [id]: "" }));
    try { await fn(); toast(ok); await reload(); }
    catch (e) { if (e instanceof ApiError && e.code === "safety_violation") setViol((v) => ({ ...v, [id]: ((e.detail as { violations?: Violation[] }).violations) ?? [] })); setErr((x) => ({ ...x, [id]: errorMessage(e) })); await reload(); }
    finally { setBusy(null); }
  }
  const total = (data?.replies.length ?? 0) + (data?.posts.length ?? 0) + (data?.profile.length ?? 0);
  return (
    <>
      <PageHeader title="Waiting for your approval" subtitle="Only the exact text you approve here is sent to Google." />
      {!isAdmin && <div className="mb-4"><Alert tone="info">You can see what is waiting; an owner or admin approves it.</Alert></div>}
      {error && <Alert tone="error">{error}</Alert>}
      {data && total > 0 && (
        <ul aria-label="What is waiting" className="mb-4 flex flex-wrap gap-2 text-[13.5px] text-ink-700">
          {([["Review replies", data.replies.length], ["Google posts", data.posts.length], ["Profile changes", data.profile.length]] as const).filter(([, n]) => n > 0).map(([l, n]) => (
            <li key={l} className="inline-flex min-h-9 items-center gap-1.5 rounded-full bg-surface px-3.5 shadow-pill ring-1 ring-line"><b className="num font-semibold text-ink">{n}</b> {l.toLowerCase()}</li>))}
        </ul>
      )}
      {loading && !data ? <Skeleton className="h-48" /> : total === 0 ? <EmptyState title="Nothing is waiting for approval">New AI drafts and scheduled posts show up here before anything goes live.</EmptyState> : (
        <div className="space-y-6">
          {data!.replies.length > 0 && <Panel title={`Review replies (${data!.replies.length})`}><ul className="space-y-5">{data!.replies.map((r) => (
            <li key={r.id} className="space-y-2 border-b border-ink-100 pb-5 last:border-0 last:pb-0">
              <div className="flex flex-wrap items-center gap-2 text-sm"><Stars rating={r.rating} /><span className="font-medium">{r.reviewer ?? "A customer"}</span>{r.ai && <Badge tone="blue">AI draft</Badge>}{r.flags.length > 0 && <Badge tone="amber">needs personal handling</Badge>}</div>
              {r.review_text && <p className="text-sm italic text-ink-700">&ldquo;{r.review_text}&rdquo;</p>}
              <Violations items={[...r.violations, ...(viol[r.id] ?? [])]} />
              <Textarea label="Reply" rows={3} value={edits[r.id] ?? r.body} onChange={(e) => setEdits({ ...edits, [r.id]: e.target.value })} />
              {r.flags.length > 0 && <label className="flex items-start gap-2 text-[13px] text-amber-900"><input type="checkbox" className="mt-0.5 h-4 w-4" checked={!!ack[r.id]} onChange={(e) => setAck({ ...ack, [r.id]: e.target.checked })} />I have read this review and want to reply ({r.flags.join(", ").replace(/_/g, " ")}).</label>}
              {err[r.id] && <Alert tone="error">{err[r.id]}</Alert>}
              <div className="flex gap-2">
                <Button size="sm" disabled={!isAdmin || (r.flags.length > 0 && !ack[r.id])} loading={busy === r.id} onClick={() => void run(r.id, async () => {
                  if (edits[r.id] !== undefined && edits[r.id] !== r.body) await api(`/reply-drafts/${r.id}`, { method: "PATCH", body: { body: edits[r.id] } });
                  await api(`/reply-drafts/${r.id}/approve`, { method: "POST", body: { acknowledge_flags: !!ack[r.id] } });
                  await api(`/reply-drafts/${r.id}/publish`, { method: "POST" });
                }, "Reply sent to Google.")}>Approve &amp; publish</Button>
                <Button size="sm" variant="ghost" disabled={!isAdmin} onClick={() => void run(r.id, () => api(`/reply-drafts/${r.id}`, { method: "DELETE" }), "Draft rejected.")}>Reject</Button>
              </div>
            </li>))}</ul></Panel>}

          {data!.posts.length > 0 && <Panel title={`Google posts (${data!.posts.length})`}><ul className="space-y-5">{data!.posts.map((p) => (
            <li key={p.id} className="space-y-2 border-b border-ink-100 pb-5 last:border-0 last:pb-0">
              <div className="flex items-center gap-2 text-sm">{p.generated_by_ai && <Badge tone="blue">AI draft</Badge>}<span className="text-ink-500">{p.summary.length} characters</span></div>
              <p className="whitespace-pre-wrap rounded-lg bg-ink-50 p-3 text-sm">{p.summary}</p>
              <Violations items={[...p.violations, ...(viol[p.id] ?? [])]} />
              {err[p.id] && <Alert tone="error">{err[p.id]}</Alert>}
              <div className="flex flex-wrap items-end gap-2">
                <Button size="sm" disabled={!isAdmin} loading={busy === p.id} onClick={() => void run(p.id, async () => { const r = await api<{ status: string; failure_reason: string | null }>(`/posts/${p.id}/approve`, { method: "POST", body: {} }); if (r.status !== "published") throw new Error(r.failure_reason ?? "Google did not publish it yet; it will be retried."); }, "Published on Google.")}>Publish now</Button>
                <div className="w-52"><Input label="Or schedule for" type="datetime-local" value={when[p.id] ?? ""} onChange={(e) => setWhen({ ...when, [p.id]: e.target.value })} /></div>
                <Button size="sm" variant="secondary" disabled={!isAdmin || !when[p.id]} onClick={() => void run(p.id, () => api(`/posts/${p.id}/approve`, { method: "POST", body: { scheduled_for: when[p.id] } }), "Scheduled.")}>Schedule</Button>
                <Button size="sm" variant="ghost" disabled={!isAdmin} onClick={() => void run(p.id, () => api(`/posts/${p.id}/reject`, { method: "POST" }), "Moved back to draft.")}>Back to draft</Button>
              </div>
            </li>))}</ul></Panel>}

          {data!.profile.length > 0 && <Panel title={`Profile changes (${data!.profile.length})`}><ul className="space-y-5">{data!.profile.map((t) => (
            <li key={t.id} className="space-y-2">
              <p className="text-sm font-medium">{t.title}</p>
              <Violations items={[...t.violations, ...(viol[t.id] ?? [])]} />
              <Textarea label="Proposed description" rows={5} maxLength={750} value={edits[t.id] ?? t.draft?.description ?? ""} onChange={(e) => setEdits({ ...edits, [t.id]: e.target.value })} />
              {err[t.id] && <Alert tone="error">{err[t.id]}</Alert>}
              <Button size="sm" disabled={!isAdmin} loading={busy === t.id} onClick={() => void run(t.id, async () => {
                if (edits[t.id] !== undefined && edits[t.id] !== t.draft?.description) { const r = await api<{ violations: Violation[] }>(`/agent/tasks/${t.id}/draft`, { method: "PATCH", body: { description: edits[t.id] } }); if (r.violations.length) { setViol((v) => ({ ...v, [t.id]: r.violations })); throw new Error("Fix the highlighted text first."); } }
                await api(`/agent/tasks/${t.id}/approve`, { method: "POST" });
              }, "Description updated on Google.")}>Approve &amp; publish to Google</Button>
            </li>))}</ul></Panel>}
        </div>)}
    </>
  );
}
