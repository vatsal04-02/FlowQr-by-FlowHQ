"use client";
import { Check, RefreshCw, Sparkles } from "lucide-react";
import { useState } from "react";
import { Violations } from "@/components/agent/TaskCard";
import { GbpFrame } from "@/components/gbp/GbpFrame";
import { ProfileOptimizer } from "@/components/gbp/ProfileOptimizer";
import { InfoTab } from "@/components/gbp/tools";
import { Button } from "@/components/ui/Button";
import { Alert, PageHeader, Skeleton } from "@/components/ui/Card";
import { Textarea } from "@/components/ui/Form";
import { Panel, Status } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import type { Task, Violation } from "@/lib/agent";
import { api, ApiError, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { timeAgo } from "@/lib/format";
import { useFetch } from "@/lib/use-api";

interface State { completeness: { percent: number; missing: { key: string; label: string; needs: string }[]; fields: { key: string; label: string; weight: number; ok: boolean }[] } | null; fetched_at: string | null; error: string | null; task: Task | null }

/** A progress ring: the completeness percentage, drawn. The number is also printed in the middle for screen readers and exactness. */
function Ring({ percent }: { percent: number }) {
  const r = 34, c = 2 * Math.PI * r;
  return (
    <div role="img" aria-label={`Profile ${percent} percent complete`} className="relative h-[88px] w-[88px] shrink-0">
      <svg viewBox="0 0 80 80" className="h-full w-full -rotate-90" aria-hidden>
        <circle cx="40" cy="40" r={r} fill="none" stroke="#FFE5D1" strokeWidth="8" />
        <circle cx="40" cy="40" r={r} fill="none" stroke="rgb(var(--c-accent))" strokeWidth="8" strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - percent / 100)} style={{ transition: "stroke-dashoffset .8s cubic-bezier(.22,1,.36,1)" }} />
      </svg>
      <span aria-hidden className="num absolute inset-0 grid place-items-center text-xl font-bold text-navy">{percent}%</span>
    </div>
  );
}

function Completeness({ gid, compact = false }: { gid: string; compact?: boolean }) {
  const toast = useToast();
  const { isAdmin } = useAuth();
  const { data, error, loading, reload } = useFetch<State>(`/agent/profile/${gid}`);
  const [busy, setBusy] = useState<"refresh" | "ai" | "publish" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [viol, setViol] = useState<Violation[]>([]);
  const [text, setText] = useState<string | null>(null);
  async function run(k: "refresh" | "ai" | "publish", fn: () => Promise<unknown>, ok: string) {
    setBusy(k); setErr(null);
    try { await fn(); toast(ok); setText(null); await reload(); }
    catch (e) { if (e instanceof ApiError && e.code === "safety_violation") setViol(((e.detail as { violations?: Violation[] }).violations) ?? []); setErr(errorMessage(e)); await reload(); } finally { setBusy(null); }
  }
  if (loading && !data) return <Skeleton className="h-32" />;
  if (error || !data) return <Alert tone="error">{error}</Alert>;
  const c = data.completeness;
  const t = data.task;
  const draft = t?.status === "awaiting_approval" ? t.draft?.description : undefined;
  return (
    <Panel title="Description" meta={data.fetched_at ? `as Google reported ${timeAgo(data.fetched_at)}` : "Google hasn't been checked yet"}
      action={isAdmin ? <Button size="sm" variant="secondary" icon={<RefreshCw className="h-4 w-4" />} loading={busy === "refresh"} onClick={() => void run("refresh", () => api("/agent/google/refresh", { method: "POST" }), "Refreshed from Google.")}>Check Google now</Button> : undefined}>
      {data.error && <div className="mb-3"><Alert tone="warning" title="Google didn't answer everything">{data.error}</Alert></div>}
      {!compact && (<>
      {!c ? <p className="text-sm text-ink-700">Press &ldquo;Check Google now&rdquo; to see how complete your profile is.</p> : (
        <div className="flex flex-wrap items-center gap-x-6 gap-y-4">
          <Ring percent={c.percent} />
          <div className="min-w-0 flex-1 basis-64">
            <p className="text-sm font-semibold text-navy">{c.missing.length ? `${c.missing.length} ${c.missing.length === 1 ? "thing" : "things"} to add` : "Your profile is complete"}</p>
            <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Profile checklist">
              {c.fields.map((f) => (
                <li key={f.key} className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[13px] font-medium ${f.ok ? "bg-green-50 text-green-900" : "bg-brand-50 text-brand-800"}`}>
                  {f.ok ? <Check className="h-3.5 w-3.5" strokeWidth={2.5} aria-hidden /> : <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-brand-600" />}{f.label}<span className="sr-only">{f.ok ? " (done)" : " (missing)"}</span></li>))}
            </ul>
            {c.missing.length > 0 && <p className="mt-2 text-[13px] text-ink-500">{c.missing.map((m) => `${m.label}: ${m.needs}`).join(" · ")}</p>}
          </div>
        </div>)}
      </>)}
      <div className={compact ? "" : "mt-4 border-t border-ink-100 pt-4"}>
        <div className="flex flex-wrap items-center gap-2"><Button size="sm" icon={<Sparkles className="h-4 w-4" />} loading={busy === "ai"} disabled={!c || !!draft} onClick={() => void run("ai", () => api(`/agent/profile/${gid}/suggest-description`, { method: "POST" }), "Draft ready below. Review it before anything goes live.")}>Suggest a description with AI</Button>
          <span className="text-[13px] text-ink-500">Written from your Knowledge Base. It goes live only when you approve it.</span></div>
        {err && <div className="mt-3"><Alert tone="error">{err}</Alert></div>}
        {draft && t && (
          <div className="mt-3 space-y-2"><Violations items={viol} /><Textarea label="Proposed description (edit before approving)" rows={5} maxLength={750} value={text ?? draft} onChange={(e) => setText(e.target.value)} />
            {isAdmin ? <Button size="sm" loading={busy === "publish"} onClick={() => void run("publish", async () => {
              if (text !== null && text !== draft) { const r = await api<{ violations: Violation[] }>(`/agent/tasks/${t.id}/draft`, { method: "PATCH", body: { description: text } }); setViol(r.violations); if (r.violations.length) throw new Error("Fix the highlighted text first."); }
              await api(`/agent/tasks/${t.id}/approve`, { method: "POST" });
            }, "Description updated on Google.")}>Approve &amp; publish to Google</Button> : <p className="text-[13px] text-ink-500">An owner or admin has to approve this.</p>}</div>)}
      </div>
    </Panel>
  );
}

export default function ProfilePage() {
  return (
    <>
      <PageHeader title="Business info" subtitle="Description and category. Changes you save go straight to Google; AI suggestions wait for your approval." />
      <GbpFrame>{(gid) => <div className="space-y-6"><ProfileOptimizer key={`o-${gid}`} gid={gid} /><div id="description" className="scroll-mt-6"><Completeness key={`c-${gid}`} gid={gid} compact /></div><InfoTab key={gid} gid={gid} part="info" /></div>}</GbpFrame>
    </>
  );
}
