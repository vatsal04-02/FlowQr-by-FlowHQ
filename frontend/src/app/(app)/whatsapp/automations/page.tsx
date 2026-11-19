"use client";
import { Check, Circle } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, PageHeader, Skeleton } from "@/components/ui/Card";
import { Input } from "@/components/ui/Form";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate } from "@/lib/format";
import { useFetch } from "@/lib/use-api";
import { AUTOMATION_FIELDS, automationStatus, reasonWords, RUN_STATUS, type WaAutomation, type WaAutomations, type WaAutomationState, type WaRun } from "@/lib/whatsapp";

function Need({ done, children }: { done: boolean; children: React.ReactNode }) {
  return <li className="flex items-start gap-2 text-[13px] text-ink-700">{done ? <Check className="mt-0.5 h-4 w-4 shrink-0 text-pos" aria-label="Done" /> : <Circle className="mt-0.5 h-4 w-4 shrink-0 text-ink-300" aria-label="Not yet" />}<span>{children}</span></li>;
}

const STATE_TONE = { on: "green", paused: "amber", off: "gray" } as const;
const STATE_WORD = { on: "On", paused: "Paused", off: "Off" } as const;

function Runs({ k }: { k: string }) {
  const { data } = useFetch<WaRun[]>(`/whatsapp/automations/${k}/runs`);
  if (!data) return <Skeleton className="h-16" />;
  if (data.length === 0) return <p className="text-[13px] text-ink-500">Nothing has been sent by this helper yet.</p>;
  return (
    <ul className="divide-y divide-ink-100 text-[13px]">{data.slice(0, 8).map((r) => (
      <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
        <span className="text-ink-700">{r.to ?? "A customer"}{r.phone_last4 ? <span className="text-ink-400"> · …{r.phone_last4}</span> : null}</span>
        <span className="flex items-center gap-2"><Badge tone={RUN_STATUS[r.status]?.tone ?? "gray"}>{RUN_STATUS[r.status]?.label ?? r.status}</Badge>{r.reason && <span className="max-w-[16rem] text-ink-500">{reasonWords(r.reason)}</span>}<span className="text-ink-400">{fmtDate(r.executed_at ?? r.scheduled_at)}</span></span>
      </li>))}</ul>
  );
}

function Helper({ a, canEdit, onChange, sendingOn }: { a: WaAutomation; canEdit: boolean; onChange: () => void; sendingOn: boolean }) {
  const toast = useToast();
  const st = a.state as WaAutomationState;
  const fields = AUTOMATION_FIELDS[a.key] ?? [];
  const [cfg, setCfg] = useState<Record<string, number | boolean>>({ ...st.config });
  const [busy, setBusy] = useState<string | null>(null), [err, setErr] = useState<string | null>(null), [runs, setRuns] = useState(false);
  async function set(status: "on" | "paused" | "off") {
    setBusy(status); setErr(null);
    try { await api(`/whatsapp/automations/${a.key}`, { method: "PUT", body: { status, config: cfg } }); toast(status === "on" ? "Switched on." : status === "paused" ? "Paused. Nothing waiting will be sent." : "Switched off."); onChange(); }
    catch (e) { setErr(errorMessage(e)); } finally { setBusy(null); }
  }
  const c = st.checklist;
  return (
    <Card>
      <div className="flex items-start justify-between gap-3"><h2 className="text-lg font-semibold text-ink">{a.title}</h2><Badge tone={STATE_TONE[st.status]}>{STATE_WORD[st.status]}</Badge></div>
      <p className="mt-1 text-sm text-ink-700">{a.description}</p>
      <ul className="mt-3 space-y-1">
        <Need done={c.connected}>Your WhatsApp number is connected</Need>
        <Need done={c.templates_approved}>{c.waiting.length ? "WhatsApp is still reviewing the message" : c.refused.length ? "WhatsApp did not approve the message" : "WhatsApp has approved the message (we prepare it when you switch this on)"}</Need>
        <Need done={a.ready.customers}>{a.purpose === "marketing" ? "Customers who agreed to receive offers" : a.purpose === "occasion" ? "Customers who agreed to birthday and festival greetings" : "Customers who agreed to updates about their visit or enquiry"}</Need>
      </ul>
      {fields.length > 0 && (
        <div className="mt-4 grid gap-3 sm:grid-cols-2">{fields.map((f) => "bool" in f ? (
          <label key={f.key} className="flex items-center gap-2 text-sm text-ink-700"><input type="checkbox" disabled={!canEdit} checked={!!cfg[f.key]} onChange={(e) => setCfg({ ...cfg, [f.key]: e.target.checked })} className="h-4 w-4 accent-[#BD3E1B]" />{f.label}</label>
        ) : (
          <Input key={f.key} label={`${f.label} (${f.unit})`} type="number" min={f.min} max={f.max} disabled={!canEdit} value={String(cfg[f.key] ?? "")} onChange={(e) => setCfg({ ...cfg, [f.key]: Number(e.target.value) })} hint={`Between ${f.min} and ${f.max}.`} />
        ))}</div>
      )}
      {err && <div className="mt-3"><Alert tone="warning">{err}</Alert></div>}
      {!sendingOn && st.status === "on" && <p className="mt-3 text-[13px] text-ink-500">Sending is not switched on for FlowQR yet, so nothing is sent for now. Everything waits safely.</p>}
      {canEdit ? (
        <div className="mt-4 flex flex-wrap gap-2">
          {st.status !== "on" && <Button variant="brand" loading={busy === "on"} onClick={() => void set("on")}>Switch on</Button>}
          {st.status === "on" && <><Button variant="secondary" loading={busy === "on"} onClick={() => void set("on")}>Save settings</Button><Button variant="secondary" loading={busy === "paused"} onClick={() => void set("paused")}>Pause</Button></>}
          {st.status !== "off" && <Button variant="ghost" loading={busy === "off"} onClick={() => void set("off")}>Switch off</Button>}
        </div>
      ) : <p className="mt-3 text-[13px] text-ink-500">Only the owner or an admin can change this.</p>}
      <button type="button" onClick={() => setRuns(!runs)} className="mt-4 text-[13px] font-semibold text-brand-700 hover:underline">{runs ? "Hide recent activity" : "Show recent activity"}</button>
      {runs && <div className="mt-2"><Runs k={a.key} /></div>}
    </Card>
  );
}

/** Ready-made helpers. Switch one on, check a few details, and it works. Customers are only ever messaged if they agreed. */
export default function Automations() {
  const { isAdmin } = useAuth();
  const { data, error, reload } = useFetch<WaAutomations>("/whatsapp/automations");
  return (
    <>
      <PageHeader title="Automations" subtitle="Ready-made helpers. Switch one on and it looks after the rest." />
      {error && <Alert tone="error">{error}</Alert>}
      {!data ? <Skeleton className="h-64" /> : (
        <div className="space-y-4">
          {!data.sending && <Alert tone="info" title="Sending is not switched on yet">You can set your helpers up now. Nothing is sent until FlowQR switches WhatsApp sending on.</Alert>}
          {data.limit !== null && <p className="text-sm text-ink-700">Your plan allows up to <b>{data.limit}</b> helpers at a time. <b>{data.active}</b> {data.active === 1 ? "is" : "are"} on.</p>}
          <div className="grid gap-4 lg:grid-cols-2">{data.items.map((a) => a.state ? <Helper key={a.key} a={a} canEdit={isAdmin} onChange={() => void reload()} sendingOn={data.sending} /> : (
            <Card key={a.key}>
              <div className="flex items-start justify-between gap-3"><h2 className="text-lg font-semibold text-ink">{a.title}</h2><Badge tone={a.available ? "green" : "gray"}>{a.available ? "Ready" : automationStatus(a)}</Badge></div>
              <p className="mt-1 text-sm text-ink-700">{a.description}</p>
              {a.key === "offers" && <p className="mt-3 text-sm">{a.campaigns_allowed ? <Link href="/whatsapp/campaigns" className="font-semibold text-brand-700 hover:underline">Create an offer</Link> : <span className="text-ink-500">Offers are part of the Growth and Pro add-ons. Ask the FlowQR team to upgrade.</span>}</p>}
            </Card>))}</div>
          <p className="text-[13px] text-ink-500">WhatsApp charges for each message, separately from FlowQR. <Link href="/whatsapp/messages" className="font-semibold text-brand-700 hover:underline">See your messages and costs</Link></p>
        </div>
      )}
    </>
  );
}
