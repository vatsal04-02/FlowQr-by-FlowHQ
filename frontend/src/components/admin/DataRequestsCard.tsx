"use client";
import { Download } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, CardHeader } from "@/components/ui/Card";
import { Input, Select, Textarea } from "@/components/ui/Form";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api, apiFile, errorMessage } from "@/lib/api";
import { fmtDate } from "@/lib/format";

export interface DataRequestInfo {
  id: string; kind: "export" | "deletion"; status: "open" | "verified" | "fulfilled" | "rejected" | "cancelled"; business_name: string; requester_name: string; requester_role: string; received_via: string;
  requester_contact: string | null; created_at: string; created_by: string | null; verification_method: string | null; contact_matched_record: boolean | null; verified_at: string | null; verified_by: string | null;
  eligible_at: string | null; resolved_at: string | null; resolution: string | null; export_count: number;
  events: { at: string; action: string; by: string | null; detail: string | null }[];
  deletion?: { ready: boolean; reason: string | null; eligible_at: string | null; impact?: { locations: number; cards: number; live_cards: number } };
}

const TONE: Record<string, "blue" | "amber" | "green" | "gray" | "red"> = { open: "amber", verified: "blue", fulfilled: "green", rejected: "gray", cancelled: "gray" };
const WHY: Record<string, string> = { has_owner: "The business now has an owner, who has the real export and delete tools.", not_verified: "Verify who is asking first.", cooling_off: "Still in the waiting period.",
  paid_subscription: "Cancel the paid subscription first.", business_gone: "The business no longer exists." };
const VIA: [string, string][] = [["phone", "By phone"], ["in_person", "In person"], ["whatsapp", "On WhatsApp"], ["email", "By email"], ["paper", "On paper"], ["other", "Another way"]];
const ROLE: [string, string][] = [["owner", "The owner"], ["representative", "Someone speaking for the owner"], ["other", "Someone else"]];
const METHOD: [string, string][] = [["callback_to_shop_phone", "I called the shop back on the number on file"], ["whatsapp_from_shop_phone", "They messaged me from the number on file"], ["email_from_known_address", "They emailed from the address on file"],
  ["in_person_at_shop", "I met them at the shop"], ["other", "Another way (describe it)"]];
const DELIVERY: [string, string][] = [["handed_over_in_person", "Handed over in person"], ["emailed_to_verified_address", "Emailed to the verified address"], ["sent_on_whatsapp_to_verified_number", "Sent on WhatsApp to the verified number"], ["other", "Another way"]];
const label = (list: [string, string][], v: string) => list.find(([k]) => k === v)?.[1] ?? v;
const stamp = (v: string | null) => fmtDate(v, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });

type Step = { kind: "new" } | { kind: "verify" | "reject" | "cancel" | "delivered" | "delete"; r: DataRequestInfo } | null;

/** Export and deletion requests for a business with no owner login. Every step is the administrator's own, verified, recorded and audited; nothing is sent or deleted automatically. */
export function DataRequestsCard({ tenantId, businessName, phone, email, requests, reload }: { tenantId: string; businessName: string; phone: string | null; email: string | null; requests: DataRequestInfo[]; reload: () => Promise<unknown> | void }) {
  const toast = useToast();
  const [step, setStep] = useState<Step>(null);
  const [f, setF] = useState({ kind: "export", name: "", role: "owner", via: "phone", contact: "", note: "", method: "callback_to_shop_phone", contacted: "", sure: false, reason: "", delivery: "handed_over_in_person", typed: "", ack: false });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((x) => ({ ...x, [k]: v }));
  const open = (s: Step) => { setErr(null); setF((x) => ({ ...x, note: "", contacted: "", sure: false, reason: "", typed: "", ack: false, name: "", contact: "" })); setStep(s); };
  const hasOpen = (kind: string) => requests.some((r) => r.kind === kind && (r.status === "open" || r.status === "verified"));

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true); setErr(null);
    try { await fn(); toast(ok); setStep(null); await reload(); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  async function download(r: DataRequestInfo) {
    try {
      const { blob } = await apiFile(`/admin/data-requests/${r.id}/export`);
      const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = `flowqr-export-${r.business_name.replace(/\W+/g, "-").toLowerCase()}.zip`; a.click(); URL.revokeObjectURL(url);
      toast("Export downloaded. Hand it only to the person you verified."); await reload();
    } catch (e) { toast(errorMessage(e), "error"); }
  }

  const needsContact = step && step.kind === "verify" && ["callback_to_shop_phone", "whatsapp_from_shop_phone", "email_from_known_address"].includes(f.method);
  const onRecord = f.method === "email_from_known_address" ? email : phone;

  return (
    <Card><CardHeader title="Data export and deletion" action={<Button size="sm" variant="secondary" onClick={() => { open({ kind: "new" }); }}>Log a request</Button>} />
      <p className="mb-3 text-sm text-ink-500">This business has no owner login, so it cannot use Settings to export or delete its data. Log the request here, verify who is asking, then act on it. Nothing is sent or deleted automatically.</p>
      {requests.length === 0 && <p className="text-sm text-ink-500">No requests.</p>}
      <ul className="space-y-3">{requests.map((r) => (
        <li key={r.id} className="rounded-xl border border-ink-100 p-3 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-2"><p className="font-semibold">{r.kind === "export" ? "Export my data" : "Delete my data"} <Badge tone={TONE[r.status]}>{r.status}</Badge></p><p className="text-xs text-ink-500">{stamp(r.created_at)}</p></div>
          <p className="mt-1 text-ink-700">{r.requester_name} ({label(ROLE, r.requester_role).toLowerCase()}) · {label(VIA, r.received_via).toLowerCase()}{r.requester_contact ? ` · ${r.requester_contact}` : ""}</p>
          {r.verified_at && <p className="mt-1 text-ink-500">Verified by {r.verified_by} · {label(METHOD, r.verification_method ?? "")}{r.contact_matched_record ? " · contact matches the record" : ""}</p>}
          {r.resolution && <p className="mt-1 text-ink-500">{r.resolution}</p>}
          {r.kind === "deletion" && r.status === "verified" && r.deletion && (
            <p className="mt-1 text-ink-700">{r.deletion.ready ? "The waiting period is over. This will erase the business and return its cards to stock." : `${WHY[r.deletion.reason ?? ""] ?? ""}${r.deletion.reason === "cooling_off" ? ` Earliest ${fmtDate(r.deletion.eligible_at)}.` : ""}`}</p>)}
          <details className="mt-2 text-xs text-ink-500"><summary className="cursor-pointer">History ({r.events.length})</summary><ol className="mt-1 space-y-0.5">{r.events.map((e, i) => <li key={i}>{stamp(e.at)} · <b>{e.action.replace(/_/g, " ")}</b>{e.by ? ` · ${e.by}` : ""}{e.detail ? ` · ${e.detail}` : ""}</li>)}</ol></details>
          {(r.status === "open" || r.status === "verified") && (
            <div className="mt-3 flex flex-wrap gap-2">
              {r.status === "open" && <Button size="sm" onClick={() => open({ kind: "verify", r })}>Verify who is asking</Button>}
              {r.status === "verified" && r.kind === "export" && <Button size="sm" icon={<Download className="h-3.5 w-3.5" />} onClick={() => void download(r)}>Download export</Button>}
              {r.status === "verified" && r.kind === "export" && r.export_count > 0 && <Button size="sm" variant="secondary" onClick={() => open({ kind: "delivered", r })}>Mark as delivered</Button>}
              {r.status === "verified" && r.kind === "deletion" && <Button size="sm" variant="danger" disabled={!r.deletion?.ready} onClick={() => open({ kind: "delete", r })}>Delete the business…</Button>}
              <Button size="sm" variant="secondary" onClick={() => open({ kind: "reject", r })}>Reject</Button><Button size="sm" variant="secondary" onClick={() => open({ kind: "cancel", r })}>Cancel</Button>
            </div>)}
        </li>))}</ul>

      <Modal open={step?.kind === "new"} onClose={() => setStep(null)} title="Log a data request" footer={<><Button variant="secondary" onClick={() => setStep(null)}>Cancel</Button>
        <Button loading={busy} disabled={f.name.trim().length < 2 || hasOpen(f.kind)} onClick={() => void run(() => api(`/admin/tenants/${tenantId}/data-requests`, { method: "POST", body: { kind: f.kind, requester_name: f.name.trim(), requester_role: f.role, received_via: f.via, requester_contact: f.contact.trim() || null, note: f.note.trim() || null } }), "Request logged.")}>Log request</Button></>}>
        <div className="space-y-4">{err && <Alert tone="error">{err}</Alert>}
          <Select label="What do they want?" value={f.kind} onChange={(e) => set("kind", e.target.value)}><option value="export">A copy of their data (export)</option><option value="deletion">Their data deleted</option></Select>
          {hasOpen(f.kind) && <Alert tone="warning">There is already an open {f.kind} request for this business.</Alert>}
          <Input label="Who is asking?" value={f.name} onChange={(e) => set("name", e.target.value)} />
          <div className="grid gap-4 sm:grid-cols-2"><Select label="They are" value={f.role} onChange={(e) => set("role", e.target.value)}>{ROLE.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select>
            <Select label="They asked" value={f.via} onChange={(e) => set("via", e.target.value)}>{VIA.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select></div>
          <Input label="How they reached you (optional)" value={f.contact} onChange={(e) => set("contact", e.target.value)} hint="Kept only until the request ends. It is not used to verify them: you verify against the details already on the business record." />
          <Input label="Note (optional)" value={f.note} onChange={(e) => set("note", e.target.value)} />
        </div>
      </Modal>

      <Modal open={step?.kind === "verify"} onClose={() => setStep(null)} title="Verify who is asking" footer={<><Button variant="secondary" onClick={() => setStep(null)}>Cancel</Button>
        <Button loading={busy} disabled={!f.sure || (f.method === "other" && !f.note.trim()) || (!!needsContact && !f.contacted.trim())} onClick={() => step && step.kind === "verify" && void run(() => api(`/admin/data-requests/${step.r.id}/verify`, { method: "POST", body: { method: f.method, contacted_on: f.contacted.trim() || null, note: f.note.trim() || null, confirm: true } }), "Verified.")}>Record verification</Button></>}>
        <div className="space-y-4">{err && <Alert tone="error">{err}</Alert>}
          <Alert tone="warning">Check that this really is the business, using the contact details already on its record, not details that came with the request.</Alert>
          <Select label="How did you check?" value={f.method} onChange={(e) => set("method", e.target.value)}>{METHOD.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select>
          {needsContact && <Input label={f.method === "email_from_known_address" ? "Email address used" : "Phone number used"} value={f.contacted} onChange={(e) => set("contacted", e.target.value)} hint={onRecord ? `On the record: ${onRecord}. It must match.` : "There is nothing on the record to match. Add it to the business first, or choose another method."} />}
          <Textarea label={f.method === "other" ? "Describe how you verified them (required)" : "Note (optional)"} rows={2} value={f.note} onChange={(e) => set("note", e.target.value)} />
          <label className="flex min-h-11 items-start gap-2.5 text-sm"><input type="checkbox" checked={f.sure} onChange={(e) => set("sure", e.target.checked)} className="mt-1 h-5 w-5" /><span>I checked who is asking and I am satisfied they speak for this business.</span></label>
        </div>
      </Modal>

      <Modal open={step?.kind === "reject" || step?.kind === "cancel"} onClose={() => setStep(null)} title={step?.kind === "reject" ? "Reject this request?" : "Cancel this request?"} footer={<><Button variant="secondary" onClick={() => setStep(null)}>Back</Button>
        <Button variant="danger" loading={busy} disabled={f.reason.trim().length < 5} onClick={() => step && step.kind !== "new" && void run(() => api(`/admin/data-requests/${step.r.id}/${step.kind}`, { method: "POST", body: { reason: f.reason.trim() } }), step.kind === "reject" ? "Request rejected." : "Request cancelled.")}>{step?.kind === "reject" ? "Reject" : "Cancel request"}</Button></>}>
        <div className="space-y-4">{err && <Alert tone="error">{err}</Alert>}<p className="text-sm text-ink-700">Nothing is changed in the business&rsquo;s data. The reason is recorded, and the contact detail that came with the request is erased.</p>
          <Textarea label="Reason (required)" rows={2} value={f.reason} onChange={(e) => set("reason", e.target.value)} /></div>
      </Modal>

      <Modal open={step?.kind === "delivered"} onClose={() => setStep(null)} title="How was the export handed over?" footer={<><Button variant="secondary" onClick={() => setStep(null)}>Cancel</Button>
        <Button loading={busy} onClick={() => step && step.kind === "delivered" && void run(() => api(`/admin/data-requests/${step.r.id}/delivered`, { method: "POST", body: { delivery: f.delivery, note: f.note.trim() || null } }), "Marked as delivered.")}>Save</Button></>}>
        <div className="space-y-4">{err && <Alert tone="error">{err}</Alert>}<Select label="Delivery" value={f.delivery} onChange={(e) => set("delivery", e.target.value)}>{DELIVERY.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select><Input label="Note (optional)" value={f.note} onChange={(e) => set("note", e.target.value)} /></div>
      </Modal>

      <Modal open={step?.kind === "delete"} onClose={() => setStep(null)} title="Permanently delete this business?" footer={<><Button variant="secondary" onClick={() => setStep(null)}>Cancel</Button>
        <Button variant="danger" loading={busy} disabled={f.typed !== businessName || !f.ack} onClick={() => step && step.kind === "delete" && void run(() => api(`/admin/data-requests/${step.r.id}/execute-deletion`, { method: "POST", body: { confirm_name: f.typed, acknowledge: true } }).then(() => { window.location.href = "/admin/customers"; }), "Business deleted.")}>Delete permanently</Button></>}>
        <div className="space-y-4">{err && <Alert tone="error">{err}</Alert>}
          <Alert tone="error">This cannot be undone. The business, its locations and every record it owns are erased{step?.kind === "delete" && step.r.deletion?.impact ? ` (${step.r.deletion.impact.locations} location${step.r.deletion.impact.locations === 1 ? "" : "s"}, ${step.r.deletion.impact.cards} card${step.r.deletion.impact.cards === 1 ? "" : "s"}, ${step.r.deletion.impact.live_cards} of them live)` : ""}. Its printed cards go back to stock and stop working for customers.</Alert>
          <Input label={`Type the business name to confirm: ${businessName}`} value={f.typed} onChange={(e) => set("typed", e.target.value)} autoComplete="off" />
          <label className="flex min-h-11 items-start gap-2.5 text-sm"><input type="checkbox" checked={f.ack} onChange={(e) => set("ack", e.target.checked)} className="mt-1 h-5 w-5" /><span>I understand this permanently erases the business and returns its cards to stock.</span></label>
        </div>
      </Modal>
    </Card>
  );
}
