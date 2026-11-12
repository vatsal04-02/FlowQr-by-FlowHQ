"use client";
import { Check, Pencil, RotateCcw, Sparkles, X } from "lucide-react";
import { useState } from "react";
import { Violations } from "@/components/agent/TaskCard";
import { GbpFrame } from "@/components/gbp/GbpFrame";
import { PostCalendar } from "@/components/gbp/PostCalendar";
import { Button } from "@/components/ui/Button";
import { Alert, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { Input, Select, Textarea } from "@/components/ui/Form";
import { Panel, Segmented, Status } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import { POST_LABEL, type PostItem, type Violation } from "@/lib/agent";
import { api, ApiError, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-api";

const CTAS = [["", "No button"], ["LEARN_MORE", "Learn more"], ["BOOK", "Book"], ["ORDER", "Order online"], ["SHOP", "Shop"], ["SIGN_UP", "Sign up"], ["CALL", "Call now"]] as const;
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "");

function PostCard({ p, onChange }: { p: PostItem; onChange: () => void }) {
  const toast = useToast();
  const { isAdmin } = useAuth();
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [viol, setViol] = useState<Violation[]>([]);
  const [edit, setEdit] = useState<string | null>(null);
  const [at, setAt] = useState("");
  async function go(key: string, fn: () => Promise<unknown>, ok?: string) {
    setBusy(key); setErr(null);
    try { const r = (await fn()) as { status?: string; failure_reason?: string | null } | undefined; if (r && "status" in r && key === "approve" && r.status !== "published" && r.status !== "scheduled") setErr(r.failure_reason ?? "Google did not accept it."); else if (ok) toast(ok); onChange(); }
    catch (e) { if (e instanceof ApiError && e.code === "safety_violation") setViol(((e.detail as { violations?: Violation[] }).violations) ?? []); setErr(errorMessage(e)); onChange(); }
    finally { setBusy(null); }
  }
  const st = POST_LABEL[p.status];
  const editable = ["draft", "awaiting_approval", "failed"].includes(p.status);
  return (
    <li className="rounded-xl border border-ink-100 bg-white p-4" aria-label={`Post: ${p.summary.slice(0, 40)}`}>
      <div className="flex flex-wrap items-center justify-between gap-2"><Status tone={st.tone}>{st.label}</Status><span className="text-xs text-ink-500">{p.generated_by_ai ? "AI draft · " : ""}{p.location_title}</span></div>
      {edit === null ? <p className="mt-2 whitespace-pre-wrap text-sm">{p.summary}</p> : <div className="mt-2"><Textarea label="Post text" rows={4} maxLength={1500} value={edit} onChange={(e) => setEdit(e.target.value)} /></div>}
      {p.cta_type && <p className="mt-1 text-[13px] text-ink-500">Button: {p.cta_type.replace("_", " ").toLowerCase()}{p.cta_url ? ` → ${p.cta_url}` : ""}</p>}
      {p.status === "scheduled" && <p className="mt-1 text-[13px] text-ink-700">Goes out {when(p.scheduled_for)}{p.attempts > 0 ? ` · attempt ${p.attempts} failed, next try ${when(p.next_attempt_at)}` : ""}</p>}
      {p.status === "published" && <p className="mt-1 text-[13px] text-green-800">Google confirmed it {when(p.published_at)}.</p>}
      {p.failure_reason && p.status !== "published" && <p className="mt-1 text-[13px] text-red-700">{p.failure_reason}</p>}
      <div className="mt-2"><Violations items={[...p.violations, ...viol]} /></div>
      {err && <div className="mt-2"><Alert tone="error">{err}</Alert></div>}
      <div className="mt-3 flex flex-wrap items-end gap-2">
        {editable && edit === null && <Button size="sm" variant="ghost" icon={<Pencil className="h-4 w-4" />} onClick={() => setEdit(p.summary)}>Edit</Button>}
        {edit !== null && <><Button size="sm" loading={busy === "save"} onClick={() => void go("save", async () => { await api(`/posts/${p.id}`, { method: "PATCH", body: { summary: edit } }); setEdit(null); setViol([]); }, "Saved. Submit it for approval again.")}>Save</Button><Button size="sm" variant="ghost" onClick={() => setEdit(null)}>Cancel</Button></>}
        {p.status === "draft" && edit === null && <Button size="sm" loading={busy === "submit"} onClick={() => void go("submit", () => api(`/posts/${p.id}/submit`, { method: "POST" }), "Submitted for approval.")}>Submit for approval</Button>}
        {p.status === "awaiting_approval" && edit === null && isAdmin && <>
          <Button size="sm" icon={<Check className="h-4 w-4" />} loading={busy === "approve"} onClick={() => void go("approve", () => api(`/posts/${p.id}/approve`, { method: "POST", body: {} }), "Published on Google.")}>Approve &amp; publish now</Button>
          <div className="w-52"><Input label="Or schedule for" type="datetime-local" value={at} onChange={(e) => setAt(e.target.value)} /></div>
          <Button size="sm" variant="secondary" disabled={!at} loading={busy === "approve"} onClick={() => void go("approve", () => api(`/posts/${p.id}/approve`, { method: "POST", body: { scheduled_for: at } }), "Scheduled.")}>Approve &amp; schedule</Button>
          <Button size="sm" variant="ghost" onClick={() => void go("reject", () => api(`/posts/${p.id}/reject`, { method: "POST" }), "Moved back to draft.")}>Back to draft</Button></>}
        {p.status === "awaiting_approval" && !isAdmin && <span className="text-[13px] text-ink-500">An owner or admin has to approve this.</span>}
        {p.status === "failed" && isAdmin && <Button size="sm" icon={<RotateCcw className="h-4 w-4" />} loading={busy === "retry"} onClick={() => void go("retry", () => api(`/posts/${p.id}/retry`, { method: "POST" }), "Published on Google.")}>Retry</Button>}
        {["draft", "awaiting_approval", "approved", "scheduled", "failed"].includes(p.status) && isAdmin && <Button size="sm" variant="ghost" icon={<X className="h-4 w-4" />} loading={busy === "cancel"} onClick={() => void go("cancel", () => api(`/posts/${p.id}/cancel`, { method: "POST" }), "Canceled.")}>Cancel post</Button>}
      </div>
    </li>
  );
}

function Compose({ gid, onCreated }: { gid: string; onCreated: () => void }) {
  const toast = useToast();
  const [text, setText] = useState("");
  const [cta, setCta] = useState("");
  const [url, setUrl] = useState("");
  const [photo, setPhoto] = useState("");
  const [topic, setTopic] = useState("");
  const [busy, setBusy] = useState<"save" | "ai" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  async function go(kind: "save" | "ai") {
    setBusy(kind); setErr(null);
    try {
      if (kind === "ai") { await api("/posts/ai-draft", { method: "POST", body: { google_location_id: gid, topic: topic || null } }); toast("AI draft ready: review and approve it below."); }
      else { await api("/posts", { method: "POST", body: { google_location_id: gid, summary: text, cta_type: cta || null, cta_url: url || null, photo_url: photo || null } }); setText(""); setCta(""); setUrl(""); setPhoto(""); toast("Draft saved."); }
      onCreated();
    } catch (e) { setErr(e instanceof ApiError && e.status === 422 ? errorMessage(e) : errorMessage(e)); } finally { setBusy(null); }
  }
  return (
    <Panel title="New post" meta="nothing goes live until an owner or admin approves it">
      <div className="space-y-3">
        {err && <Alert tone="error">{err}</Alert>}
        <Textarea label="What's new?" rows={4} maxLength={1500} value={text} onChange={(e) => setText(e.target.value)} />
        <div className="grid gap-3 sm:grid-cols-2"><Select label="Button (optional)" value={cta} onChange={(e) => setCta(e.target.value)}>{CTAS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select>
          {cta && cta !== "CALL" && <Input label="Button link" inputMode="url" placeholder="https://…" value={url} onChange={(e) => setUrl(e.target.value)} />}</div>
        <Input label="Photo link (optional)" inputMode="url" placeholder="https://…/photo.jpg" value={photo} onChange={(e) => setPhoto(e.target.value)} />
        <div className="flex flex-wrap items-end gap-2"><Button loading={busy === "save"} disabled={text.trim().length < 10} onClick={() => void go("save")}>Save draft</Button>
          <span className="text-sm text-ink-500">or</span>
          <div className="min-w-[200px] flex-1"><Input label="Write with AI: topic (optional)" placeholder="e.g. Winter back care tips" value={topic} onChange={(e) => setTopic(e.target.value)} /></div>
          <Button variant="secondary" icon={<Sparkles className="h-4 w-4" />} loading={busy === "ai"} onClick={() => void go("ai")}>Write with AI</Button></div>
      </div>
    </Panel>
  );
}

function Body({ gid }: { gid: string }) {
  const [tab, setTab] = useState<"queue" | "calendar">("queue");
  const [filter, setFilter] = useState<"open" | "published" | "all">("open");
  const { data, error, loading, reload } = useFetch<{ posts: PostItem[]; timezone: string }>("/posts", { google_location_id: gid });
  const shown = (data?.posts ?? []).filter((p) => filter === "all" || (filter === "published" ? p.status === "published" : !["published", "canceled"].includes(p.status)));
  return (
    <div className="space-y-5">
      <Compose gid={gid} onCreated={() => void reload()} />
      <div className="flex flex-wrap items-center justify-between gap-2"><Segmented label="View" value={tab} onChange={setTab} options={[["queue", "Posts"], ["calendar", "Calendar"]] as const} />
        {tab === "queue" && <Segmented label="Show" value={filter} onChange={setFilter} options={[["open", "In progress"], ["published", "Published"], ["all", "All"]] as const} />}</div>
      {tab === "calendar" ? <PostCalendar /> : (
        error ? <Alert tone="error">{error}</Alert> : loading && !data ? <Skeleton className="h-40" /> : shown.length === 0 ? <EmptyState title="No posts here">Write one above, or let the agent suggest one in Today&rsquo;s plan.</EmptyState>
          : <ul className="space-y-3">{shown.map((p) => <PostCard key={p.id} p={p} onChange={() => void reload()} />)}</ul>)}
    </div>
  );
}

export default function PostsPage() {
  return (
    <>
      <PageHeader eyebrow="Google Business" title="Posts" subtitle="Draft, approve and schedule updates for your Google profile. FlowQR holds approved posts and publishes them at the time you choose; a post is marked published only after Google confirms it." />
      <GbpFrame>{(gid) => <Body key={gid} gid={gid} />}</GbpFrame>
    </>
  );
}
