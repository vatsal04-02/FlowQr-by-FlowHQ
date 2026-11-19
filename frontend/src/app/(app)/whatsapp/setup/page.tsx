"use client";
import { Check, ChevronDown } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, PageHeader, Skeleton } from "@/components/ui/Card";
import { Input } from "@/components/ui/Form";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-api";
import { connectWhatsApp } from "@/lib/whatsapp-connect";
import { currentStep, HELPER_TITLES, looksLikeMobile, setupPercent, setupProgress, STEP_STATE, stepOpen, type WaSetup, type WaStep } from "@/lib/whatsapp";

/** Get set up: six short steps from nothing to your first helper. Each step is checked against what really exists, so you can leave and come back and it picks up where you were. */
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
      <PageHeader title="Get set up" subtitle="Six short steps. You can stop any time and carry on later." />
      {q.error && <Alert tone="error">{q.error}</Alert>}
      {!s ? <Skeleton className="h-72" /> : (
        <div className="space-y-4">
          <Card>
            <div className="flex items-center justify-between gap-3"><p className="font-semibold text-ink">{setupProgress(s)}</p>{s.complete && <Badge tone="green">Finished</Badge>}</div>
            <div className="mt-3 h-2 rounded-full bg-surface-3" role="progressbar" aria-valuemin={0} aria-valuemax={s.total} aria-valuenow={s.done} aria-label="Set-up progress"><div className="h-2 rounded-full bg-brand-700 transition-[width] duration-500" style={{ width: `${setupPercent(s)}%` }} /></div>
            {!s.sending && <p className="mt-3 text-[13px] text-ink-500">Sending is not switched on for FlowQR yet, so test messages and helpers will start working as soon as it is.</p>}
          </Card>
          <ol className="space-y-3">{s.steps.map((st, i) => {
            const open = stepOpen(st, cur, openKey);
            return (
              <li key={st.key}>
                <Card pad={false}>
                  <button type="button" onClick={() => setOpenKey(open ? null : st.key)} aria-expanded={open} className="flex w-full items-center gap-3 p-4 text-left sm:p-5">
                    <span aria-hidden className={`grid h-8 w-8 shrink-0 place-items-center rounded-full text-sm font-semibold ${st.state === "done" ? "bg-pos-tint text-pos" : "bg-surface-2 text-ink-700"}`}>{st.state === "done" ? <Check className="h-4 w-4" /> : i + 1}</span>
                    <span className="min-w-0 flex-1"><span className="block font-semibold text-ink">{st.title}</span><span className="block text-[13px] text-ink-500">{st.body}</span></span>
                    <Badge tone={STEP_STATE[st.state].tone}>{STEP_STATE[st.state].label}</Badge>
                    <ChevronDown aria-hidden className={`h-4 w-4 shrink-0 text-ink-400 transition-transform ${open ? "rotate-180" : ""}`} />
                  </button>
                  {open && <div className="border-t border-line p-4 sm:p-5"><StepBody step={st} isAdmin={isAdmin} setup={s} onChange={() => void q.reload()} /></div>}
                </Card>
              </li>);
          })}</ol>
          {s.complete && <Card><p className="font-semibold text-ink">You are all set up.</p><p className="mt-1 text-sm text-ink-700">Mark a customer's visit as done on the <Link href="/whatsapp/contacts" className="font-semibold text-brand-700 hover:underline">Customers</Link> page to send a review request, or create an <Link href="/whatsapp/campaigns" className="font-semibold text-brand-700 hover:underline">offer</Link>.</p></Card>}
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

  if (step.state === "blocked") return <p className="text-sm text-ink-700">{step.key === "plan" ? "Ask the FlowQR team to switch WhatsApp on for your business. You do not need to do anything else here until they do." : "This step opens when the one before it is done."}</p>;
  if (step.key === "plan") return <p className="text-sm text-ink-700">{step.body}</p>;
  if (only) return only;
  return (
    <div className="space-y-3">
      {err && <Alert tone="warning">{err}</Alert>}
      {step.key === "connect" && (step.state === "waiting"
        ? <p className="text-sm text-ink-700">{step.body}</p>
        : <><p className="text-sm text-ink-700">A WhatsApp window opens. Choose your business number there. FlowQR never sees your WhatsApp password.</p>
          <Button variant="brand" loading={busy === "connect"} onClick={() => void run("connect", connectWhatsApp, "WhatsApp is connected.")}>{step.state === "done" ? "Connect again" : "Connect WhatsApp"}</Button></>)}
      {step.key === "messages" && (
        <>
          <p className="text-sm text-ink-700">{step.state === "done" ? "WhatsApp has approved the messages your helpers use." : "WhatsApp approves every message before it can be sent. One click sends yours for approval."}</p>
          <div className="flex flex-wrap gap-2">
            {step.state !== "done" && step.action === "prepare_messages" && <Button variant="brand" loading={busy === "prep"} onClick={() => void run("prep", () => api("/whatsapp/setup/prepare-messages", { method: "POST", body: {} }), "Sent to WhatsApp for approval.")}>Prepare my messages</Button>}
            {step.state !== "done" && <Button variant="secondary" loading={busy === "sync"} onClick={() => void run("sync", () => api("/whatsapp/templates/sync", { method: "POST" }), "Checked with WhatsApp.")}>Check with WhatsApp</Button>}
            <Link href="/whatsapp/messages" className="inline-flex min-h-11 items-center px-2 text-[13px] font-semibold text-brand-700 hover:underline">See your messages</Link>
          </div>
        </>
      )}
      {step.key === "customers" && (
        <>
          <p className="text-sm text-ink-700">Add yourself first, so you can try everything on your own phone. Only people who agreed are ever messaged.</p>
          <div className="grid gap-3 sm:grid-cols-2"><Input label="Mobile number" inputMode="tel" placeholder="98765 43210" value={phone} onChange={(e) => setPhone(e.target.value)} /><Input label="Name (optional)" value={name} onChange={(e) => setName(e.target.value)} /></div>
          <label className="flex items-start gap-3 text-sm text-ink-700"><input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} className="mt-1 h-4 w-4 accent-[#BD3E1B]" /><span>This person agreed to receive WhatsApp messages about their visit or enquiry.</span></label>
          <Input label="How did they agree?" value={how} onChange={(e) => setHow(e.target.value)} hint="Kept as a record. At least 10 characters." />
          <div className="flex flex-wrap items-center gap-3"><Button variant="brand" disabled={!looksLikeMobile(phone) || !agreed || how.trim().length < 10} loading={busy === "cust"} onClick={() => void run("cust", () => api("/whatsapp/contacts", { method: "POST", body: { phone, name: name || null, utility: true, attested: true, evidence: how.trim() } }), "Customer added.")}>Add customer</Button><Link href="/whatsapp/contacts" className="text-[13px] font-semibold text-brand-700 hover:underline">Add many at once</Link></div>
        </>
      )}
      {step.key === "test" && (
        <>
          <p className="text-sm text-ink-700">{step.state === "done" ? step.body : "We send the thank-you message customers get after an enquiry, so you see exactly how it looks."}</p>
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
          <Link href="/whatsapp/automations" className="text-[13px] font-semibold text-brand-700 hover:underline">See all helpers and their settings</Link>
        </>
      )}
    </div>
  );
}
