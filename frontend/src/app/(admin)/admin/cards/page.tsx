"use client";
import { API_V1 } from "@/lib/config";
import { Archive, Download, FileStack, FileText, Image as ImageIcon, Link2Off, PackageCheck, Plus, QrCode, Search, UserPlus } from "lucide-react";
import { useEffect, useState } from "react";
import { AssignCards } from "@/components/cards/AssignCards";
import { PosterDownload } from "@/components/cards/PosterDownload";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, CardHeader, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { ErrorSummary, FilterSelect, Input, Select, Textarea } from "@/components/ui/Form";
import { Segmented } from "@/components/ui/kit";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api, ApiError, apiFile, errorMessage, saveBlob } from "@/lib/api";
import { CARD_LIFECYCLE, CARD_STATUS, STATUS_TONE } from "@/lib/card-ui";
import { fmtDate, fmtNum } from "@/lib/format";
import { useForm } from "@/lib/form";
import type { Batch, Card as CardT } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

const PAGE = 25;
const SIZES = [50, 100, 250, 500];
interface Inventory { counts: Record<string, number>; available: number; in_use: number; batches: (Batch & { counts: Record<string, number> })[] }
interface TenantRow { id: string; name: string }
interface Opt { id: string; name: string; city?: string | null; location_id?: string | null; status?: string }

export default function AdminCards() {
  const toast = useToast();
  const [tab, setTab] = useState<"inventory" | "assign">("inventory");
  const [f, setF] = useState({ search: "", status: "", batch_id: "" });
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  useEffect(() => { const t = setTimeout(() => { setF((p) => ({ ...p, search: q })); setPage(0); }, 300); return () => clearTimeout(t); }, [q]);
  const cards = useFetch<{ total: number; items: CardT[] }>("/admin/cards", { ...f, limit: PAGE, offset: page * PAGE });
  const inv = useFetch<Inventory>("/admin/inventory");
  const [newBatch, setNewBatch] = useState(false);
  const [assign, setAssign] = useState<CardT | null>(null);
  const [reserve, setReserve] = useState<CardT | null>(null);
  const [view, setView] = useState<CardT | null>(null);
  const [printProblem, setPrintProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = () => { void cards.reload(); void inv.reload(); };

  /** Run a card action. A 409 "confirmation_required" is explained and, if confirmed in the browser, repeated with confirm: true. */
  async function act(c: CardT, path: string, body: Record<string, unknown>, msg: string, ask?: string) {
    if (ask && !confirm(ask)) return;
    try { await api(`/admin/cards/${c.id}/${path}`, { method: "POST", body }); toast(msg); refresh(); }
    catch (e) {
      if (e instanceof ApiError && e.code === "confirmation_required" && !body.confirm && confirm(`${e.message}\n\nContinue?`)) return act(c, path, { ...body, confirm: true }, msg);
      toast(errorMessage(e), "error");
    }
  }

  /** Download a print file. A temporary public address (localhost, a tunnel) is refused by the server; say so plainly instead of saving an error page. */
  async function getFile(path: string, name: string, key: string) {
    setBusy(key); setPrintProblem(null);
    try { const { blob, headers } = await apiFile(path); saveBlob(blob, name); toast(`Downloaded ${name}${headers.get("x-flowqr-codes") ? ` (${headers.get("x-flowqr-codes")} cards)` : ""}.`); }
    catch (e) {
      if (e instanceof ApiError && e.code === "print_domain_not_permanent") setPrintProblem(e.message);
      else toast(errorMessage(e), "error");
    } finally { setBusy(null); }
  }

  const counts = inv.data?.counts ?? {};
  return (
    <>
      <PageHeader eyebrow="Platform" title="Card inventory" subtitle="Make batches before you know who they are for, print them, then assign each card to a business by scanning it."
        actions={<><Segmented label="Section" value={tab} onChange={setTab} options={[["inventory", "Inventory"], ["assign", "Assign cards"]] as const} />
          <Button icon={<Plus className="h-4 w-4" />} onClick={() => setNewBatch(true)}>New batch</Button></>} />

      {printProblem && <div className="mb-4"><Alert tone="error" title="Not printable yet">{printProblem}</Alert></div>}

      {tab === "assign" ? <AssignCards mode="admin" onDone={refresh} /> : (
        <>
          <section aria-label="Stock" className="mb-5 grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-ink-100 bg-ink-100 sm:grid-cols-4 lg:grid-cols-8" data-testid="stock-strip">
            {CARD_LIFECYCLE.map((s) => (
              <button key={s} onClick={() => { setF({ ...f, status: f.status === s ? "" : s }); setPage(0); }} aria-pressed={f.status === s}
                className={`bg-white p-3 text-left hover:bg-ink-50 ${f.status === s ? "ring-2 ring-inset ring-brand-600" : ""}`}>
                <p className="num text-2xl font-bold leading-none">{inv.data ? fmtNum(counts[s] ?? 0) : "–"}</p><p className="mt-1 text-xs text-ink-500">{CARD_STATUS[s].label.replace(" for you", "")}</p>
              </button>))}
          </section>

          <Card className="mb-5" pad={false}>
            <div className="p-5 sm:p-6"><CardHeader title="Batches" subtitle={inv.data ? `${fmtNum(inv.data.available)} cards in stock · ${fmtNum(inv.data.in_use)} in use` : "Print sheets, NFC lists and files for each batch."} /></div>
            {inv.data && inv.data.batches.length === 0 ? <p className="px-6 pb-6 text-sm text-ink-500">No batches yet. Generate 50, 100, 250 or 500 cards to start.</p> : (
              <ul className="divide-y divide-ink-100 border-t border-ink-100">{inv.data?.batches.slice(0, 8).map((b) => (
                <li key={b.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 sm:px-6" data-testid="batch-row">
                  <div className="min-w-0"><p className="font-semibold">{b.name}</p>
                    <p className="text-sm text-ink-500">{b.quantity} cards · {b.prefix} · {fmtDate(b.created_at)} · {b.released_at ? <span className="text-green-700">printed, in stock</span> : <span className="text-amber-700">not marked printed</span>}</p></div>
                  <div className="flex flex-wrap gap-2">
                    {!b.released_at && <Button size="sm" icon={<PackageCheck className="h-4 w-4" />} loading={busy === `rel${b.id}`} onClick={async () => { setBusy(`rel${b.id}`); try { await api(`/admin/batches/${b.id}/release`, { method: "POST" }); toast("Batch marked printed and in stock."); refresh(); } catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(null); } }}>Mark printed</Button>}
                    <Button size="sm" variant="secondary" icon={<FileText className="h-4 w-4" />} loading={busy === `pp${b.id}`} onClick={() => void getFile(`/admin/batches/${b.id}/posters.pdf`, `${b.prefix}-poster-sheets.pdf`, `pp${b.id}`)}>Poster sheets (PDF)</Button>
                    {Array.from({ length: Math.ceil(b.quantity / 100) }, (_, i) => (
                      <Button key={i} size="sm" variant="ghost" icon={<ImageIcon className="h-4 w-4" />} loading={busy === `pz${b.id}${i}`} aria-label={`Poster PNG files ${i * 100 + 1} to ${Math.min(b.quantity, (i + 1) * 100)}`}
                        onClick={() => void getFile(`/admin/batches/${b.id}/posters.zip?fmt=png&offset=${i * 100}&limit=100`, `${b.prefix}-posters-${i * 100 + 1}-${Math.min(b.quantity, (i + 1) * 100)}.zip`, `pz${b.id}${i}`)}>
                        PNG {i * 100 + 1}–{Math.min(b.quantity, (i + 1) * 100)}</Button>))}
                    <Button size="sm" variant="secondary" icon={<Download className="h-4 w-4" />} loading={busy === `csv${b.id}`} onClick={() => void getFile(`/admin/batches/${b.id}/inventory.csv`, `${b.prefix}-inventory.csv`, `csv${b.id}`)}>Inventory + NFC list (CSV)</Button>
                    <Button size="sm" variant="ghost" loading={busy === `zip${b.id}`} onClick={() => void getFile(`/admin/batches/${b.id}/export.zip`, `${b.prefix}-codes.zip`, `zip${b.id}`)}>Plain codes (ZIP)</Button>
                    <Button size="sm" variant="ghost" onClick={() => { setF({ ...f, batch_id: b.id }); setPage(0); }}>Show cards</Button>
                  </div>
                </li>))}</ul>)}
          </Card>

          <Card pad={false} className="mb-4 p-3 sm:p-4"><div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-[200px] flex-1"><Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" aria-hidden />
              <input aria-label="Search by serial number" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search serial, e.g. FQR-0012" className="min-h-11 w-full rounded-xl border border-ink-200 pl-9 pr-3 text-sm sm:min-h-10" /></div>
            <FilterSelect label="Status" value={f.status} onChange={(e) => { setF({ ...f, status: e.target.value }); setPage(0); }}>
              <option value="">All statuses</option>{[...CARD_LIFECYCLE, "deactivated", "lost"].map((s) => <option key={s} value={s}>{s}</option>)}</FilterSelect>
            {f.batch_id && <Button variant="secondary" size="sm" onClick={() => setF({ ...f, batch_id: "" })}>Clear batch filter</Button>}
          </div></Card>

          {cards.error && <Alert tone="error">{cards.error}</Alert>}
          {cards.loading && !cards.data ? <Skeleton className="h-64" /> : cards.data && cards.data.items.length === 0 ? (
            <EmptyState icon={<FileStack className="h-6 w-6" />} title="No cards found" action={<Button onClick={() => setNewBatch(true)}>Create a batch</Button>}>Generate a batch of unique cards to get started.</EmptyState>
          ) : (
            <Card pad={false}><div className="overflow-x-auto"><table className="dt min-w-[980px]">
              <thead><tr>{["Card", "Status", "Business / location", "Review page", "QR", "NFC", "Visits", ""].map((h, i) => <th key={i} className="px-4 py-2.5 font-semibold">{h}</th>)}</tr></thead>
              <tbody>{cards.data?.items.map((c) => (
                <tr key={c.id} className="border-b border-ink-100 last:border-0" data-testid="card-row">
                  <td className="whitespace-nowrap px-4 py-3 font-semibold">{c.card_code}{c.batch_name && <span className="block text-xs font-normal text-ink-500">{c.batch_name}</span>}</td>
                  <td className="px-4"><Badge tone={STATUS_TONE[c.status]}>{c.status}</Badge></td>
                  <td className="px-4">{c.tenant_name ? <>{c.tenant_name}<span className="block text-xs text-ink-500">{c.location_name ?? "no location yet"}</span></> : <span className="text-ink-400">In stock</span>}</td>
                  <td className="px-4 text-sm">{c.campaign_name ?? (c.tenant_id ? <span className="text-ink-500">Plain page</span> : "")}</td>
                  <td className="px-4 tabular-nums">{c.stats.qr_scan ?? 0}</td><td className="px-4 tabular-nums">{c.stats.nfc_scan ?? 0}</td><td className="px-4 tabular-nums">{c.stats.landing_view ?? 0}</td>
                  <td className="px-4"><div className="flex flex-wrap justify-end gap-1">
                    <Button size="sm" variant="ghost" aria-label={`QR for ${c.card_code}`} icon={<QrCode className="h-4 w-4" />} onClick={() => setView(c)} />
                    {c.status !== "retired" && <PosterDownload path={`/admin/cards/${c.id}/poster`} filename={c.card_code} label="Poster" variant="ghost" />}
                    {(c.status === "generated" || c.status === "unassigned") && <Button size="sm" variant="secondary" onClick={() => setReserve(c)}>Reserve</Button>}
                    {c.status !== "retired" && c.status !== "archived" && <Button size="sm" variant="secondary" icon={<UserPlus className="h-4 w-4" />} onClick={() => setAssign(c)}>{c.location_id ? "Change" : "Assign"}</Button>}
                    {c.tenant_id && c.status !== "retired" && <Button size="sm" variant="ghost" aria-label={`Return ${c.card_code} to stock`} icon={<Link2Off className="h-4 w-4" />}
                      onClick={() => void act(c, "unassign", {}, `${c.card_code} is back in stock.`)} />}
                    {(c.status === "generated" || c.status === "unassigned") && <Button size="sm" variant="ghost" aria-label={`Archive ${c.card_code}`} icon={<Archive className="h-4 w-4" />} onClick={() => void act(c, "archive", {}, "Archived.")} />}
                    {c.status === "archived" && <Button size="sm" variant="ghost" onClick={() => void act(c, "unarchive", {}, "Back in stock.")}>Restore</Button>}
                    {c.status !== "retired" && <Button size="sm" variant="ghost" onClick={() => void act(c, "retire", { confirm: true }, `${c.card_code} retired.`, `Retire ${c.card_code} permanently?\n\nAnyone who scans or taps it will see that it is no longer active, and it can never be used again. History is kept.`)}>Retire</Button>}
                  </div></td>
                </tr>))}</tbody>
            </table></div></Card>
          )}
          {cards.data && cards.data.total > PAGE && (
            <div className="mt-4 flex items-center justify-between"><Button variant="secondary" size="sm" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</Button>
              <span className="text-sm text-ink-500">{page * PAGE + 1}–{Math.min(cards.data.total, (page + 1) * PAGE)} of {cards.data.total}</span>
              <Button variant="secondary" size="sm" disabled={(page + 1) * PAGE >= cards.data.total} onClick={() => setPage(page + 1)}>Next</Button></div>)}
        </>
      )}

      {newBatch && <BatchModal onClose={() => setNewBatch(false)} onCreated={(n) => { setNewBatch(false); toast(`Created ${n} cards. Print them, then mark the batch printed.`); refresh(); }} />}
      {assign && <AssignModal card={assign} onClose={() => setAssign(null)} onDone={() => { setAssign(null); toast("Card assigned."); refresh(); }} />}
      {reserve && <ReserveModal card={reserve} onClose={() => setReserve(null)} onDone={() => { setReserve(null); toast("Card reserved. The business can now give it a location."); refresh(); }} />}
      {view && <Modal open onClose={() => setView(null)} title={`${view.card_code}`} footer={<Button variant="secondary" onClick={() => setView(null)}>Done</Button>}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <div className="grid place-items-center"><img src={`${API_V1}/admin/cards/${view.id}/qr.svg`} alt={`QR for ${view.card_code}`} className="h-56 w-56 rounded-xl border border-ink-100 p-2" /></div>
        <dl className="mt-4 space-y-2 text-xs"><div><dt className="font-semibold text-ink-700">Printed QR address</dt><dd className="break-all rounded-xl bg-ink-50 p-3 font-mono">{view.url}</dd></div>
          <div><dt className="font-semibold text-ink-700">NFC tag address (write as a URL record)</dt><dd className="break-all rounded-xl bg-ink-50 p-3 font-mono">{view.nfc_url}</dd></div></dl>
      </Modal>}
    </>
  );
}

function BatchModal({ onClose, onCreated }: { onClose: () => void; onCreated: (n: number) => void }) {
  const [busy, setBusy] = useState(false);
  const f = useForm({ name: "", quantity: "100", prefix: "FQR", notes: "" }, {
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
        <Input label="Batch name" required placeholder="e.g. Pre-print run – Nov 2026" {...f.bind("name")} />
        <fieldset>
          <legend className="mb-1.5 text-sm font-semibold">How many cards?</legend>
          <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Batch size">
            {SIZES.map((n) => (
              <button key={n} type="button" role="radio" aria-checked={Number(f.values.quantity) === n} onClick={() => f.set("quantity", String(n))}
                className={`min-h-11 min-w-[72px] rounded-xl border px-4 text-sm font-semibold ${Number(f.values.quantity) === n ? "border-brand-600 bg-brand-50 text-brand-800" : "border-ink-200 hover:bg-ink-50"}`}>{n}</button>))}
          </div>
        </fieldset>
        <div className="grid gap-4 sm:grid-cols-2"><Input label="Or another number" inputMode="numeric" {...f.bind("quantity")} /><Input label="Code prefix" hint="Serials become FQR-0001…" {...f.bind("prefix")} /></div>
        <Textarea label="Notes (optional)" {...f.bind("notes")} />
        <p className="text-sm text-ink-500">Every card gets a unique, permanent, unguessable identity with a printed-QR address and an NFC address. They are not tied to any business yet, so you can print first and assign later.</p>
      </form>
    </Modal>
  );
}

function ReserveModal({ card, onClose, onDone }: { card: CardT; onClose: () => void; onDone: () => void }) {
  const tenants = useFetch<{ items: TenantRow[] }>("/admin/tenants");
  const [tenant, setTenant] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function save() { setBusy(true); setErr(null); try { await api(`/admin/cards/${card.id}/reserve`, { method: "POST", body: { tenant_id: tenant } }); onDone(); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); } }
  return (
    <Modal open onClose={onClose} title={`Reserve ${card.card_code}`} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={busy} disabled={!tenant} onClick={() => void save()}>Reserve</Button></>}>
      <div className="space-y-4">{err && <Alert tone="error">{err}</Alert>}
        <Select label="Business" value={tenant} onChange={(e) => setTenant(e.target.value)}><option value="">Choose a business…</option>{tenants.data?.items.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</Select>
        <p className="text-sm text-ink-500">The card stays switched off. The business will see it and can scan it to give it a location and review page.</p></div>
    </Modal>
  );
}

function AssignModal({ card, onClose, onDone }: { card: CardT; onClose: () => void; onDone: () => void }) {
  const tenants = useFetch<{ items: TenantRow[] }>("/admin/tenants");
  const [tenant, setTenant] = useState(card.tenant_id ?? "");
  const locs = useFetch<Opt[]>(tenant ? `/admin/tenants/${tenant}/locations` : null);
  const camps = useFetch<Opt[]>(tenant ? `/admin/tenants/${tenant}/campaigns` : null);
  const [loc, setLoc] = useState("");
  const [campaign, setCampaign] = useState("");
  const [label, setLabel] = useState(card.label ?? "");
  const [ack, setAck] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inUse = ["assigned", "active", "paused", "reserved"].includes(card.status) && !!card.tenant_id;
  async function save() {
    setBusy(true); setErr(null);
    try { await api(`/admin/cards/${card.id}/assign`, { method: "POST", body: { tenant_id: tenant, location_id: loc, campaign_id: campaign || null, label: label.trim() || null, confirm: ack, activate: true } }); onDone(); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <Modal open onClose={onClose} title={`Assign ${card.card_code}`} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={busy} disabled={!tenant || !loc || (inUse && !ack)} onClick={() => void save()}>Assign and activate</Button></>}>
      <div className="space-y-4">
        {err && <Alert tone="error">{err}</Alert>}
        <Select label="Business" value={tenant} onChange={(e) => { setTenant(e.target.value); setLoc(""); setCampaign(""); }}><option value="">Choose a business…</option>{tenants.data?.items.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</Select>
        <Select label="Location" value={loc} disabled={!tenant} onChange={(e) => { setLoc(e.target.value); setCampaign(""); }}><option value="">Choose a location…</option>{locs.data?.map((l) => <option key={l.id} value={l.id}>{l.name}{l.city ? ` – ${l.city}` : ""}</option>)}</Select>
        <Select label="Review campaign" value={campaign} disabled={!loc} onChange={(e) => setCampaign(e.target.value)}><option value="">Plain review page</option>
          {(camps.data ?? []).filter((c) => !c.location_id || c.location_id === loc).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select>
        <Input label="Label (optional)" placeholder="e.g. Reception desk" value={label} onChange={(e) => setLabel(e.target.value)} />
        {inUse && (
          <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
            <p>This card is already {card.status === "reserved" ? "reserved for" : "in use by"} <b>{card.tenant_name}</b>. Assigning it sends everyone who scans or taps it to the new destination. The printed code and NFC tag do not change; history is kept.</p>
            <label className="mt-2 flex min-h-11 items-center gap-2 font-medium"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} className="h-5 w-5" />I understand, move this card</label>
          </div>)}
      </div>
    </Modal>
  );
}
