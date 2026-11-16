"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { PlanCards } from "@/components/PlanCards";
import { Button } from "@/components/ui/Button";
import { Alert, Card, Skeleton, Spinner } from "@/components/ui/Card";
import { api, errorMessage } from "@/lib/api";
import { rupees } from "@/lib/billing";
import { fmtDate } from "@/lib/format";
import type { Plan, PlansResponse, SubscriptionInfo } from "@/lib/types";
import { useFetch } from "@/lib/use-api";
import { CashfreeCheckoutDialog } from "./CashfreeCheckout";

/** Onboarding step "Plan and payment". The 7-day free trial starts only when the SERVER, having asked Cashfree, says the payment authorisation is confirmed. This step never decides that: it
 *  shows the plans, opens the disclosure, and afterwards asks the server (POST /billing/subscription/sync) what happened. Progress lives on the server, so leaving checkout, closing the tab or
 *  failing the authorisation loses nothing: this step simply shows the right state again, and "try again" never creates a second mandate. */
export function PlanAuthorizationStep({ onDone }: { onDone: () => void }) {
  const sub = useFetch<SubscriptionInfo>("/billing/subscription");
  const plans = useFetch<PlansResponse>("/billing/plans");
  const [pick, setPick] = useState<Plan | null>(null);
  const [checking, setChecking] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const checked = useRef(false);
  const s = sub.data;
  const auth = s?.authorization_status ?? null;
  const authorised = s?.status === "trialing" && auth === "authorized";

  const check = useCallback(async (n = 0) => {
    setChecking(true);
    try {
      const out = await api<{ authorization_status: string | null; status: string }>("/billing/subscription/sync", { method: "POST" });
      setNote(null);
      await sub.reload();
      if (out.authorization_status === "bank_pending" && n < 24) timer.current = setTimeout(() => void check(n + 1), 5000);  // the bank approves in its own time: keep asking, politely
    } catch (e) { setNote(errorMessage(e)); }
    finally { setChecking(false); }
  }, [sub]);

  useEffect(() => {  // arriving here with an authorisation already started (coming back from Cashfree, or reopening the page): ask the server once
    if (!s || checked.current) return;
    checked.current = true;
    if (s.has_cashfree_subscription && (auth === "initialized" || auth === "bank_pending") && s.status === "incomplete") void check();
    if (typeof window !== "undefined" && window.location.search.includes("checkout=")) window.history.replaceState(null, "", window.location.pathname);
  }, [s, auth, check]);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  if (!s || !plans.data) return <Card><Skeleton className="h-40" /></Card>;

  if (authorised) {
    const first = s.first_charge_at ?? s.next_charge_at;
    return (
      <Card>
        <h1 className="text-2xl font-semibold">Your free trial has started</h1>
        <p className="mt-2 text-ink-700">Cashfree confirmed your payment authorisation, so your {plans.data.trial_days}-day free trial is running{s.trial_ends_at ? <> until <b>{fmtDate(s.trial_ends_at)}</b></> : null}.</p>
        <ul className="mt-4 space-y-1.5 text-sm text-ink-700">
          {first && <li><b>First payment:</b> {s.next_charge_amount_paise ? rupees(s.next_charge_amount_paise) : "your plan amount"} on {fmtDate(first)}, then every month.</li>}
          <li><b>Payment method:</b> {s.payment_method === "upi" ? "UPI AutoPay" : s.payment_method === "card" ? "Card" : "Authorised with Cashfree"}</li>
          <li>The refundable {rupees(plans.data.billing.authorization_paise ?? 100)} authorisation is returned to you automatically. Cancel any time in Billing before the first payment and nothing is charged.</li>
        </ul>
        <Button className="mt-5 w-full" size="lg" onClick={onDone}>Continue</Button>
      </Card>
    );
  }

  const open = s.has_cashfree_subscription && auth === "initialized";
  const pending = auth === "bank_pending";
  const failed = auth === "expired" || auth === "cancelled";
  const pendingPlan = plans.data.plans.find((p) => p.code === s.pending_plan) ?? null;

  return (
    <Card>
      <h1 className="text-2xl font-semibold">Choose your plan to start your free trial</h1>
      <p className="mt-2 text-ink-700">Your {plans.data.trial_days}-day free trial starts once you authorise a payment method with Cashfree (UPI AutoPay or a card). You are not charged for the plan until the trial ends. We tell you the exact first payment date and the refundable ₹1 authorisation before you continue.</p>
      {note && <div className="mt-4"><Alert tone="warning">{note}</Alert></div>}
      {pending && <div className="mt-4"><Alert tone="info" title="Your bank is approving the authorisation">This can take a day or two. Your trial starts as soon as it is approved, and this page updates by itself. Nothing was charged.
        <div className="mt-2"><Button size="sm" variant="secondary" loading={checking} onClick={() => void check()}>Check now</Button></div></Alert></div>}
      {open && <div className="mt-4"><Alert tone="warning" title="We haven't received your authorisation yet">The trial has not started and nothing was charged. If you completed it, check again; if you left, start again. Starting again never creates a second authorisation.
        <div className="mt-2 flex flex-wrap gap-2"><Button size="sm" loading={checking} onClick={() => void check()}>Check again</Button>{pendingPlan && <Button size="sm" variant="secondary" onClick={() => setPick(pendingPlan)}>Start again with {pendingPlan.name}</Button>}</div></Alert></div>}
      {failed && <div className="mt-4"><Alert tone="error" title="The authorisation didn't complete">Nothing was charged and your trial has not started. You can choose a plan and try again.</Alert></div>}
      {checking && !pending && !open && <div className="mt-4 flex items-center gap-2 text-sm text-ink-700"><Spinner /> Confirming with Cashfree&hellip;</div>}
      <div className="mt-5">
        <PlanCards plans={plans.data.plans} current={null} action={(p) => (
          <Button className="w-full" variant={p.code === "growth" ? "primary" : "secondary"} disabled={!plans.data!.billing.configured || pending} onClick={() => setPick(p)}>Choose {p.name}</Button>
        )} />
      </div>
      <p className="mt-4 text-xs text-ink-500">You can cancel in Billing at any time. Plan changes later take effect at your next payment, with nothing extra charged.</p>
      {pick && <CashfreeCheckoutDialog plan={pick} plans={plans.data} onClose={() => setPick(null)} />}
    </Card>
  );
}
