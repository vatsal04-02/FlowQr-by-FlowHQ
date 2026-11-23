"use client";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { PaymentTicket } from "@/components/billing/PaymentTicket";
import { LinkButton } from "@/components/ui/Button";
import { Alert, PageHeader, Spinner } from "@/components/ui/Card";
import { api, errorMessage } from "@/lib/api";
import type { PrepaidResult } from "@/lib/types";

const PLAN: Record<string, string> = { starter: "Launch", growth: "Growth", pro: "Scale" };
const ID = /^fqp_[0-9a-f]{24}$/;

/** Where Cashfree sends the customer back to after a one-time payment. It reads ONE thing from the address bar, our own order id, and uses it only to ask the SERVER what really happened (the
 *  server asks Cashfree). So a copied, edited or forged link can say anything and change nothing. While the payment is still being confirmed it asks again every few seconds. */
function Body() {
  const orderId = useSearchParams().get("order_id") ?? "";
  const [r, setR] = useState<PrepaidResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!ID.test(orderId)) return;
    let live = true;
    async function check(n: number) {
      try {
        const out = await api<PrepaidResult>("/billing/prepaid/verify", { method: "POST", body: { order_id: orderId } });
        if (!live) return;
        setR(out); setErr(null);
        if ((out.state === "pending" || out.state === "open" || out.unconfirmed) && n < 20) timer.current = setTimeout(() => void check(n + 1), 4000);
      } catch (e) {
        if (!live) return;
        setErr(errorMessage(e));
        if (n < 5) timer.current = setTimeout(() => void check(n + 1), 4000);
      }
    }
    void check(0);
    return () => { live = false; if (timer.current) clearTimeout(timer.current); };
  }, [orderId]);

  if (!ID.test(orderId)) return <Alert tone="error" title="This payment link isn't valid">Open Billing to start again. Nothing was charged.</Alert>;
  const name = r ? PLAN[r.plan] ?? r.plan : "";
  return (
    <div className="mx-auto max-w-xl space-y-4">
      {!r && !err && <div className="flex items-center gap-3 text-sm text-ink-700" role="status"><Spinner /> Confirming your payment with the payment provider&hellip;</div>}
      {err && !r && /not found/i.test(err) && <Alert tone="error" title="We can't find this payment">This link doesn&rsquo;t match any payment on your account, so nothing was changed. Open Billing to start again.</Alert>}
      {err && !r && !/not found/i.test(err) && <Alert tone="warning" title="We couldn't confirm this yet">{err} If you paid, your plan starts by itself once the payment is confirmed. Nothing is lost.</Alert>}
      {r?.state === "paid" && <PaymentTicket plan={name} months={r.months} amountPaise={r.amount_paise} endsAt={r.ends_at} orderId={r.order_id} />}
      {r?.state === "pending" && <Alert tone="info" title="Your payment is being confirmed">{r.unconfirmed ? "We couldn't reach the payment provider just now, so we are asking again. " : "Your bank or UPI app hasn't finished yet. "}This page updates by itself. If money was taken, your plan starts as soon as it is confirmed, even if you close this page.</Alert>}
      {r?.state === "open" && <Alert tone="info" title="No payment received yet">We haven&rsquo;t received a payment for this order. If you closed the payment page, nothing was charged. You can start again from Billing.</Alert>}
      {r?.state === "failed" && <Alert tone="warning" title="The payment didn't go through">Nothing was charged and your account is unchanged.{r.failure_reason ? ` Reason given: ${r.failure_reason}.` : ""} You can try again from Billing.</Alert>}
      {r?.state === "expired" && <Alert tone="warning" title="The payment page expired">Nothing was charged and your account is unchanged. Start again from Billing.</Alert>}
      {r?.state === "mismatch" && <Alert tone="error" title="This payment needs a person to look at it">The amount we received doesn&rsquo;t match this order, so we did not start the plan. Please contact support with order <b>{r.order_id}</b>; if you were charged we will put it right.</Alert>}
      <div className={r?.state === "paid" ? "relative z-10 mx-auto flex w-full max-w-sm flex-col gap-2" : "flex flex-wrap gap-2"}>{r?.state === "paid" && <LinkButton href="/overview" variant="brand" size="lg" className="w-full !rounded-full">Go to Home</LinkButton>}<LinkButton href="/settings/billing" variant={r?.state === "paid" ? "secondary" : "primary"} className={r?.state === "paid" ? "w-full !rounded-full" : undefined}>{r?.state === "paid" ? "Back to Billing" : "Open Billing"}</LinkButton></div>
    </div>
  );
}

export default function PayReturn() {
  return (
    <>
      <PageHeader eyebrow="Business" title="Your payment" subtitle="Checking what happened." />
      <Suspense fallback={<div className="flex items-center gap-3 text-sm text-ink-700"><Spinner /> Loading&hellip;</div>}><Body /></Suspense>
    </>
  );
}
