"use client";
import { AlertTriangle, ArrowLeft, CheckCircle2, History, Send, Sparkles, XCircle } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, CardHeader, Skeleton, Stars } from "@/components/ui/Card";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api, ApiError, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate } from "@/lib/format";
import type { Draft, Review, ReviewLog } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

interface Detail { review: Review; drafts: Draft[]; logs: ReviewLog[] }

export default function ReviewDetail() {
  const { id } = useParams<{ id: string }>();
  const { isAdmin } = useAuth();
  const toast = useToast();
  const { data, error, loading, reload } = useFetch<Detail>(`/reviews/${id}`);
  const draft = data?.drafts.find((d) => d.status !== "published" && d.status !== "rejected") ?? null;
  const [body, setBody] = useState("");
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [replaceOpen, setReplaceOpen] = useState(false);
  useEffect(() => { setBody(draft?.body ?? ""); setAck(false); }, [draft?.id, draft?.body]);

  const dirty = !!draft && body.trim() !== draft.body.trim();
  async function run(name: string, fn: () => Promise<unknown>, ok?: string) {
    setBusy(name);
    try { await fn(); if (ok) toast(ok); await reload(); }
    catch (e) { if (e instanceof ApiError && e.code === "reply_exists") setReplaceOpen(true); else toast(errorMessage(e), "error"); }
    finally { setBusy(null); }
  }
  const generate = () => run("gen", () => api(`/reviews/${id}/drafts/generate`, { method: "POST" }), "AI draft ready. Review and edit it before approving.");
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

  if (loading && !data) return <Skeleton className="h-96" />;
  if (error || !data) return <Alert tone="error" title="Couldn't load this review">{error}</Alert>;
  const { review: r } = data;
  const needsAck = !!draft?.requires_human_handling;

  return (
    <>
      <Link href="/reviews" className="mb-4 inline-flex min-h-11 items-center gap-1.5 text-sm font-semibold text-brand-700 hover:underline"><ArrowLeft className="h-4 w-4" aria-hidden />All reviews</Link>
      <div className="grid gap-5 lg:grid-cols-[1fr_1.1fr]">
        <Card>
          <div className="flex flex-wrap items-center justify-between gap-2"><Stars rating={r.rating} size={20} /><Badge tone={r.reply_state === "published" ? "green" : "amber"}>{r.reply_state === "published" ? "Replied" : "Awaiting reply"}</Badge></div>
          <h1 className="mt-3 text-xl font-semibold">{r.reviewer_name ?? "Google user"}</h1>
          <p className="text-sm text-ink-500">{r.location_name} · {fmtDate(r.review_created_at)}{r.update_count > 0 && " · edited by reviewer"}</p>
          <blockquote className="mt-4 whitespace-pre-wrap rounded-xl bg-ink-50 p-4 text-[16px] leading-relaxed">{r.text || <span className="italic text-ink-400">Rating only, no written review</span>}</blockquote>
          {r.google_reply_text && (
            <div className="mt-4 rounded-xl border border-green-200 bg-green-50 p-4"><p className="flex items-center gap-1.5 text-sm font-semibold text-green-800"><CheckCircle2 className="h-4 w-4" aria-hidden />Reply shown on Google · {fmtDate(r.google_reply_at)}</p><p className="mt-1 whitespace-pre-wrap text-sm text-ink-700">{r.google_reply_text}</p></div>
          )}
        </Card>

        <Card>
          <CardHeader title="Reply" subtitle="Nothing is published until you approve and Google confirms." action={draft && <Badge tone={draft.status === "failed" ? "red" : draft.status === "approved" ? "green" : "blue"}>{draft.status}</Badge>} />
          {needsAck && draft && (
            <div className="mb-4"><Alert tone="warning" title="Flagged for human handling">
              <ul className="mt-1 list-disc space-y-0.5 pl-4">{draft.flag_messages.map((m) => <li key={m}>{m}</li>)}</ul>
            </Alert></div>
          )}
          {!draft && r.sensitive_reasons.length > 0 && <div className="mb-4"><Alert tone="warning" title="This review may need personal attention">Consider replying yourself. AI drafts are always reviewed by you first.</Alert></div>}

          {draft?.status === "failed" && <div className="mb-4"><Alert tone="error" title="Google did not accept this reply">{draft.failure_reason ?? "Unknown error"} Attempts: {draft.attempts}.</Alert></div>}

          <label htmlFor="reply" className="mb-1.5 flex items-center gap-2 text-sm font-semibold text-ink-700">
            Your reply {draft?.generated_by_ai && <Badge tone="orange"><Sparkles className="h-3 w-3" aria-hidden />AI draft</Badge>}
          </label>
          <textarea id="reply" rows={7} value={body} onChange={(e) => setBody(e.target.value)} maxLength={4000} disabled={draft?.status === "approved" && !dirty && false}
            placeholder={draft ? "" : "Write a reply, or let AI draft one for you to edit."}
            className="w-full resize-y rounded-xl border border-ink-200 bg-white p-3.5 text-[16px] leading-relaxed focus-visible:border-brand-500" />
          <p className="mt-1 text-xs text-ink-500">{body.length}/4000 · Don't share patient or medical details in public replies.</p>

          {needsAck && draft?.status === "draft" && isAdmin && (
            <label className="mt-3 flex min-h-11 cursor-pointer items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm">
              <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} className="mt-0.5 h-5 w-5 accent-brand-600" />
              <span>I've read the original review and I'm personally handling this reply.</span>
            </label>
          )}

          <div className="mt-4 flex flex-wrap gap-2">
            <Button variant="secondary" icon={<Sparkles className="h-4 w-4" />} loading={busy === "gen"} onClick={() => void generate()}>{draft ? "Regenerate with AI" : "Draft with AI"}</Button>
            {!draft && <Button variant="secondary" loading={busy === "save"} disabled={body.trim().length < 2} onClick={() => void saveManual()}>Save my own draft</Button>}
            {draft && dirty && <Button variant="secondary" loading={busy === "save"} onClick={() => void save()}>Save changes</Button>}
          </div>

          {draft && (
            <div className="mt-4 border-t border-ink-100 pt-4">
              {isAdmin ? (
                <div className="flex flex-wrap gap-2">
                  {(draft.status === "draft" || dirty) && <Button loading={busy === "approve"} disabled={(needsAck && !ack) || body.trim().length < 2} onClick={() => void approve()} icon={<CheckCircle2 className="h-4 w-4" />}>Approve reply</Button>}
                  {(draft.status === "approved" || draft.status === "failed") && !dirty && (
                    <Button variant="accent" loading={busy === "publish"} onClick={() => void publish()} icon={<Send className="h-4 w-4" />}>{draft.status === "failed" ? "Retry publishing" : "Publish to Google"}</Button>
                  )}
                  <Button variant="danger" loading={busy === "discard"} onClick={() => void discard()} icon={<XCircle className="h-4 w-4" />}>Discard</Button>
                </div>
              ) : <p className="text-sm text-ink-500">An owner or admin must approve and publish replies.</p>}
            </div>
          )}
        </Card>
      </div>

      {(data.logs.length > 0 || data.drafts.filter((d) => d.id !== draft?.id).length > 0) && (
        <Card className="mt-5"><CardHeader title="Reply history" />
          <ul className="divide-y divide-ink-100 text-sm">
            {data.logs.map((l) => (
              <li key={l.id} className="flex flex-wrap items-center gap-2 py-2.5"><History className="h-4 w-4 text-ink-400" aria-hidden /><span>{fmtDate(l.created_at, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</span>
                <Badge tone={l.success ? "green" : "red"}>{l.success ? "Published" : "Failed"}</Badge>{l.error && <span className="text-red-700">{l.error}</span>}</li>
            ))}
            {data.drafts.filter((d) => d.id !== draft?.id).map((d) => (
              <li key={d.id} className="py-2.5"><div className="flex items-center gap-2"><Badge>{d.status}</Badge><span className="text-xs text-ink-500">{fmtDate(d.created_at)}</span></div><p className="mt-1 whitespace-pre-wrap text-ink-700">{d.body}</p></li>
            ))}
          </ul>
        </Card>
      )}

      <Modal open={replaceOpen} onClose={() => setReplaceOpen(false)} title="Replace the existing reply?" footer={<><Button variant="secondary" onClick={() => setReplaceOpen(false)}>Cancel</Button><Button variant="accent" onClick={() => { setReplaceOpen(false); void publish(true); }}>Replace on Google</Button></>}>
        <p className="flex gap-2 text-ink-700"><AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" aria-hidden />Google already shows a reply to this review. Publishing will overwrite it.</p>
      </Modal>
    </>
  );
}
