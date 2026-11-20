"use client";
import clsx from "clsx";
import { Check, ChevronDown } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, PageHeader, Skeleton } from "@/components/ui/Card";
import { Input } from "@/components/ui/Form";
import { Note, Ring, StepNode } from "@/components/whatsapp/ui";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-api";
import { connectWhatsApp } from "@/lib/whatsapp-connect";
import { currentStep, HELPER_TITLES, looksLikeMobile, STEP_STATE, stepOpen, type WaSetup, type WaStep } from "@/lib/whatsapp";
import { STEP_ACTION, stepLine } from "@/lib/whatsapp-ui";

/** Set up: six short steps from nothing to your first helper. Only the step to do now is open; each one is checked against what really exists, so you can leave and come back and it picks up where you were. */
export default function SetUp() {
  const { isAdmin } = useAuth();
  const q = useFetch<WaSetup>("/whatsapp/setup");
  const [openKey, setOpenKey] = useState<string | null>(null);
  const s = q.data;
  const cur = s ? currentStep(s) : null;
  // after a test message is sent, keep checking for a short while so the owner sees it arrive
  const tested = s?.steps.find((x) => x.key === "test");
  const waiting = tested?.state === "done" && tested.test?.status === "sent";
  useEffect(() => {
    if (!waiting) return;
    let n = 0;
    const t = setInterval(() => { n += 1; void q.reload(); if (n >= 12) clearInterval(t); }, 5000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [waiting]);

  return (
    <>
      <PageHeader title="Set up" />
      {q.error && <Alert tone="error">{q.error}</Alert>}
      {!s ? <Skeleton className="h-72" /> : (
        <div className="space-y-3">
          <section className="panel flex items-center gap-4 p-4 sm:p-5" aria-label="Progress">
            <Ring done={s.done} total={s.total} size={76} stroke={8} complete={s.complete} label={`${s.done} of ${s.total} steps done`}>
              {s.complete ? <Check className="h-8 w-8 text-pos" strokeWidth={2.5} aria-hidden /> : <span className="num text-[22px] font-semibold leading-none text-ink">{s.done}<span className="text-[14px] font-medium text-ink-300">/{s.total}</span></span>}
            </Ring>
            <div className="min-w-0 flex-1">
              <p className="text-[18px] font-semibold leading-6 text-ink">{s.complete ? "All set" : `${s.done} of ${s.total} done`}</p>
              <p className="mt-0.5 text-[14px] text-muted">{s.complete ? "Helpers are ready." : "Stop any time. Carry on later."}</p>
            </div>
          </section>
          {!s.sending && <Note className="px-1">Sending is off for now. Tests and helpers start when it is on.</Note>}
          <ol className="space-y-2.5">{s.steps.map((st) => {
            const open = stepOpen(st, cur, openKey);
            const isCur = st.key === cur?.key;
            return (
              <li key={st.key}>
                <section className={clsx("panel overflow-hidden", open && isCur && "ring-2 ring-brand-600/30")}>
                  <button type="button" onClick={() => setOpenKey(open ? null : st.key)} aria-expanded={open} className="flex min-h-[68px] w-full items-center gap-3.5 p-4 text-left sm:p-5">
                    <StepNode keyName={st.key} state={st.state} now={isCur} size={44} />
                    <span className="min-w-0 flex-1">
                      <span className="block text-[16px] font-semibold leading-5 text-ink">{STEP_ACTION[st.key]}</span>
                      <span className="mt-0.5 block text-[13px] leading-4 text-muted">{stepLine(st)}<span className="sr-only">. {STEP_STATE[st.state].label}</span></span>
                    </span>
                    <ChevronDown aria-hidden className={clsx("h-4 w-4 shrink-0 text-ink-400 transition-transform motion-reduce:transition-none", open && "rotate-180")} />
                  </button>
                  {open && <div className="border-t border-line p-4 sm:p-5"><StepBody step={st} isAdmin={isAdmin} setup={s} onChange={() => void q.reload()} /></div>}
                </section>
              </li>);
          })}</ol>
          {s.complete && <p className="px-1 text-[14px] text-muted">Next: mark a visit as done on <Link href="/whatsapp/contacts" className="font-semibold text-brand-700 hover:underline">Customers</Link>.</p>}
        </div>
      )}
    </>
  );
}

function StepBody({ step, isAdmin, setup, onChange }: { step: WaStep; isAdmin: boolean; setup: WaSetup; onChange: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null), [err, setErr] = useState<string | null>(null);
  const [phone, setPhone] = useState(""), [name, setName] = useState(""), [own, setOwn] = useState(false), [agreed, setAgreed] = useState(false), [how, setHow] = useState("Asked in person and wrote it in my register");
  const only = !isAdmin && step.state !== "done" ? <p className="text-[13px] text-ink-500">Only the owner or an admin of the business can do this step.</p> : null;
  async function run<T>(key: string, fn: () => Promise<T>, ok: string) {
    setBusy(key); setErr(null);
    try { await fn(); toast(ok); onChange(); } catch (e) { setErr(errorMessage(e)); onChange(); } finally { setBusy(null); }
  }

  if (step.state === "blocked") return <p className="text-sm text-ink-700">{step.key === "plan" ? "FlowQR switches this on for you." : "This step opens when the one before it is done."}</p>;
  if (step.key === "plan") return <p className="text-sm text-ink-700">{step.body}</p>;
  if (only) return only;
  return (
    <div className="space-y-3">
      {err && <Alert tone="warning">{err}</Alert>}
      {step.key === "connect" && (step.state === "waiting"
        ? <p className="text-sm text-ink-700">{step.body}</p>
        : <><p className="text-sm text-ink-700">A WhatsApp window opens. Pick your number there. FlowQR never sees your password.</p>
          <Button variant="brand" loading={busy === "connect"} onClick={() => void run("connect", connectWhatsApp, "WhatsApp is connected.")}>{step.state === "done" ? "Connect again" : "Connect WhatsApp"}</Button></>)}
      {step.key === "messages" && (
        <>
          <p className="text-sm text-ink-700">{step.state === "done" ? "WhatsApp approved your messages." : "WhatsApp approves each message first. One tap sends yours."}</p>
          <div className="flex flex-wrap gap-2">
            {step.state !== "done" && step.action === "prepare_messages" && <Button variant="brand" loading={busy === "prep"} onClick={() => void run("prep", () => api("/whatsapp/setup/prepare-messages", { method: "POST", body: {} }), "Sent to WhatsApp for approval.")}>Prepare my messages</Button>}
            {step.state !== "done" && <Button variant="secondary" loading={busy === "sync"} onClick={() => void run("sync", () => api("/whatsapp/templates/sync", { method: "POST" }), "Checked with WhatsApp.")}>Check with WhatsApp</Button>}
            <Link href="/whatsapp/messages" className="inline-flex min-h-11 items-center px-2 text-[13px] font-semibold text-brand-700 hover:underline">Your messages</Link>
          </div>
        </>
      )}
      {step.key === "customers" && (
        <>
          <p className="text-sm text-ink-700">Add your own number first, to try things out.</p>
          <div className="grid gap-3 sm:grid-cols-2"><Input label="Mobile number" inputMode="tel" placeholder="98765 43210" value={phone} onChange={(e) => setPhone(e.target.value)} /><Input label="Name (optional)" value={name} onChange={(e) => setName(e.target.value)} /></div>
          <label className="flex items-start gap-3 text-sm text-ink-700"><input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} className="mt-1 h-4 w-4 accent-[#BD3E1B]" /><span>This person agreed to receive WhatsApp messages about their visit or enquiry.</span></label>
          <Input label="How did they agree?" value={how} onChange={(e) => setHow(e.target.value)} hint="Kept as a record. At least 10 characters." />
          <div className="flex flex-wrap items-center gap-3"><Button variant="brand" disabled={!looksLikeMobile(phone) || !agreed || how.trim().length < 10} loading={busy === "cust"} onClick={() => void run("cust", () => api("/whatsapp/contacts", { method: "POST", body: { phone, name: name || null, utility: true, attested: true, evidence: how.trim() } }), "Customer added.")}>Add customer</Button><Link href="/whatsapp/contacts" className="text-[13px] font-semibold text-brand-700 hover:underline">Add many at once</Link></div>
        </>
      )}
      {step.key === "test" && (
        <>
          <p className="text-sm text-ink-700">{step.state === "done" ? step.body : "We send you the thank-you customers get after an enquiry."}</p>
          {step.state === "waiting" ? <p className="text-[13px] text-ink-500">{step.body}</p> : (
            <>
              <Input label="Your own mobile number" inputMode="tel" placeholder="98765 43210" value={phone} onChange={(e) => setPhone(e.target.value)} />
              <label className="flex items-start gap-3 text-sm text-ink-700"><input type="checkbox" checked={own} onChange={(e) => setOwn(e.target.checked)} className="mt-1 h-4 w-4 accent-[#BD3E1B]" /><span>This is my own number. I am sending a test to myself, not to a customer.</span></label>
              <Button variant="brand" disabled={!looksLikeMobile(phone) || !own} loading={busy === "test"} onClick={() => void run("test", () => api("/whatsapp/setup/test-message", { method: "POST", body: { phone, own_number: true } }), "Test message sent. Check your phone.")}>{step.state === "done" ? "Send another test" : "Send me a test"}</Button>
            </>
          )}
        </>
      )}
      {step.key === "helper" && (
        <>
          <p className="text-sm text-ink-700">{setup.recommended.why}</p>
          <ul className="space-y-2">{(step.recommended ?? []).map((k) => (
            <li key={k} className="flex flex-wrap items-center justify-between gap-2 rounded-2xl bg-surface-2 p-3">
              <span className="text-sm font-semibold text-ink">{HELPER_TITLES[k] ?? k}</span>
              {k === "offers" ? <Link href="/whatsapp/campaigns" className="text-[13px] font-semibold text-brand-700 hover:underline">Create an offer</Link>
                : <Button size="sm" variant="brand" loading={busy === k} onClick={() => void run(k, () => api(`/whatsapp/automations/${k}`, { method: "PUT", body: { status: "on" } }), "Switched on.")}>Switch on</Button>}
            </li>))}</ul>
          <Link href="/whatsapp/automations" className="text-[13px] font-semibold text-brand-700 hover:underline">All helpers</Link>
        </>
      )}
    </div>
  );
}
