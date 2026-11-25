"use client";
import { CheckCircle2, CircleAlert, Send } from "lucide-react";
import Link from "next/link";
import { useRef, useState } from "react";
import { ChangeCard } from "@/components/operator/ChangeCard";
import { Button } from "@/components/ui/Button";
import { Alert, PageHeader } from "@/components/ui/Card";
import { Textarea } from "@/components/ui/Form";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { countLabel, type AskResponse } from "@/lib/operator";

const TOOL_WORDS: Record<string, string> = {
  get_business_context: "Read what FlowQr knows about your business", audit_profile: "Checked your Google profile area by area", get_pending_changes: "Looked at what is waiting for you",
  prepare_change: "Prepared a change", list_reviews_needing_reply: "Looked for reviews without a reply", draft_review_reply: "Drafted a review reply", draft_google_post: "Drafted a Google post",
};
const SUGGESTIONS = ["Improve my Google profile", "Reply to my new reviews", "What is waiting for me?", "Write a Google post about this week at the clinic"];
type Turn = { ask: string; res?: AskResponse; error?: string };

/** FlowQr AI Business Operator. The screen shows only what the backend returned: the request while it runs, then the tool steps that really ran, the answer, and every change the operator
 * prepared as the stored proposal (not the model's description of it). The operator can prepare and draft; approving is always yours, here or on the other pending screens. */
export default function OperatorPage() {
  const { isAdmin } = useAuth();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<Record<string, { tone: "success" | "warning" | "error"; text: string }>>({});
  const end = useRef<HTMLDivElement>(null);

  async function send(text: string) {
    const ask = text.trim();
    if (ask.length < 2 || busy) return;
    setBusy(true); setMsg("");
    setTurns((t) => [...t, { ask }]);
    try {
      const res = await api<AskResponse>("/operator/ask", { method: "POST", body: { message: ask } });
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, res } : x)));
    } catch (e) {
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, error: errorMessage(e) } : x)));
    } finally { setBusy(false); setTimeout(() => end.current?.scrollIntoView({ behavior: "smooth" }), 50); }
  }

  return (
    <>
      <PageHeader title="AI Business Operator" subtitle="Ask for what you want done. The operator looks at your real profile and reviews, prepares the exact changes, and waits for your approval. It cannot publish or change anything on its own." />
      <div className="space-y-4">
        {!isAdmin && <Alert tone="info">Only an owner or admin can ask the operator to prepare changes. You can still see what is waiting under <Link href="/ai/changes" className="font-semibold text-accent-ink hover:underline">Pending changes</Link>.</Alert>}
        {turns.length === 0 && (
          <div className="rounded-tile bg-surface p-5 shadow-card">
            <p className="font-semibold">What would you like done?</p>
            <p className="mt-1 text-sm text-muted">For example:</p>
            <div className="mt-3 flex flex-wrap gap-2">{SUGGESTIONS.map((s) => <button key={s} type="button" disabled={!isAdmin || busy} onClick={() => void send(s)} className="min-h-9 rounded-full bg-surface-2 px-3.5 text-[13px] font-semibold text-ink-700 ring-1 ring-inset ring-line hover:bg-accent-tint disabled:opacity-50">{s}</button>)}</div>
          </div>)}

        {turns.map((t, i) => (
          <div key={i} className="space-y-3">
            <div className="ml-auto max-w-xl rounded-2xl rounded-br-md bg-navy px-4 py-2.5 text-sm text-white">{t.ask}</div>
            {!t.res && !t.error && <div className="rounded-tile bg-surface p-4 text-sm text-muted shadow-card" role="status">Working on it. The operator is reading your profile and preparing the changes. This can take up to a minute.</div>}
            {t.error && <Alert tone="error">{t.error}</Alert>}
            {t.res && (
              <div className="space-y-3">
                {t.res.status === "unavailable" && <Alert tone="error" title="The AI could not run">{t.res.reason_text ?? "The AI service is not available right now."} Nothing was prepared.</Alert>}
                {t.res.steps.length > 0 && (
                  <div className="rounded-tile bg-surface p-4 shadow-card">
                    <p className="text-[13px] font-semibold text-muted">What I did</p>
                    <ul className="mt-2 space-y-1.5 text-sm">{t.res.steps.map((s, j) => (
                      <li key={j} className="flex items-start gap-2">{s.ok ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-pos" aria-hidden /> : <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-neg" aria-hidden />}
                        <span><span className="font-medium">{TOOL_WORDS[s.tool] ?? s.tool}.</span> <span className="text-muted">{s.summary}</span></span></li>))}</ul>
                  </div>)}
                {t.res.answer && <div className="max-w-2xl whitespace-pre-line rounded-2xl rounded-bl-md bg-surface-2 px-4 py-3 text-sm">{t.res.answer}</div>}
                {t.res.changes.length > 0 && (
                  <div className="space-y-2">
                    <p className="text-[13px] font-semibold text-muted">{countLabel(t.res.changes.length, "change", "changes")} prepared for your approval</p>
                    {Object.entries(done).filter(([k]) => t.res!.changes.some((c) => c.key === k)).map(([k, o]) => <Alert key={k} tone={o.tone}>{o.text}</Alert>)}
                    <ul className="space-y-3">{t.res.changes.filter((c) => !done[c.key]).map((c) => (
                      <ChangeCard key={c.key} item={c} canDecide={isAdmin} onChanged={() => undefined} onDone={(k, o) => setDone((p) => ({ ...p, [k]: o }))} />))}</ul>
                    <p className="text-[13px] text-muted">All pending work is under <Link href="/ai/changes" className="font-semibold text-accent-ink hover:underline">Pending changes</Link>.</p>
                  </div>)}
              </div>)}
          </div>))}
        <div ref={end} />

        <form className="sticky bottom-2 flex items-end gap-2 rounded-tile bg-surface p-3 shadow-card" onSubmit={(e) => { e.preventDefault(); void send(msg); }}>
          <div className="min-w-0 flex-1"><Textarea label="Ask the operator" rows={2} maxLength={600} value={msg} disabled={!isAdmin || busy} onChange={(e) => setMsg(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(msg); } }} /></div>
          <Button type="submit" icon={<Send className="h-4 w-4" />} loading={busy} disabled={!isAdmin || msg.trim().length < 2}>Send</Button>
        </form>
      </div>
    </>
  );
}
