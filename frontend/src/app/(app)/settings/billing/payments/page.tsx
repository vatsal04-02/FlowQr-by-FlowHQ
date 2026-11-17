"use client";
import { Package } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, PageHeader, Skeleton } from "@/components/ui/Card";
import { ErrorSummary, Input } from "@/components/ui/Form";
import { Panel, Segmented, Status } from "@/components/ui/kit";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { openCheckout, rupees } from "@/lib/billing";
import { fmtDate } from "@/lib/format";
import { phoneRule, required, useForm } from "@/lib/form";
import type { CardOffer, CardOrder, Payment, PlansResponse } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

const TONE: Record<string, "ok" | "warn" | "bad" | "idle" | "info"> = { captured: "ok", paid: "ok", shipped: "ok", authorized: "info", processing: "info", created: "idle", failed: "bad", refunded: "warn", cancelled: "bad" };

export default function PaymentsPage() {
  const { role } = useAuth();
  const toast = useToast();
  const [tab, setTab] = useState<"" | "subscription" | "card_order">("");
  const pays = useFetch<Payment[]>("/billing/payments", { kind: tab });
  const orders = useFetch<CardOrder[]>("/billing/card-orders");
  const plans = useFetch<PlansResponse>("/billing/plans");
  const [orderOpen, setOrderOpen] = useState(false);

  return (
    <>
      <PageHeader eyebrow="Business" title="Payments" subtitle="Software subscription payments and physical card orders are tracked separately."
        actions={role === "owner" ? <Button size="sm" icon={<Package className="h-4 w-4" />} onClick={() => setOrderOpen(true)} disabled={!plans.data?.card_ordering_enabled}>Order cards</Button> : undefined} />
      {plans.data && !plans.data.card_ordering_enabled && <div className="mb-4"><Alert tone="warning" title="Card ordering: configuration pending">{!plans.data.billing.configured ? "Card ordering opens once online payments are switched on." : "Card pricing hasn't been set yet. Please contact FlowQR."}</Alert></div>}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)]">
        <Panel title="Card orders" meta="shipped after payment is confirmed" flush>
          {orders.loading && !orders.data ? <Skeleton className="m-4 h-20" /> : orders.data && orders.data.length === 0 ? <p className="p-4 text-sm text-ink-500">No card orders yet. Physical cards are paid per order and shipped by the FlowQR team.</p> : (
            <ul className="divide-y divide-ink-100">{orders.data?.map((o) => (
              <li key={o.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
                <div><p className="text-sm font-semibold"><span className="num">{o.quantity}</span> cards · <span className="num">{rupees(o.amount_paise)}</span></p><p className="text-[13px] text-ink-500">{fmtDate(o.created_at)}{o.tracking_note && ` · ${o.tracking_note}`}</p></div>
                <Status tone={TONE[o.status] ?? "idle"}>{o.status === "created" ? "Awaiting payment" : o.status}</Status>
              </li>))}</ul>
          )}
        </Panel>

        <Panel title="Payment history" action={<Segmented label="Payment type" value={tab} onChange={setTab} options={[["", "All"], ["subscription", "Subscription"], ["card_order", "Cards"]] as const} />} flush>
          {pays.loading && !pays.data ? <Skeleton className="m-4 h-32" /> : pays.data && pays.data.length === 0 ? (
            <p className="p-4 text-sm text-ink-500">No payments yet. They appear here once your payment provider confirms them.</p>
          ) : (
            <div className="overflow-x-auto"><table className="dt min-w-[560px]">
              <thead><tr><th>Date</th><th>Type</th><th className="!text-right">Amount</th><th>Status</th><th>Reference</th></tr></thead>
              <tbody>{pays.data?.map((p) => (
                <tr key={p.id}>
                  <td className="whitespace-nowrap">{fmtDate(p.paid_at ?? p.created_at)}</td><td>{p.kind === "sub_auth" ? "Authorisation (returned to you)" : p.kind === "subscription" && p.payment_type === "PREPAID" ? "Prepaid plan (one payment)" : p.kind === "subscription" ? "Subscription" : "Card order"}</td>
                  <td className="n font-semibold">{rupees(p.amount_paise)}</td>
                  <td><Status tone={TONE[p.status] ?? "idle"}>{p.status}</Status>{(p.error_description ?? p.failure_reason) && <p className="text-xs text-red-700">{p.error_description ?? p.failure_reason}</p>}</td>
                  <td className="font-mono text-xs text-ink-500">{p.razorpay_payment_id ?? "–"}{p.razorpay_invoice_id && <span className="block">inv {p.razorpay_invoice_id}</span>}</td>
                </tr>))}</tbody>
            </table></div>
          )}
        </Panel>
      </div>
      {orderOpen && plans.data && (plans.data.card_offers.length > 0 || plans.data.card_price_paise) && <OrderModal offers={plans.data.card_offers} unit={plans.data.card_price_paise} onClose={() => setOrderOpen(false)} onDone={() => { setOrderOpen(false); void orders.reload(); void pays.reload(); }} toast={toast} />}
    </>
  );
}

function OrderModal({ offers, unit, onClose, onDone, toast }: { offers: CardOffer[]; unit: number | null; onClose: () => void; onDone: () => void; toast: (m: string, t?: "success" | "error") => void }) {
  const { me } = useAuth();
  const [busy, setBusy] = useState(false);
  const [key] = useState(() => crypto.randomUUID()); // idempotency: a double-click can't create two orders
  const f = useForm({ quantity: String(offers[0]?.quantity ?? 20), name: me?.user.full_name ?? "", phone: me?.user.phone ?? "", address_line: "", city: "", state: "", postal_code: "" }, {
    quantity: (v) => (offers.some((o) => o.quantity === Number(v)) || (unit && Number.isInteger(Number(v)) && Number(v) >= 10 && Number(v) <= 1000) ? undefined : `Choose ${offers.map((o) => o.quantity).join(" or ")} cards`),
    name: required("Name"), phone: (v) => (String(v).trim() ? phoneRule(v) : "Phone is required"), address_line: required("Address"), city: required("City"), state: required("State"),
    postal_code: (v) => (/^\d{6}$/.test(String(v)) ? undefined : "Enter a 6-digit PIN code"),
  });
  const offer = offers.find((o) => o.quantity === Number(f.values.quantity));
  const total = offer ? offer.price_paise : Number(f.values.quantity || 0) * (unit ?? 0);

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
        {offers.length > 0 && <fieldset><legend className="mb-2 text-sm font-medium">Choose a pack</legend><div className="grid gap-2 sm:grid-cols-2">{offers.map((o) => (
          <label key={o.code} className={`flex cursor-pointer flex-col rounded-tile border p-3 ${Number(f.values.quantity) === o.quantity ? "border-ink bg-surface-2" : "border-line"}`}>
            <input type="radio" name="pack" className="sr-only" checked={Number(f.values.quantity) === o.quantity} onChange={() => f.set("quantity", String(o.quantity))} />
            <span className="font-semibold">{o.quantity} {o.quantity === 1 ? "card" : "cards"}</span><span className="num text-lg">{rupees(o.price_paise)}</span><span className="text-xs text-muted">one-time · includes {o.includes} free</span></label>))}</div></fieldset>}
        {unit ? <Input label={offers.length ? "Or a bulk order (10 to 1000 cards)" : "Number of cards"} inputMode="numeric" hint={`${rupees(unit)} per card for bulk orders`} {...f.bind("quantity")} /> : null}
        <Input label="Contact name" {...f.bind("name")} /><Input label="Phone" type="tel" {...f.bind("phone")} /><Input label="Address" {...f.bind("address_line")} />
        <div className="grid gap-4 sm:grid-cols-3"><Input label="City" {...f.bind("city")} /><Input label="State" {...f.bind("state")} /><Input label="PIN code" inputMode="numeric" {...f.bind("postal_code")} /></div>
        <p className="text-xs text-ink-500">Cards are assigned to your locations by the FlowQR team after dispatch. This is a one-time purchase, separate from any subscription. The included free month is access, not a subscription: nothing is charged when it ends.</p>
      </form>
    </Modal>
  );
}
