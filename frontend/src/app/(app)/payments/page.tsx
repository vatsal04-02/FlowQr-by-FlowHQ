"use client";
import { Package, Receipt } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, CardHeader, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { ErrorSummary, Input } from "@/components/ui/Form";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { openCheckout, rupees } from "@/lib/billing";
import { fmtDate } from "@/lib/format";
import { phoneRule, required, useForm } from "@/lib/form";
import type { CardOrder, Payment, PlansResponse } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

const TONE: Record<string, "green" | "amber" | "red" | "gray" | "blue"> = { captured: "green", paid: "green", shipped: "green", authorized: "blue", processing: "blue", created: "gray", failed: "red", refunded: "amber", cancelled: "red" };

export default function PaymentsPage() {
  const { role } = useAuth();
  const toast = useToast();
  const [tab, setTab] = useState<"subscription" | "card_order" | "">("");
  const pays = useFetch<Payment[]>("/billing/payments", { kind: tab });
  const orders = useFetch<CardOrder[]>("/billing/card-orders");
  const plans = useFetch<PlansResponse>("/billing/plans");
  const [orderOpen, setOrderOpen] = useState(false);

  return (
    <>
      <PageHeader title="Payments" subtitle="Software subscription payments and physical card orders are tracked separately."
        actions={role === "owner" ? <Button icon={<Package className="h-4 w-4" />} onClick={() => setOrderOpen(true)} disabled={!plans.data?.card_ordering_enabled}>Order cards</Button> : undefined} />
      {plans.data && !plans.data.card_ordering_enabled && <div className="mb-5"><Alert tone="warning" title="Card ordering: configuration pending">{!plans.data.billing.configured ? "Card ordering opens once Razorpay is configured on this server." : "Card pricing hasn't been set yet. Please contact FlowQR."}</Alert></div>}

      <Card className="mb-6" pad={false}>
        <div className="p-5 sm:p-6"><CardHeader title="Card orders" subtitle="Physical QR/NFC cards. Shipped by the FlowQR team after payment is confirmed." /></div>
        {orders.loading && !orders.data ? <Skeleton className="m-5 h-20" /> : orders.data && orders.data.length === 0 ? <p className="px-6 pb-6 text-sm text-ink-500">No card orders yet.</p> : (
          <ul className="divide-y divide-ink-100 border-t border-ink-100">{orders.data?.map((o) => (
            <li key={o.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3.5 sm:px-6">
              <div><p className="font-semibold">{o.quantity} cards · {rupees(o.amount_paise)}</p><p className="text-sm text-ink-500">{fmtDate(o.created_at)}{o.tracking_note && ` · ${o.tracking_note}`}</p></div>
              <Badge tone={TONE[o.status] ?? "gray"}>{o.status === "created" ? "awaiting payment" : o.status}</Badge>
            </li>))}</ul>
        )}
      </Card>

      <Card pad={false}>
        <div className="flex flex-wrap items-center justify-between gap-3 p-5 sm:p-6">
          <CardHeader title="Payment history" />
          <div role="tablist" aria-label="Payment type" className="flex gap-1 rounded-xl bg-ink-50 p-1">
            {([["", "All"], ["subscription", "Subscription"], ["card_order", "Cards"]] as const).map(([k, l]) => (
              <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)} className={`min-h-9 rounded-lg px-3 text-sm font-semibold ${tab === k ? "bg-white shadow-card" : "text-ink-500"}`}>{l}</button>))}
          </div>
        </div>
        {pays.loading && !pays.data ? <Skeleton className="m-5 h-32" /> : pays.data && pays.data.length === 0 ? (
          <div className="p-6"><EmptyState icon={<Receipt className="h-6 w-6" />} title="No payments yet">Payments appear here once Razorpay confirms them.</EmptyState></div>
        ) : (
          <div className="overflow-x-auto"><table className="w-full min-w-[640px] text-left text-sm">
            <thead className="border-y border-ink-100 bg-ink-50 text-xs uppercase tracking-wide text-ink-500"><tr>{["Date", "Type", "Amount", "Status", "Reference"].map((h) => <th key={h} className="px-4 py-2.5 font-semibold">{h}</th>)}</tr></thead>
            <tbody>{pays.data?.map((p) => (
              <tr key={p.id} className="border-b border-ink-100 last:border-0">
                <td className="px-4 py-3">{fmtDate(p.paid_at ?? p.created_at)}</td><td className="px-4">{p.kind === "subscription" ? "Subscription" : "Card order"}</td>
                <td className="px-4 font-semibold tabular-nums">{rupees(p.amount_paise)}</td>
                <td className="px-4"><Badge tone={TONE[p.status] ?? "gray"}>{p.status}</Badge>{p.error_description && <span className="mt-0.5 block text-xs text-red-700">{p.error_description}</span>}</td>
                <td className="px-4 font-mono text-xs text-ink-500">{p.razorpay_payment_id ?? "–"}{p.razorpay_invoice_id && <span className="block">inv {p.razorpay_invoice_id}</span>}</td>
              </tr>))}</tbody>
          </table></div>
        )}
      </Card>
      {orderOpen && plans.data?.card_price_paise && <OrderModal unit={plans.data.card_price_paise} onClose={() => setOrderOpen(false)} onDone={() => { setOrderOpen(false); void orders.reload(); void pays.reload(); }} toast={toast} />}
    </>
  );
}

function OrderModal({ unit, onClose, onDone, toast }: { unit: number; onClose: () => void; onDone: () => void; toast: (m: string, t?: "success" | "error") => void }) {
  const { me } = useAuth();
  const [busy, setBusy] = useState(false);
  const [key] = useState(() => crypto.randomUUID()); // idempotency: a double-click can't create two orders
  const f = useForm({ quantity: "20", name: me?.user.full_name ?? "", phone: me?.user.phone ?? "", address_line: "", city: "", state: "", postal_code: "" }, {
    quantity: (v) => (Number.isInteger(Number(v)) && Number(v) >= 10 && Number(v) <= 1000 ? undefined : "Order 10 to 1000 cards"),
    name: required("Name"), phone: (v) => (String(v).trim() ? phoneRule(v) : "Phone is required"), address_line: required("Address"), city: required("City"), state: required("State"),
    postal_code: (v) => (/^\d{6}$/.test(String(v)) ? undefined : "Enter a 6-digit PIN code"),
  });
  const total = Number(f.values.quantity || 0) * unit;

  async function submit(e: React.FormEvent) {
    e.preventDefault(); f.setServerError(null);
    if (!f.validateAll()) return;
    setBusy(true);
    try {
      const v = f.values;
      const o = await api<{ order_id: string; key_id: string; amount_paise: number }>("/billing/card-orders", { method: "POST", headers: { "Idempotency-Key": key }, body: { quantity: Number(v.quantity), shipping: { name: v.name.trim(), phone: v.phone, address_line: v.address_line.trim(), city: v.city.trim(), state: v.state.trim(), postal_code: v.postal_code } } });
      await openCheckout({
        key: o.key_id, order_id: o.order_id, description: `${v.quantity} FlowQR cards`, prefill: { name: v.name, email: me?.user.email }, onDismiss: () => setBusy(false),
        onSuccess: async (r) => {
          try { const res = await api<{ status: string }>("/billing/card-orders/verify", { method: "POST", body: { razorpay_order_id: r.razorpay_order_id, razorpay_payment_id: r.razorpay_payment_id, razorpay_signature: r.razorpay_signature } });
            toast(res.status === "paid" ? "Payment confirmed. We'll ship your cards soon." : "Payment received. Confirmation is pending."); } catch (er) { toast(errorMessage(er), "error"); }
          onDone();
        },
      });
    } catch (err) { f.fail(errorMessage(err)); setBusy(false); }
  }
  return (
    <Modal open onClose={onClose} title="Order physical cards" footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" form="order-form" loading={busy}>Pay {rupees(total)}</Button></>}>
      <form id="order-form" onSubmit={submit} noValidate className="space-y-4">
        <ErrorSummary errors={f.errors} serverError={f.serverError} summaryRef={f.summaryRef} />
        <Input label="Number of cards" inputMode="numeric" hint={`${rupees(unit)} per card · min 10`} {...f.bind("quantity")} />
        <Input label="Contact name" {...f.bind("name")} /><Input label="Phone" type="tel" {...f.bind("phone")} /><Input label="Address" {...f.bind("address_line")} />
        <div className="grid gap-4 sm:grid-cols-3"><Input label="City" {...f.bind("city")} /><Input label="State" {...f.bind("state")} /><Input label="PIN code" inputMode="numeric" {...f.bind("postal_code")} /></div>
        <p className="text-xs text-ink-500">Cards are assigned to your locations by the FlowQR team after dispatch. This is a one-time purchase and is separate from your subscription.</p>
      </form>
    </Modal>
  );
}
