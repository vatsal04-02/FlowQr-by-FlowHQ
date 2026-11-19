"use client";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, CardHeader, PageHeader, Skeleton } from "@/components/ui/Card";
import { Input } from "@/components/ui/Form";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { useFetch } from "@/lib/use-api";
import type { WaFestival } from "@/lib/whatsapp";

/** The dated festival list. A business greets its customers only on festivals it chose, and only customers who agreed to greetings. A festival is switched off, never deleted. */
export default function WhatsAppFestivals() {
  const toast = useToast();
  const q = useFetch<{ items: WaFestival[]; note: string }>("/admin/whatsapp/festivals");
  const [f, setF] = useState({ name: "", date: "", region: "All India" }), [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null);
  async function add() {
    if (!/^[A-Za-z][A-Za-z '’-]{1,39}$/.test(f.name.trim())) { setErr("Use 2 to 40 letters for the festival's name. Numbers and symbols are not allowed."); return; }
    if (!f.date) { setErr("Choose the date."); return; }
    setBusy(true); setErr(null);
    try { await api("/admin/whatsapp/festivals", { method: "POST", body: { name: f.name.trim(), festival_date: f.date, region: f.region.trim() || "All India" } }); toast("Festival added."); setF({ ...f, name: "", date: "" }); void q.reload(); }
    catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  async function toggle(x: WaFestival) {
    try { await api(`/admin/whatsapp/festivals/${x.id}`, { method: "PATCH", body: { active: !x.active } }); void q.reload(); } catch (e) { toast(errorMessage(e)); }
  }
  return (
    <>
      <PageHeader eyebrow="Platform" title="WhatsApp festivals" subtitle="The dated list businesses choose from for festival greetings." />
      {q.error && <Alert tone="error">{q.error}</Alert>}
      <div className="space-y-4">
        <Card>
          <CardHeader title="Add a festival" subtitle="Use only the festival's own name. A name that sounds like an offer (sale, free, discount and so on) is refused, because a greeting is never an offer." />
          <div className="grid items-start gap-3 sm:grid-cols-3">
            <Input label="Name" value={f.name} maxLength={40} onChange={(e) => setF({ ...f, name: e.target.value })} hint="For example: Diwali." />
            <Input label="Date" type="date" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} />
            <Input label="Region" value={f.region} maxLength={40} onChange={(e) => setF({ ...f, region: e.target.value })} hint="All India, or a state." />
          </div>
          {err && <div className="mt-3"><Alert tone="warning">{err}</Alert></div>}
          <div className="mt-3"><Button variant="brand" loading={busy} onClick={() => void add()}>Add festival</Button></div>
        </Card>
        <Card>
          <CardHeader title="The list" subtitle={q.data?.note} />
          {!q.data ? <Skeleton className="h-24" /> : q.data.items.length === 0 ? <p className="text-sm text-ink-500">No festivals yet. Businesses see nothing to choose until you add some.</p> : (
            <ul className="divide-y divide-ink-100">{q.data.items.map((x) => (
              <li key={x.id} className="flex flex-wrap items-center justify-between gap-2 py-3">
                <span><b className="text-ink">{x.name}</b> <span className="text-[13px] text-ink-500">{fmtDate(x.date)} · {x.region}</span> <Badge tone={x.active ? "green" : "gray"}>{x.active ? "On the list" : "Switched off"}</Badge></span>
                <Button variant="secondary" size="sm" onClick={() => void toggle(x)}>{x.active ? "Switch off" : "Switch on"}</Button>
              </li>))}</ul>
          )}
        </Card>
      </div>
    </>
  );
}
