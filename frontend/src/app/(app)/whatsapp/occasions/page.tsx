"use client";
import clsx from "clsx";
import { Cake, ChevronDown, PartyPopper, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, PageHeader, Skeleton } from "@/components/ui/Card";
import { Input } from "@/components/ui/Form";
import { useToast } from "@/components/ui/Toast";
import { Bubble, Figure, IconTile, Note, StateDot, Switch } from "@/components/whatsapp/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate } from "@/lib/format";
import { useFetch } from "@/lib/use-api";
import { greetingKindWords, rupees, type WaGreetingKind, type WaOccasions } from "@/lib/whatsapp";

const STATE = { on: ["ok", "On"], paused: ["warn", "Paused"], off: ["off", "Off"] } as const;

/** One greeting helper: a switch, the message as a chat bubble, three numbers, and the cost. The detail sits one tap down. */
function Greeting({ title, helperKey, icon, g, hours, canEdit, allowed, onChange }: { title: string; helperKey: "birthday" | "festival"; icon: LucideIcon; g: WaGreetingKind; hours: WaOccasions["hours"]; canEdit: boolean; allowed: boolean; onChange: () => void }) {
  const toast = useToast();
  const st = g.helper;
  const kind = greetingKindWords(g);
  const [hour, setHour] = useState(String(st.config.send_hour ?? 10)), [busy, setBusy] = useState<string | null>(null), [err, setErr] = useState<string | null>(null);
  async function set(status: "on" | "paused" | "off") {
    setBusy(status); setErr(null);
    try { await api(`/whatsapp/automations/${helperKey}`, { method: "PUT", body: { status, config: { send_hour: Number(hour) } } }); toast(status === "on" ? "Switched on." : status === "paused" ? "Paused." : "Switched off."); onChange(); }
    catch (e) { setErr(errorMessage(e)); } finally { setBusy(null); }
  }
  const [dot, word] = STATE[st.status];
  const on = st.status === "on";
  const changed = hour !== String(st.config.send_hour ?? 10);
  const last = helperKey === "birthday" ? { label: "Birthday saved", value: g.audience.with_birthday } : { label: "Left out", value: g.audience.left_out };
  return (
    <section className={clsx("panel p-5", on && "ring-1 ring-pos/30")} aria-label={title}>
      <div className="flex items-center gap-3">
        <IconTile icon={icon} tone={on ? "pos" : st.status === "paused" ? "warn" : "accent"} size={44} />
        <div className="min-w-0 flex-1">
          <h2 className="text-[17px] font-semibold leading-6 text-ink">{title}</h2>
          <p className="inline-flex items-center gap-1.5 text-[13px] font-medium text-ink-700"><StateDot state={dot} />{word}</p>
        </div>
        {canEdit && <Switch checked={on} disabled={!allowed && !on} busy={busy === "on" || busy === "off"} label={`${title}: ${word}`} onChange={(v) => void set(v ? "on" : "off")} />}
      </div>

      {g.body && <div className="mt-4 flex flex-col rounded-2xl bg-surface-2 p-3"><Bubble side="out" className="max-w-full">{g.body.replace("{{1}}", "Asha").replace("{{2}}", "your business").replace("{{3}}", "the festival")}</Bubble></div>}

      <dl className="mt-4 grid grid-cols-3 gap-2">
        {[{ label: "Agreed", value: g.audience.agreed }, { label: "Would get it", value: g.audience.would_receive }, last].map((x) => (
          <div key={x.label} className="rounded-2xl bg-surface-2 px-2 py-3 text-center"><dd className="num text-[22px] font-semibold leading-7 text-ink">{x.value}</dd><dt className="text-[13px] leading-4 text-muted">{x.label}</dt></div>
        ))}
      </dl>
      {g.warning && <div className="mt-3"><Alert tone="warning" title="Who will get it">{g.warning}</Alert></div>}
      {err && <div className="mt-3"><Alert tone="warning">{err}</Alert></div>}
      {!canEdit && <Note className="mt-3">Only the owner or an admin can change this.</Note>}

      <details className="group mt-4 border-t border-line pt-1">
        <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between text-[14px] font-semibold text-ink-700 [&::-webkit-details-marker]:hidden">Cost and time<ChevronDown aria-hidden className="h-4 w-4 text-ink-400 transition-transform group-open:rotate-180" /></summary>
        <div className="space-y-3 pb-1">
          <div className="flex items-center justify-between gap-3 rounded-2xl bg-surface-2 p-3" data-testid={`${helperKey}-cost`}>
            <div><Figure value={rupees(g.estimate.per_greeting.amount)} /><p className="text-[13px] text-muted">likely charge for each greeting</p></div>
            <Badge tone={kind.tone}>{kind.label}</Badge>
          </div>
          <p className="text-[13px] leading-5 text-muted">An estimate{g.estimate.category_used === "marketing" ? ", at the marketing price" : ""}{g.estimate.per_greeting.effective_from ? `, using the price dated ${fmtDate(g.estimate.per_greeting.effective_from)}` : ""}. {g.audience.would_receive > 0 ? `If all ${g.audience.would_receive} who would get it had one: ${rupees(g.estimate.for_everyone_who_would_get_it.amount)}.` : ""} WhatsApp charges this to you, apart from FlowQR&apos;s fee.</p>
          {g.estimate.per_greeting.warning && <p className="text-[13px] font-semibold text-warn">{g.estimate.per_greeting.warning}</p>}
          {g.status && g.status !== "approved" && <Badge tone="amber">WhatsApp: {g.status}</Badge>}
          {canEdit && allowed && (
            <>
              <div className="max-w-xs"><Input label="Send at (India time)" type="number" min={hours.start} max={hours.end - 1} value={hour} onChange={(e) => setHour(e.target.value)} hint={`An hour from ${hours.start} to ${hours.end - 1}. Never outside ${hours.start} am to ${hours.end - 12} pm.`} /></div>
              {on && <div className="flex flex-wrap gap-2"><Button variant="brand" loading={busy === "on"} disabled={!changed} onClick={() => void set("on")}>Save hour</Button><Button variant="secondary" loading={busy === "paused"} onClick={() => void set("paused")}>Pause</Button></div>}
            </>
          )}
        </div>
      </details>
    </section>
  );
}

/** Birthday and festival greetings: a short, neutral greeting, never an offer, only for customers who agreed to it. */
export default function Occasions() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const q = useFetch<WaOccasions>("/whatsapp/occasions");
  const o = q.data;
  const [err, setErr] = useState<string | null>(null);
  async function choose(id: string, enabled: boolean) {
    setErr(null);
    try { await api(`/whatsapp/occasions/festivals/${id}`, { method: "PUT", body: { enabled } }); toast(enabled ? "You will greet customers on this festival." : "Not greeting customers on this festival."); void q.reload(); }
    catch (e) { setErr(errorMessage(e)); }
  }
  return (
    <>
      <PageHeader title="Greetings" />
      {q.error && <Alert tone="error">{q.error}</Alert>}
      {!o ? <Skeleton className="h-64" /> : (
        <div className="space-y-3 sm:space-y-4">
          {!o.allowed && <Alert tone="info" title="Part of the Growth and Pro plans">Ask the FlowQR team about upgrading.</Alert>}
          <Note className="px-1">{o.note} Customers agree to greetings on the <Link href="/whatsapp/contacts" className="font-semibold text-brand-700 hover:underline">Customers</Link> page.</Note>
          <div className="grid gap-3 sm:gap-4 lg:grid-cols-2">
            <Greeting title="Birthday wishes" helperKey="birthday" icon={Cake} g={o.birthday} hours={o.hours} canEdit={isAdmin} allowed={o.allowed} onChange={() => void q.reload()} />
            <Greeting title="Festival wishes" helperKey="festival" icon={PartyPopper} g={o.festival} hours={o.hours} canEdit={isAdmin} allowed={o.allowed} onChange={() => void q.reload()} />
          </div>
          <section className="panel p-5 sm:p-6" aria-label="Festivals">
            <h2 className="text-[17px] font-semibold text-ink">Festivals</h2>
            <p className="text-[13px] text-muted">Nothing is sent for a festival you have not chosen.</p>
            {err && <div className="mt-3"><Alert tone="warning">{err}</Alert></div>}
            {o.festivals.length === 0 ? <p className="mt-3 rounded-2xl bg-surface-2 px-4 py-5 text-center text-[14px] text-muted">No upcoming festivals yet</p> : (
              <ul className="mt-2 divide-y divide-line">{o.festivals.map((f) => (
                <li key={f.id} className="flex items-center gap-3 py-2">
                  <div className="min-w-0 flex-1"><p className="text-[15px] font-semibold text-ink">{f.name}</p><p className="text-[13px] text-muted">{fmtDate(f.date)} · {f.region}</p></div>
                  {isAdmin ? <Switch checked={f.enabled} label={`Greet my customers on ${f.name}`} onChange={(v) => void choose(f.id, v)} /> : <Badge tone={f.enabled ? "green" : "gray"}>{f.enabled ? "Chosen" : "Not chosen"}</Badge>}
                </li>))}</ul>
            )}
          </section>
          <Note className="px-1">What customers agree to: “{o.wording}”</Note>
        </div>
      )}
    </>
  );
}
