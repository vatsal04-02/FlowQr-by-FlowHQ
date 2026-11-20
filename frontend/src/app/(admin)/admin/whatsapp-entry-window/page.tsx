"use client";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, CardHeader, PageHeader, Skeleton } from "@/components/ui/Card";
import { Input } from "@/components/ui/Form";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { useFetch } from "@/lib/use-api";
import { type WaEntryWindowRow } from "@/lib/whatsapp";

/** How long WhatsApp's free window after an ad or page-button click lasts. Sources disagree, so every length is unverified until someone has checked it against Meta's own documentation. Rows are never edited. */
export default function EntryWindow() {
  const toast = useToast();
  const q = useFetch<{ items: WaEntryWindowRow[]; warning: string; note: string }>("/admin/whatsapp/entry-windows");
  const [f, setF] = useState({ hours: "", effective_from: "", source: "" }), [note, setNote] = useState<Record<string, string>>({}), [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null);
  async function add() { setBusy(true); setErr(null); try { await api("/admin/whatsapp/entry-windows", { method: "POST", body: { ...f, hours: Number(f.hours) } }); toast("Added."); setF({ hours: "", effective_from: "", source: "" }); await q.reload(); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); } }
  async function check(id: string, verified: boolean) { try { await api(`/admin/whatsapp/entry-windows/${id}/check`, { method: "POST", body: { verified, note: note[id] ?? "" } }); toast("Check recorded."); await q.reload(); } catch (e) { toast(errorMessage(e)); } }
  return (
    <div className="space-y-5">
      <PageHeader title="WhatsApp free window" subtitle="The free period after a customer starts a chat from an ad or page button." />
      {!q.data ? <Skeleton className="h-40" /> : (
        <>
          <Alert tone="info" title="Nothing is counted as free until a length is checked">{q.data.note}</Alert>
          <Card>
            <CardHeader title="Lengths by date" />
            <ul className="divide-y divide-ink-100">{q.data.items.map((w) => (
              <li key={w.id} className="py-3" data-testid="window">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1"><b className="text-ink">{w.hours} hours</b><span className="text-[13px] text-ink-500">from {fmtDate(w.effective_from)}</span>{w.in_force && <Badge tone="blue">In force today</Badge>}{w.verified ? <Badge tone="green">Checked</Badge> : <Badge tone="amber">Not checked</Badge>}</div>
                <p className="mt-1 text-[13px] text-ink-700">Source: {w.source}</p>
                <p className="text-[13px] text-ink-500">{w.check ? `Latest check: ${w.check.verified ? "matches" : "does not match"} Meta's documentation. ${w.check.note}` : "Never checked."}</p>
                <div className="mt-2 flex flex-wrap items-end gap-2"><Input label="What did you check?" value={note[w.id] ?? ""} maxLength={300} onChange={(e) => setNote({ ...note, [w.id]: e.target.value })} /><Button size="sm" variant="secondary" disabled={(note[w.id] ?? "").trim().length < 10} onClick={() => void check(w.id, true)}>It matches</Button><Button size="sm" variant="ghost" disabled={(note[w.id] ?? "").trim().length < 10} onClick={() => void check(w.id, false)}>It does not match</Button></div>
              </li>))}</ul>
          </Card>
          <Card>
            <CardHeader title="Add a new length" subtitle="A change is a new dated row. It starts unchecked." />
            <div className="grid gap-3 sm:grid-cols-3"><Input label="Hours" type="number" min={1} max={720} value={f.hours} onChange={(e) => setF({ ...f, hours: e.target.value })} /><Input label="From (date)" type="date" value={f.effective_from} onChange={(e) => setF({ ...f, effective_from: e.target.value })} /><Input label="Where it comes from" value={f.source} maxLength={300} onChange={(e) => setF({ ...f, source: e.target.value })} /></div>
            {err && <div className="mt-2"><Alert tone="warning">{err}</Alert></div>}
            <Button className="mt-3" variant="brand" loading={busy} disabled={!f.hours || !f.effective_from || f.source.trim().length < 10} onClick={() => void add()}>Add</Button>
          </Card>
        </>)}
    </div>
  );
}
