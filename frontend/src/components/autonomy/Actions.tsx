"use client";
import clsx from "clsx";
import { ArrowRight, CheckCircle2, ShieldCheck, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Skeleton } from "@/components/ui/Card";
import { Textarea } from "@/components/ui/Form";
import { Modal } from "@/components/ui/Modal";
import { Status } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { EVENT_WORDS, STATUS_WORDS, showValue, type ActionDetail, type ActionRow } from "@/lib/autonomy";
import { fmtDate, timeAgo } from "@/lib/format";
import { useFetch } from "@/lib/use-api";

const LEVEL_TONE = { 1: "green", 2: "amber", 3: "red" } as const;
const LEVEL_WORDS = { 1: "Level 1: safe", 2: "Level 2: needs a pre-approval", 3: "Level 3: owner only" } as const;

export function LevelBadge({ level }: { level: 1 | 2 | 3 }) { return <Badge tone={LEVEL_TONE[level]}>{LEVEL_WORDS[level]}</Badge>; }

/** Before and after as two stacked blocks on a phone, side by side on a wide screen. */
function Lines({ xs, tone }: { xs: string[]; tone: string }) {
  return xs.length === 0 ? <p className={clsx("mt-1 rounded-tile p-3 text-sm text-muted", tone)}>Nothing</p>
    : <ul className={clsx("mt-1 max-h-44 space-y-0.5 overflow-auto break-words rounded-tile p-3 text-sm", tone)}>{xs.slice(0, 14).map((x, i) => <li key={i}>{x}</li>)}{xs.length > 14 && <li className="text-muted">and {xs.length - 14} more</li>}</ul>;
}

function BeforeAfter({ a }: { a: ActionRow }) {
  if (a.diff && !a.subject_type) {
    return (
      <div className="grid items-start gap-2 sm:grid-cols-[1fr_auto_1fr]">
        <div className="min-w-0"><p className="text-xs font-medium text-muted">On Google now</p><Lines xs={a.diff.before} tone="bg-surface-2" /></div>
        <ArrowRight className="mx-auto mt-7 hidden h-4 w-4 text-muted sm:block" aria-hidden />
        <div className="min-w-0"><p className="text-xs font-medium text-muted">Would become</p><Lines xs={a.diff.after} tone="bg-accent-tint" />
          {a.diff.added.length > 0 && <p className="mt-1 text-xs text-pos">Adds: {a.diff.added.slice(0, 4).join(", ")}{a.diff.added.length > 4 ? "…" : ""}</p>}
          {a.diff.removed.length > 0 && <p className="mt-0.5 text-xs text-neg">Removes: {a.diff.removed.join(", ")}</p>}</div>
      </div>
    );
  }
  if (a.subject_type) return <div><p className="text-xs font-medium text-muted">What a person approved</p><p className="mt-1 whitespace-pre-wrap rounded-tile bg-surface-2 p-3 text-sm">{showValue(a.after)}</p></div>;
  return (
    <div className="grid items-start gap-2 sm:grid-cols-[1fr_auto_1fr]">
      <div><p className="text-xs font-medium text-muted">On Google now</p><p className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap rounded-tile bg-surface-2 p-3 text-sm">{showValue(a.before)}</p></div>
      <ArrowRight className="mx-auto mt-7 hidden h-4 w-4 text-muted sm:block" aria-hidden />
      <div><p className="text-xs font-medium text-muted">Would become</p><p className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap rounded-tile bg-accent-tint p-3 text-sm">{showValue(a.after)}</p></div>
    </div>
  );
}

function who(a: ActionRow) {
  if (a.subject_type) return "A person approved this exact content";
  return a.authorization === "owner" ? "A person decides" : a.authorization === "preauthorized" ? "You pre-authorised this type" : "Allowed by your autonomy switch (Level 1)";
}

/** One thing waiting for a person. Approve runs it immediately and reports Google's answer; reject needs a reason. */
export function WaitingCard({ a, canDecide, isOwner, onChanged }: { a: ActionRow; canDecide: boolean; isOwner: boolean; onChanged: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [why, setWhy] = useState("");
  const [detail, setDetail] = useState(false);
  const needsOwner = a.policy_level === 3 && !isOwner;

  async function approve() {
    setBusy("approve");
    try {
      const r = await api<{ status: string; execution?: { status: string; detail?: string } }>(`/agent/actions/${a.id}/approve`, { method: "POST", body: {} });
      toast(r.status === "executed" ? "Done. Google's own profile now shows it." : r.execution?.detail ?? "Approved. It could not be confirmed yet; see the problems tab.", r.status === "executed" ? undefined : "error");
      onChanged();
    } catch (e) { toast(errorMessage(e), "error"); onChanged(); } finally { setBusy(null); }
  }
  async function reject() {
    setBusy("reject");
    try { await api(`/agent/actions/${a.id}/reject`, { method: "POST", body: { reason: why } }); toast("Rejected. FlowQR won't propose it again for a while."); onChanged(); }
    catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(null); }
  }
  return (
    <li className="space-y-3 rounded-tile border border-line p-4">
      <div className="flex flex-wrap items-center gap-2"><span className="font-semibold">{a.label}</span><LevelBadge level={a.policy_level} />{a.proposed_by === "agent" && <Badge tone="blue">Suggested by FlowQR</Badge>}</div>
      <p className="text-sm text-muted">{a.problem}</p>
      <BeforeAfter a={a} />
      <p className="text-sm"><span className="font-medium">Why: </span>{a.reason}</p>
      <p className="flex items-start gap-1.5 text-xs text-muted"><ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />{who(a)}. {a.expected_outcome}</p>
      {needsOwner && <Alert tone="info">Only the business owner can approve this kind of change.</Alert>}
      {rejecting && <Textarea label="Why are you rejecting it? (FlowQR uses this to avoid suggesting it again)" rows={2} value={why} onChange={(e) => setWhy(e.target.value)} maxLength={500} />}
      <div className="flex flex-wrap items-center gap-2">
        {!rejecting ? (
          <>
            <Button size="sm" onClick={() => void approve()} loading={busy === "approve"} disabled={!canDecide || needsOwner}>Approve &amp; apply</Button>
            <Button size="sm" variant="secondary" onClick={() => setRejecting(true)} disabled={!canDecide}>Reject</Button>
          </>
        ) : (
          <>
            <Button size="sm" variant="secondary" onClick={() => void reject()} loading={busy === "reject"} disabled={why.trim().length < 3}>Confirm rejection</Button>
            <Button size="sm" variant="ghost" onClick={() => setRejecting(false)}>Back</Button>
          </>
        )}
        <Button size="sm" variant="ghost" onClick={() => setDetail(true)}>Details</Button>
        {a.expires_at && <span className="text-xs text-muted">Expires {fmtDate(a.expires_at)}</span>}
      </div>
      {detail && <DetailModal id={a.id} onClose={() => setDetail(false)} />}
    </li>
  );
}

/** A finished or failed action, one line, opening the full record. */
export function ActionLine({ a }: { a: ActionRow }) {
  const [open, setOpen] = useState(false);
  const w = STATUS_WORDS[a.status];
  return (
    <li className="py-3">
      <button type="button" onClick={() => setOpen(true)} className="flex w-full min-h-11 flex-col gap-1 text-left sm:flex-row sm:items-center sm:justify-between sm:gap-4" aria-label={`${a.label}: ${w.label}. Open the record`}>
        <span className="min-w-0"><span className="block truncate font-medium">{a.label}</span>
          {a.last_error && (a.status === "failed" || a.status === "blocked" || a.status === "invalidated") ? <span className="mt-0.5 block text-sm text-muted">{a.last_error}</span> : <span className="mt-0.5 block truncate text-sm text-muted">{a.problem}</span>}</span>
        <span className="flex shrink-0 items-center gap-3"><Status tone={w.tone}>{w.label}</Status><span className="text-xs text-muted">{timeAgo(a.executed_at ?? a.created_at)}</span></span>
      </button>
      {open && <DetailModal id={a.id} onClose={() => setOpen(false)} />}
    </li>
  );
}

/** The full record of one action: what it was, who authorised it, every step, and whether the record itself is intact. */
export function DetailModal({ id, onClose }: { id: string; onClose: () => void }) {
  const { data, error } = useFetch<ActionDetail>(`/agent/actions/${id}`);
  return (
    <Modal open onClose={onClose} title={data?.label ?? "Action record"} footer={<Button variant="secondary" onClick={onClose}>Close</Button>}>
      {error && <Alert tone="error">{error}</Alert>}
      {!data && !error && <Skeleton className="h-40" />}
      {data && (
        <div className="space-y-4 text-sm">
          <div className="flex flex-wrap items-center gap-2"><LevelBadge level={data.policy_level} /><Status tone={STATUS_WORDS[data.status].tone}>{STATUS_WORDS[data.status].label}</Status></div>
          <p>{data.problem}</p>
          <BeforeAfter a={data} />
          {data.last_error && <Alert tone={data.status === "executed" ? "info" : "warning"}>{data.last_error}</Alert>}
          {data.verification && <p className="flex items-start gap-1.5"><CheckCircle2 className={clsx("mt-0.5 h-4 w-4 shrink-0", data.verification.matched ? "text-pos" : "text-neg")} aria-hidden />{data.verification.matched ? "Read back from Google: it matches." : "Read back from Google: it does not match."} {data.verification.detail}</p>}
          {data.approvals.length > 0 && <div><h3 className="font-semibold">Authorisation</h3><ul className="mt-1 space-y-1 text-muted">{data.approvals.map((p, i) => <li key={i}>{p.decision.replace("_", " ")} ({p.basis.replace(/_/g, " ")}) {fmtDate(p.at)}{p.reason ? `: ${p.reason}` : ""}{p.invalidated_reason ? `. Withdrawn: ${p.invalidated_reason}` : ""}</li>)}</ul></div>}
          <div>
            <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold">History</h3>
              <span className={clsx("inline-flex items-center gap-1 text-xs", data.history_integrity.ok ? "text-pos" : "text-neg")}>{data.history_integrity.ok ? <ShieldCheck className="h-3.5 w-3.5" aria-hidden /> : <ShieldAlert className="h-3.5 w-3.5" aria-hidden />}{data.history_integrity.ok ? `Record intact (${data.history_integrity.events} entries)` : `Record problem: ${data.history_integrity.reason}`}</span></div>
            <ol className="mt-2 space-y-2 border-l border-line pl-4">{data.history.map((h) => <li key={h.seq} className="relative"><span aria-hidden className="absolute -left-[21px] top-1.5 h-2 w-2 rounded-full bg-muted-soft" /><p className="font-medium">{EVENT_WORDS[h.type] ?? h.type.replace(/_/g, " ")}</p><p className="text-xs text-muted">{fmtDate(h.at, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })} · {h.actor}</p></li>)}</ol>
          </div>
          {data.outcome?.label && <p className="rounded-tile bg-surface-2 p-3"><span className="font-medium">Ranking afterwards: {data.outcome.label}. </span>{data.outcome.note}</p>}
        </div>
      )}
    </Modal>
  );
}
