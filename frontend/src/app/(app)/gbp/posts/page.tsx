"use client";
import { Check, Pencil, RotateCcw, PenLine, X } from "lucide-react";
import { useState } from "react";
import { Violations } from "@/components/agent/TaskCard";
import { GbpFrame } from "@/components/gbp/GbpFrame";
import { PostCalendar } from "@/components/gbp/PostCalendar";
import { PostPreview } from "@/components/gbp/PostPreview";
import { Button } from "@/components/ui/Button";
import { Alert, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { Input, Select, Textarea } from "@/components/ui/Form";
import { Panel, Segmented, Status } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import { POST_LABEL, type PostItem, type Violation } from "@/lib/agent";
import { api, ApiError, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-api";
import { useGbp } from "@/lib/use-gbp";

const CTAS = [["", "No button"], ["LEARN_MORE", "Learn more"], ["BOOK", "Book"], ["ORDER", "Order online"], ["SHOP", "Shop"], ["SIGN_UP", "Sign up"], ["CALL", "Call now"]] as const;
/** colour per post state: meaning colours only (amber waits for you, green is live on Google, red failed) */
const DOT: Record<string, string> = { draft: "bg-ink-300", awaiting_approval: "bg-warn", scheduled: "bg-ink-solid", published: "bg-pos", failed: "bg-neg", all: "bg-ink-300" };
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
    <li className="min-w-0 rounded-xl border border-ink-100 bg-surface p-4" aria-label={`Post: ${p.summary.slice(0, 40)}`}>
      <div className="flex flex-wrap items-center justify-between gap-2"><Status tone={st.tone}>{st.label}</Status><span data-words="skip" className="min-w-0 truncate text-xs text-ink-500">{p.generated_by_ai ? "Draft by FlowQR · " : ""}{p.location_title}</span></div>
      {edit === null ? <div className="mt-2"><PostPreview business={p.location_title ?? "Your business"} text={p.summary} photo={p.photo_url} cta={p.cta_type} when={p.published_at ? when(p.published_at) : p.scheduled_for ? when(p.scheduled_for) : "Not published yet"}
        topic={p.topic_type ?? "STANDARD"} title={p.event_title} start={p.event_start} end={p.event_end} coupon={p.offer_coupon} terms={p.offer_terms} />
        {p.visual_hint && <p className="mt-2 rounded-inner bg-surface-2 px-3 py-2 text-[13px]"><b className="font-semibold">Photo idea:</b> {p.visual_hint}</p>}
        {!!p.topic_problems?.length && <p className="mt-2 rounded-inner bg-warn-tint px-3 py-2 text-[13px] text-warn">{p.topic_problems.join(" ")}</p>}</div> : <div className="mt-2"><Textarea label="Post text" rows={4} maxLength={1500} value={edit} onChange={(e) => setEdit(e.target.value)} /></div>}
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
  const [kind, setKind] = useState<"STANDARD" | "OFFER" | "EVENT">("STANDARD");
  const [title, setTitle] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [coupon, setCoupon] = useState("");
  const [terms, setTerms] = useState("");
  const [busy, setBusy] = useState<"save" | "ai" | "ideas" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [ideas, setIdeas] = useState<{ type: string; title: string; text: string; image: string | null; why: string | null }[] | null>(null);
  async function getIdeas() {
    setBusy("ideas"); setErr(null);
    try { const r = await api<{ ideas: NonNullable<typeof ideas> }>("/posts/ideas", { method: "POST", body: { google_location_id: gid, count: 3 } }); setIdeas(r.ideas); }
    catch (e) { setErr(errorMessage(e)); } finally { setBusy(null); }
  }
  async function go(which: "save" | "ai") {
    setBusy(which); setErr(null);
    try {
      const ev = kind !== "STANDARD" ? { event_title: title || null, event_start: start || null, event_end: end || null } : {};
      if (which === "ai") { await api("/posts/ai-draft", { method: "POST", body: { google_location_id: gid, topic: topic || null, kind: kind === "OFFER" ? "offer" : kind === "EVENT" ? "event" : "update", ...ev } }); toast("Draft ready: review and approve it below."); }
      else {
        await api("/posts", { method: "POST", body: { google_location_id: gid, summary: text, cta_type: cta || null, cta_url: url || null, photo_url: photo || null, topic_type: kind, ...ev,
          ...(kind === "OFFER" ? { offer_coupon: coupon || null, offer_terms: terms || null } : {}) } });
        setText(""); setCta(""); setUrl(""); setPhoto(""); setTitle(""); setStart(""); setEnd(""); setCoupon(""); setTerms(""); toast("Draft saved.");
      }
      onCreated();
    } catch (e) { setErr(e instanceof ApiError && e.status === 422 ? errorMessage(e) : errorMessage(e)); } finally { setBusy(null); }
  }
  const gbp = useGbp();
  const business = gbp.selected.find((l) => l.id === gid)?.title ?? "Your business";
  return (
    <section aria-labelledby="new-post-h" className="panel p-5 sm:p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2"><h2 id="new-post-h" className="text-[15px] font-semibold">New post</h2><span className="text-[13px] text-muted">Goes live only after approval</span></div>
      <div className="mt-4 grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0 space-y-3">
          {err && <Alert tone="error">{err}</Alert>}
          <div role="radiogroup" aria-label="Post type" className="inline-flex rounded-full bg-surface-2 p-1">
            {([["STANDARD", "Update"], ["OFFER", "Offer"], ["EVENT", "Event"]] as const).map(([v, l]) => (
              <button key={v} type="button" role="radio" aria-checked={kind === v} onClick={() => setKind(v)}
                className={`min-h-9 rounded-full px-4 text-sm font-medium ${kind === v ? "bg-surface text-ink shadow-pill" : "text-muted"}`}>{l}</button>))}
          </div>
          {kind !== "STANDARD" && (
            <div className="grid gap-3 sm:grid-cols-3">
              <Input label={kind === "OFFER" ? "Offer title" : "Event title"} maxLength={58} value={title} onChange={(e) => setTitle(e.target.value)} wrapperClassName="sm:col-span-3" />
              <Input label="Starts" type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} />
              <Input label="Ends" type="datetime-local" value={end} onChange={(e) => setEnd(e.target.value)} />
              {kind === "OFFER" && <Input label="Coupon code (optional)" maxLength={58} value={coupon} onChange={(e) => setCoupon(e.target.value)} />}
              {kind === "OFFER" && <Input label="Terms (optional)" maxLength={300} value={terms} onChange={(e) => setTerms(e.target.value)} wrapperClassName="sm:col-span-3" />}
              <p className="text-[13px] text-muted sm:col-span-3">{kind === "OFFER" ? "Only real offers. Google needs a title and the dates the offer runs. The AI writes offers only from verified offers in your Business brain." : "Google needs a title, start and end."}</p>
            </div>
          )}
          <Textarea label={kind === "STANDARD" ? "What's new?" : "Details"} rows={5} maxLength={1500} value={text} onChange={(e) => setText(e.target.value)} hint={`${text.length}/1500`} />
          <Input label="Photo link (optional)" inputMode="url" placeholder="https://…/photo.jpg" value={photo} onChange={(e) => setPhoto(e.target.value)} />
          <div className="grid gap-3 sm:grid-cols-2"><Select label="Button (optional)" value={cta} onChange={(e) => setCta(e.target.value)}>{CTAS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select>
            {cta && cta !== "CALL" && <Input label="Button link" inputMode="url" placeholder="https://…" value={url} onChange={(e) => setUrl(e.target.value)} />}</div>
          <div className="flex flex-wrap items-end gap-2 border-t border-ink-100 pt-3">
            <Button loading={busy === "save"} disabled={text.trim().length < 10} onClick={() => void go("save")}>Save draft</Button>
            <span className="pb-3 text-sm text-ink-500">or</span>
            <div className="min-w-0 basis-full sm:basis-auto sm:min-w-[180px] sm:flex-1"><Input label="Draft topic (optional)" placeholder="e.g. Winter back care tips" value={topic} onChange={(e) => setTopic(e.target.value)} /></div>
            <Button variant="secondary" icon={<PenLine className="h-4 w-4" />} loading={busy === "ai"} onClick={() => void go("ai")}>Draft a post</Button>
            <Button variant="ghost" loading={busy === "ideas"} onClick={() => void getIdeas()}>Suggest 3 ideas</Button></div>
          {ideas && (
            <div className="space-y-2 border-t border-ink-100 pt-3" aria-label="Post ideas">
              <p className="text-[13px] font-semibold text-ink-700">Three different ideas. Pick one, edit it, then save it as a draft.</p>
              <ul className="grid gap-2 lg:grid-cols-3">
                {ideas.map((i) => (
                  <li key={i.title + i.text.slice(0, 12)} className="flex flex-col rounded-xl bg-white p-3 ring-1 ring-ink-100">
                    <span className="text-[12px] font-medium text-muted">{i.type.replace("_", " ").toLowerCase().replace(/^./, (c) => c.toUpperCase())}</span>
                    <p className="mt-0.5 text-sm font-bold text-navy">{i.title}</p>
                    <p className="mt-1 flex-1 text-[13px] leading-snug text-ink-700">{i.text}</p>
                    {i.image && <p className="mt-2 text-xs text-ink-500"><span className="font-semibold">Photo to take:</span> {i.image}</p>}
                    {i.why && <p className="mt-1 text-xs text-ink-500"><span className="font-semibold">Why:</span> {i.why}</p>}
                    <Button size="sm" variant="secondary" className="mt-2" onClick={() => { setText(i.text); setKind("STANDARD"); }}>Use this text</Button>
                  </li>))}
              </ul>
            </div>)}
        </div>
        <div className="min-w-0 lg:sticky lg:top-4 lg:self-start"><p className="mb-2 text-[13px] font-semibold text-ink-700">Preview</p><PostPreview business={business} text={text} photo={photo} cta={cta || null} topic={kind} title={title} start={start || null} end={end || null} coupon={coupon} terms={terms} /></div>
      </div>
    </section>
  );
}

function Body({ gid }: { gid: string }) {
  const [tab, setTab] = useState<"queue" | "calendar">("queue");
  const [filter, setFilter] = useState<"all" | "draft" | "awaiting_approval" | "scheduled" | "published" | "failed">("all");
  const { data, error, loading, reload } = useFetch<{ posts: PostItem[]; timezone: string }>("/posts", { google_location_id: gid });
  const live = (data?.posts ?? []).filter((p) => p.status !== "canceled");
  const group = (p: PostItem) => (p.status === "approved" || p.status === "publishing" ? "scheduled" : p.status);
  const count = (k: string) => live.filter((p) => group(p) === k).length;
  const shown = live.filter((p) => filter === "all" || group(p) === filter);
  const STEPS: [typeof filter, string][] = [["draft", "Drafts"], ["awaiting_approval", "Waiting"], ["scheduled", "Scheduled"], ["published", "Published"]];
  return (
    <div className="space-y-5">
      <Compose gid={gid} onCreated={() => void reload()} />
      <div className="flex flex-wrap items-center justify-between gap-2"><Segmented label="View" value={tab} onChange={setTab} options={[["queue", "Posts"], ["calendar", "Calendar"]] as const} />
      </div>
      {tab === "queue" && (() => {
        const steps: [typeof filter, string][] = [...STEPS, ...(count("failed") > 0 ? [["failed", "Didn't publish"] as [typeof filter, string]] : [])];
        return (
          <div className="space-y-2">
            {/* one bar for where every post is; dashed when there are none yet */}
            {live.length ? (
              <div role="img" aria-label={steps.map(([k, l]) => `${l} ${count(k)}`).join(", ")} className="flex h-2.5 gap-[2px] overflow-hidden rounded-full">
                {steps.filter(([k]) => count(k) > 0).map(([k]) => <span key={k} className={`fq-bar-x h-full ${DOT[k]}`} style={{ flexGrow: count(k) }} />)}
              </div>
            ) : <div aria-hidden className="h-2.5 rounded-full border border-dashed border-ink-300" />}
            <ol aria-label="Where your posts are" className="grid grid-cols-2 gap-2 sm:grid-cols-5">
              {steps.map(([k, l]) => (
                <li key={k} className="min-w-0"><button type="button" aria-pressed={filter === k} onClick={() => setFilter(filter === k ? "all" : k)}
                  className={`flex min-h-11 w-full items-center gap-2 rounded-[12px] px-3 text-left text-[13px] font-medium transition-colors ${filter === k ? "bg-ink-solid text-ink-on" : "bg-surface-2 text-ink hover:bg-surface-3"}`}>
                  <span aria-hidden className={`h-2 w-2 shrink-0 rounded-full ${DOT[k]}`} /><span className="min-w-0 flex-1 truncate">{l}</span><span className="num font-semibold">{count(k)}</span></button></li>))}
            </ol>
          </div>
        );
      })()}
      {tab === "calendar" ? <PostCalendar /> : (
        error ? <Alert tone="error">{error}</Alert> : loading && !data ? <Skeleton className="h-40" /> : shown.length === 0 ? <EmptyState title="No posts here" />
          : <ul className="space-y-3">{shown.map((p) => <PostCard key={p.id} p={p} onChange={() => void reload()} />)}</ul>)}
    </div>
  );
}

export default function PostsPage() {
  return (
    <>
      <PageHeader title="Posts" subtitle="Updates on your Google profile." />
      <GbpFrame>{(gid) => <Body key={gid} gid={gid} />}</GbpFrame>
    </>
  );
}
