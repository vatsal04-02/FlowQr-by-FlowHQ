"use client";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Skeleton } from "@/components/ui/Card";
import { Input } from "@/components/ui/Form";
import { Modal } from "@/components/ui/Modal";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { openCashfreeCheckout, rupees } from "@/lib/billing";
import { fmtDate } from "@/lib/format";
import type { Plan, PlansResponse } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

interface Preview {
  plan_name: string; amount_paise: number; first_charge_at: string; free_period_honoured: boolean; trial_days: number; trial_starts_on_authorization: boolean;
  authorization_paise: number; mandate_ceiling_paise: number;
}

/** What the customer is told BEFORE they reach Cashfree. Every number and date comes from the SERVER (`/billing/subscription/preview`: it creates nothing), never from this page. Nothing here says
 *  the trial is free of any payment step: a refundable authorisation is part of setting up UPI AutoPay or a card, and the first real charge, with its amount and date, is shown first. */
export function CashfreeCheckoutDialog({ plan, plans, onClose }: { plan: Plan; plans: PlansResponse; onClose: () => void }) {
  const { me } = useAuth();
  const preview = useFetch<Preview>(`/billing/subscription/preview?plan=${plan.code}`);
  const [phone, setPhone] = useState((me?.user.phone ?? "").replace(/\D/g, "").slice(-10));
  const [agree, setAgree] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const p = preview.data;
  const auth = p?.authorization_paise ?? plans.billing.authorization_paise ?? 100;

  async function go() {
    setBusy(true); setErr(null);
    try {
      const out = await api<{ subscription_session_id: string; environment: string }>("/billing/subscription/checkout", { method: "POST", body: { plan: plan.code, phone } });
      await openCashfreeCheckout(out.subscription_session_id, out.environment);  // Cashfree takes over; we come back and ask the server what happened
    } catch (e) { setErr(e instanceof Error ? errorMessage(e) : "Something went wrong. Please try again."); setBusy(false); }
  }

  return (
    <Modal open onClose={onClose} title={`Authorise payment for ${plan.name}`}
      footer={<><Button variant="secondary" onClick={onClose} disabled={busy}>Not now</Button><Button loading={busy} disabled={!agree || phone.length !== 10 || !p} onClick={() => void go()}>Continue to Cashfree</Button></>}>
      <div className="space-y-3 text-sm text-ink-700">
        {err && <Alert tone="error">{err}</Alert>}
        {preview.error && <Alert tone="error">{preview.error}</Alert>}
        {!p && !preview.error && <Skeleton className="h-24" />}
        {p && <>
          <p><b>{plan.name}</b> is <b>{rupees(p.amount_paise)}</b> a month.</p>
          {p.trial_starts_on_authorization
            ? <p>Your <b>{p.trial_days}-day free trial starts as soon as Cashfree confirms your authorisation</b>, and not before. Your <b>first payment of {rupees(p.amount_paise)} is on {fmtDate(p.first_charge_at)}</b>, then every month. Cancel before then and you will not be charged.</p>
            : p.free_period_honoured
              ? <p>You are on your free trial. Your <b>first payment of {rupees(p.amount_paise)} is on {fmtDate(p.first_charge_at)}</b>, then every month. Cancel before then and you will not be charged.</p>
              : <p>Your free trial is over, so your <b>first payment of {rupees(p.amount_paise)} is on {fmtDate(p.first_charge_at)}</b> (about two days after you authorise), then every month.</p>}
          <div className="rounded-lg border border-ink-200 bg-ink-50 p-3">
            <p className="font-semibold text-ink">A refundable {rupees(auth)} authorisation</p>
            <p className="mt-1">To set up UPI AutoPay or a card, your bank or UPI app takes <b>{rupees(auth)} now</b> and <b>returns it to you automatically</b>. It is not a charge for the plan, and it means the trial is not completely free of any payment step.</p>
          </div>
          <p>You are only ever charged {rupees(p.amount_paise)} a month. The authorisation allows up to {rupees(p.mandate_ceiling_paise)} a month so you can change plans later without authorising again. Plan changes take effect at your next payment, with nothing extra charged.</p>
          <p>You pay with UPI AutoPay or a card through Cashfree. FlowQR never sees your card or UPI details. Cancel any time in Billing.</p>
          <Input label="Mobile number linked to your bank or UPI app" inputMode="tel" autoComplete="tel" value={phone} onChange={(e) => setPhone(e.target.value.replace(/\D/g, "").slice(0, 10))} hint="10 digits. Cashfree needs it to set up the payment." />
          <label className="flex items-start gap-2 text-ink">
            <input type="checkbox" className="mt-1" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
            <span>I understand the {rupees(auth)} authorisation, the first payment date and the monthly amount above.</span>
          </label>
        </>}
      </div>
    </Modal>
  );
}
