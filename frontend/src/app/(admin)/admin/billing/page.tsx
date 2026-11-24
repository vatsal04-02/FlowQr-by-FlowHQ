"use client";
import Link from "next/link";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Badge, Card, CardHeader, PageHeader, Skeleton } from "@/components/ui/Card";
import { FilterSelect, Input } from "@/components/ui/Form";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { rupees } from "@/lib/billing";
import { fmtDate } from "@/lib/format";
import { useFetch } from "@/lib/use-api";
import { SUB_TONE } from "@/lib/admin-ui";

interface Sub { tenant_id: string; tenant: string; plan: string; status: string; source: string; trial_ends_at: string | null; current_period_end: string | null; next_charge_at?: string | null; cancel_at_period_end: boolean }
interface Pay { id: string; tenant: string; kind: string; status: string; amount_paise: number; razorpay_payment_id: string | null; error_description: string | null; created_at: string }
interface Hook { id: string; type: string; status: string; attempts: number; subscription_ref: string | null; received_at: string; last_error: string | null }
interface Order { id: string; tenant: string; quantity: number; amount_paise: number; status: string; shipping: Record<string, string>; tracking_note: string | null; created_at: string }

export default function AdminBilling() {
  const toast = useToast();
  const [subStatus, setSubStatus] = useState(""), [kind, setKind] = useState(""), [payStatus, setPayStatus] = useState("");
  const subs = useFetch<Sub[]>("/admin/subscriptions", { status: subStatus });
  const pays = useFetch<Pay[]>("/admin/payments", { kind, status: payStatus });
  const orders = useFetch<Order[]>("/admin/card-orders");
  const hooks = useFetch<Hook[]>("/admin/webhooks");
  async function reprocess(id: string) {
    try { await api(`/admin/webhooks/${id}/reprocess`, { method: "POST" }); toast("Re-read from Cashfree."); await hooks.reload(); } catch (e) { toast(errorMessage(e), "error"); }
  }
  const [ship, setShip] = useState<Order | null>(null); const [note, setNote] = useState(""); const [busy, setBusy] = useState(false);

  async function update(status: string) {
    if (!ship) return;
    setBusy(true);
    try { await api(`/admin/card-orders/${ship.id}`, { method: "PATCH", body: { status, tracking_note: note || null } }); toast("Order updated."); setShip(null); setNote(""); await orders.reload(); } catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(false); }
  }
  return (
    <>
      <PageHeader eyebrow="Platform" title="Subscriptions & payments" subtitle="Renewals, payments and physical card orders (kept separate). Changes go through the payment provider, never around it." />
      <Card className="mb-5" pad={false}>
        <div className="flex flex-wrap items-center justify-between gap-3 p-5 sm:p-6"><CardHeader title="Card orders" subtitle="Ship only after payment shows as paid." /></div>
        {!orders.data ? <Skeleton className="m-5 h-24" /> : orders.data.length === 0 ? <p className="px-6 pb-6 text-sm text-ink-500">No card orders.</p> : (<>
          <ul aria-label="Card orders" className="space-y-2 px-3 pb-3 md:hidden">{orders.data.map((o) => (
            <li key={o.id} className="rounded-xl border border-ink-100 p-3"><div className="flex items-start justify-between gap-2"><span className="min-w-0 truncate text-[15px] font-semibold">{o.tenant}</span><Badge tone={o.status === "paid" ? "green" : o.status === "shipped" ? "blue" : o.status === "created" ? "gray" : "amber"}>{o.status === "created" ? "unpaid" : o.status}</Badge></div>
              <p className="mt-1 text-[13px]">{o.quantity} cards · <b className="num font-semibold">{rupees(o.amount_paise)}</b> · {fmtDate(o.created_at)}</p>
              <p className="mt-1 text-xs text-ink-500">{o.shipping.name}, {o.shipping.address_line}, {o.shipping.city} {o.shipping.postal_code}</p>
              {["paid", "processing"].includes(o.status) && <Button size="sm" variant="secondary" className="mt-2" onClick={() => { setShip(o); setNote(o.tracking_note ?? ""); }}>Fulfil</Button>}</li>))}</ul>
          <div className="hidden overflow-x-auto md:block"><table className="dt min-w-[720px]"><thead><tr>{["Date", "Business", "Qty", "Amount", "Status", "Ship to", ""].map((h) => <th key={h} className="px-4 py-2.5">{h}</th>)}</tr></thead>
            <tbody>{orders.data.map((o) => (
              <tr key={o.id} className="border-b border-ink-100 last:border-0"><td className="px-4 py-3">{fmtDate(o.created_at)}</td><td className="px-4 font-semibold">{o.tenant}</td><td className="px-4 tabular-nums">{o.quantity}</td><td className="px-4 tabular-nums">{rupees(o.amount_paise)}</td>
                <td className="px-4"><Badge tone={o.status === "paid" ? "green" : o.status === "shipped" ? "blue" : o.status === "created" ? "gray" : "amber"}>{o.status === "created" ? "unpaid" : o.status}</Badge></td>
                <td className="max-w-[220px] px-4 text-xs text-ink-500">{o.shipping.name}, {o.shipping.address_line}, {o.shipping.city} {o.shipping.postal_code}</td>
                <td className="px-4 text-right">{["paid", "processing"].includes(o.status) && <Button size="sm" variant="secondary" onClick={() => { setShip(o); setNote(o.tracking_note ?? ""); }}>Fulfil</Button>}</td></tr>))}</tbody></table></div></>)}
      </Card>

      <div className="grid gap-5 xl:grid-cols-2">
        <Card pad={false}><div className="flex flex-wrap items-center justify-between gap-3 p-5"><CardHeader title="Subscriptions" /><FilterSelect label="Status" value={subStatus} onChange={(e) => setSubStatus(e.target.value)}><option value="">All</option>{["trialing", "active", "past_due", "halted", "expired", "canceled", "pending"].map((s) => <option key={s}>{s}</option>)}</FilterSelect></div>
          {!subs.data ? <Skeleton className="m-5 h-32" /> : <>
            <ul aria-label="Subscriptions" className="max-h-[560px] space-y-2 overflow-auto px-3 pb-3 md:hidden">{subs.data.map((x) => (
              <li key={x.tenant_id} className="rounded-xl border border-ink-100 p-3"><div className="flex items-start justify-between gap-2"><Link href={`/admin/customers/${x.tenant_id}`} className="min-w-0 truncate text-[15px] font-semibold text-brand-700">{x.tenant}</Link><Badge tone={SUB_TONE[x.status] ?? "gray"}>{x.status}</Badge></div>
                <p className="mt-1 text-xs text-ink-500">{x.plan} · {x.source}{x.cancel_at_period_end ? " · cancels at period end" : ""}</p>
                <p className="mt-1 text-[13px]">{x.status === "trialing" ? "Trial ends" : "Renews"} {fmtDate(x.status === "trialing" ? x.trial_ends_at : x.next_charge_at || x.current_period_end)}</p></li>))}
              {subs.data.length === 0 && <li className="py-4 text-center text-sm text-ink-500">No subscriptions.</li>}</ul>
            <div className="hidden max-h-[480px] overflow-auto md:block"><table className="dt"><thead className="sticky top-0 bg-ink-50"><tr>{["Business", "Plan", "Status", "Ends"].map((h) => <th key={h} className="px-4 py-2.5">{h}</th>)}</tr></thead>
            <tbody>{subs.data.map((s) => <tr key={s.tenant_id} className="border-b border-ink-100"><td className="px-4 py-2.5 font-semibold">{s.tenant}</td><td className="px-4">{s.plan}<span className="block text-xs text-ink-500">{s.source}</span></td><td className="px-4"><Badge tone={SUB_TONE[s.status] ?? "gray"}>{s.status}</Badge>{s.cancel_at_period_end && <span className="block text-xs text-amber-700">cancels</span>}</td><td className="px-4 text-xs">{fmtDate(s.status === "trialing" ? s.trial_ends_at : s.current_period_end)}</td></tr>)}</tbody></table></div></>}</Card>
        <Card pad={false}><div className="flex flex-wrap items-center justify-between gap-3 p-5"><CardHeader title="Payments" /><div className="flex gap-2"><FilterSelect label="Type" value={kind} onChange={(e) => setKind(e.target.value)}><option value="">All types</option><option value="subscription">Subscription</option><option value="card_order">Cards</option></FilterSelect><FilterSelect label="Payment status" value={payStatus} onChange={(e) => setPayStatus(e.target.value)}><option value="">All</option><option>captured</option><option>failed</option><option>refunded</option></FilterSelect></div></div>
          {!pays.data ? <Skeleton className="m-5 h-32" /> : <>
            <ul aria-label="Payments" className="max-h-[560px] space-y-2 overflow-auto px-3 pb-3 md:hidden">{pays.data.map((p) => (
              <li key={p.id} className="rounded-xl border border-ink-100 p-3"><div className="flex items-start justify-between gap-2"><span className="min-w-0 truncate text-[15px] font-semibold">{p.tenant}</span><Badge tone={p.status === "captured" ? "green" : p.status === "failed" ? "red" : "gray"}>{p.status}</Badge></div>
                <p className="mt-1 text-[13px]"><b className="num font-semibold">{rupees(p.amount_paise)}</b> · {p.kind === "card_order" ? "Cards" : "Subscription"} · {fmtDate(p.created_at)}</p>
                {p.error_description && <p className="mt-1 text-xs text-neg">{p.error_description}</p>}</li>))}
              {pays.data.length === 0 && <li className="py-4 text-center text-sm text-ink-500">No payments.</li>}</ul>
            <div className="hidden max-h-[480px] overflow-auto md:block"><table className="dt"><thead className="sticky top-0 bg-ink-50"><tr>{["Date", "Business", "Type", "Amount", "Status"].map((h) => <th key={h} className="px-4 py-2.5">{h}</th>)}</tr></thead>
            <tbody>{pays.data.map((p) => <tr key={p.id} className="border-b border-ink-100"><td className="px-4 py-2.5">{fmtDate(p.created_at)}</td><td className="px-4 font-semibold">{p.tenant}</td><td className="px-4">{p.kind === "card_order" ? "Cards" : "Subscription"}</td><td className="px-4 tabular-nums">{rupees(p.amount_paise)}</td><td className="px-4"><Badge tone={p.status === "captured" ? "green" : p.status === "failed" ? "red" : "gray"}>{p.status}</Badge>{p.error_description && <span className="block text-xs text-red-700">{p.error_description}</span>}</td></tr>)}{pays.data.length === 0 && <tr><td colSpan={5} className="px-4 py-6 text-center text-ink-500">No payments.</td></tr>}</tbody></table></div></>}</Card>
      </div>

      <Card className="mt-5" pad={false}>
        <div className="p-5"><CardHeader title="Cashfree events" subtitle="Each event is only a hint: reprocessing re-reads the subscription from Cashfree and cannot mark anything paid." /></div>
        {!hooks.data ? <Skeleton className="m-5 h-24" /> : hooks.data.length === 0 ? <p className="px-6 pb-6 text-sm text-ink-500">No events yet.</p> : (
          <div className="max-h-[360px] overflow-auto"><table className="dt min-w-[640px]"><thead className="sticky top-0 bg-ink-50"><tr>{["Received", "Event", "Subscription", "Status", "Tries", ""].map((h) => <th key={h} className="px-4 py-2.5">{h}</th>)}</tr></thead>
            <tbody>{hooks.data.map((h) => (
              <tr key={h.id} className="border-b border-ink-100"><td className="px-4 py-2.5">{fmtDate(h.received_at)}</td><td className="px-4 font-mono text-xs">{h.type}</td><td className="px-4 font-mono text-xs">{h.subscription_ref ?? "-"}</td>
                <td className="px-4"><Badge tone={h.status === "processed" ? "green" : h.status === "failed" ? "red" : "gray"}>{h.status}</Badge>{h.last_error && <p className="text-xs text-red-700">{h.last_error}</p>}</td><td className="px-4 tabular-nums">{h.attempts}</td>
                <td className="px-4 text-right">{h.status !== "processed" && h.subscription_ref && <Button size="sm" variant="secondary" onClick={() => void reprocess(h.id)}>Reprocess</Button>}</td></tr>))}</tbody></table></div>
        )}
      </Card>

      <Modal open={!!ship} onClose={() => setShip(null)} title="Fulfil card order" footer={<><Button variant="secondary" onClick={() => setShip(null)}>Close</Button><Button variant="secondary" loading={busy} onClick={() => void update("processing")}>Mark processing</Button><Button loading={busy} onClick={() => void update("shipped")}>Mark shipped</Button></>}>
        {ship && <><p className="mb-3 text-sm">{ship.quantity} cards for <b>{ship.tenant}</b> → {ship.shipping.name}, {ship.shipping.address_line}, {ship.shipping.city}, {ship.shipping.state} {ship.shipping.postal_code} · {ship.shipping.phone}</p><Input label="Tracking / note" value={note} onChange={(e) => setNote(e.target.value)} /></>}
      </Modal>
    </>
  );
}
