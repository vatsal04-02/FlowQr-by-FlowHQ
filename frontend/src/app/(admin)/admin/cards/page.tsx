"use client";
import { Download, FileStack, Link2Off, Plus, Printer, QrCode, Search, UserPlus } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, CardHeader, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { ErrorSummary, FilterSelect, Input, Select, Textarea } from "@/components/ui/Form";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { useForm } from "@/lib/form";
import type { Batch, Card as CardT, CardStatus } from "@/lib/types";
import { useFetch } from "@/lib/use-api";
import { STATUS_TONE } from "@/lib/card-ui";

const PAGE = 25;
interface TenantRow { id: string; name: string }
interface Loc { id: string; name: string; city: string | null }

export default function AdminCards() {
  const toast = useToast();
  const [f, setF] = useState({ search: "", status: "", batch_id: "" });
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  useEffect(() => { const t = setTimeout(() => { setF((p) => ({ ...p, search: q })); setPage(0); }, 300); return () => clearTimeout(t); }, [q]);
  const cards = useFetch<{ total: number; items: CardT[] }>("/admin/cards", { ...f, limit: PAGE, offset: page * PAGE });
  const batches = useFetch<Batch[]>("/admin/batches");
  const [newBatch, setNewBatch] = useState(false);
  const [assign, setAssign] = useState<CardT | null>(null);
  const [view, setView] = useState<CardT | null>(null);

  async function act(c: CardT, path: string, body: unknown, msg: string) {
    try { await api(`/admin/cards/${c.id}/${path}`, { method: "POST", body }); toast(msg); void cards.reload(); } catch (e) { toast(errorMessage(e), "error"); }
  }

  return (
    <>
      <PageHeader eyebrow="Platform" title="Card inventory" subtitle="Create batches, export print files, and assign cards to business locations."
        actions={<Button icon={<Plus className="h-4 w-4" />} onClick={() => setNewBatch(true)}>New batch</Button>} />

      <Card className="mb-5" pad={false}>
        <div className="p-5 sm:p-6"><CardHeader title="Batches" subtitle="Export a ZIP (PNG + SVG per card, plus manifest.csv for NFC encoding) or a printable sheet." /></div>
        {batches.data && batches.data.length === 0 ? <p className="px-6 pb-6 text-sm text-ink-500">No batches yet.</p> : (
          <ul className="divide-y divide-ink-100 border-t border-ink-100">{batches.data?.slice(0, 8).map((b) => (
            <li key={b.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 sm:px-6">
              <div><p className="font-semibold">{b.name}</p><p className="text-sm text-ink-500">{b.quantity} cards · {b.prefix} · {fmtDate(b.created_at)}</p></div>
              <div className="flex gap-2">
                <a href={`/api/v1/admin/batches/${b.id}/export.zip`} className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-ink-200 px-3 text-sm font-semibold hover:bg-ink-50 sm:min-h-9"><Download className="h-4 w-4" aria-hidden />ZIP</a>
                <a href={`/api/v1/admin/batches/${b.id}/sheet`} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-ink-200 px-3 text-sm font-semibold hover:bg-ink-50 sm:min-h-9"><Printer className="h-4 w-4" aria-hidden />Print sheet</a>
                <Button size="sm" variant="ghost" onClick={() => { setF({ ...f, batch_id: b.id }); setPage(0); }}>Filter</Button>
              </div>
            </li>))}</ul>)}
      </Card>

      <Card pad={false} className="mb-4 p-3 sm:p-4"><div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[200px] flex-1"><Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" aria-hidden />
          <input aria-label="Search by card ID" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search card ID, e.g. FQR-0012" className="min-h-11 w-full rounded-xl border border-ink-200 pl-9 pr-3 text-sm sm:min-h-10" /></div>
        <FilterSelect label="Status" value={f.status} onChange={(e) => { setF({ ...f, status: e.target.value }); setPage(0); }}>
          <option value="">All statuses</option>{["unassigned", "assigned", "active", "paused", "deactivated", "lost"].map((s) => <option key={s} value={s}>{s}</option>)}</FilterSelect>
        {f.batch_id && <Button variant="secondary" size="sm" onClick={() => setF({ ...f, batch_id: "" })}>Clear batch filter</Button>}
      </div></Card>

      {cards.error && <Alert tone="error">{cards.error}</Alert>}
      {cards.loading && !cards.data ? <Skeleton className="h-64" /> : cards.data && cards.data.items.length === 0 ? (
        <EmptyState icon={<FileStack className="h-6 w-6" />} title="No cards found" action={<Button onClick={() => setNewBatch(true)}>Create a batch</Button>}>Generate a batch of unique cards to get started.</EmptyState>
      ) : (
        <Card pad={false}><div className="overflow-x-auto"><table className="dt min-w-[760px]">
          <thead><tr>{["Card", "Status", "Business / location", "Scans", "Visits", "Clicks", ""].map((h, i) => <th key={i} className="px-4 py-2.5 font-semibold">{h}</th>)}</tr></thead>
          <tbody>{cards.data?.items.map((c) => (
            <tr key={c.id} className="border-b border-ink-100 last:border-0">
              <td className="whitespace-nowrap px-4 py-3 font-semibold">{c.card_code}</td><td className="px-4"><Badge tone={STATUS_TONE[c.status]}>{c.status}</Badge></td>
              <td className="px-4">{c.tenant_name ? <>{c.tenant_name}<span className="block text-xs text-ink-500">{c.location_name}</span></> : <span className="text-ink-400">Unassigned</span>}</td>
              <td className="px-4 tabular-nums">{c.stats.scan ?? 0}</td><td className="px-4 tabular-nums">{c.stats.landing_view ?? 0}</td><td className="px-4 tabular-nums">{c.stats.google_click ?? 0}</td>
              <td className="px-4"><div className="flex justify-end gap-1">
                <Button size="sm" variant="ghost" aria-label={`QR for ${c.card_code}`} icon={<QrCode className="h-4 w-4" />} onClick={() => setView(c)} />
                <Button size="sm" variant="secondary" icon={<UserPlus className="h-4 w-4" />} onClick={() => setAssign(c)}>{c.tenant_id ? "Reassign" : "Assign"}</Button>
                {c.tenant_id && <Button size="sm" variant="ghost" aria-label={`Unassign ${c.card_code}`} icon={<Link2Off className="h-4 w-4" />} onClick={() => { if (confirm(`Unassign ${c.card_code}? Scan history is kept.`)) void act(c, "unassign", undefined, "Card unassigned."); }} />}
                <select aria-label={`Set status for ${c.card_code}`} value="" onChange={(e) => e.target.value && void act(c, "status", { status: e.target.value }, `Marked ${e.target.value}.`)} className="min-h-9 rounded-lg border border-ink-200 bg-white px-2 text-xs">
                  <option value="">Status…</option>{(["active", "paused", "deactivated", "lost"] as CardStatus[]).map((s) => <option key={s} value={s}>{s}</option>)}</select>
              </div></td>
            </tr>))}</tbody>
        </table></div></Card>
      )}
      {cards.data && cards.data.total > PAGE && (
        <div className="mt-4 flex items-center justify-between"><Button variant="secondary" size="sm" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</Button>
          <span className="text-sm text-ink-500">{page * PAGE + 1}–{Math.min(cards.data.total, (page + 1) * PAGE)} of {cards.data.total}</span>
          <Button variant="secondary" size="sm" disabled={(page + 1) * PAGE >= cards.data.total} onClick={() => setPage(page + 1)}>Next</Button></div>)}

      {newBatch && <BatchModal onClose={() => setNewBatch(false)} onCreated={(n) => { setNewBatch(false); toast(`Created ${n} cards.`); void batches.reload(); void cards.reload(); }} />}
      {assign && <AssignModal card={assign} onClose={() => setAssign(null)} onDone={() => { setAssign(null); toast("Card assigned."); void cards.reload(); }} />}
      {view && <Modal open onClose={() => setView(null)} title={`${view.card_code}`} footer={<Button variant="secondary" onClick={() => setView(null)}>Done</Button>}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <div className="grid place-items-center"><img src={`/api/v1/admin/cards/${view.id}/qr.svg`} alt={`QR for ${view.card_code}`} className="h-56 w-56 rounded-xl border border-ink-100 p-2" /></div>
        <p className="mt-4 break-all rounded-xl bg-ink-50 p-3 font-mono text-xs">{view.url}</p>
        <div className="mt-3 flex justify-center gap-2"><a className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-ink-200 px-4 text-sm font-semibold hover:bg-ink-50" href={`/api/v1/admin/cards/${view.id}/qr.png`}><Download className="h-4 w-4" aria-hidden />PNG</a>
          <a className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-ink-200 px-4 text-sm font-semibold hover:bg-ink-50" href={`/api/v1/admin/cards/${view.id}/qr.svg`}><Download className="h-4 w-4" aria-hidden />SVG</a></div></Modal>}
    </>
  );
}

function BatchModal({ onClose, onCreated }: { onClose: () => void; onCreated: (n: number) => void }) {
  const [busy, setBusy] = useState(false);
  const f = useForm({ name: "", quantity: "50", prefix: "FQR", notes: "" }, {
    name: (v) => (String(v).trim().length >= 2 ? undefined : "Enter a batch name"),
    quantity: (v) => { const n = Number(v); return Number.isInteger(n) && n >= 1 && n <= 2000 ? undefined : "Enter a whole number from 1 to 2000"; },
    prefix: (v) => (/^[A-Z]{2,6}$/.test(String(v)) ? undefined : "2–6 capital letters"),
  });
  async function save(e: React.FormEvent) {
    e.preventDefault(); f.setServerError(null);
    if (!f.validateAll()) return;
    setBusy(true);
    try { await api("/admin/batches", { method: "POST", body: { name: f.values.name.trim(), quantity: Number(f.values.quantity), prefix: f.values.prefix, notes: f.values.notes.trim() || null } }); onCreated(Number(f.values.quantity)); }
    catch (err) { f.fail(errorMessage(err)); } finally { setBusy(false); }
  }
  return (
    <Modal open onClose={onClose} title="New card batch" footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" form="batch-form" loading={busy}>Generate cards</Button></>}>
      <form id="batch-form" onSubmit={save} noValidate className="space-y-4">
        <ErrorSummary errors={f.errors} serverError={f.serverError} summaryRef={f.summaryRef} />
        <Input label="Batch name" required placeholder="e.g. Lucknow clinics – Nov 2026" {...f.bind("name")} />
        <div className="grid gap-4 sm:grid-cols-2"><Input label="Quantity" inputMode="numeric" required {...f.bind("quantity")} /><Input label="Code prefix" hint="Cards become FQR-0001…" {...f.bind("prefix")} /></div>
        <Textarea label="Notes (optional)" {...f.bind("notes")} />
        <p className="text-sm text-ink-500">Each card gets a unique, permanent, unguessable link.</p>
      </form>
    </Modal>
  );
}

function AssignModal({ card, onClose, onDone }: { card: CardT; onClose: () => void; onDone: () => void }) {
  const tenants = useFetch<{ items: TenantRow[] }>("/admin/tenants");
  const [tenant, setTenant] = useState(card.tenant_id ?? "");
  const locs = useFetch<Loc[]>(tenant ? `/admin/tenants/${tenant}/locations` : null);
  const [loc, setLoc] = useState("");
  const [label, setLabel] = useState(card.label ?? "");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function save() {
    setBusy(true); setErr(null);
    try { await api(`/admin/cards/${card.id}/assign`, { method: "POST", body: { tenant_id: tenant, location_id: loc, label: label.trim() || null } }); onDone(); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <Modal open onClose={onClose} title={`Assign ${card.card_code}`} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={busy} disabled={!tenant || !loc} onClick={() => void save()}>Assign card</Button></>}>
      <div className="space-y-4">
        {err && <Alert tone="error">{err}</Alert>}
        <Select label="Business" value={tenant} onChange={(e) => { setTenant(e.target.value); setLoc(""); }}><option value="">Choose a business…</option>{tenants.data?.items.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</Select>
        <Select label="Location" value={loc} disabled={!tenant} onChange={(e) => setLoc(e.target.value)}><option value="">Choose a location…</option>{locs.data?.map((l) => <option key={l.id} value={l.id}>{l.name}{l.city ? ` – ${l.city}` : ""}</option>)}</Select>
        <Input label="Label (optional)" placeholder="e.g. Reception desk" value={label} onChange={(e) => setLabel(e.target.value)} />
        {card.tenant_id && <Alert tone="warning">This card is already assigned. Reassigning keeps its scan history but future scans count for the new location.</Alert>}
      </div>
    </Modal>
  );
}
