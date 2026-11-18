"use client";
import { Download, Plus, Search, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { FilterSelect, Input, Select, Textarea } from "@/components/ui/Form";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api, apiFile, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate } from "@/lib/format";
import { useFetch } from "@/lib/use-api";
import { consentWords, csvPreview, CSV_TEMPLATE, reasonWords, SOURCE_WORDS, type WaContact, type WaContacts } from "@/lib/whatsapp";

const PAGE = 25;
type Purpose = "marketing" | "utility";

function Check({ checked, onChange, children }: { checked: boolean; onChange: (v: boolean) => void; children: React.ReactNode }) {
  return <label className="flex cursor-pointer items-start gap-3 text-sm text-ink-700"><input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="mt-1 h-4 w-4 shrink-0 accent-[#BD3E1B]" /><span>{children}</span></label>;
}

/** The people you may message, and what each one agreed to. Having someone in this list is NOT permission to message them: only the agreement is. */
export default function Customers() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const [q, setQ] = useState(""), [search, setSearch] = useState(""), [filter, setFilter] = useState(""), [page, setPage] = useState(0);
  const [add, setAdd] = useState(false), [imp, setImp] = useState(false), [agree, setAgree] = useState<WaContact | null>(null), [erase, setErase] = useState<WaContact | null>(null);
  useEffect(() => { const t = setTimeout(() => { setSearch(q); setPage(0); }, 300); return () => clearTimeout(t); }, [q]);
  const locs = useFetch<{ id: string; name: string }[]>("/locations");
  const [loc, setLoc] = useState("");
  const list = useFetch<WaContacts>("/whatsapp/contacts", { search, consent_filter: filter, location_id: loc, limit: PAGE, offset: page * PAGE });
  const d = list.data;
  const manyLocs = (locs.data?.length ?? 0) > 1;
  const locName = (id: string | null | undefined) => (id ? locs.data?.find((l) => l.id === id)?.name : undefined);

  async function stopOffers(c: WaContact) {
    try { await api(`/whatsapp/contacts/${c.id}/opt-out`, { method: "POST", body: { purpose: "marketing" } }); toast("Done. This customer will not get offers."); void list.reload(); } catch (e) { toast(errorMessage(e)); }
  }
  async function visitDone(c: WaContact) {
    try {
      const r = await api<{ scheduled: boolean; reason: string }>(`/whatsapp/contacts/${c.id}/visit`, { method: "POST" });
      toast(r.scheduled ? "Done. A request for honest feedback will go out shortly." : reasonWords(r.reason));
    } catch (e) { toast(errorMessage(e)); }
  }
  async function doErase() {
    if (!erase) return;
    try { await api(`/whatsapp/contacts/${erase.id}`, { method: "DELETE" }); setErase(null); toast("Customer deleted."); void list.reload(); } catch (e) { toast(errorMessage(e)); }
  }
  async function exportCsv() {
    try {
      const { blob } = await apiFile("/whatsapp/contacts/export");
      const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = "whatsapp-customers.csv"; a.click(); URL.revokeObjectURL(url);
    } catch (e) { toast(errorMessage(e)); }
  }

  return (
    <>
      <PageHeader title="Your customers" subtitle="Only customers who agreed can get WhatsApp messages. Here you can see who agreed, and to what."
        actions={isAdmin ? <><Button variant="secondary" icon={<Download className="h-4 w-4" />} onClick={() => void exportCsv()}>Download list</Button><Button variant="secondary" icon={<Upload className="h-4 w-4" />} onClick={() => setImp(true)}>Upload a list</Button><Button variant="brand" icon={<Plus className="h-4 w-4" />} onClick={() => setAdd(true)}>Add a customer</Button></> : undefined} />
      {d && <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[["Customers", d.counts.contacts], ["Agreed to offers", d.counts.marketing], ["Agreed to visit updates", d.counts.utility], ["Asked to stop offers", d.counts.opted_out]].map(([l, v]) => <Card key={String(l)}><p className="text-[13px] text-ink-500">{l}</p><p className="mt-1 text-2xl font-semibold tabular-nums text-ink">{v}</p></Card>)}
      </div>}
      <Card pad={false} className="mb-4 p-3 sm:p-4"><div className="flex flex-wrap gap-2">
        <div className="relative min-w-[200px] flex-1"><Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" aria-hidden /><input aria-label="Search customers" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name or phone" className="min-h-11 w-full rounded-xl border border-ink-200 pl-9 pr-3 text-sm sm:min-h-10" /></div>
        {manyLocs && <FilterSelect label="Location" value={loc} onChange={(e) => { setLoc(e.target.value); setPage(0); }}><option value="">All locations</option>{locs.data?.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</FilterSelect>}
        <FilterSelect label="Show" value={filter} onChange={(e) => { setFilter(e.target.value); setPage(0); }}><option value="">Everyone</option><option value="marketing">Agreed to offers</option><option value="utility">Agreed to visit updates</option><option value="opted_out">Asked to stop offers</option><option value="none">No agreement yet</option></FilterSelect>
      </div></Card>
      {list.error && <Alert tone="error">{list.error}</Alert>}
      {!d ? <Skeleton className="h-64" /> : d.items.length === 0 ? (
        <EmptyState title={search || filter ? "No customers match" : "No customers yet"} action={isAdmin && !search && !filter ? <Button variant="brand" onClick={() => setAdd(true)}>Add a customer</Button> : undefined}>
          {search || filter ? "Try a different search." : "Add customers who told you they are happy to hear from you on WhatsApp. We never add anyone from review forms or enquiries by ourselves."}
        </EmptyState>
      ) : (
        <div className="space-y-3">{d.items.map((c) => {
          const w = consentWords(c);
          return (
            <Card key={c.id}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-semibold text-ink">{c.customer_name ?? "No name"} <span className="ml-1 font-normal tabular-nums text-ink-500">{c.phone}</span></p>
                  <p className="mt-1 flex flex-wrap items-center gap-2 text-[13px] text-ink-500"><Badge tone={w.tone}>{w.label}</Badge>{c.tags.map((t) => <Badge key={t}>{t}</Badge>)}{manyLocs && locName(c.location_id) && <Badge tone="blue">{locName(c.location_id)}</Badge>}<span>{SOURCE_WORDS[c.source] ?? c.source} · {fmtDate(c.created_at)}</span></p>
                  {c.opted_out && c.opted_out_at && <p className="mt-1 text-[13px] text-neg">Asked to stop offers on {fmtDate(c.opted_out_at)}. Only the customer can start them again.</p>}
                </div>
                {isAdmin && <div className="flex flex-wrap gap-2">
                  {!c.opted_out && !(c.marketing && c.utility) && <Button size="sm" variant="secondary" onClick={() => setAgree(c)}>Record agreement</Button>}
                  {c.utility && <Button size="sm" variant="secondary" onClick={() => void visitDone(c)}>Visit done</Button>}
                  {c.marketing && !c.opted_out && <Button size="sm" variant="secondary" onClick={() => void stopOffers(c)}>Stop offers</Button>}
                  <Button size="sm" variant="ghost" onClick={() => setErase(c)}>Delete</Button>
                </div>}
              </div>
            </Card>);
        })}</div>
      )}
      {d && d.total > PAGE && <div className="mt-4 flex items-center justify-between"><Button variant="secondary" size="sm" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</Button><span className="text-sm text-ink-500">{page * PAGE + 1}–{Math.min(d.total, (page + 1) * PAGE)} of {d.total}</span><Button variant="secondary" size="sm" disabled={(page + 1) * PAGE >= d.total} onClick={() => setPage(page + 1)}>Next</Button></div>}

      {add && d && <AddCustomer wording={d.wording} locations={manyLocs ? locs.data ?? [] : []} onClose={() => setAdd(false)} onDone={() => { setAdd(false); void list.reload(); }} />}
      {imp && d && <ImportList wording={d.wording} onClose={() => setImp(false)} onDone={() => void list.reload()} />}
      {agree && d && <RecordAgreement contact={agree} wording={d.wording} onClose={() => setAgree(null)} onDone={() => { setAgree(null); void list.reload(); }} />}
      <Modal open={!!erase} onClose={() => setErase(null)} title="Delete this customer?" footer={<><Button variant="secondary" onClick={() => setErase(null)}>Keep</Button><Button variant="danger" onClick={() => void doErase()}>Delete customer</Button></>}>
        <p className="text-sm text-ink-700">{erase?.customer_name ?? erase?.phone} and what they agreed to will be removed. {erase?.opted_out ? "Because they asked to stop offers, their number stays on a private do-not-message list so they are never messaged by mistake." : ""}</p>
      </Modal>
    </>
  );
}

function Agreement({ wording, marketing, utility, setMarketing, setUtility, attested, setAttested, evidence, setEvidence }: {
  wording: WaContacts["wording"]; marketing: boolean; utility: boolean; setMarketing: (v: boolean) => void; setUtility: (v: boolean) => void; attested: boolean; setAttested: (v: boolean) => void; evidence: string; setEvidence: (v: string) => void;
}) {
  return (
    <fieldset className="space-y-3 rounded-2xl border border-line p-4">
      <legend className="px-1 text-sm font-semibold">What did they agree to?</legend>
      <Check checked={marketing} onChange={setMarketing}><b>Offers and updates.</b> <span className="text-ink-500">“{wording.marketing}”</span></Check>
      <Check checked={utility} onChange={setUtility}><b>Updates about their visit or enquiry.</b> <span className="text-ink-500">“{wording.utility}”</span></Check>
      {(marketing || utility) && (
        <div className="space-y-3 border-t border-line pt-3">
          <Check checked={attested} onChange={setAttested}>I confirm this customer agreed to the message above.</Check>
          <Textarea label="How did they agree?" rows={2} value={evidence} onChange={(e) => setEvidence(e.target.value)} hint="For example: asked at the counter on 12 Nov and wrote it in the register." />
        </div>
      )}
    </fieldset>
  );
}

function AddCustomer({ wording, locations, onClose, onDone }: { wording: WaContacts["wording"]; locations: { id: string; name: string }[]; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [f, setF] = useState({ phone: "", name: "", tags: "", location: "" }), [marketing, setMarketing] = useState(false), [utility, setUtility] = useState(false), [attested, setAttested] = useState(false), [evidence, setEvidence] = useState("");
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null);
  const any = marketing || utility;
  const ok = f.phone.replace(/\D/g, "").length >= 10 && (!any || (attested && evidence.trim().length >= 10));
  async function save() {
    setBusy(true); setErr(null);
    try {
      await api("/whatsapp/contacts", { method: "POST", body: { phone: f.phone, name: f.name || null, tags: f.tags.split(",").map((t) => t.trim()).filter(Boolean), marketing, utility, attested, evidence: evidence.trim() || null, location_id: f.location || null } });
      toast("Customer added."); onDone();
    } catch (e) { setErr(errorMessage(e)); setBusy(false); }
  }
  return (
    <Modal open onClose={onClose} title="Add a customer" footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button variant="brand" loading={busy} disabled={!ok} onClick={() => void save()}>Add customer</Button></>}>
      <div className="space-y-4">
        {err && <Alert tone="error">{err}</Alert>}
        <Input label="Mobile number" inputMode="tel" placeholder="98765 43210" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} />
        <Input label="Name (optional)" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        <Input label="Groups (optional)" placeholder="regular, family" value={f.tags} onChange={(e) => setF({ ...f, tags: e.target.value })} hint="Separate with commas." />
        {locations.length > 0 && <Select label="Location (optional)" value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} hint="Lets you send an offer to one location's customers (Pro)."><option value="">Not set</option>{locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</Select>}
        <Agreement wording={wording} marketing={marketing} utility={utility} setMarketing={setMarketing} setUtility={setUtility} attested={attested} setAttested={setAttested} evidence={evidence} setEvidence={setEvidence} />
        {!any && <p className="text-[13px] text-ink-500">You can add someone without an agreement. They will not get any message until they agree.</p>}
      </div>
    </Modal>
  );
}

function RecordAgreement({ contact, wording, onClose, onDone }: { contact: WaContact; wording: WaContacts["wording"]; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [marketing, setMarketing] = useState(false), [utility, setUtility] = useState(false), [attested, setAttested] = useState(false), [evidence, setEvidence] = useState("");
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null);
  const ok = (marketing || utility) && attested && evidence.trim().length >= 10;
  async function save() {
    setBusy(true); setErr(null);
    try {
      for (const [on, purpose] of [[marketing && !contact.marketing, "marketing"], [utility && !contact.utility, "utility"]] as [boolean, Purpose][]) {
        if (on) await api(`/whatsapp/contacts/${contact.id}/consent`, { method: "POST", body: { purpose, attested, evidence: evidence.trim() } });
      }
      toast("Agreement recorded."); onDone();
    } catch (e) { setErr(errorMessage(e)); setBusy(false); }
  }
  return (
    <Modal open onClose={onClose} title={`Record agreement: ${contact.customer_name ?? contact.phone}`} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button variant="brand" loading={busy} disabled={!ok} onClick={() => void save()}>Save agreement</Button></>}>
      <div className="space-y-4">
        {err && <Alert tone="error">{err}</Alert>}
        <Agreement wording={wording} marketing={marketing} utility={utility} setMarketing={setMarketing} setUtility={setUtility} attested={attested} setAttested={setAttested} evidence={evidence} setEvidence={setEvidence} />
      </div>
    </Modal>
  );
}

interface ImportResult { rows: number; added: number; already_there: number; consents_recorded: number; skipped: number; errors: { row: number; reason: string }[] }

function ImportList({ wording, onClose, onDone }: { wording: WaContacts["wording"]; onClose: () => void; onDone: () => void }) {
  const file = useRef<HTMLInputElement>(null);
  const [text, setText] = useState(""), [name, setName] = useState("");
  const [marketing, setMarketing] = useState(false), [utility, setUtility] = useState(false), [attested, setAttested] = useState(false), [evidence, setEvidence] = useState("");
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null), [res, setRes] = useState<ImportResult | null>(null);
  const pv = text ? csvPreview(text) : null;
  const ok = !!pv && pv.total > 0 && (marketing || utility) && attested && evidence.trim().length >= 10;
  async function pick(f: File | undefined) {
    setErr(null);
    if (!f) return;
    if (f.size > 300_000) { setErr("That file is too large. Split it into smaller files."); return; }
    setText(await f.text()); setName(f.name);
  }
  async function run() {
    setBusy(true); setErr(null);
    try {
      setRes(await api<ImportResult>("/whatsapp/contacts/import", { method: "POST", body: { csv: text, purposes: [marketing && "marketing", utility && "utility"].filter(Boolean), attested, evidence: evidence.trim() } }));
      onDone();
    } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  function template() { const url = URL.createObjectURL(new Blob([CSV_TEMPLATE], { type: "text/csv" })); const a = document.createElement("a"); a.href = url; a.download = "customers-template.csv"; a.click(); URL.revokeObjectURL(url); }
  return (
    <Modal open onClose={onClose} title="Upload a list of customers" footer={res ? <Button variant="brand" onClick={onClose}>Done</Button> : <><Button variant="secondary" onClick={onClose}>Cancel</Button><Button variant="brand" loading={busy} disabled={!ok} onClick={() => void run()}>Upload list</Button></>}>
      {res ? (
        <div className="space-y-3 text-sm text-ink-700">
          <Alert tone="success">{res.added} added, {res.already_there} already in your list, {res.consents_recorded} agreements recorded{res.skipped ? `, ${res.skipped} skipped` : ""}.</Alert>
          {res.errors.length > 0 && <ul className="list-disc space-y-1 pl-5 text-[13px]">{res.errors.map((e) => <li key={e.row}>Row {e.row}: {e.reason}</li>)}</ul>}
        </div>
      ) : (
        <div className="space-y-4">
          {err && <Alert tone="error">{err}</Alert>}
          <Alert tone="warning" title="Only upload customers who agreed">Do not upload a list you bought or collected for another reason. Each customer must have agreed to hear from you on WhatsApp.</Alert>
          <div>
            <input ref={file} type="file" accept=".csv,text/csv" className="sr-only" aria-label="Choose a CSV file" onChange={(e) => void pick(e.target.files?.[0])} />
            <div className="flex flex-wrap items-center gap-2"><Button variant="secondary" onClick={() => file.current?.click()}>{name || "Choose a file"}</Button><Button variant="ghost" size="sm" onClick={template}>Download an example</Button></div>
            <p className="mt-1 text-[13px] text-ink-500">A CSV file with a column called phone. Optional columns: name and tags. Up to 2,000 customers.</p>
          </div>
          {pv && <div className="overflow-x-auto rounded-xl bg-surface-2 p-3 text-[13px]"><p className="mb-1 font-semibold">{pv.total} customers found. First rows:</p><table className="w-full text-left"><thead><tr>{pv.header.map((h, i) => <th key={i} className="pr-3 font-semibold">{h}</th>)}</tr></thead><tbody>{pv.rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} className="pr-3 text-ink-700">{c}</td>)}</tr>)}</tbody></table></div>}
          <Agreement wording={wording} marketing={marketing} utility={utility} setMarketing={setMarketing} setUtility={setUtility} attested={attested} setAttested={setAttested} evidence={evidence} setEvidence={setEvidence} />
        </div>
      )}
    </Modal>
  );
}
