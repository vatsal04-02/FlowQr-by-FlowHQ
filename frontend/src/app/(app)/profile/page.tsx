"use client";
import { RefreshCw, Sparkles } from "lucide-react";
import { useState } from "react";
import { Violations } from "@/components/agent/TaskCard";
import { GbpFrame } from "@/components/gbp/GbpFrame";
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

function Completeness({ gid }: { gid: string }) {
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
    <Panel title="Profile completeness" meta={data.fetched_at ? `as Google reported ${timeAgo(data.fetched_at)}` : "Google hasn't been checked yet"}
      action={isAdmin ? <Button size="sm" variant="secondary" icon={<RefreshCw className="h-4 w-4" />} loading={busy === "refresh"} onClick={() => void run("refresh", () => api("/agent/google/refresh", { method: "POST" }), "Refreshed from Google.")}>Check Google now</Button> : undefined}>
      {data.error && <div className="mb-3"><Alert tone="warning" title="Google didn't answer everything">{data.error}</Alert></div>}
      {!c ? <p className="text-sm text-ink-500">No profile data from Google yet, so no score is shown. Press &ldquo;Check Google now&rdquo;.</p> : (
        <div className="space-y-3">
          <div className="flex items-center gap-3"><p className="num text-3xl font-bold">{c.percent}%</p><p className="text-sm text-ink-500">{c.missing.length ? `Missing: ${c.missing.map((m) => `${m.label.toLowerCase()} (${m.needs})`).join(", ")}.` : "Every field we check is filled in."}</p></div>
          <ul className="flex flex-wrap gap-2 text-[13px]">{c.fields.map((f) => <li key={f.key}><Status tone={f.ok ? "ok" : "warn"}>{f.label}</Status></li>)}</ul>
        </div>)}
      <div className="mt-4 border-t border-ink-100 pt-4">
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
      <PageHeader eyebrow="Google Business" title="Profile manager" subtitle="Your live Google profile. Edits you make below go straight to Google; AI suggestions are only ever proposals until you approve them." />
      <GbpFrame>{(gid) => <div className="space-y-5"><Completeness key={`c-${gid}`} gid={gid} /><InfoTab key={gid} gid={gid} /></div>}</GbpFrame>
    </>
  );
}
