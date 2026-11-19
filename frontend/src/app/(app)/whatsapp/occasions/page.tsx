"use client";
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
import { greetingKindWords, type WaGreetingKind, type WaOccasions } from "@/lib/whatsapp";

const STATE = { on: ["green", "On"], paused: ["amber", "Paused"], off: ["gray", "Off"] } as const;

/** One greeting helper: what kind of message WhatsApp says it is, who would really get it, and the switch. */
function Greeting({ title, helperKey, g, hours, canEdit, allowed, onChange }: { title: string; helperKey: "birthday" | "festival"; g: WaGreetingKind; hours: WaOccasions["hours"]; canEdit: boolean; allowed: boolean; onChange: () => void }) {
  const toast = useToast();
  const st = g.helper;
  const kind = greetingKindWords(g);
  const [hour, setHour] = useState(String(st.config.send_hour ?? 10)), [busy, setBusy] = useState<string | null>(null), [err, setErr] = useState<string | null>(null);
  async function set(status: "on" | "paused" | "off") {
    setBusy(status); setErr(null);
    try { await api(`/whatsapp/automations/${helperKey}`, { method: "PUT", body: { status, config: { send_hour: Number(hour) } } }); toast(status === "on" ? "Switched on." : status === "paused" ? "Paused." : "Switched off."); onChange(); }
    catch (e) { setErr(errorMessage(e)); } finally { setBusy(null); }
  }
  const [tone, word] = STATE[st.status];
  return (
    <Card>
      <div className="flex items-start justify-between gap-3"><h2 className="text-lg font-semibold text-ink">{title}</h2><Badge tone={tone}>{word}</Badge></div>
      <p className="mt-2 flex flex-wrap items-center gap-2 text-[13px] text-ink-500"><span>Kind of message:</span><Badge tone={kind.tone}>{kind.label}</Badge>{g.status && g.status !== "approved" && <Badge tone="amber">WhatsApp: {g.status}</Badge>}</p>
      {g.warning && <div className="mt-3"><Alert tone="warning" title="Who will get it">{g.warning}</Alert></div>}
      <dl className="mt-3 grid grid-cols-3 gap-2 text-center text-[13px]">
        <div className="rounded-xl bg-surface-2 p-2"><dt className="text-ink-500">Agreed to greetings</dt><dd className="mt-0.5 text-xl font-semibold tabular-nums text-ink">{g.audience.agreed}</dd></div>
        <div className="rounded-xl bg-surface-2 p-2"><dt className="text-ink-500">Would get it now</dt><dd className="mt-0.5 text-xl font-semibold tabular-nums text-ink">{g.audience.would_receive}</dd></div>
        <div className="rounded-xl bg-surface-2 p-2"><dt className="text-ink-500">{helperKey === "birthday" ? "With a birthday saved" : "Left out for now"}</dt><dd className="mt-0.5 text-xl font-semibold tabular-nums text-ink">{helperKey === "birthday" ? g.audience.with_birthday : g.audience.left_out}</dd></div>
      </dl>
      {g.body && <p className="mt-3 rounded-xl bg-surface-2 p-3 text-[13px] text-ink-700"><span className="font-semibold text-ink">What customers read: </span>{g.body.replace("{{1}}", "Asha").replace("{{2}}", "your business").replace("{{3}}", "the festival")}</p>}
      {canEdit && allowed && <div className="mt-3 max-w-xs"><Input label="Send at (India time)" type="number" min={hours.start} max={hours.end - 1} value={hour} onChange={(e) => setHour(e.target.value)} hint={`An hour from ${hours.start} to ${hours.end - 1}. Never outside ${hours.start} am to ${hours.end - 12} pm.`} /></div>}
      {err && <div className="mt-3"><Alert tone="warning">{err}</Alert></div>}
      {canEdit ? (
        <div className="mt-4 flex flex-wrap gap-2">
          {st.status !== "on" && <Button variant="brand" loading={busy === "on"} disabled={!allowed} onClick={() => void set("on")}>Switch on</Button>}
          {st.status === "on" && <><Button variant="secondary" loading={busy === "on"} onClick={() => void set("on")}>Save hour</Button><Button variant="secondary" loading={busy === "paused"} onClick={() => void set("paused")}>Pause</Button></>}
          {st.status !== "off" && <Button variant="ghost" loading={busy === "off"} onClick={() => void set("off")}>Switch off</Button>}
        </div>
      ) : <p className="mt-3 text-[13px] text-ink-500">Only the owner or an admin can change this.</p>}
    </Card>
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
      <PageHeader title="Greetings" subtitle="A short birthday or festival greeting for customers who agreed to receive one. Never an offer, never a discount." />
      {q.error && <Alert tone="error">{q.error}</Alert>}
      {!o ? <Skeleton className="h-64" /> : (
        <div className="space-y-4">
          {!o.allowed && <Alert tone="info" title="Part of the Growth and Pro plans">Birthday and festival greetings are not part of your plan. Ask the FlowQR team about upgrading.</Alert>}
          <Alert tone="info" title="The rules">{o.note} Customers agree to greetings separately from offers and visit updates, and you can record that on the <Link href="/whatsapp/contacts" className="font-semibold text-brand-700 hover:underline">Customers</Link> page.</Alert>
          <div className="grid gap-4 lg:grid-cols-2">
            <Greeting title="Birthday wishes" helperKey="birthday" g={o.birthday} hours={o.hours} canEdit={isAdmin} allowed={o.allowed} onChange={() => void q.reload()} />
            <Greeting title="Festival wishes" helperKey="festival" g={o.festival} hours={o.hours} canEdit={isAdmin} allowed={o.allowed} onChange={() => void q.reload()} />
          </div>
          <Card>
            <h2 className="text-lg font-semibold text-ink">Festivals</h2>
            <p className="mt-1 text-sm text-ink-700">Choose the festivals you want to greet your customers on. Nothing is sent for a festival you have not chosen.</p>
            {err && <div className="mt-3"><Alert tone="warning">{err}</Alert></div>}
            {o.festivals.length === 0 ? <p className="mt-3 text-[13px] text-ink-500">No upcoming festivals are on the list yet. FlowQR adds them.</p> : (
              <ul className="mt-2 divide-y divide-ink-100">{o.festivals.map((f) => (
                <li key={f.id} className="flex flex-wrap items-center justify-between gap-2 py-3">
                  <span><b className="text-ink">{f.name}</b> <span className="text-[13px] text-ink-500">{fmtDate(f.date)} · {f.region}</span></span>
                  {isAdmin ? <label className="flex items-center gap-2 text-sm text-ink-700"><input type="checkbox" className="h-4 w-4 accent-[#BD3E1B]" checked={f.enabled} onChange={(e) => void choose(f.id, e.target.checked)} />Greet my customers</label> : <Badge tone={f.enabled ? "green" : "gray"}>{f.enabled ? "Chosen" : "Not chosen"}</Badge>}
                </li>))}</ul>
            )}
          </Card>
          <p className="text-[13px] text-ink-500">What customers agree to: “{o.wording}”</p>
        </div>
      )}
    </>
  );
}
