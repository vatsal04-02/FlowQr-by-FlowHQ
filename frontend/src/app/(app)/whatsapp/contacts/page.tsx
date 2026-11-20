"use client";
import clsx from "clsx";
import { Ban, Bell, Download, Gift, Megaphone, Plus, Search, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { FilterSelect, Input, Select, Textarea } from "@/components/ui/Form";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { ActionMenu, Avatar, Chips, Figure, IconButton, IconTile, Meter } from "@/components/whatsapp/ui";
import { api, apiFile, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate } from "@/lib/format";
import { useFetch } from "@/lib/use-api";
import { birthdayProblem, birthdayWords, csvPreview, CSV_TEMPLATE, MONTHS, reasonWords, type WaContact, type WaContacts } from "@/lib/whatsapp";
import { consentRows, initials } from "@/lib/whatsapp-ui";

const PAGE = 25;
type Show = "" | "marketing" | "utility" | "opted_out" | "none";
const CONSENT_ICON = { offers: Megaphone, updates: Bell, greetings: Gift, stopped: Ban } as const;
const CONSENT_TONE = { offers: "brand", updates: "pos", greetings: "accent", stopped: "neg" } as const;
type Purpose = "marketing" | "utility" | "occasion";

function Check({ checked, onChange, children }: { checked: boolean; onChange: (v: boolean) => void; children: React.ReactNode }) {
  return <label className="flex cursor-pointer items-start gap-3 text-sm text-ink-700"><input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="mt-1 h-4 w-4 shrink-0 accent-[#BD3E1B]" /><span>{children}</span></label>;
}

/** Three small icons say what a customer agreed to (lit when they did); a red one says they stopped offers. Each has a name for screen readers. */
function Agreed({ c }: { c: WaContact }) {
  const g = [
    { on: !!c.marketing && !c.opted_out, icon: Megaphone, yes: "Agreed to offers", no: "Has not agreed to offers" },
    { on: !!c.utility, icon: Bell, yes: "Agreed to visit updates", no: "Has not agreed to visit updates" },
    { on: !!c.occasion, icon: Gift, yes: "Agreed to greetings", no: "Has not agreed to greetings" },
  ];
  const stopped = "Asked to stop offers. Only the customer can start them again.";
  return (
    <ul className="flex shrink-0 items-center gap-1">
      {g.map((x) => <li key={x.yes} role="img" aria-label={x.on ? x.yes : x.no} title={x.on ? x.yes : x.no} className={clsx("grid h-6 w-6 place-items-center rounded-full", x.on ? "bg-pos-tint text-pos" : "bg-surface-2 text-ink-300")}><x.icon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden /></li>)}
      {c.opted_out && <li role="img" aria-label={stopped} title={stopped} className="grid h-7 w-7 place-items-center rounded-full bg-neg-tint text-neg"><Ban className="h-3.5 w-3.5" strokeWidth={2} aria-hidden /></li>}
    </ul>
  );
}

/** The people you may message, and what each one agreed to. Having someone in this list is NOT permission to message them: only the agreement is. */
export default function Customers() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const [q, setQ] = useState(""), [search, setSearch] = useState(""), [filter, setFilter] = useState<Show>(""), [page, setPage] = useState(0);
  const [add, setAdd] = useState(false), [imp, setImp] = useState(false), [agree, setAgree] = useState<WaContact | null>(null), [erase, setErase] = useState<WaContact | null>(null);
  useEffect(() => { const t = setTimeout(() => { setSearch(q); setPage(0); }, 300); return () => clearTimeout(t); }, [q]);
  const locs = useFetch<{ id: string; name: string }[]>("/locations");
  const [loc, setLoc] = useState("");
  const list = useFetch<WaContacts>("/whatsapp/contacts", { search, consent_filter: filter, location_id: loc, limit: PAGE, offset: page * PAGE });
  const d = list.data;
  const manyLocs = (locs.data?.length ?? 0) > 1;
  const rows = d ? consentRows(d.counts) : [];

  async function stopOffers(c: WaContact) {
    try { await api(`/whatsapp/contacts/${c.id}/opt-out`, { method: "POST", body: { purpose: "marketing" } }); toast("Done. This customer will not get offers."); void list.reload(); } catch (e) { toast(errorMessage(e)); }
  }
  async function visitDone(c: WaContact) {
    try {
      const r = await api<{ visit_recorded?: boolean; scheduled: boolean; reason: string }>(`/whatsapp/contacts/${c.id}/visit`, { method: "POST" });
      toast(r.scheduled ? "Visit saved. A request for honest feedback will go out shortly." : `Visit saved. ${r.reason === "automation_off" ? "No review request was sent because that helper is off." : reasonWords(r.reason)}`);
      void list.reload();
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
      <PageHeader title="Customers"
        actions={isAdmin ? <><IconButton label="Download list" icon={Download} onClick={() => void exportCsv()} /><IconButton label="Upload a list" icon={Upload} onClick={() => setImp(true)} /><Button variant="brand" size="lg" icon={<Plus className="h-4 w-4" />} onClick={() => setAdd(true)}>Add</Button></> : undefined} />
      {d && (
        <section className="panel mb-3 p-5 sm:mb-4 sm:p-6" aria-label="Who agreed to what">
          <Figure value={d.counts.contacts} label={d.counts.contacts === 1 ? "customer" : "customers"} />
          {d.counts.contacts > 0 && (
            <ul className="mt-5 space-y-3.5">
              {rows.map((r) => (
                <li key={r.key} className="grid grid-cols-[28px_1fr_auto] items-center gap-3">
                  <IconTile icon={CONSENT_ICON[r.key]} size={28} tone={CONSENT_TONE[r.key]} />
                  <div><p className="mb-1.5 text-[14px] leading-4 text-ink-700">{r.label}</p><Meter value={r.share} tone={CONSENT_TONE[r.key]} label={`${r.label}: ${r.value} of ${d.counts.contacts}`} /></div>
                  <span className="num text-[17px] font-semibold text-ink">{r.value}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
      <div className="mb-3 space-y-3 sm:mb-4">
        <div className="relative"><Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" aria-hidden /><input aria-label="Search customers" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name or phone" className="min-h-12 w-full rounded-2xl border border-ink-200 bg-white pl-10 pr-3 text-[16px]" /></div>
        {manyLocs && <FilterSelect label="Location" value={loc} onChange={(e) => { setLoc(e.target.value); setPage(0); }}><option value="">All locations</option>{locs.data?.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</FilterSelect>}
        <Chips label="Show" value={filter} onChange={(v) => { setFilter(v); setPage(0); }} options={[{ value: "", label: "Everyone" }, { value: "marketing", label: "Offers" }, { value: "utility", label: "Visit updates" }, { value: "opted_out", label: "Stopped" }, { value: "none", label: "No agreement" }]} />
      </div>
      {list.error && <Alert tone="error">{list.error}</Alert>}
      {!d ? <Skeleton className="h-64" /> : d.items.length === 0 ? (
        <EmptyState title={search || filter ? "No customers match" : "No customers yet"} action={isAdmin && !search && !filter ? <Button variant="brand" onClick={() => setAdd(true)}>Add a customer</Button> : undefined}>
          {search || filter ? "Try a different search." : "Add customers who told you they are happy to hear from you on WhatsApp. We never add anyone from review forms or enquiries by ourselves."}
        </EmptyState>
      ) : (
        <ul className="panel divide-y divide-line">{d.items.map((c) => {
          const name = c.customer_name ?? "No name";
          const menu = isAdmin ? [
            ...(!c.opted_out && !(c.marketing && c.utility && c.occasion) ? [{ label: "Record agreement", onClick: () => setAgree(c) }] : []),
            { label: "Visit done", onClick: () => void visitDone(c) },
            ...(c.marketing && !c.opted_out ? [{ label: "Stop offers", onClick: () => void stopOffers(c) }] : []),
            { label: "Delete", onClick: () => setErase(c), danger: true },
          ] : [];
          const extra = [c.birth_day && c.birth_month ? `Birthday ${birthdayWords(c.birth_day, c.birth_month)}` : null, c.last_visit_at ? `Visited ${fmtDate(c.last_visit_at)}` : null].filter(Boolean);
          return (
            <li key={c.id} className="flex items-center gap-3 p-3.5 sm:p-4">
              <Avatar text={initials(c.customer_name, c.phone)} tone={c.opted_out ? "neg" : c.marketing || c.utility ? "pos" : "neutral"} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-[16px] font-semibold leading-5 text-ink">{name}</p>
                <p className="num mt-0.5 truncate text-[13px] leading-4 text-muted">{c.phone}</p>
                {extra.length > 0 && <p className="mt-0.5 truncate text-[13px] leading-4 text-muted">{extra.join(" · ")}</p>}
                {c.opted_out && c.opted_out_at && <p className="mt-0.5 text-[13px] leading-4 text-neg">Stopped offers {fmtDate(c.opted_out_at)}</p>}
              </div>
              <Agreed c={c} />
              {isAdmin && <ActionMenu label={`Actions for ${name}`} items={menu} />}
            </li>);
        })}</ul>
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

function Agreement({ wording, marketing, utility, setMarketing, setUtility, attested, setAttested, evidence, setEvidence, occasion, setOccasion, needAttest }: {
  wording: WaContacts["wording"]; marketing: boolean; utility: boolean; setMarketing: (v: boolean) => void; setUtility: (v: boolean) => void; attested: boolean; setAttested: (v: boolean) => void; evidence: string; setEvidence: (v: string) => void;
  occasion?: boolean; setOccasion?: (v: boolean) => void; needAttest?: boolean;
}) {
  return (
    <fieldset className="space-y-3 rounded-2xl border border-line p-4">
      <legend className="px-1 text-sm font-semibold">What did they agree to?</legend>
      <Check checked={marketing} onChange={setMarketing}><b>Offers and updates.</b> <span className="text-ink-500">“{wording.marketing}”</span></Check>
      <Check checked={utility} onChange={setUtility}><b>Updates about their visit or enquiry.</b> <span className="text-ink-500">“{wording.utility}”</span></Check>
      {setOccasion && <Check checked={!!occasion} onChange={setOccasion}><b>Birthday and festival greetings.</b> <span className="text-ink-500">“{wording.occasion ?? "I agree to receive birthday and festival greetings on WhatsApp."}”</span></Check>}
      {(marketing || utility || occasion || needAttest) && (
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
  const [f, setF] = useState({ phone: "", name: "", tags: "", location: "", day: "", month: "" }), [marketing, setMarketing] = useState(false), [utility, setUtility] = useState(false), [occasion, setOccasion] = useState(false), [attested, setAttested] = useState(false), [evidence, setEvidence] = useState("");
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null);
  const hasBirth = f.day !== "" || f.month !== "";
  const birthBad = hasBirth ? (f.day === "" || f.month === "" ? "Choose both the day and the month." : birthdayProblem(Number(f.day), Number(f.month))) : null;
  const any = marketing || utility || occasion || hasBirth;
  const ok = f.phone.replace(/\D/g, "").length >= 10 && !birthBad && (!any || (attested && evidence.trim().length >= 10));
  async function save() {
    setBusy(true); setErr(null);
    try {
      await api("/whatsapp/contacts", { method: "POST", body: { phone: f.phone, name: f.name || null, tags: f.tags.split(",").map((t) => t.trim()).filter(Boolean), marketing, utility, occasion, birth_day: hasBirth ? Number(f.day) : null, birth_month: hasBirth ? Number(f.month) : null, attested, evidence: evidence.trim() || null, location_id: f.location || null } });
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
        <div className="grid grid-cols-2 gap-3">
          <Input label="Birthday: day (optional)" inputMode="numeric" placeholder="14" value={f.day} onChange={(e) => setF({ ...f, day: e.target.value.replace(/\D/g, "").slice(0, 2) })} error={birthBad ?? undefined} />
          <Select label="Birthday: month" value={f.month} onChange={(e) => setF({ ...f, month: e.target.value })} hint="Day and month only, never a year."><option value="">Not set</option>{MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}</Select>
        </div>
        <Agreement wording={wording} marketing={marketing} utility={utility} setMarketing={setMarketing} setUtility={setUtility} occasion={occasion} setOccasion={setOccasion} needAttest={hasBirth} attested={attested} setAttested={setAttested} evidence={evidence} setEvidence={setEvidence} />
        {!any && <p className="text-[13px] text-ink-500">You can add someone without an agreement. They will not get any message until they agree.</p>}
      </div>
    </Modal>
  );
}

function RecordAgreement({ contact, wording, onClose, onDone }: { contact: WaContact; wording: WaContacts["wording"]; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [marketing, setMarketing] = useState(false), [utility, setUtility] = useState(false), [occasion, setOccasion] = useState(false), [attested, setAttested] = useState(false), [evidence, setEvidence] = useState("");
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null);
  const ok = (marketing || utility || occasion) && attested && evidence.trim().length >= 10;
  async function save() {
    setBusy(true); setErr(null);
    try {
      for (const [on, purpose] of [[marketing && !contact.marketing, "marketing"], [utility && !contact.utility, "utility"], [occasion && !contact.occasion, "occasion"]] as [boolean, Purpose][]) {
        if (on) await api(`/whatsapp/contacts/${contact.id}/consent`, { method: "POST", body: { purpose, attested, evidence: evidence.trim() } });
      }
      toast("Agreement recorded."); onDone();
    } catch (e) { setErr(errorMessage(e)); setBusy(false); }
  }
  return (
    <Modal open onClose={onClose} title={`Record agreement: ${contact.customer_name ?? contact.phone}`} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button variant="brand" loading={busy} disabled={!ok} onClick={() => void save()}>Save agreement</Button></>}>
      <div className="space-y-4">
        {err && <Alert tone="error">{err}</Alert>}
        <Agreement wording={wording} marketing={marketing} utility={utility} setMarketing={setMarketing} setUtility={setUtility} occasion={occasion} setOccasion={setOccasion} attested={attested} setAttested={setAttested} evidence={evidence} setEvidence={setEvidence} />
      </div>
    </Modal>
  );
}

interface ImportResult { rows: number; added: number; already_there: number; consents_recorded: number; birthdays_set?: number; skipped: number; errors: { row: number; reason: string }[] }

function ImportList({ wording, onClose, onDone }: { wording: WaContacts["wording"]; onClose: () => void; onDone: () => void }) {
  const file = useRef<HTMLInputElement>(null);
  const [text, setText] = useState(""), [name, setName] = useState("");
  const [marketing, setMarketing] = useState(false), [utility, setUtility] = useState(false), [occasion, setOccasion] = useState(false), [attested, setAttested] = useState(false), [evidence, setEvidence] = useState("");
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null), [res, setRes] = useState<ImportResult | null>(null);
  const pv = text ? csvPreview(text) : null;
  const ok = !!pv && pv.total > 0 && (marketing || utility || occasion) && attested && evidence.trim().length >= 10;
  async function pick(f: File | undefined) {
    setErr(null);
    if (!f) return;
    if (f.size > 300_000) { setErr("That file is too large. Split it into smaller files."); return; }
    setText(await f.text()); setName(f.name);
  }
  async function run() {
    setBusy(true); setErr(null);
    try {
      setRes(await api<ImportResult>("/whatsapp/contacts/import", { method: "POST", body: { csv: text, purposes: [marketing && "marketing", utility && "utility", occasion && "occasion"].filter(Boolean), attested, evidence: evidence.trim() } }));
      onDone();
    } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  function template() { const url = URL.createObjectURL(new Blob([CSV_TEMPLATE], { type: "text/csv" })); const a = document.createElement("a"); a.href = url; a.download = "customers-template.csv"; a.click(); URL.revokeObjectURL(url); }
  return (
    <Modal open onClose={onClose} title="Upload a list of customers" footer={res ? <Button variant="brand" onClick={onClose}>Done</Button> : <><Button variant="secondary" onClick={onClose}>Cancel</Button><Button variant="brand" loading={busy} disabled={!ok} onClick={() => void run()}>Upload list</Button></>}>
      {res ? (
        <div className="space-y-3 text-sm text-ink-700">
          <Alert tone="success">{res.added} added, {res.already_there} already in your list, {res.consents_recorded} agreements recorded{res.birthdays_set ? `, ${res.birthdays_set} birthdays saved` : ""}{res.skipped ? `, ${res.skipped} skipped` : ""}.</Alert>
          {res.errors.length > 0 && <ul className="list-disc space-y-1 pl-5 text-[13px]">{res.errors.map((e) => <li key={e.row}>Row {e.row}: {e.reason}</li>)}</ul>}
        </div>
      ) : (
        <div className="space-y-4">
          {err && <Alert tone="error">{err}</Alert>}
          <Alert tone="warning" title="Only upload customers who agreed">Do not upload a list you bought or collected for another reason. Each customer must have agreed to hear from you on WhatsApp.</Alert>
          <div>
            <input ref={file} type="file" accept=".csv,text/csv" className="sr-only" aria-label="Choose a CSV file" onChange={(e) => void pick(e.target.files?.[0])} />
            <div className="flex flex-wrap items-center gap-2"><Button variant="secondary" onClick={() => file.current?.click()}>{name || "Choose a file"}</Button><Button variant="ghost" size="sm" onClick={template}>Download an example</Button></div>
            <p className="mt-1 text-[13px] text-ink-500">A CSV file with a column called phone. Optional columns: name, tags, and birthday (a day and month like 14-03, never a year; or birth_day and birth_month). Up to 2,000 customers.</p>
          </div>
          {pv && <div className="overflow-x-auto rounded-xl bg-surface-2 p-3 text-[13px]"><p className="mb-1 font-semibold">{pv.total} customers found. First rows:</p><table className="w-full text-left"><thead><tr>{pv.header.map((h, i) => <th key={i} className="pr-3 font-semibold">{h}</th>)}</tr></thead><tbody>{pv.rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} className="pr-3 text-ink-700">{c}</td>)}</tr>)}</tbody></table></div>}
          <Agreement wording={wording} marketing={marketing} utility={utility} setMarketing={setMarketing} setUtility={setUtility} occasion={occasion} setOccasion={setOccasion} attested={attested} setAttested={setAttested} evidence={evidence} setEvidence={setEvidence} />
        </div>
      )}
    </Modal>
  );
}
