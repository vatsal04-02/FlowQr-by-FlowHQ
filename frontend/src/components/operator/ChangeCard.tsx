"use client";
import clsx from "clsx";
import { ArrowRight, Check, Pencil, RefreshCw, ShieldCheck, X } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge } from "@/components/ui/Card";
import { Textarea } from "@/components/ui/Form";
import { useToast } from "@/components/ui/Toast";
import { ApiError, errorMessage } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { approvalOutcome, operationLabel, type PendingItem } from "@/lib/operator";
import { runOperation } from "@/lib/operator-run";

const RISK_TONE: Record<string, "green" | "amber" | "red"> = { low: "green", medium: "amber", high: "red" };
const SOURCE_WORDS: Record<string, string> = { ai: "Written by the AI from your Business Brain", owner: "Written by you", business_knowledge: "From your Business Brain", owner_input: "From your own answers", tenant_record: "From your business record" };
/** The field each kind of change takes its reworded text in (the server's own request shape). */
const EDIT_KEY: Record<PendingItem["kind"], string> = { action: "text", reply: "body", post: "summary", profile_task: "description" };

function Lines({ text, tone }: { text: string; tone?: string }) {
  if (!text) return <p className="text-[13px] text-muted">Nothing yet</p>;
  return <p className={clsx("whitespace-pre-line text-[14px] leading-6", tone)}>{text}</p>;
}

/** One proposed change, whatever it is (a profile field, a reply, a post): BEFORE, AFTER, why, risk, and exactly the actions the server says are available. A button the server did not offer is not drawn;
 * one that exists but is unavailable says why. Nothing here claims a change is live: that is read from the server's own verified status after approval. */
export function ChangeCard({ item, canDecide, focused, onChanged, onDone }: { item: PendingItem; canDecide: boolean; focused?: boolean; onChanged: () => void; onDone: (key: string, o: { tone: "success" | "warning" | "error"; text: string }) => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(item.after);
  const [ack, setAck] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const ops = item.operations;
  const waiting = ["pending_approval", "recommended", "awaiting_approval", "draft"].includes(item.status);

  async function act(name: "approve" | "reject" | "regenerate" | "edit") {
    setBusy(name); setErr(null);
    try {
      const body = name === "approve" && item.needs_acknowledgement ? { acknowledge_flags: ack } : name === "edit" ? { [EDIT_KEY[item.kind]]: text } : undefined;
      const result = await runOperation(ops[name], body);
      if (name === "approve") onDone(item.key, approvalOutcome(item, result));
      else toast(name === "reject" ? "Rejected. FlowQr will not suggest this exact change again." : name === "edit" ? "Saved your wording. It still needs your approval." : "A new version is ready.");
      setEditing(false); onChanged();
    } catch (e) {
      const detail = e instanceof ApiError ? (e.detail as { violations?: { message?: string }[]; message?: string } | undefined) : undefined;
      setErr(detail?.violations?.length ? `${errorMessage(e)} ${detail.violations.map((v) => v.message).filter(Boolean).join(" ")}` : errorMessage(e));
      if (name === "approve") onChanged();
    } finally { setBusy(null); }
  }

  const blocked = ops.approve.available ? null : ops.approve.reason;
  return (
    <li id={`change-${item.key}`} className={clsx("space-y-3 rounded-tile border p-4", focused ? "border-accent ring-2 ring-accent/30" : "border-line")}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[16px] font-semibold">{item.title}</span>
        <Badge tone={waiting ? "amber" : item.status === "executed" ? "green" : "red"}>{item.status_label}</Badge>
        <Badge tone={RISK_TONE[item.risk] ?? "gray"}>{item.risk} risk</Badge>
        {item.location_title && <span className="text-[13px] text-muted">{item.location_title}</span>}
      </div>
      {item.problem && <p className="text-sm text-muted">{item.problem}</p>}

      <div className="grid items-start gap-2 sm:grid-cols-[1fr_auto_1fr]">
        <div><p className="text-xs font-medium text-muted">{item.before_label ?? "On Google now"}</p><div className="mt-1 max-h-52 overflow-auto rounded-tile bg-surface-2 p-3"><Lines text={item.before} /></div></div>
        <ArrowRight className="mx-auto mt-7 hidden h-4 w-4 text-muted sm:block" aria-hidden />
        <div>
          <p className="text-xs font-medium text-muted">{item.kind === "reply" ? "Proposed reply" : "Would become"}</p>
          {editing ? (
            <Textarea label="Your wording" rows={6} value={text} onChange={(e) => setText(e.target.value)} />
          ) : (
            <div className="mt-1 max-h-60 overflow-auto rounded-tile bg-accent-tint p-3"><Lines text={item.after} />
              {item.diff && item.diff.added.length > 0 && <p className="mt-1 text-[12px] text-pos">Adds: {item.diff.added.slice(0, 5).join(", ")}{item.diff.added.length > 5 ? "…" : ""}</p>}
              {item.diff && item.diff.removed.length > 0 && <p className="mt-0.5 text-[12px] text-neg">Removes: {item.diff.removed.join(", ")}</p>}</div>)}
        </div>
      </div>

      {item.reason && <p className="text-sm"><span className="font-medium">Why this change: </span>{item.reason}</p>}
      {item.expected_outcome && <p className="text-xs text-muted">{item.expected_outcome}</p>}
      <p className="text-xs text-muted">{SOURCE_WORDS[item.source ?? ""] ?? "Prepared by FlowQr"}{item.quality_score != null ? ` · quality check ${item.quality_score}` : ""}{item.created_at ? ` · ${timeAgo(item.created_at)}` : ""}</p>

      {item.flags && item.flags.length > 0 && <Alert tone="warning" title="Read this review yourself first">{item.flags.join(", ").replaceAll("_", " ")}</Alert>}
      {item.violations && item.violations.length > 0 && <Alert tone="warning" title="This text breaks a rule from your Business Brain">{item.violations.map((v) => v.message ?? v.detail).filter(Boolean).join(" ")}</Alert>}
      {item.last_error && <Alert tone="error">{item.last_error}</Alert>}
      {err && <Alert tone="error">{err}</Alert>}
      {blocked && waiting && <Alert tone="info" title="FlowQr cannot apply this one yet">{blocked}</Alert>}

      {item.needs_acknowledgement && waiting && canDecide && (
        <label className="flex min-h-11 cursor-pointer items-start gap-3 text-sm"><input type="checkbox" className="mt-0.5 h-[18px] w-[18px]" checked={ack} onChange={(e) => setAck(e.target.checked)} />I have read this review myself and this reply is right.</label>
      )}

      {waiting && (canDecide ? (
        <div className="flex flex-wrap items-center gap-2">
          {editing ? (<>
            <Button size="sm" loading={busy === "edit"} onClick={() => void act("edit")} disabled={!text.trim()}>Save my wording</Button>
            <Button size="sm" variant="secondary" onClick={() => { setEditing(false); setText(item.after); }}>Cancel</Button>
          </>) : (<>
            {ops.approve.available && <Button size="sm" icon={<Check className="h-4 w-4" />} loading={busy === "approve"} disabled={item.needs_acknowledgement && !ack} onClick={() => void act("approve")}>{operationLabel.approve}</Button>}
            {ops.edit.available && <Button size="sm" variant="secondary" icon={<Pencil className="h-4 w-4" />} onClick={() => setEditing(true)}>{operationLabel.edit}</Button>}
            {ops.regenerate.available && <Button size="sm" variant="secondary" icon={<RefreshCw className="h-4 w-4" />} loading={busy === "regenerate"} onClick={() => void act("regenerate")}>{operationLabel.regenerate}</Button>}
            {ops.reject.available && <Button size="sm" variant="secondary" icon={<X className="h-4 w-4" />} loading={busy === "reject"} onClick={() => void act("reject")}>{operationLabel.reject}</Button>}
          </>)}
          {!editing && ops.approve.available && <span className="inline-flex items-center gap-1 text-xs text-muted"><ShieldCheck className="h-3.5 w-3.5" aria-hidden />Nothing changes until you approve.</span>}
          {!editing && !ops.edit.available && ops.edit.reason && <span className="basis-full text-xs text-muted">{ops.edit.reason}</span>}
        </div>
      ) : <p className="text-[13px] text-muted">Only an owner or admin can approve this.</p>)}
    </li>
  );
}
