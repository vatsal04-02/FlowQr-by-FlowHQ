"use client";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Card";
import { Input } from "@/components/ui/Form";
import { Modal } from "@/components/ui/Modal";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { openCashfreeCheckout, rupees } from "@/lib/billing";
import { fmtDate } from "@/lib/format";
import type { Plan, PlansResponse, SubscriptionInfo } from "@/lib/types";

/** What the customer is told BEFORE they reach Cashfree. The amounts come from the server's plan list, never typed here; the dates from the subscription the server holds. Nothing
 *  here says the trial is free of any payment step: a refundable Rs 1 authorisation is part of setting up UPI AutoPay or a card, and the page says so first. */
export function CashfreeCheckoutDialog({ plan, plans, sub, onClose }: { plan: Plan; plans: PlansResponse; sub: SubscriptionInfo; onClose: () => void }) {
  const { me } = useAuth();
  const [phone, setPhone] = useState((me?.user.phone ?? "").replace(/\D/g, "").slice(-10));
  const [agree, setAgree] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const auth = plans.billing.authorization_paise ?? 100;
  const ceiling = Math.max(...plans.plans.map((p) => p.price_paise));
  const freeUntil = sub.status === "trialing" && sub.trial_ends_at ? sub.trial_ends_at : null;

  async function go() {
    setBusy(true); setErr(null);
    try {
      const out = await api<{ subscription_session_id: string; environment: string }>("/billing/subscription/checkout", { method: "POST", body: { plan: plan.code, phone } });
      await openCashfreeCheckout(out.subscription_session_id, out.environment);  // Cashfree takes over; we come back through /settings/billing/return
    } catch (e) { setErr(e instanceof Error ? errorMessage(e) : "Something went wrong. Please try again."); setBusy(false); }
  }

  return (
    <Modal open onClose={onClose} title={`Set up payment for ${plan.name}`}
      footer={<><Button variant="secondary" onClick={onClose} disabled={busy}>Not now</Button><Button loading={busy} disabled={!agree || phone.length !== 10} onClick={() => void go()}>Continue to Cashfree</Button></>}>
      <div className="space-y-3 text-sm text-ink-700">
        {err && <Alert tone="error">{err}</Alert>}
        <p><b>{plan.name}</b> is <b>{rupees(plan.price_paise)}</b> a month.</p>
        {freeUntil
          ? <p>Your free trial runs until <b>{fmtDate(freeUntil)}</b>. Your <b>first payment of {rupees(plan.price_paise)} is on {fmtDate(freeUntil)}</b>, then every month. You can cancel before then and you will not be charged.</p>
          : <p>Your free trial is over, so your <b>first payment of {rupees(plan.price_paise)} is taken about two days after you authorise it</b> (we show you the exact date when it is set up), then every month.</p>}
        <div className="rounded-lg border border-ink-200 bg-ink-50 p-3">
          <p className="font-semibold text-ink">A refundable {rupees(auth)} authorisation</p>
          <p className="mt-1">To set up UPI AutoPay or a card, your bank or UPI app takes <b>{rupees(auth)} now</b> and <b>returns it to you automatically</b>. This is not a charge for the plan, and it means the trial is not completely free of any payment step.</p>
        </div>
        <p>You are only ever charged {rupees(plan.price_paise)} a month. The authorisation allows up to {rupees(ceiling)} a month so you can change plans later without authorising again.</p>
        <p>You pay with UPI AutoPay or a card through Cashfree. FlowQR never sees your card or UPI details. Cancel any time in Billing.</p>
        <Input label="Mobile number linked to your bank or UPI app" inputMode="tel" autoComplete="tel" value={phone} onChange={(e) => setPhone(e.target.value.replace(/\D/g, "").slice(0, 10))} hint="10 digits. Cashfree needs it to set up the payment." />
        <label className="flex items-start gap-2 text-ink">
          <input type="checkbox" className="mt-1" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
          <span>I understand the {rupees(auth)} authorisation, the first payment date and the monthly amount above.</span>
        </label>
      </div>
    </Modal>
  );
}
