"use client";
import { Check, ImageIcon, Pencil, RefreshCw, RotateCcw, X } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Violations } from "@/components/agent/TaskCard";
import { Library } from "@/components/gbp/StudioParts";
import { PostPreview } from "@/components/gbp/PostPreview";
import { Button } from "@/components/ui/Button";
import { Alert, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { Input, Select, Textarea } from "@/components/ui/Form";
import { Status } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import type { Violation } from "@/lib/agent";
import { api, ApiError, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtWhen, STUDIO_STATUS, toLocalInput, type Campaign, type StudioPost } from "@/lib/marketing";
import { useFetch } from "@/lib/use-api";

const CTAS = [["", "No button"], ["CALL", "Call now"], ["LEARN_MORE", "Learn more"], ["BOOK", "Book"], ["ORDER", "Order online"], ["SHOP", "Shop"], ["SIGN_UP", "Sign up"]] as const;

function PostCard({ p, tz, onChange, business }: { p: StudioPost; tz: string; onChange: () => void; business: string }) {
  const toast = useToast();
  const { isAdmin } = useAuth();
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [viol, setViol] = useState<Violation[]>([]);
  const [edit, setEdit] = useState<{ text: string; cta: string; url: string } | null>(null);
  const [pick, setPick] = useState(false);
  const [at, setAt] = useState(toLocalInput(p.suggested_for, tz));
  const st = STUDIO_STATUS[p.status];
  const editable = ["draft", "awaiting_approval", "failed"].includes(p.status);
  async function go(key: string, fn: () => Promise<unknown>, ok?: string) {
    setBusy(key); setErr(null);
    try {
      const r = (await fn()) as { status?: string; failure_reason?: string | null } | undefined;
      if (key.startsWith("approve") && r?.status && !["published", "scheduled"].includes(r.status)) setErr(r.failure_reason ?? "Google did not accept it.");
      else if (ok) toast(ok);
      onChange();
    } catch (e) {
      if (e instanceof ApiError && e.code === "safety_violation") setViol(((e.detail as { violations?: Violation[] }).violations) ?? []);
      setErr(errorMessage(e)); onChange();
    } finally { setBusy(null); }
  }
  const saveEdit = () => go("save", async () => {
    if (!edit) return;
    await api(`/posts/${p.id}`, { method: "PATCH", body: { summary: edit.text, cta_type: edit.cta || null, ...(edit.cta && edit.cta !== "CALL" ? { cta_url: edit.url } : {}) } });
    setEdit(null); setViol([]);
  }, "Saved. Review it again, then approve.");
  return (
    <li className="min-w-0 rounded-xl border border-ink-100 bg-surface p-4" aria-label={`Post: ${p.summary.slice(0, 40)}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Status tone={st.tone}>{st.label}</Status>
        <span className="text-xs text-ink-500">{p.topic_type === "OFFER" ? "Offer" : p.topic_type === "EVENT" ? "Event" : "What's new"} · {p.status === "published" ? `published ${fmtWhen(p.published_at, tz)}` : p.scheduled_for ? `goes out ${fmtWhen(p.scheduled_for, tz)}` : `suggested ${fmtWhen(p.suggested_for, tz)}`}</span>
      </div>
      <div className="mt-2 grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0">
          {edit ? (
            <div className="space-y-2"><Textarea label="Post text" rows={6} maxLength={1500} value={edit.text} onChange={(e) => setEdit({ ...edit, text: e.target.value })} hint={`${edit.text.length}/1500`} />
              <div className="grid gap-2 sm:grid-cols-2"><Select label="Button" value={edit.cta} onChange={(e) => setEdit({ ...edit, cta: e.target.value })}>{CTAS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select>
                {edit.cta && edit.cta !== "CALL" && <Input label="Button link" inputMode="url" placeholder="https://…" value={edit.url} onChange={(e) => setEdit({ ...edit, url: e.target.value })} />}</div></div>
          ) : (
            <>
              <p className="whitespace-pre-line text-[14px] leading-relaxed text-ink-800">{p.summary}</p>
              {p.keywords.length > 0 && <p className="mt-2 text-[12px] text-muted">Local keywords used: {p.keywords.join(", ")}</p>}
              {p.visual_hint && !p.photo_url && <p className="mt-2 rounded-inner bg-surface-2 px-3 py-2 text-[13px]"><b className="font-semibold">Photo idea:</b> {p.visual_hint}</p>}
              {!!p.topic_problems?.length && <p className="mt-2 rounded-inner bg-warn-tint px-3 py-2 text-[13px] text-warn">{p.topic_problems.join(" ")}</p>}
            </>)}
          {p.failure_reason && p.status !== "published" && <p className="mt-2 text-[13px] text-neg">{p.failure_reason}</p>}
          {p.status === "published" && <p className="mt-2 text-[13px] text-pos">Google confirmed this post{p.google_post_name ? "" : ""}.</p>}
          {p.history && p.history.length > 0 && <ul className="mt-2 space-y-0.5 text-[12px] text-muted">{p.history.map((h, i) => <li key={i}>{fmtWhen(h.at, tz)} · {h.status.replace("_", " ")}{h.verified ? " · read back from Google" : ""}{h.error ? ` · ${h.error}` : ""}</li>)}</ul>}
          <div className="mt-2"><Violations items={[...p.violations, ...viol]} /></div>
          {err && <div className="mt-2"><Alert tone="error">{err}</Alert></div>}
        </div>
        <div className="min-w-0"><PostPreview business={business} text={edit?.text ?? p.summary} photo={p.photo_url} cta={edit ? edit.cta || null : p.cta_type} when={p.published_at ? fmtWhen(p.published_at, tz) : "Not published yet"}
          topic={p.topic_type ?? "STANDARD"} title={p.event_title} start={p.event_start} end={p.event_end} coupon={p.offer_coupon} terms={p.offer_terms} /></div>
      </div>
      {pick && editable && (
        <div className="mt-3 rounded-xl bg-surface-2 p-3"><p className="mb-2 text-[13px] font-semibold">Choose a photo for this post</p>
          <Library kind="image" compact picked={p.asset_id ? [p.asset_id] : []} onPick={(id) => { setPick(false); void go("photo", () => api(`/marketing/posts/${p.id}/asset`, { method: "PUT", body: { asset_id: id } }), "Photo attached."); }} />
          <Button size="sm" variant="ghost" className="mt-2" onClick={() => setPick(false)}>Close</Button></div>)}
      <div className="mt-3 flex flex-wrap items-end gap-2">
        {editable && !edit && <Button size="sm" variant="ghost" icon={<Pencil className="h-4 w-4" />} onClick={() => setEdit({ text: p.summary, cta: p.cta_type ?? "", url: p.cta_url ?? "" })}>Edit</Button>}
        {edit && <><Button size="sm" loading={busy === "save"} disabled={edit.text.trim().length < 10} onClick={() => void saveEdit()}>Save</Button><Button size="sm" variant="ghost" onClick={() => setEdit(null)}>Cancel</Button></>}
        {editable && !edit && <Button size="sm" variant="ghost" icon={<RefreshCw className="h-4 w-4" />} loading={busy === "regen"} onClick={() => void go("regen", () => api(`/marketing/posts/${p.id}/regenerate`, { method: "POST" }), "Rewritten. Please read it again.")}>Regenerate</Button>}
        {editable && !edit && <Button size="sm" variant="ghost" icon={<ImageIcon className="h-4 w-4" />} onClick={() => setPick(!pick)}>{p.photo_url ? "Change photo" : "Add photo"}</Button>}
        {editable && p.photo_url && !edit && <Button size="sm" variant="ghost" onClick={() => void go("photo", () => api(`/marketing/posts/${p.id}/asset`, { method: "PUT", body: { asset_id: null } }), "Photo removed.")}>Remove photo</Button>}
        {p.status === "draft" && !edit && <Button size="sm" loading={busy === "submit"} onClick={() => void go("submit", () => api(`/posts/${p.id}/submit`, { method: "POST" }), "Ready to approve.")}>Mark ready to approve</Button>}
        {p.status === "awaiting_approval" && !edit && isAdmin && (
          <>
            <Button size="sm" icon={<Check className="h-4 w-4" />} loading={busy === "approve-now"} onClick={() => void go("approve-now", () => api(`/posts/${p.id}/approve`, { method: "POST", body: {} }), "Published on Google.")}>Approve &amp; publish now</Button>
            <div className="w-52"><Input label="Or schedule for" type="datetime-local" value={at} onChange={(e) => setAt(e.target.value)} /></div>
            <Button size="sm" variant="secondary" disabled={!at} loading={busy === "approve-at"} onClick={() => void go("approve-at", () => api(`/posts/${p.id}/approve`, { method: "POST", body: { scheduled_for: at } }), "Approved and scheduled.")}>Approve &amp; schedule</Button>
          </>)}
        {p.status === "awaiting_approval" && !edit && !isAdmin && <span className="text-[13px] text-ink-500">An owner or admin has to approve this.</span>}
        {p.status === "scheduled" && isAdmin && <div className="flex flex-wrap items-end gap-2"><div className="w-52"><Input label="Reschedule" type="datetime-local" value={at} onChange={(e) => setAt(e.target.value)} /></div>
          <Button size="sm" variant="secondary" disabled={!at} loading={busy === "resched"} onClick={() => void go("resched", () => api(`/marketing/posts/${p.id}/reschedule`, { method: "POST", body: { scheduled_for: at } }), "Rescheduled.")}>Reschedule</Button>
          <Button size="sm" icon={<Check className="h-4 w-4" />} loading={busy === "approve-now"} onClick={() => void go("approve-now", () => api(`/marketing/posts/${p.id}/reschedule`, { method: "POST", body: {} }), "Published on Google.")}>Publish now</Button></div>}
        {p.status === "failed" && isAdmin && <Button size="sm" icon={<RotateCcw className="h-4 w-4" />} loading={busy === "retry"} onClick={() => void go("retry", () => api(`/posts/${p.id}/retry`, { method: "POST" }), "Published on Google.")}>Retry</Button>}
        {["draft", "awaiting_approval", "approved", "scheduled", "failed"].includes(p.status) && isAdmin && !edit && <Button size="sm" variant="ghost" icon={<X className="h-4 w-4" />} loading={busy === "cancel"} onClick={() => void go("cancel", () => api(`/posts/${p.id}/cancel`, { method: "POST" }), "Rejected.")}>Reject</Button>}
      </div>
    </li>
  );
}

export default function CampaignPage() {
  const { id } = useParams<{ id: string }>();
  const toast = useToast();
  const { isAdmin } = useAuth();
  const { data, error, loading, reload } = useFetch<Campaign>(`/marketing/campaigns/${id}`);
  const [bulk, setBulk] = useState(false);
  const tz = data?.timezone ?? "Asia/Kolkata";
  const posts = (data?.posts ?? []).filter((p) => p.status !== "canceled");
  const waiting = posts.filter((p) => p.status === "awaiting_approval");
  async function approveAll() {
    setBulk(true);
    let ok = 0;
    for (const p of waiting) {
      try { await api(`/posts/${p.id}/approve`, { method: "POST", body: { scheduled_for: p.suggested_for && new Date(p.suggested_for) > new Date() ? toLocalInput(p.suggested_for, tz) : undefined } }); ok++; } catch { /* the card shows why */ }
    }
    toast(`${ok} of ${waiting.length} approved.`); setBulk(false); void reload();
  }
  return (
    <>
      <PageHeader title={data?.title ?? "Campaign"} subtitle={data ? `${data.objective_label} · ${data.duration_days} days` : undefined} />
      <p className="-mt-3 mb-4 text-[13px]"><Link href="/gbp/studio" className="font-medium underline">Back to Marketing Studio</Link></p>
      {error ? <Alert tone="error">{error}</Alert> : loading && !data ? <Skeleton className="h-60" /> : !data ? null : (
        <div className="space-y-4">
          {data.notes.map((n) => <Alert key={n} tone="warning">{n}</Alert>)}
          <p className="text-[13px] text-ink-700">Nothing here is on Google yet. Read each post, change what you like, then approve. Posting regularly keeps your profile fresh; it does not by itself raise your ranking.</p>
          {isAdmin && waiting.length > 1 && <div className="flex flex-col gap-2 rounded-xl bg-surface-2 p-3 sm:flex-row sm:items-center sm:justify-between"><span className="min-w-0 text-[13px]">{waiting.length} posts are waiting. Read them first; this approves every one for its suggested date.</span>
            <Button size="sm" variant="secondary" className="!h-auto min-h-11 shrink-0 !whitespace-normal py-2" loading={bulk} onClick={() => void approveAll()}>Approve all for suggested dates</Button></div>}
          {posts.length === 0 ? <EmptyState title="No posts left in this campaign" /> : <ul className="space-y-3">{posts.map((p) => <PostCard key={p.id} p={p} tz={tz} business={p.location_title ?? "Your business"} onChange={() => void reload()} />)}</ul>}
        </div>)}
    </>
  );
}
