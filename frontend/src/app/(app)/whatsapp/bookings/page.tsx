"use client";
import { Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, CardHeader, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { Input, Select } from "@/components/ui/Form";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-api";
import { BOOKING_STATUS_WORDS, bookingDay, bookingTime, hoursSummary, reminderStateWords, reminderWords, WEEKDAY_NAMES, type WaBooking, type WaBookingOverview } from "@/lib/whatsapp";

const todayIst = () => new Date(Date.now() + 5.5 * 3600 * 1000).toISOString().slice(0, 10);

/** One booking: who, when, what, and the things you can do with it. */
function Row({ b, onChange }: { b: WaBooking; onChange: () => void }) {
  const toast = useToast();
  const [moving, setMoving] = useState(false), [d, setD] = useState(b.starts_at.slice(0, 10)), [t, setT] = useState(""), [busy, setBusy] = useState<string | null>(null);
  const st = BOOKING_STATUS_WORDS[b.status];
  const started = new Date(b.starts_at).getTime() <= Date.now();
  async function act(path: string, body?: unknown, label?: string) {
    setBusy(path);
    try { const r = await api<WaBooking>(`/whatsapp/bookings/${b.id}/${path}`, { method: "POST", body: body ?? {} }); toast(label ?? "Saved."); if (r.review && !r.review.scheduled && path === "done") toast("The visit is recorded. No review request was scheduled."); onChange(); }
    catch (e) { toast(errorMessage(e)); } finally { setBusy(null); }
  }
  const remind = reminderWords(b.reminder_soon ?? b.reminder_day);
  return (
    <li className="py-3" data-testid="booking">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <b className="tabular-nums text-ink">{bookingTime(b.starts_at)}</b><span className="text-sm text-ink-700">{b.service}</span><Badge tone={st.tone}>{st.label}</Badge>
        {b.source === "ai" && <Badge tone="blue">Booked by the assistant</Badge>}
      </div>
      <p className="mt-0.5 text-sm text-ink-700">{b.customer?.name ?? "Customer"} <span className="tabular-nums text-ink-500">{b.customer?.phone}</span></p>
      {remind && b.status === "booked" && <p className="mt-0.5 text-[12px] text-ink-500">{remind}</p>}
      {b.status === "booked" && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {started && <><Button size="sm" variant="secondary" loading={busy === "done"} onClick={() => void act("done", undefined, "Visit recorded.")}>Visit done</Button><Button size="sm" variant="ghost" loading={busy === "no-show"} onClick={() => void act("no-show")}>Did not come</Button></>}
          <Button size="sm" variant="ghost" onClick={() => setMoving(!moving)}>Move</Button>
          <Button size="sm" variant="ghost" loading={busy === "cancel"} onClick={() => void act("cancel", {}, "Cancelled.")}>Cancel</Button>
        </div>)}
      {moving && (
        <form className="mt-2 flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); void act("reschedule", { date: d, time: t }, "Moved.").then(() => setMoving(false)); }}>
          <Input label="New date" type="date" value={d} min={todayIst()} onChange={(e) => setD(e.target.value)} /><Input label="New time" type="time" value={t} onChange={(e) => setT(e.target.value)} />
          <Button size="sm" variant="brand" type="submit" disabled={!t}>Move it</Button>
        </form>)}
    </li>
  );
}

function NewBooking({ ov, onChange, version }: { ov: WaBookingOverview; onChange: () => void; version: number }) {
  const toast = useToast();
  const active = ov.services.filter((s) => s.active);
  const [sid, setSid] = useState(active[0]?.id ?? ""), [d, setD] = useState(todayIst()), [t, setT] = useState(""), [phone, setPhone] = useState(""), [name, setName] = useState(""), [agreed, setAgreed] = useState(false), [how, setHow] = useState("");
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null);
  const slots = useFetch<{ slots: { time: string; label: string }[] }>(sid ? `/whatsapp/bookings/slots?service_id=${sid}&day=${d}&v=${version}` : null);
  async function save() {
    setBusy(true); setErr(null);
    try { await api("/whatsapp/bookings", { method: "POST", body: { service_id: sid, date: d, time: t, phone, name: name || null, agreed_to_updates: agreed, agreed_evidence: agreed ? how : null, client_id: `${sid}${d}${t}${phone}` } }); toast("Booked."); setT(""); setPhone(""); setName(""); setAgreed(false); setHow(""); onChange(); }
    catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <Card>
      <CardHeader title="Book a customer in" subtitle="Pick a service and a free time. This does not send the customer anything or record any agreement by itself." />
      <div className="grid gap-3 sm:grid-cols-2">
        <Select label="Service" value={sid} onChange={(e) => { setSid(e.target.value); setT(""); }}>{active.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.duration_minutes} min)</option>)}</Select>
        <Input label="Date" type="date" value={d} min={todayIst()} onChange={(e) => { setD(e.target.value); setT(""); }} />
      </div>
      <div className="mt-3" role="group" aria-label="Free times">
        <p className="mb-1 text-sm font-medium text-ink">Free times</p>
        {!slots.data ? <Skeleton className="h-10" /> : slots.data.slots.length === 0 ? <p className="text-sm text-ink-500">Nothing free on this day.</p> : <div className="flex flex-wrap gap-1.5">{slots.data.slots.map((s) => <button key={s.time} type="button" aria-pressed={t === s.time} onClick={() => setT(s.time)} className={`rounded-full border px-3 py-1 text-[13px] tabular-nums ${t === s.time ? "border-brand-500 bg-brand-50 text-ink" : "border-ink-200 text-ink-700"}`}>{s.label}</button>)}</div>}
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2"><Input label="Customer phone" inputMode="tel" value={phone} onChange={(e) => setPhone(e.target.value)} /><Input label="Customer name (optional)" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} /></div>
      <label className="mt-3 flex items-start gap-2 text-sm text-ink-700"><input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} className="mt-0.5 h-4 w-4 accent-[#BD3E1B]" />The customer agreed to get reminders and updates about this visit on WhatsApp</label>
      {agreed && <div className="mt-2"><Input label="How did they agree?" value={how} maxLength={400} onChange={(e) => setHow(e.target.value)} hint="For example: asked at the counter and wrote it in the register." /></div>}
      {err && <div className="mt-3"><Alert tone="warning">{err}</Alert></div>}
      <Button className="mt-3" variant="brand" loading={busy} disabled={!sid || !t || !phone.trim() || (agreed && how.trim().length < 10)} onClick={() => void save()}>Book</Button>
    </Card>
  );
}

function Calendar({ ov }: { ov: WaBookingOverview }) {
  const q = useFetch<{ items: WaBooking[] }>("/whatsapp/bookings");
  const [version, setVersion] = useState(0);
  const changed = () => { void q.reload(); setVersion((v) => v + 1); };  // any change to the calendar also refreshes the free times
  const groups = useMemo(() => { const m = new Map<string, WaBooking[]>(); for (const b of q.data?.items ?? []) { const k = bookingDay(b.starts_at); m.set(k, [...(m.get(k) ?? []), b]); } return [...m.entries()]; }, [q.data]);
  return (
    <div className="space-y-5">
      <NewBooking ov={ov} onChange={changed} version={version} />
      <Card>
        <CardHeader title="Coming up" subtitle="The next two weeks, in India time." />
        {!q.data ? <Skeleton className="h-24" /> : groups.length === 0 ? <EmptyState title="No bookings yet">Bookings you make here, and ones the assistant makes in chats, show up here.</EmptyState> : groups.map(([day, rows]) => (
          <section key={day} aria-label={day} className="mb-3"><h3 className="text-sm font-semibold text-ink">{day}</h3><ul className="divide-y divide-ink-100">{rows.map((b) => <Row key={b.id} b={b} onChange={changed} />)}</ul></section>))}
      </Card>
    </div>
  );
}

function Setup({ ov, onChange, isAdmin }: { ov: WaBookingOverview; onChange: () => void; isAdmin: boolean }) {
  const toast = useToast();
  const s = ov.settings;
  const [f, setF] = useState({ capacity: String(s.capacity), step: String(s.slot_step_minutes), notice: String(s.min_notice_minutes), ahead: String(s.max_days_ahead), dayHour: String(s.reminder_day_hour), soon: String(s.reminder_soon_hours) });
  const [rows, setRows] = useState(() => WEEKDAY_NAMES.map((_, i) => { const h = ov.hours.find((x) => x.weekday === i); return { weekday: i, open: !!h, opens: h?.opens ?? "09:00", closes: h?.closes ?? "18:00" }; }));
  const [svc, setSvc] = useState({ name: "", duration: "45", buffer: "0", price: "" }), [closedDay, setClosedDay] = useState(""), [closedWhy, setClosedWhy] = useState("");
  const [busy, setBusy] = useState<string | null>(null), [err, setErr] = useState<string | null>(null);
  async function call(label: string, path: string, method: string, body?: unknown, ok = "Saved.") {
    setBusy(label); setErr(null);
    try { await api(path, { method, body }); toast(ok); onChange(); return true; } catch (e) { setErr(errorMessage(e)); return false; } finally { setBusy(null); }
  }
  const saveSettings = (extra: Record<string, unknown> = {}) => call("settings", "/whatsapp/bookings/settings", "PUT", { capacity: Number(f.capacity), slot_step_minutes: Number(f.step), min_notice_minutes: Number(f.notice), max_days_ahead: Number(f.ahead), reminder_day_hour: Number(f.dayHour), reminder_soon_hours: Number(f.soon), ...extra });
  const saveHours = () => call("hours", "/whatsapp/bookings/hours", "PUT", { days: rows.filter((r) => r.open).map((r) => ({ weekday: r.weekday, opens: r.opens, closes: r.closes })) });
  const dis = !isAdmin;
  return (
    <div className="space-y-5">
      {err && <Alert tone="warning">{err}</Alert>}
      <Card>
        <div className="flex flex-wrap items-center gap-2"><h2 className="text-lg font-semibold text-ink">Bookings</h2>{s.enabled ? <Badge tone="green">On</Badge> : <Badge>Off</Badge>}</div>
        <p className="mt-1 text-sm text-ink-700">Turn bookings on when your services and opening hours are set. The assistant, if you use it, can then offer real free times and book customers in. The server checks every booking; nobody can double-book a time.</p>
        {ov.setup_needed.length > 0 && <div className="mt-3"><Alert tone="info" title="Still to do">{ov.setup_needed.join(". ")}.</Alert></div>}
        <div className="mt-3 grid gap-3 sm:grid-cols-4">
          <Input label="How many at once" type="number" min={1} max={50} value={f.capacity} disabled={dis} onChange={(e) => setF({ ...f, capacity: e.target.value })} hint="Chairs, rooms or practitioners." />
          <Input label="Time step (minutes)" type="number" min={5} max={120} value={f.step} disabled={dis} onChange={(e) => setF({ ...f, step: e.target.value })} />
          <Input label="Least notice (minutes)" type="number" min={0} value={f.notice} disabled={dis} onChange={(e) => setF({ ...f, notice: e.target.value })} hint="For the assistant. You can always book sooner." />
          <Input label="Days ahead" type="number" min={1} max={180} value={f.ahead} disabled={dis} onChange={(e) => setF({ ...f, ahead: e.target.value })} />
        </div>
        {isAdmin && <div className="mt-3 flex gap-2"><Button variant="secondary" loading={busy === "settings"} onClick={() => void saveSettings()}>Save</Button>{s.enabled ? <Button variant="ghost" onClick={() => void saveSettings({ enabled: false })}>Turn bookings off</Button> : <Button variant="brand" onClick={() => void saveSettings({ enabled: true })}>Turn bookings on</Button>}</div>}
      </Card>
      <Card>
        <CardHeader title="Services" subtitle="What customers can book. The gap is kept free after each visit." />
        <ul className="divide-y divide-ink-100">{ov.services.map((x) => <li key={x.id} className="flex items-center justify-between gap-3 py-2 text-sm"><span className="text-ink-700"><b className="text-ink">{x.name}</b> · {x.duration_minutes} min{x.buffer_minutes ? ` + ${x.buffer_minutes} gap` : ""}{x.price_inr !== null ? ` · ₹${x.price_inr}` : ""}</span>{isAdmin && <Button size="sm" variant="ghost" aria-label={`Delete ${x.name}`} onClick={() => void call("del" + x.id, `/whatsapp/bookings/services/${x.id}`, "DELETE", undefined, "Removed.")}><Trash2 size={15} /></Button>}</li>)}</ul>
        {isAdmin && <form className="mt-3 grid gap-3 sm:grid-cols-5" onSubmit={(e) => { e.preventDefault(); void call("svc", "/whatsapp/bookings/services", "POST", { name: svc.name, duration_minutes: Number(svc.duration), buffer_minutes: Number(svc.buffer), price_inr: svc.price || null }).then((ok) => ok && setSvc({ name: "", duration: "45", buffer: "0", price: "" })); }}>
          <div className="sm:col-span-2"><Input label="Service name" value={svc.name} maxLength={120} onChange={(e) => setSvc({ ...svc, name: e.target.value })} /></div>
          <Input label="Minutes" type="number" value={svc.duration} onChange={(e) => setSvc({ ...svc, duration: e.target.value })} /><Input label="Gap after" type="number" value={svc.buffer} onChange={(e) => setSvc({ ...svc, buffer: e.target.value })} /><Input label="Price ₹ (optional)" inputMode="decimal" value={svc.price} onChange={(e) => setSvc({ ...svc, price: e.target.value })} />
          <div className="sm:col-span-5"><Button variant="secondary" type="submit" loading={busy === "svc"} disabled={svc.name.trim().length < 2}>Add service</Button></div></form>}
      </Card>
      <Card>
        <CardHeader title="Opening hours" subtitle={hoursSummary(ov.hours)} />
        <ul className="space-y-1.5">{rows.map((r, i) => (
          <li key={r.weekday} className="flex flex-wrap items-center gap-3 text-sm"><label className="flex w-36 items-center gap-2 text-ink-700"><input type="checkbox" checked={r.open} disabled={dis} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, open: e.target.checked } : x)))} className="h-4 w-4 accent-[#BD3E1B]" />{WEEKDAY_NAMES[r.weekday]}</label>
            {r.open ? <><input aria-label={`${WEEKDAY_NAMES[r.weekday]} opens`} type="time" value={r.opens} disabled={dis} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, opens: e.target.value } : x)))} className="rounded-lg border border-ink-200 px-2 py-1" />to<input aria-label={`${WEEKDAY_NAMES[r.weekday]} closes`} type="time" value={r.closes} disabled={dis} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, closes: e.target.value } : x)))} className="rounded-lg border border-ink-200 px-2 py-1" /></> : <span className="text-ink-500">Closed</span>}</li>))}</ul>
        {isAdmin && <Button className="mt-3" variant="secondary" loading={busy === "hours"} onClick={() => void saveHours()}>Save hours</Button>}
        <h3 className="mt-5 text-sm font-semibold text-ink">Closed days</h3>
        <ul className="divide-y divide-ink-100">{ov.closed.map((c) => <li key={c.id} className="flex items-center justify-between py-1.5 text-sm text-ink-700"><span>{c.day}{c.reason ? ` · ${c.reason}` : ""}</span>{isAdmin && <Button size="sm" variant="ghost" onClick={() => void call("c" + c.id, `/whatsapp/bookings/closed-days/${c.id}`, "DELETE", undefined, "Removed.")}>Remove</Button>}</li>)}</ul>
        {isAdmin && <div className="mt-2 flex flex-wrap items-end gap-2"><Input label="Closed on" type="date" value={closedDay} onChange={(e) => setClosedDay(e.target.value)} /><Input label="Why (optional)" value={closedWhy} maxLength={120} onChange={(e) => setClosedWhy(e.target.value)} /><Button variant="secondary" disabled={!closedDay} onClick={() => void call("closed", "/whatsapp/bookings/closed-days", "POST", { day: closedDay, reason: closedWhy || null }).then((ok) => ok && setClosedDay(""))}>Add</Button></div>}
      </Card>
      <Card>
        <CardHeader title="Reminders" subtitle="Two fixed messages: one the day before, one a few hours before." />
        <Alert tone="info" title="Who gets a reminder">{ov.reminder_note}</Alert>
        <div className="mt-3 grid gap-3 sm:grid-cols-2"><Input label="Day-before reminder at (hour, 9 to 20)" type="number" min={9} max={20} value={f.dayHour} disabled={dis} onChange={(e) => setF({ ...f, dayHour: e.target.value })} /><Input label="Second reminder this many hours before" type="number" min={1} max={6} value={f.soon} disabled={dis} onChange={(e) => setF({ ...f, soon: e.target.value })} /></div>
        <ul className="mt-3 space-y-3">{(["booking_reminder_day", "booking_reminder_soon"] as const).map((k) => { const t = ov.reminder_templates[k]; return (
          <li key={k} className="rounded-xl bg-surface-2 p-3 text-sm"><p className="text-ink-700">{t?.body}</p><p className="mt-1 text-[13px] text-ink-500" data-testid={`state-${k}`}>{reminderStateWords(t)}</p>
            {isAdmin && !t?.submitted && <Button className="mt-2" size="sm" variant="secondary" loading={busy === k} onClick={() => void call(k, "/whatsapp/templates/install", "POST", { key: k }, "Sent to WhatsApp for approval.")}>Send for approval</Button>}</li>); })}</ul>
        {isAdmin && <div className="mt-3 flex gap-2"><Button variant="secondary" loading={busy === "settings"} onClick={() => void saveSettings()}>Save times</Button>{s.reminders_enabled ? <Button variant="ghost" onClick={() => void saveSettings({ reminders_enabled: false })}>Turn reminders off</Button> : <Button variant="brand" onClick={() => void saveSettings({ reminders_enabled: true })}>Turn reminders on</Button>}</div>}
      </Card>
    </div>
  );
}

export default function Bookings() {
  const { isAdmin } = useAuth();
  const ov = useFetch<WaBookingOverview>("/whatsapp/bookings/overview");
  const [tab, setTab] = useState<"calendar" | "setup">("calendar");
  const d = ov.data;
  return (
    <div className="space-y-5">
      <PageHeader title="Bookings" subtitle="Appointments for your customers, made by your team or by the assistant in a chat." />
      {!d ? <Skeleton className="h-48" /> : (
        <>
          {!d.platform_on && <Alert tone="info" title="Not available yet">Bookings have not been switched on for everyone yet.</Alert>}
          {d.platform_on && !d.plan_ok && <Alert tone="info" title="Part of the Growth and Pro add-ons">Ask the FlowQR team to move your WhatsApp add-on to Growth or Pro.</Alert>}
          {d.platform_on && d.plan_ok && (
            <>
              <div className="flex gap-1.5" role="tablist">{(["calendar", "setup"] as const).map((k) => <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)} className={`rounded-full border px-4 py-1.5 text-sm ${tab === k ? "border-brand-500 bg-brand-50 text-ink" : "border-ink-200 text-ink-700"}`}>{k === "calendar" ? "Calendar" : "Set up"}</button>)}</div>
              {tab === "calendar" ? (d.active ? <Calendar ov={d} /> : <Alert tone="info" title="Bookings are off">Open Set up, add a service and your opening hours, then turn bookings on.</Alert>) : <Setup ov={d} onChange={() => void ov.reload()} isAdmin={isAdmin} />}
            </>)}
        </>)}
    </div>
  );
}
