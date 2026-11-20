"use client";
import clsx from "clsx";
import { Cake, Check, ChevronDown, Circle, Clock, Megaphone, MessageSquareText, PartyPopper, Star, Zap, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Button, LinkButton } from "@/components/ui/Button";
import { Alert, Badge, PageHeader, Skeleton } from "@/components/ui/Card";
import { Input } from "@/components/ui/Form";
import { useToast } from "@/components/ui/Toast";
import { IconTile, Note, StateDot, Switch } from "@/components/whatsapp/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate } from "@/lib/format";
import { useFetch } from "@/lib/use-api";
import { AUTOMATION_FIELDS, automationStatus, reasonWords, RUN_STATUS, type WaAutomation, type WaAutomations, type WaAutomationState, type WaRun } from "@/lib/whatsapp";

const ICON: Record<string, LucideIcon> = { review_followup: Star, enquiry_followup: MessageSquareText, birthday: Cake, festival: PartyPopper, offers: Megaphone };
const STATE_WORD = { on: "On", paused: "Paused", off: "Off" } as const;
const STATE_DOT = { on: "ok", paused: "warn", off: "off" } as const;

/** One of the three things a helper needs, as a small icon and one word. The longer sentence is the name read out to screen readers. */
function Need({ done, waiting, word, full }: { done: boolean; waiting?: boolean; word: string; full: string }) {
  const State = done ? Check : waiting ? Clock : Circle;
  return (
    <li title={full} className={clsx("inline-flex min-h-8 items-center gap-1.5 rounded-full px-2.5 text-[13px] font-medium", done ? "bg-pos-tint text-pos" : waiting ? "bg-warn-tint text-warn" : "bg-surface-2 text-muted")}>
      {word}<State className="h-3.5 w-3.5" strokeWidth={2.5} aria-hidden /><span className="sr-only">{done ? "Ready: " : waiting ? "Waiting: " : "Not yet: "}{full}</span>
    </li>
  );
}

function Runs({ k }: { k: string }) {
  const { data } = useFetch<WaRun[]>(`/whatsapp/automations/${k}/runs`);
  if (!data) return <Skeleton className="h-16" />;
  if (data.length === 0) return <p className="rounded-2xl bg-surface-2 px-4 py-4 text-center text-[13px] text-muted">Nothing sent yet</p>;
  return (
    <ul className="divide-y divide-line text-[13px]">{data.slice(0, 8).map((r) => (
      <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
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
  const Icon = ICON[a.key] ?? Zap;
  const on = st.status === "on";
  const messagesFull = c.waiting.length ? "WhatsApp is still reviewing the message" : c.refused.length ? "WhatsApp did not approve the message" : "WhatsApp has approved the message (we prepare it when you switch this on)";
  const customersFull = a.purpose === "marketing" ? "Customers who agreed to receive offers" : a.purpose === "occasion" ? "Customers who agreed to birthday and festival greetings" : "Customers who agreed to updates about their visit or enquiry";
  const changed = fields.some((f) => cfg[f.key] !== st.config[f.key]);
  return (
    <section className={clsx("panel p-5 transition-shadow", on && "ring-1 ring-pos/30")} aria-label={a.title}>
      <div className="flex items-start gap-3">
        <IconTile icon={Icon} tone={on ? "pos" : st.status === "paused" ? "warn" : "neutral"} size={44} />
        <div className="min-w-0 flex-1">
          <h2 className="text-[17px] font-semibold leading-6 text-ink">{a.title}</h2>
          <p className="mt-0.5 text-[14px] leading-5 text-muted">{a.description}</p>
          <p className="mt-1.5 inline-flex items-center gap-1.5 text-[13px] font-medium text-ink-700"><StateDot state={STATE_DOT[st.status]} />{STATE_WORD[st.status]}</p>
        </div>
        {canEdit && <Switch checked={on} busy={busy === "on" || busy === "off"} label={`${a.title}: ${STATE_WORD[st.status]}`} onChange={(v) => void set(v ? "on" : "off")} />}
      </div>

      <ul className="mt-4 flex flex-wrap gap-2" aria-label="What this helper needs">
        <Need done={c.connected} word="Number" full="Your WhatsApp number is connected" />
        <Need done={c.templates_approved} waiting={c.waiting.length > 0} word="Messages" full={messagesFull} />
        <Need done={a.ready.customers} word="Customers" full={customersFull} />
      </ul>

      {err && <div className="mt-3"><Alert tone="warning">{err}</Alert></div>}
      {!sendingOn && on && <Note className="mt-3">Nothing is sent yet. Everything waits safely.</Note>}
      {!canEdit && <Note className="mt-3">Only the owner or an admin can change this.</Note>}

      <details className="group mt-4 border-t border-line pt-1" onToggle={(e) => setRuns((e.currentTarget as HTMLDetailsElement).open)}>
        <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between text-[14px] font-semibold text-ink-700 [&::-webkit-details-marker]:hidden">Settings and activity<ChevronDown aria-hidden className="h-4 w-4 text-ink-400 transition-transform group-open:rotate-180" /></summary>
        {fields.length > 0 && (
          <div className="mt-2 grid gap-3 sm:grid-cols-2">{fields.map((f) => "bool" in f ? (
            <div key={f.key} className="flex items-center justify-between gap-3 rounded-2xl bg-surface-2 pl-4 pr-1"><span className="py-2 text-[14px] text-ink-700">{f.label}</span><Switch checked={!!cfg[f.key]} disabled={!canEdit} label={f.label} onChange={(v) => setCfg({ ...cfg, [f.key]: v })} /></div>
          ) : (
            <Input key={f.key} label={`${f.label} (${f.unit})`} type="number" min={f.min} max={f.max} disabled={!canEdit} value={String(cfg[f.key] ?? "")} onChange={(e) => setCfg({ ...cfg, [f.key]: Number(e.target.value) })} hint={`Between ${f.min} and ${f.max}.`} />
          ))}</div>
        )}
        {canEdit && (on || changed) && (
          <div className="mt-3 flex flex-wrap gap-2">
            {on && <Button variant="brand" loading={busy === "on"} disabled={!changed} onClick={() => void set("on")}>Save settings</Button>}
            {on && <Button variant="secondary" loading={busy === "paused"} onClick={() => void set("paused")}>Pause</Button>}
          </div>
        )}
        <div className="mt-3">{runs && <Runs k={a.key} />}</div>
      </details>
    </section>
  );
}

/** Ready-made helpers. Switch one on, check a few details, and it works. Customers are only ever messaged if they agreed. */
export default function Automations() {
  const { isAdmin } = useAuth();
  const { data, error, reload } = useFetch<WaAutomations>("/whatsapp/automations");
  return (
    <>
      <PageHeader title="Automations"
        actions={data && data.limit !== null ? (
          <span className="inline-flex min-h-11 items-center gap-2 rounded-full bg-white px-4 shadow-pill ring-1 ring-line" role="img" aria-label={`${data.active} of ${data.limit} helpers on`}>
            <span className="flex gap-1" aria-hidden>{Array.from({ length: data.limit }, (_, i) => <span key={i} className={clsx("h-2.5 w-2.5 rounded-full", i < data.active ? "bg-pos" : "bg-surface-3")} />)}</span>
            <span className="num text-[14px] font-semibold text-ink">{data.active}/{data.limit}</span>
          </span>
        ) : undefined} />
      {error && <Alert tone="error">{error}</Alert>}
      {!data ? <Skeleton className="h-64" /> : (
        <div className="space-y-3 sm:space-y-4">
          {!data.sending && <Note className="px-1">Sending is not switched on yet. Set helpers up now; nothing is sent until it is.</Note>}
          <div className="grid gap-3 sm:gap-4 lg:grid-cols-2">{data.items.map((a) => a.state ? <Helper key={a.key} a={a} canEdit={isAdmin} onChange={() => void reload()} sendingOn={data.sending} /> : (
            <section key={a.key} className="panel p-5" aria-label={a.title}>
              <div className="flex items-start gap-3">
                <IconTile icon={ICON[a.key] ?? Zap} tone={a.available ? "brand" : "neutral"} size={44} />
                <div className="min-w-0 flex-1">
                  <h2 className="text-[17px] font-semibold leading-6 text-ink">{a.title}</h2>
                  <p className="mt-0.5 text-[14px] leading-5 text-muted">{a.description}</p>
                </div>
                <Badge tone={a.available ? "green" : "gray"}>{a.available ? "Ready" : automationStatus(a)}</Badge>
              </div>
              {a.key === "offers" && (a.campaigns_allowed ? <LinkButton href="/whatsapp/campaigns" variant="brand" className="mt-4 w-full sm:w-auto">Create an offer</LinkButton> : <Note className="mt-3">Offers come with the Growth and Pro add-ons. Ask the FlowQR team to upgrade.</Note>)}
            </section>))}</div>
          <Note className="px-1">WhatsApp charges for each message, apart from FlowQR. <Link href="/whatsapp/messages" className="font-semibold text-brand-700 hover:underline">See costs</Link></Note>
        </div>
      )}
    </>
  );
}
