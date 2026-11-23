"use client";
import { Ring } from "@/components/charts/Bars";
import clsx from "clsx";
import { AlertTriangle, ArrowRight, Check, Lock, PenLine, Star, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Button, LinkButton } from "@/components/ui/Button";
import { Alert, PageHeader, Skeleton } from "@/components/ui/Card";
import { Panel, Toggle } from "@/components/ui/kit";
import { useConfirm } from "@/components/ui/Confirm";
import { useToast } from "@/components/ui/Toast";
import { api, ApiError, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtNum, timeAgo } from "@/lib/format";
import type { Overview, Review } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

type List = { total: number; items: Review[] };
interface AgentSettingsOut { daily_plan: boolean; auto_draft_replies: boolean; auto_draft_posts: boolean; auto_publish: false; notes: Record<string, string> }

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** One AI draft as an action card: the review, the reply, and the human decision. Flagged reviews need an explicit acknowledgement. */
function DraftCard({ r, canApprove, onDone, selected }: { r: Review; canApprove: boolean; onDone: () => void; selected: boolean }) {
  const toast = useToast();
  const d = r.latest_draft!;
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState<"approve" | "publish" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const flagged = d.requires_human_handling || r.sensitive_reasons.length > 0;
  const approved = d.status === "approved";

  async function approve() {
    setBusy("approve"); setErr(null);
    try { await api(`/reply-drafts/${d.id}/approve`, { method: "POST", body: { acknowledge_flags: ack } }); toast("Approved. Publish it when you're ready."); onDone(); }
    catch (e) { setErr(e instanceof ApiError && e.code === "flags_need_acknowledgement" ? "Tick the box to confirm you've read this review." : errorMessage(e)); }
    finally { setBusy(null); }
  }
  async function publish() {
    setBusy("publish"); setErr(null);
    try {
      const out = await api<{ status: string }>(`/reply-drafts/${d.id}/publish`, { method: "POST" });
      toast(out.status === "published" ? "Google confirmed: the reply is live." : "Sent. It shows as published once Google confirms."); onDone();
    } catch (e) { setErr(errorMessage(e)); } finally { setBusy(null); }
  }

  return (
    <li className={clsx("flex flex-col rounded-tile p-[18px]", selected ? "bg-accent-tint ring-1 ring-inset ring-accent-edge" : "bg-surface-2")}>
      <div className="flex items-start justify-between gap-3">
        <span className={clsx("grid h-10 w-10 shrink-0 place-items-center rounded-inner bg-surface", flagged ? "text-warn" : "text-accent-ink")} aria-hidden>{flagged ? <AlertTriangle className="h-[18px] w-[18px]" /> : <Star className="h-[18px] w-[18px]" />}</span>
        <span className="text-xs text-muted">{timeAgo(r.review_created_at)}</span>
      </div>
      <p className="mt-3 font-semibold">{r.reviewer_name ?? "A Google user"} <span className="font-semibold text-accent-ink">{r.rating}★</span>{r.location_name && <span className="font-normal text-muted"> · {r.location_name}</span>}</p>
      {r.text && <p className="mt-1 line-clamp-2 text-[13px] text-muted">&ldquo;{r.text}&rdquo;</p>}
      <div className="mt-3 rounded-inner bg-surface p-3 text-[13px] leading-relaxed"><p className="mb-1 text-xs font-medium text-muted">{approved ? "Approved reply" : "AI draft"}</p><p className="line-clamp-5 whitespace-pre-wrap">{d.body}</p></div>
      {flagged && !approved && (
        <div className="mt-3 rounded-inner bg-warn-tint p-3 text-[13px]">
          <p className="font-semibold text-warn">Needs you personally</p>
          {d.flag_messages.length > 0 && <p className="mt-0.5 text-ink-700">{d.flag_messages[0]}</p>}
          {canApprove && <label className="mt-2 flex min-h-11 items-center gap-2 font-medium sm:min-h-0"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} className="h-4 w-4" />I&rsquo;ve read the review and this reply</label>}
        </div>
      )}
      {err && <p className="mt-2 text-[13px] text-neg" role="alert">{err}</p>}
      <div className="mt-auto flex flex-wrap items-center justify-between gap-2 pt-3">
        <Link href={`/gbp/reviews/${r.id}`} className="inline-flex min-h-11 items-center gap-1.5 text-sm font-semibold text-ink hover:underline sm:min-h-9"><PenLine className="h-4 w-4" aria-hidden />Edit</Link>
        {!canApprove ? <span className="text-xs text-muted">An owner or admin approves</span>
          : approved ? <Button size="sm" variant={selected ? "brand" : "primary"} loading={busy === "publish"} onClick={() => void publish()}>Publish to Google</Button>
          : <Button size="sm" variant={selected ? "brand" : "primary"} icon={<Check className="h-4 w-4" />} loading={busy === "approve"} disabled={flagged && !ack} onClick={() => void approve()}>Approve</Button>}
      </div>
    </li>
  );
}

/**
 * AI › Reply assistant (PRD §6.3): every AI draft waiting for a person, across all reviews, in one place. Approve here; publishing is a
 * separate step and a reply shows as published only after Google confirms. Settings rows: auto-draft (drafts only, never publishes),
 * sensitive-review flagging (always on) and reviewer-language drafting (always on).
 */
export default function ReplyAssistantPage() {
  const confirm = useConfirm();
  const { isAdmin } = useAuth();
  const toast = useToast();
  const drafts = useFetch<List>("/reviews", { reply_state: "draft", limit: 12 });
  const approved = useFetch<List>("/reviews", { reply_state: "approved", limit: 6 });
  const published = useFetch<List>("/reviews", { reply_state: "published", limit: 6 });
  const failed = useFetch<List>("/reviews", { reply_state: "failed", limit: 4 });
  const to = new Date(), from = new Date(); from.setDate(to.getDate() - 29);
  const ov = useFetch<Overview>("/analytics/overview", { from: iso(from), to: iso(to) });
  const settings = useFetch<AgentSettingsOut>("/agent/settings");
  const [saving, setSaving] = useState(false);

  const reload = () => { void drafts.reload(); void approved.reload(); void published.reload(); void failed.reload(); void ov.reload(); };
  const waiting = [...(approved.data?.items ?? []), ...(drafts.data?.items ?? [])].filter((r) => r.latest_draft);
  const n = (drafts.data?.total ?? 0) + (approved.data?.total ?? 0);
  const o = ov.data?.reviews;
  const replied = o ? Math.round((o.reply_rate_in_range ?? 0) * o.new_in_range) : 0;
  const history = [...(failed.data?.items ?? []).map((r) => ({ r, ok: false })), ...(published.data?.items ?? []).map((r) => ({ r, ok: true }))].slice(0, 8);

  // Batch approval: only drafts that need no personal acknowledgement. Each reply is approved, then published; the summary counts only
  // what Google confirmed. Flagged reviews always stay one-by-one.
  const [bulk, setBulk] = useState<{ done: number; total: number; ok: number; failed: number } | null>(null);
  const ready = (drafts.data?.items ?? []).filter((r) => r.latest_draft && r.latest_draft.status === "draft" && !r.latest_draft.requires_human_handling && r.sensitive_reasons.length === 0);
  async function approveAll() {
    if (!(await confirm({ title: `Publish ${ready.length} ${ready.length === 1 ? "reply" : "replies"}?`, body: "Each is approved and published to Google exactly as written. Flagged reviews are not included.", tone: "neutral", confirmLabel: "Approve and publish" }))) return;
    let ok = 0, failed = 0;
    setBulk({ done: 0, total: ready.length, ok, failed });
    for (const [i, r] of ready.entries()) {
      try {
        await api(`/reply-drafts/${r.latest_draft!.id}/approve`, { method: "POST", body: { acknowledge_flags: false } });
        const out = await api<{ status: string }>(`/reply-drafts/${r.latest_draft!.id}/publish`, { method: "POST" });
        if (out.status === "published") ok++; else failed++;
      } catch { failed++; }
      setBulk({ done: i + 1, total: ready.length, ok, failed });
    }
    toast(failed ? `${ok} published on Google, ${failed} didn't go through. Open them to see why.` : `${ok} replies published. Google confirmed each one.`, failed ? "error" : "success");
    reload();
  }

  async function setAuto(v: boolean) {
    setSaving(true);
    try { settings.setData(await api<AgentSettingsOut>("/agent/settings", { method: "PUT", body: { auto_draft_replies: v } })); toast(v ? "New reviews will get a draft, waiting for you." : "Auto-drafting is off."); }
    catch (e) { toast(errorMessage(e), "error"); } finally { setSaving(false); }
  }

  return (
    <>
      <h1 className="mb-4 text-[22px] font-semibold leading-7 sm:text-[26px]">Drafts</h1>
      <div className="grid gap-5 sm:gap-6 xl:grid-cols-3">
        <section className="rounded-[16px] bg-surface p-4 shadow-card lg:p-5 xl:col-span-2" aria-label="Drafts waiting">
          <h2 className="text-[15px] font-semibold">Waiting for you</h2>
          <div className="mt-3 flex flex-wrap items-center gap-5">
            <Ring value={o && o.new_in_range ? Math.min(100, (replied / o.new_in_range) * 100) : null} size={104} stroke={10} label={o ? `${replied} of ${o.new_in_range} new reviews answered` : "No new reviews"}>
              <span><b className="num block text-[26px] font-semibold leading-none">{o ? fmtNum(replied) : "–"}</b><span className="num text-[12px] text-muted">of {o ? fmtNum(o.new_in_range) : "–"}</span></span>
            </Ring>
            <dl className="grid min-w-0 flex-1 grid-cols-2 gap-3 text-[14px]">
              <div><dt className="text-muted">Drafts</dt><dd className="num text-[24px] font-semibold">{drafts.loading && !drafts.data ? "–" : fmtNum(n)}</dd></div>
              <div><dt className="text-muted">No reply</dt><dd className="num text-[24px] font-semibold">{o ? fmtNum(o.awaiting_reply) : "–"}</dd></div>
            </dl>
            <a href="#drafts" className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-[12px] bg-ink-solid px-5 text-sm font-semibold text-ink-on sm:w-auto">Review drafts<ArrowRight className="h-4 w-4" aria-hidden /></a>
          </div>
        </section>

        <Panel dense title="Draft settings">
          <ul className="divide-y divide-line">
            <li className="flex items-center justify-between gap-3 pb-3">
              <span><span className="block font-semibold">Draft new reviews</span></span>
              {settings.data ? <Toggle on={settings.data.auto_draft_replies} label="Auto-draft replies for new reviews" disabled={!isAdmin || saving} onChange={(v) => void setAuto(v)} /> : <Skeleton className="h-8 w-14" />}
            </li>
            <li className="flex items-center justify-between gap-3 py-3">
              <span><span className="block font-semibold">Flag sensitive reviews</span></span>
              <span className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full bg-surface-2 px-2.5 py-1 text-xs font-medium text-muted"><Lock className="h-3 w-3" aria-hidden />Always on</span>
            </li>
            <li className="flex items-center justify-between gap-3 pt-3">
              <span><span className="block font-semibold">Match the language</span></span>
              <span className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full bg-surface-2 px-2.5 py-1 text-xs font-medium text-muted"><Lock className="h-3 w-3" aria-hidden />Always on</span>
            </li>
          </ul>
          <LinkButton href="/settings/ai/voice" variant="secondary" size="sm" className="mt-4">Brand voice</LinkButton>
        </Panel>

        <section id="drafts" className="panel rv scroll-mt-6 p-5 sm:p-6 xl:col-span-2" aria-labelledby="drafts-h">
          <div className="flex flex-wrap items-center justify-between gap-2"><h2 id="drafts-h" className="text-lg font-semibold">Drafts</h2>
            <div className="flex flex-wrap items-center gap-3">
              {n > waiting.length && <Link href="/gbp/reviews?state=draft" className="text-sm font-semibold text-accent-ink hover:underline">See all {fmtNum(n)}</Link>}
              {isAdmin && ready.length > 1 && <Button size="sm" variant="brand" icon={<Check className="h-4 w-4" />} loading={!!bulk && bulk.done < bulk.total} onClick={() => void approveAll()}>Approve & publish {ready.length} unflagged</Button>}
            </div></div>
          {bulk && <div className="mt-4 rounded-tile bg-surface-2 p-4" role="status">
            <div className="hatch h-2.5 overflow-hidden rounded-full"><div className="h-full rounded-full bg-accent transition-[width]" style={{ width: `${(bulk.done / bulk.total) * 100}%` }} /></div>
            <p className="mt-2 text-sm">{bulk.done < bulk.total ? `Publishing ${bulk.done + 1} of ${bulk.total}…` : "Done."} <span className="text-muted">{bulk.ok} confirmed by Google{bulk.failed ? ` · ${bulk.failed} didn't go through` : ""}</span></p>
          </div>}
          {drafts.error && <div className="mt-4"><Alert tone="error">{drafts.error}</Alert></div>}
          {drafts.loading && !drafts.data ? <div className="mt-5 grid gap-3.5 md:grid-cols-2">{[0, 1].map((k) => <Skeleton key={k} className="h-64 !rounded-tile" />)}</div>
            : waiting.length === 0 ? (
              <div className="mt-5 flex flex-wrap items-center gap-4 rounded-tile bg-surface-2 p-5">
                <span aria-hidden className="grid h-10 w-10 place-items-center rounded-full bg-pos-tint text-pos"><Check className="h-5 w-5" strokeWidth={2.5} /></span>
                <p className="min-w-0 flex-1 basis-60 text-sm text-muted">No drafts waiting.</p>
                <LinkButton href="/gbp/reviews?state=none" variant="secondary" size="sm">Reviews without a reply</LinkButton>
              </div>
            ) : <ul className="mt-5 grid gap-3.5 md:grid-cols-2">{waiting.map((r, i) => <DraftCard key={r.id} r={r} selected={i === 0} canApprove={isAdmin} onDone={reload} />)}</ul>}
        </section>

        <Panel dense title="History">
          {history.length === 0 ? <p className="text-sm text-muted">Replies you publish appear here once Google confirms them.</p> : (
            <ul className="divide-y divide-line">{history.map(({ r, ok }) => (
              <li key={r.id}><Link href={`/gbp/reviews/${r.id}`} className="flex items-center gap-3 py-3">
                <span aria-hidden className={clsx("grid h-9 w-9 shrink-0 place-items-center rounded-full", ok ? "bg-pos-tint text-pos" : "bg-neg-tint text-neg")}>{ok ? <Check className="h-4 w-4" /> : <X className="h-4 w-4" />}</span>
                <span className="min-w-0 flex-1"><span data-words="skip" className="block truncate font-medium">{r.reviewer_name ?? "A Google user"} · {r.rating}★</span><span className="block text-xs text-muted">{ok ? (r.google_reply_at ? "Replied" : "Published on Google") : "Didn't reach Google · open to retry"}</span></span>
              </Link></li>))}</ul>
          )}
        </Panel>
      </div>
    </>
  );
}
