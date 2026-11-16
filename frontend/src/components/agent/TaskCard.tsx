"use client";
import { Check, Clock, ExternalLink, Sparkles, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Button, LinkButton } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Card";
import { Textarea } from "@/components/ui/Form";
import { Status } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import { TASK_LABEL, type Task, type Violation } from "@/lib/agent";
import { api, ApiError, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { timeAgo } from "@/lib/format";

const OPEN_LINK: Partial<Record<Task["kind"], [string, string]>> = {
  connect_google: ["/gbp/locations", "Open Google connection"], complete_knowledge: ["/settings/ai/brain", "Open Knowledge Base"], add_photo: ["/gbp/photos", "Open Photos & Media"],
  profile_fix: ["/gbp/info", "Open Profile Manager"],
};
const AI_KINDS = new Set(["reply_review", "create_post"]);

export function Violations({ items }: { items: Violation[] }) {
  if (!items.length) return null;
  return <Alert tone="error" title="This text breaks a rule from your knowledge base"><ul className="ml-4 list-disc">{items.map((v) => <li key={v.message}>{v.message}</li>)}</ul></Alert>;
}

/** One task from the plan, with exactly the actions its state allows. Nothing here reaches Google without an explicit approve click. */
export function TaskCard({ t, onChange }: { t: Task; onChange: () => void }) {
  const toast = useToast();
  const { isAdmin } = useAuth();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [viol, setViol] = useState<Violation[]>([]);
  const [text, setText] = useState<string | null>(null);
  const [ack, setAck] = useState(false);
  const st = TASK_LABEL[t.status];

  async function run(key: string, fn: () => Promise<unknown>, ok?: string) {
    setBusy(key); setError(null);
    try { await fn(); if (ok) toast(ok); onChange(); }
    catch (e) {
      if (e instanceof ApiError && e.code === "safety_violation") setViol(((e.detail as { violations?: Violation[] }).violations) ?? []);
      setError(errorMessage(e)); onChange();
    } finally { setBusy(null); }
  }
  const reply = t.reply;
  const desc = t.draft?.description;
  const flagged = (reply?.flags?.length ?? 0) > 0;
  const editing = text !== null;

  return (
    <li className="rounded-xl border border-ink-100 bg-white p-4" aria-label={t.title}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1"><p className="text-[15px] font-semibold">{t.title}</p><p className="mt-0.5 text-sm text-ink-500">{t.why}</p></div>
        <Status tone={st.tone}>{st.label}</Status>
      </div>
      {t.kind === "reply_review" && typeof t.evidence.snippet === "string" && t.evidence.snippet && <blockquote className="mt-3 border-l-2 border-ink-200 pl-3 text-sm italic text-ink-700">&ldquo;{t.evidence.snippet}&rdquo;</blockquote>}
      {t.suggested_action && t.status === "suggested" && <p className="mt-2 text-[13px] text-ink-500">{t.suggested_action}</p>}
      {error && <div className="mt-3"><Alert tone="error">{error}</Alert></div>}
      <div className="mt-3"><Violations items={viol} /></div>

      {t.status === "awaiting_approval" && (reply || desc || t.post) && (
        <div className="mt-3 space-y-2">
          {reply && <Textarea label="Draft reply (edit before approving)" rows={4} value={text ?? reply.body} onChange={(e) => setText(e.target.value)} />}
          {desc && <Textarea label="Proposed description (edit before approving)" rows={5} value={text ?? desc} maxLength={750} onChange={(e) => setText(e.target.value)} />}
          {t.post && <p className="whitespace-pre-wrap rounded-lg bg-ink-50 p-3 text-sm">{t.post.summary}</p>}
          {flagged && reply && <label className="flex items-start gap-2 text-[13px] text-amber-900"><input type="checkbox" className="mt-0.5 h-4 w-4" checked={ack} onChange={(e) => setAck(e.target.checked)} />This review needs personal handling ({reply.flags.join(", ").replace(/_/g, " ")}). I have read it and want to reply.</label>}
        </div>)}
      {t.status === "failed" && t.failure_reason && <p className="mt-2 text-sm text-red-700">{t.failure_reason}</p>}
      {t.status === "approved" && reply && <p className="mt-2 text-sm text-ink-500">Approved. Waiting to be published to Google.</p>}
      {(t.status === "scheduled" || t.status === "approved") && t.post && <p className="mt-2 text-sm text-ink-500">{t.post.scheduled_for ? `Goes out ${new Date(t.post.scheduled_for).toLocaleString("en-IN")}` : "Approved."} Track it in <Link className="text-brand-700 underline" href="/gbp/posts">Posts</Link>.</p>}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {t.status === "suggested" && AI_KINDS.has(t.kind) && <Button size="sm" icon={<Sparkles className="h-4 w-4" />} loading={busy === "draft"} onClick={() => void run("draft", () => api(`/agent/tasks/${t.id}/draft`, { method: "POST" }), "Draft ready for your approval.")}>Draft with AI</Button>}
        {t.status === "suggested" && t.kind === "profile_fix" && t.evidence.field === "description" && <Button size="sm" icon={<Sparkles className="h-4 w-4" />} loading={busy === "draft"} onClick={() => void run("draft", () => api(`/agent/tasks/${t.id}/draft`, { method: "POST" }), "Draft ready for your approval.")}>Draft with AI</Button>}
        {t.status === "suggested" && OPEN_LINK[t.kind] && !(t.kind === "profile_fix" && t.evidence.field === "description") && <LinkButton href={OPEN_LINK[t.kind]![0]} size="sm" variant="secondary" icon={<ExternalLink className="h-4 w-4" />}>{OPEN_LINK[t.kind]![1]}</LinkButton>}
        {t.status === "suggested" && t.kind === "reply_review" && t.evidence.review_id && <LinkButton href={`/gbp/reviews/${t.evidence.review_id}`} size="sm" variant="secondary">Open review</LinkButton>}

        {t.status === "awaiting_approval" && reply && isAdmin && (
          <Button size="sm" icon={<Check className="h-4 w-4" />} loading={busy === "approve"} disabled={flagged && !ack} onClick={() => void run("approve", async () => {
            if (editing && text !== reply.body) await api(`/reply-drafts/${reply.id}`, { method: "PATCH", body: { body: text } });
            await api(`/reply-drafts/${reply.id}/approve`, { method: "POST", body: { acknowledge_flags: ack } });
            await api(`/reply-drafts/${reply.id}/publish`, { method: "POST" });
          }, "Reply sent to Google.")}>Approve &amp; publish</Button>)}
        {t.status === "failed" && reply && isAdmin && <Button size="sm" loading={busy === "retry"} onClick={() => void run("retry", () => api(`/reply-drafts/${reply.id}/publish`, { method: "POST" }), "Reply sent to Google.")}>Retry publishing</Button>}
        {t.status === "awaiting_approval" && desc && isAdmin && (
          <Button size="sm" icon={<Check className="h-4 w-4" />} loading={busy === "approve"} onClick={() => void run("approve", async () => {
            if (editing && text !== desc) { const r = await api<{ violations: Violation[] }>(`/agent/tasks/${t.id}/draft`, { method: "PATCH", body: { description: text } }); setViol(r.violations); if (r.violations.length) throw new Error("Fix the highlighted text first."); }
            await api(`/agent/tasks/${t.id}/approve`, { method: "POST" });
          }, "Description updated on Google.")}>Approve &amp; publish to Google</Button>)}
        {t.status === "awaiting_approval" && t.post && <LinkButton href="/ai/approvals" size="sm">Review &amp; approve</LinkButton>}
        {t.status === "awaiting_approval" && !isAdmin && <span className="text-[13px] text-ink-500">An owner or admin has to approve this.</span>}

        {["suggested", "awaiting_approval", "failed"].includes(t.status) && <Button size="sm" variant="ghost" icon={<Clock className="h-4 w-4" />} loading={busy === "snooze"} onClick={() => void run("snooze", () => api(`/agent/tasks/${t.id}/snooze`, { method: "POST", body: { days: 1 } }), "Snoozed until tomorrow.")}>Snooze</Button>}
        {["suggested", "awaiting_approval", "failed"].includes(t.status) && <Button size="sm" variant="ghost" icon={<X className="h-4 w-4" />} loading={busy === "dismiss"} onClick={() => void run("dismiss", () => api(`/agent/tasks/${t.id}/dismiss`, { method: "POST" }), "Dismissed.")}>Dismiss</Button>}
        <span className="ml-auto text-xs text-ink-400">{t.completed_at ? `finished ${timeAgo(t.completed_at)}` : `added ${timeAgo(t.created_at)}`}</span>
      </div>
    </li>
  );
}
