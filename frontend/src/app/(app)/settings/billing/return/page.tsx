"use client";
import { useEffect, useRef, useState } from "react";
import { Button, LinkButton } from "@/components/ui/Button";
import { Alert, PageHeader, Spinner } from "@/components/ui/Card";
import { api, errorMessage } from "@/lib/api";
import { rupees } from "@/lib/billing";
import { fmtDate } from "@/lib/format";
import type { SubscriptionInfo } from "@/lib/types";

interface Synced { status: string; billing_state: string; authorization_status: string | null }

/** Where Cashfree sends the customer back to. It reads NOTHING from the address bar: it asks the server, which asks Cashfree. So a copied, edited or forged link can say anything and
 *  change nothing. While a bank approval is pending it asks again every few seconds. */
export default function BillingReturn() {
  const [r, setR] = useState<Synced | null>(null);
  const [sub, setSub] = useState<SubscriptionInfo | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tries, setTries] = useState(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let live = true;
    async function check(n: number) {
      try {
        const out = await api<Synced>("/billing/subscription/sync", { method: "POST" });
        if (!live) return;
        setR(out); setErr(null); setTries(n);
        setSub(await api<SubscriptionInfo>("/billing/subscription"));
        if ((out.authorization_status === "bank_pending" || out.billing_state === "authorization_pending") && n < 24) timer.current = setTimeout(() => void check(n + 1), 5000);
      } catch (e) {
        if (!live) return;
        setErr(errorMessage(e)); setTries(n);
        if (n < 6) timer.current = setTimeout(() => void check(n + 1), 5000);
      }
    }
    void check(0);
    return () => { live = false; if (timer.current) clearTimeout(timer.current); };
  }, []);

  const st = r?.authorization_status;
  const first = sub?.first_charge_at ?? sub?.next_charge_at;
  return (
    <>
      <PageHeader eyebrow="Business" title="Payment setup" subtitle="Checking with Cashfree what happened." />
      <div className="max-w-xl space-y-4">
        {!r && !err && <div className="flex items-center gap-3 text-sm text-ink-700"><Spinner /> Confirming with Cashfree&hellip;</div>}
        {err && !r && <Alert tone="warning" title="We couldn't confirm this yet">{err} We keep checking, and your plan updates by itself once Cashfree confirms.</Alert>}
        {r?.billing_state === "active" && <Alert tone="success" title="Your plan is active">Your payment went through. Thank you.</Alert>}
        {r && r.billing_state !== "active" && st === "authorized" && (
          <Alert tone="success" title="Payment set up">
            Cashfree confirmed your authorisation. {first ? <>Your <b>first payment{sub?.price_paise ? ` of ${rupees(sub.price_paise)}` : ""} is on {fmtDate(first)}</b>, and nothing is charged before then. </> : null}
            The refundable authorisation is returned to you automatically. Your plan becomes active when that first payment is confirmed. You can cancel any time in Billing.
          </Alert>
        )}
        {r && st === "bank_pending" && <Alert tone="info" title="Your bank is approving the setup">This can take up to a day or two. Your free trial continues meanwhile and this page updates by itself{tries >= 24 ? " (we stopped checking here; come back to Billing any time)" : ""}.</Alert>}
        {r && st === "initialized" && <Alert tone="warning" title="No authorisation received yet">Cashfree hasn&rsquo;t received your authorisation, so nothing was set up and nothing was charged. You can try again.</Alert>}
        {r && (st === "expired" || st === "cancelled") && <Alert tone="error" title="The payment setup didn't complete">Nothing was charged. Your free trial is unchanged. You can start again from Billing.</Alert>}
        {r && st === "paused" && <Alert tone="warning" title="The payment is paused">Your UPI app shows this payment as paused, so Cashfree cannot collect it. Resume it there, or set it up again from Billing.</Alert>}
        <div className="flex flex-wrap gap-2"><LinkButton href="/settings/billing">Back to Billing</LinkButton>{(st === "initialized" || st === "expired") && <Button variant="secondary" onClick={() => { window.location.href = "/settings/billing"; }}>Try again</Button>}</div>
      </div>
    </>
  );
}
