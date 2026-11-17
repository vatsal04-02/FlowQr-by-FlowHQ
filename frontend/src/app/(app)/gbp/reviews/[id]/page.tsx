"use client";
import clsx from "clsx";
import { AlertTriangle, ArrowLeft, Check, CheckCircle2, Send, PenLine, XCircle } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Skeleton, Stars } from "@/components/ui/Card";
import { Status } from "@/components/ui/kit";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { REPLY_STATE, useReviewsList } from "@/components/reviews-ctx";
import { api, ApiError, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { reviewTimeline } from "@/lib/charts";
import { fmtDate } from "@/lib/format";
import type { Draft, Review, ReviewLog } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

interface Detail { review: Review; drafts: Draft[]; logs: ReviewLog[] }
const REASON: Record<string, string> = { medical: "medical or treatment details", legal: "legal action or authorities", threat: "a threat", accusation: "an accusation", low_rating: "a low rating" };
const fmtTime = (iso: string) => fmtDate(iso, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

/** Where the reply is in its life: Draft, Approved, Published (with "Sending to Google" in between). A failure marks the step that didn't happen. */
function Tracker({ status }: { status: "none" | "draft" | "approved" | "publishing" | "failed" | "published" }) {
  const at = { none: -1, draft: 0, approved: 1, publishing: 2, failed: 1, published: 2 }[status];
  const steps = ["Draft", "Approved", status === "publishing" ? "Sending to Google…" : "Published"];
  return (
    <ol aria-label="Reply progress" className="flex items-center gap-2 text-xs">
      {steps.map((s, i) => {
        const done = i < at || (status === "published" && i === 2), cur = i === at && status !== "published", bad = status === "failed" && i === 2;
        return (
          <li key={s} className="flex items-center gap-2" aria-current={cur ? "step" : undefined}>
            <span className={clsx("grid h-4 w-4 place-items-center rounded-full text-[10px] font-bold", done ? "bg-ok text-white" : cur ? "bg-brand-600 text-navy" : bad ? "bg-red-600 text-white" : "bg-ink-100 text-ink-500")}>{done ? <Check className="h-2.5 w-2.5" strokeWidth={3.5} /> : i + 1}</span>
            <span className={clsx("font-medium", done || cur ? "text-ink" : "text-ink-500")}>{s}</span>
            {i < 2 && <span aria-hidden className={clsx("h-px w-5", done ? "bg-ok" : "bg-ink-200")} />}
          </li>
        );
      })}
    </ol>
  );
}

/** What has happened to this review, in order, from the timestamps the server stored (received, drafted, approved, sent, or a reply made on Google). A step that has no timestamp is not shown. */
function Timeline({ r, drafts }: { r: Review; drafts: Draft[] }) {
  const latest = [...drafts].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))[0] ?? null;
  const steps = reviewTimeline({ review_created_at: r.review_created_at, google_reply_at: r.google_reply_at, latest_draft: latest });
  if (steps.length < 2) return null;
  return (
    <ol aria-label="What happened to this review" className="mt-4 grid">
      {steps.map((st, i) => (
        <li key={st.key} className="relative grid grid-cols-[28px_minmax(0,1fr)] gap-3 pb-4 last:pb-0">
          {i < steps.length - 1 && <span aria-hidden className="absolute bottom-[-2px] left-[13px] top-7 w-0.5 bg-ink-200" />}
          <span aria-hidden className="grid h-7 w-7 place-items-center rounded-full bg-pos-tint text-pos motion-safe:animate-[fq-badge_.5s_cubic-bezier(.3,1.35,.5,1)_both]" style={{ animationDelay: `${i * 120}ms` }}><Check className="h-4 w-4" /></span>
          <span className="min-w-0"><b className="block text-[14px] font-semibold">{st.label}</b><span className="text-[13px] text-ink-500">{fmtTime(st.at)}</span></span>
        </li>
      ))}
    </ol>
  );
}

export default function ReviewDetail() {
  const { id } = useParams<{ id: string }>();
  const { isAdmin } = useAuth();
  const toast = useToast();
  const list = useReviewsList();
  const { data, error, loading, reload } = useFetch<Detail>(`/reviews/${id}`);
  const draft = data?.drafts.find((d) => d.status !== "published" && d.status !== "rejected") ?? null;
  const [body, setBody] = useState("");
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [replaceOpen, setReplaceOpen] = useState(false);
  useEffect(() => { setBody(draft?.body ?? ""); setAck(false); }, [draft?.id, draft?.body, id]);

  const dirty = !!draft && body.trim() !== draft.body.trim();
  async function run(name: string, fn: () => Promise<unknown>, ok?: string) {
    setBusy(name);
    try { await fn(); if (ok) toast(ok); await reload(); list.refresh(); }
    catch (e) { if (e instanceof ApiError && e.code === "reply_exists") setReplaceOpen(true); else toast(errorMessage(e), "error"); }
    finally { setBusy(null); }
  }
  const [tone, setTone] = useState("");
  const [lang, setLang] = useState("");
  const generate = () => run("gen", () => api(`/reviews/${id}/drafts/generate`, { method: "POST", body: { tone: tone || null, language: lang || null } }), "Draft ready. Review and edit it before approving.");
  const saveManual = () => run("save", () => api(`/reviews/${id}/drafts`, { method: "POST", body: { body } }), "Draft saved.");
  const save = () => run("save", () => api(`/reply-drafts/${draft!.id}`, { method: "PATCH", body: { body } }), "Changes saved. Approval is required again.");
  const approve = () => run("approve", async () => {
    if (dirty) await api(`/reply-drafts/${draft!.id}`, { method: "PATCH", body: { body } });
    await api(`/reply-drafts/${draft!.id}/approve`, { method: "POST", body: { acknowledge_flags: ack } });
  }, "Approved. Press Publish to send it to Google.");
  const publish = (replace = false) => run("publish", async () => {
    const d = await api<Draft>(`/reply-drafts/${draft!.id}/publish`, { method: "POST", params: replace ? { replace_existing: "true" } : undefined });
    toast(d.status === "published" ? "Published on Google." : "Google didn't accept the reply. See details below.", d.status === "published" ? "success" : "error");
  });
  const discard = () => run("discard", () => api(`/reply-drafts/${draft!.id}`, { method: "DELETE" }), "Draft discarded.");

  if (loading && !data) return <div className="space-y-3 p-5"><Skeleton className="h-8 w-1/2" /><Skeleton className="h-28" /><Skeleton className="h-52" /></div>;
  if (error || !data) return <div className="p-5"><Alert tone="error" title="Couldn't load this review">{error}</Alert></div>;
  const { review: r } = data;
  const st = REPLY_STATE[r.reply_state];
  const needsAck = !!draft?.requires_human_handling;
  const sensitive = r.sensitive_reasons.length > 0 && r.reply_state !== "published";
  const earlier = data.drafts.filter((d) => d.id !== draft?.id);
  type Event = { at: string; kind: "log" | "draft"; log?: ReviewLog; draft?: Draft };
  const history: Event[] = [...data.logs.map((l) => ({ at: l.created_at, kind: "log" as const, log: l })), ...earlier.map((d) => ({ at: d.created_at, kind: "draft" as const, draft: d }))].sort((a, b) => b.at.localeCompare(a.at));

  return (
    <article className="mx-auto max-w-3xl">
      <div className="border-b border-ink-100 px-5 py-4 sm:px-6">
        <Link href="/gbp/reviews" className="mb-3 inline-flex min-h-11 items-center gap-1.5 text-[13px] font-medium text-brand-700 hover:underline md:hidden"><ArrowLeft className="h-4 w-4" aria-hidden />All reviews</Link>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2.5"><Stars rating={r.rating} size={20} /><h1 className="truncate text-lg font-semibold">{r.reviewer_name ?? "Google user"}</h1></div>
            <p className="mt-1 text-[13px] text-ink-500">{r.location_name} · {fmtDate(r.review_created_at)}{r.update_count > 0 && " · edited by reviewer"}</p>
          </div>
          <Status tone={st.tone}>{st.label}</Status>
        </div>
        <blockquote className={clsx("mt-4 whitespace-pre-wrap border-l-[3px] py-0.5 pl-4 text-[16px] leading-relaxed", sensitive ? "border-red-600" : "border-ink-200")}>
          {r.text || <span className="italic text-ink-400">Rating only, no written review</span>}
        </blockquote>
        {sensitive && (
          <p className="mt-3 flex items-start gap-2 rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-900"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            <span><b className="font-semibold">Handle personally.</b> This review {r.sensitive_reasons.length === 1 && r.sensitive_reasons[0] === "low_rating" ? "has a low rating" : `mentions ${r.sensitive_reasons.map((x) => REASON[x] ?? x.replace(/_/g, " ")).join(", ")}`}. AI can draft a reply, but a person should write or sign it off.</span></p>
        )}
        {!r.google_reply_text && r.google_reply_state === "REJECTED" && (
          <p className="mt-4 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3.5 text-[13px] text-red-900"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            <span><b className="font-semibold">Google rejected the reply.</b> It is not visible to customers. Edit the reply below and publish it again.</span></p>
        )}
        {r.google_reply_text && (
          <div className="mt-4 rounded-lg border border-green-200 bg-green-50/70 p-3.5"><p className="flex items-center gap-1.5 text-[13px] font-semibold text-green-800"><CheckCircle2 className="h-4 w-4" aria-hidden />{r.google_reply_state === "PENDING" ? "Reply sent to Google, waiting for Google to check it" : "Reply live on Google"} · {fmtDate(r.google_reply_at)}</p><p className="mt-1 whitespace-pre-wrap text-sm text-ink-700">{r.google_reply_text}</p></div>
        )}
        <Timeline r={r} drafts={data.drafts} />
      </div>

      <div className="px-5 py-4 sm:px-6">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold">Reply</h2>
          <Tracker status={draft ? (draft.status === "failed" ? "failed" : draft.status === "approved" ? "approved" : "draft") : r.reply_state === "published" ? "published" : "none"} />
        </div>

        {needsAck && draft && <div className="mb-3"><Alert tone="warning" title="Flagged for human handling"><ul className="mt-1 list-disc space-y-0.5 pl-4">{draft.flag_messages.map((m) => <li key={m}>{m}</li>)}</ul></Alert></div>}
        {draft?.status === "failed" && <div className="mb-3"><Alert tone="error" title="Google did not accept this reply">{draft.failure_reason ?? "Unknown error"} Attempts: {draft.attempts}.</Alert></div>}

        <label htmlFor="reply" className="mb-1.5 flex items-center gap-2 text-[13px] font-medium text-ink-700">
          Your reply {draft?.generated_by_ai && <span className="inline-flex items-center rounded-md bg-surface-2 px-1.5 py-0.5 text-xs font-medium text-ink-700">Draft by FlowQR</span>}
        </label>
        <textarea id="reply" rows={6} value={body} onChange={(e) => setBody(e.target.value)} maxLength={4000}
          placeholder={draft ? "" : "Write a reply, or ask FlowQR for a draft."}
          className="w-full resize-y rounded-lg border border-ink-300 bg-white p-3 text-base leading-relaxed hover:border-ink-500 focus-visible:border-brand-600 sm:text-[15px]" />
        <p className="mt-1 text-xs text-ink-500"><span className="num">{body.length}/4000</span> · Nothing is posted until you approve it. Don&rsquo;t share private details.</p>

        {needsAck && draft?.status === "draft" && isAdmin && (
          <label className="mt-3 flex min-h-11 cursor-pointer items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm">
            <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} className="mt-0.5 h-4 w-4" />
            <span>I&rsquo;ve read the original review and I&rsquo;m personally handling this reply.</span>
          </label>
        )}

        <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-ink-100 pt-4">
          <div className="flex flex-wrap gap-2">
            <select aria-label="Reply tone" value={tone} onChange={(e) => setTone(e.target.value)} className="min-h-9 rounded-full bg-surface-2 px-3 text-[13px] font-medium">
              <option value="">Brand voice tone</option><option value="warm">Warm</option><option value="professional">Professional</option><option value="brief">Brief</option><option value="apologetic">Apologetic</option></select>
            <select aria-label="Reply language" value={lang} onChange={(e) => setLang(e.target.value)} className="min-h-9 rounded-full bg-surface-2 px-3 text-[13px] font-medium">
              <option value="">Same language as the review</option><option value="en">English</option><option value="hi">Hindi</option><option value="hinglish">Hinglish</option></select>
            <Button variant="secondary" size="sm" icon={<PenLine className="h-3.5 w-3.5" />} loading={busy === "gen"} onClick={() => void generate()}>{draft ? "Redraft" : "Draft a reply"}</Button>
            {!draft && <Button variant="secondary" size="sm" loading={busy === "save"} disabled={body.trim().length < 2} onClick={() => void saveManual()}>Save my own draft</Button>}
            {draft && dirty && <Button variant="secondary" size="sm" loading={busy === "save"} onClick={() => void save()}>Save changes</Button>}
            {draft && isAdmin && <Button variant="ghost" size="sm" loading={busy === "discard"} onClick={() => void discard()} icon={<XCircle className="h-3.5 w-3.5" />}>Discard</Button>}
          </div>
          {draft && (isAdmin ? (
            <div className="flex flex-wrap gap-2">
              {(draft.status === "draft" || dirty) && <Button size="sm" loading={busy === "approve"} disabled={(needsAck && !ack) || body.trim().length < 2} onClick={() => void approve()} icon={<CheckCircle2 className="h-3.5 w-3.5" />}>Approve reply</Button>}
              {(draft.status === "approved" || draft.status === "failed") && !dirty && <Button variant="ink" size="sm" loading={busy === "publish"} onClick={() => void publish()} icon={<Send className="h-3.5 w-3.5" />}>{draft.status === "failed" ? "Retry publishing" : "Publish to Google"}</Button>}
            </div>
          ) : <p className="text-[13px] text-ink-500">An owner or admin must approve and publish replies.</p>)}
        </div>
        {!draft && r.sensitive_reasons.length === 0 && r.reply_state !== "published" && <p className="mt-3 text-xs text-ink-500">Nothing is published until you approve it and Google confirms.</p>}
      </div>

      {history.length > 0 && (
        <div className="border-t border-ink-100 px-5 py-4 sm:px-6">
          <h2 className="mb-2 text-sm font-semibold">Response history</h2>
          <ol className="relative space-y-3 border-l border-ink-200 pl-4">
            {history.map((h) => (
              <li key={h.log?.id ?? h.draft?.id} className="relative text-sm">
                <span aria-hidden className={clsx("absolute -left-[21px] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-white", h.kind === "log" ? (h.log!.success ? "bg-ok" : "bg-red-600") : "bg-ink-300")} />
                {h.kind === "log" ? (
                  <><p className="font-medium">{h.log!.success ? "Published to Google" : "Publish attempt failed"}<span className="ml-2 text-xs font-normal text-ink-500">{fmtTime(h.at)}</span></p>{h.log!.error && <p className="text-[13px] text-red-700">{h.log!.error}</p>}</>
                ) : (
                  <><p className="font-medium capitalize">{h.draft!.status} draft{h.draft!.generated_by_ai ? " (AI)" : ""}<span className="ml-2 text-xs font-normal normal-case text-ink-500">{fmtTime(h.at)}</span></p><p className="mt-0.5 whitespace-pre-wrap text-[13px] text-ink-700">{h.draft!.body}</p></>
                )}
              </li>
            ))}
          </ol>
        </div>
      )}

      <Modal open={replaceOpen} onClose={() => setReplaceOpen(false)} title="Replace the existing reply?" footer={<><Button variant="secondary" onClick={() => setReplaceOpen(false)}>Cancel</Button><Button variant="ink" onClick={() => { setReplaceOpen(false); void publish(true); }}>Replace on Google</Button></>}>
        <p className="flex gap-2 text-ink-700"><AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" aria-hidden />Google already shows a reply to this review. Publishing will overwrite it.</p>
      </Modal>
    </article>
  );
}
