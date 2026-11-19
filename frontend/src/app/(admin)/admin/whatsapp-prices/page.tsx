"use client";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, CardHeader, PageHeader, Skeleton } from "@/components/ui/Card";
import { Input, Select } from "@/components/ui/Form";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { useFetch } from "@/lib/use-api";
import { categoryLabel, freeAllowanceWords, rateProblem, RATE_CATEGORIES, rateStatus, type RateCategory, type WaRate, type WaRates } from "@/lib/whatsapp";

const inr = (v: string) => `₹${Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;

function Check({ r, onDone }: { r: WaRate; onDone: () => void }) {
  const toast = useToast();
  const [open, setOpen] = useState(false), [ok, setOk] = useState("yes"), [note, setNote] = useState(""), [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null);
  async function save() {
    if (note.trim().length < 10) { setErr("Write what you checked, at least a short sentence."); return; }
    setBusy(true); setErr(null);
    try { await api(`/admin/whatsapp/rates/${r.id}/verification`, { method: "POST", body: { verified: ok === "yes", note: note.trim() } }); toast("Check recorded."); setOpen(false); setNote(""); onDone(); }
    catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  if (!open) return <Button variant="secondary" size="sm" onClick={() => setOpen(true)}>Record a check</Button>;
  return (
    <div className="mt-2 w-full max-w-md space-y-2 rounded-xl bg-surface-2 p-3">
      <Select label="Does this match Meta's own rate card?" value={ok} onChange={(e) => setOk(e.target.value)}><option value="yes">Yes, it matches</option><option value="no">No, it does not match</option></Select>
      <Input label="What did you check?" value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} hint="For example: Matches Meta's India rate card, page dated 1 Oct 2026." />
      {err && <Alert tone="warning">{err}</Alert>}
      <div className="flex gap-2"><Button variant="brand" size="sm" loading={busy} onClick={() => void save()}>Save check</Button><Button variant="ghost" size="sm" onClick={() => setOpen(false)}>Cancel</Button></div>
      <p className="text-[12px] text-ink-500">This adds a record. The price itself is never changed.</p>
    </div>
  );
}

function Row({ r, onDone }: { r: WaRate; onDone: () => void }) {
  const st = rateStatus(r);
  return (
    <li className="py-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <b className="text-[15px] tabular-nums text-ink">{inr(r.rate)}</b><Badge tone={st.tone}>{st.label}</Badge>{r.in_force && <Badge tone="blue">In force today</Badge>}
        <span className="text-[13px] text-ink-500">from {fmtDate(r.effective_from)} · {freeAllowanceWords(r.free_per_number_month)}</span>
      </div>
      <p className="mt-1 text-[13px] text-ink-700">Source: {r.source}</p>
      <p className="mt-0.5 text-[13px] text-ink-500">{r.verification ? `Latest check: ${r.verification.verified ? "matches" : "does not match"} Meta's rate card. ${r.verification.note} (${r.verification.by ?? "an administrator"}, ${fmtDate(r.verification.at)})` : "Never checked against Meta's own rate card."}</p>
      <div className="mt-2"><Check r={r} onDone={onDone} /></div>
    </li>
  );
}

/** Meta's per-message prices. A price is a dated row that is never overwritten: a change is a new row with a later date. Whether a row matches Meta's own rate card is a separate, append-only record of checks. */
export default function WhatsAppPrices() {
  const toast = useToast();
  const q = useFetch<WaRates>("/admin/whatsapp/rates");
  const [form, setForm] = useState({ category: "marketing" as RateCategory, rate: "", effective_from: "", source: "", free: "0", verified: false });
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null), [showAll, setShowAll] = useState(false);
  const items = q.data?.items ?? [];
  const force = items.filter((i) => i.in_force);
  const history = items.filter((i) => !i.in_force);
  async function add() {
    const bad = rateProblem(form.rate);
    if (bad) { setErr(bad); return; }
    if (!form.effective_from) { setErr("Choose the date this price starts."); return; }
    if (form.source.trim().length < 10) { setErr("Write where this price comes from, at least a short sentence."); return; }
    setBusy(true); setErr(null);
    try {
      await api("/admin/whatsapp/rates", { method: "POST", body: { category: form.category, rate: form.rate.trim(), effective_from: form.effective_from, source: form.source.trim(), verified: form.verified, free_per_number_month: Number(form.free) || 0 } });
      toast("Price added."); setForm({ ...form, rate: "", source: "", free: "0", verified: false }); void q.reload();
    } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <>
      <PageHeader eyebrow="Platform" title="WhatsApp prices" subtitle="What Meta charges per delivered message, by category. Owners see these as estimates, always apart from FlowQR's fee." />
      {q.error && <Alert tone="error">{q.error}</Alert>}
      {!q.data ? <Skeleton className="h-64" /> : (
        <div className="space-y-4">
          {q.data.unverified_in_use.length > 0 && <Alert tone="warning" title="Prices in use are not verified">Owners see a warning above every cost figure until the prices for {q.data.unverified_in_use.map(categoryLabel).join(", ")} are checked against Meta's own rate card.</Alert>}
          <div className="grid gap-4 lg:grid-cols-2">{RATE_CATEGORIES.map((c) => {
            const rows = force.filter((r) => r.category === c.value);
            return (
              <Card key={c.value}><CardHeader title={c.label} />
                {rows.length === 0 ? <p className="text-sm text-ink-500">No price is in force for this category yet. Cost estimates claim nothing for it.</p> : <ul className="divide-y divide-ink-100">{rows.map((r) => <Row key={r.id} r={r} onDone={() => void q.reload()} />)}</ul>}
              </Card>
            );
          })}</div>

          <Card>
            <CardHeader title="Add a new price" subtitle="Existing prices are never edited. A change is a new price with a later date, and the old one stays in the history." />
            <div className="grid items-start gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Select label="Category" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value as RateCategory })}>{RATE_CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}</Select>
              <Input label="Price per message (₹)" inputMode="decimal" value={form.rate} onChange={(e) => setForm({ ...form, rate: e.target.value })} hint="India, in rupees." />
              <Input label="Starts on" type="date" value={form.effective_from} onChange={(e) => setForm({ ...form, effective_from: e.target.value })} />
              <Input label="Free per number each month" type="number" min={0} value={form.free} onChange={(e) => setForm({ ...form, free: e.target.value })} hint="0 if Meta gives none." />
            </div>
            <div className="mt-3"><Input label="Where this price comes from" value={form.source} maxLength={300} onChange={(e) => setForm({ ...form, source: e.target.value })} hint="For example: Meta rate card for India, effective 1 Jan 2027." /></div>
            <label className="mt-3 flex items-start gap-2 text-sm text-ink-700"><input type="checkbox" className="mt-1 h-4 w-4 accent-[#BD3E1B]" checked={form.verified} onChange={(e) => setForm({ ...form, verified: e.target.checked })} />I have checked this price against Meta's own rate card (leave this off if you have not)</label>
            {err && <div className="mt-3"><Alert tone="warning">{err}</Alert></div>}
            <div className="mt-3"><Button variant="brand" loading={busy} onClick={() => void add()}>Add price</Button></div>
          </Card>

          <Card>
            <CardHeader title="History" subtitle={`${history.length} earlier or future-dated price${history.length === 1 ? "" : "s"}. Nothing is ever deleted.`} action={<Button variant="ghost" size="sm" onClick={() => setShowAll(!showAll)}>{showAll ? "Hide" : "Show"}</Button>} />
            {showAll && (history.length === 0 ? <p className="text-sm text-ink-500">No other prices yet.</p> : <ul className="divide-y divide-ink-100">{history.map((r) => <li key={r.id}><p className="pt-3 text-[13px] font-semibold text-ink-500">{categoryLabel(r.category)}</p><Row r={r} onDone={() => void q.reload()} /></li>)}</ul>)}
          </Card>
          <p className="text-[13px] text-ink-500">{q.data.note}</p>
        </div>
      )}
    </>
  );
}
