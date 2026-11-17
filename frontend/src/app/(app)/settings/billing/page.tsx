"use client";
import { AlertTriangle, CalendarClock, CreditCard } from "lucide-react";
import { useState } from "react";
import { PricingExperience } from "@/components/billing/PricingExperience";
import { Button, LinkButton } from "@/components/ui/Button";
import { Alert, Badge, Card, CardHeader, PageHeader, Skeleton } from "@/components/ui/Card";
import { Ring } from "@/components/charts/Bars";
import { CountUp } from "@/components/charts/CountUp";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { CashfreeCheckoutDialog } from "@/components/billing/CashfreeCheckout";
import { EVENT_LABELS, rupees } from "@/lib/billing";
import { fmtDate } from "@/lib/format";
import type { Plan, PlansResponse, SubscriptionEvent, SubscriptionInfo } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

/** One usage figure as a ring plus the exact "used / limit" (full or near-full turns amber then red). Real numbers from the subscription's usage and limits only. */
function UsageMeter({ label, used, limit }: { label: string; used: number; limit: number }) {
  const pct = limit ? Math.min(100, (used / limit) * 100) : 0;
  const tone = pct >= 90 ? "bad" : pct >= 70 ? "watch" : "good";
  return (
    <div className="flex items-center gap-3.5 rounded-[14px] bg-surface-2 p-3">
      <Ring value={limit ? pct : null} size={64} stroke={8} tone={tone} label={`${label}: ${used} of ${limit}`}><b className="num text-[15px] font-semibold"><CountUp value={used} /></b></Ring>
      <div className="min-w-0"><p className="text-[13.5px] font-medium leading-5 text-ink">{label}</p><p className="num text-[13px] text-muted">{used.toLocaleString("en-IN")} / {limit.toLocaleString("en-IN")}{limit > 0 && used >= limit ? " · full" : ""}</p></div>
    </div>
  );
}

function CashfreeNotices({ s, isOwner, onSetup }: { s: SubscriptionInfo; isOwner: boolean; onSetup: () => void }) {
  if (s.provider !== "cashfree") return null;
  const redo = isOwner && ["paused", "card_expired", "cancelled"].includes(s.authorization_status ?? "");
  return (
    <div className="mb-5 space-y-3">
      {s.billing_state === "authorization_pending" && <Alert tone="info" title="Payment setup in progress">Your bank is approving the payment setup. Your plan stays as it is and nothing is charged until it is approved.</Alert>}
      {s.billing_state === "trialing" && s.authorization_status === "authorized" && s.first_charge_at && <Alert tone="success" title="Payment set up">You have every Growth feature during your free trial. Your first payment{s.selected_plan_name ? ` for ${s.selected_plan_name}` : ""} is on {fmtDate(s.first_charge_at)}, when you move to that plan. Nothing is charged before then. You can cancel any time.</Alert>}
      {s.billing_state === "past_due" && <Alert tone="warning" title="Your last payment didn't go through" action={redo ? <Button size="sm" onClick={onSetup}>Set up payment again</Button> : undefined}>We ask your bank to try again{s.grace_until ? `, and your access continues until ${fmtDate(s.grace_until)}` : ""}. Make sure the account has the balance and the payment is allowed in your UPI app or card.</Alert>}
      {s.billing_state === "cancellation_pending" && <Alert tone="info" title="Cancelled">You won&rsquo;t be charged again. You keep access until {fmtDate(s.current_period_end)}.</Alert>}
    </div>
  );
}

function CashfreeOverview({ s, isOwner, onSetup, onRetry, retrying }: { s: SubscriptionInfo; isOwner: boolean; onSetup: () => void; onRetry: () => void; retrying: boolean }) {
  if (s.provider !== "cashfree") return null;
  const method = s.payment_method === "upi" ? "UPI AutoPay" : s.payment_method === "card" ? "Card" : s.has_cashfree_subscription ? "Authorised with Cashfree" : "None yet";
  const mandate: Record<string, string> = { initialized: "Waiting for your authorisation", bank_pending: "Your bank is approving it", authorized: "Active", paused: "Paused in your UPI app", card_expired: "Card expired", expired: "Not completed", cancelled: "Cancelled", failed: "Failed" };
  const broken = isOwner && ["paused", "card_expired", "cancelled", "expired"].includes(s.authorization_status ?? "") && s.billing_state !== "cancellation_pending";
  const rows: [string, React.ReactNode][] = [
    ["Plan", `${s.plan_name ?? "None"}${s.price_paise ? ` · ${rupees(s.price_paise)} a month` : ""}`],
    ["Status", s.billing_state === "cancellation_pending" ? "Cancelled: access continues until the end date" : (s.billing_state ?? s.status).replace(/_/g, " ")],
    ...(s.status === "trialing" && s.selected_plan_name ? [["Your plan after the trial", `${s.selected_plan_name} (you have every Growth feature until then)`] as [string, React.ReactNode]] : []),
    ["Free trial", s.trial_started_at ? `${fmtDate(s.trial_started_at)} to ${s.trial_ends_at ? fmtDate(s.trial_ends_at) : "-"}` : "Starts when your payment authorisation is confirmed"],
    ["Next payment", s.next_charge_amount_paise && (s.next_charge_at ?? s.first_charge_at) ? `${rupees(s.next_charge_amount_paise)} on ${fmtDate((s.next_charge_at ?? s.first_charge_at) as string)}` : "Nothing scheduled"],
    ["Payment method", method],
    ["Authorisation", mandate[s.authorization_status ?? ""] ?? "Not set up"],
  ];
  return (
    <Card className="mb-6">
      <CardHeader title="Subscription and payment" subtitle="What you pay, when, and how." />
      <dl className="mt-3 grid gap-x-8 gap-y-2 text-sm sm:grid-cols-[max-content_1fr]">{rows.map(([k, v]) => <div key={k} className="contents"><dt className="text-ink-500">{k}</dt><dd className="font-medium text-ink">{v}</dd></div>)}</dl>
      <div className="mt-4 flex flex-wrap gap-2">
        {isOwner && s.status === "past_due" && <Button size="sm" loading={retrying} onClick={onRetry}>Retry failed payment</Button>}
        {broken && <Button size="sm" variant="secondary" onClick={onSetup}>Update payment method</Button>}
        {isOwner && s.billing_state === "cancellation_pending" && <Button size="sm" variant="secondary" onClick={onSetup}>Resume subscription</Button>}
      </div>
      <p className="mt-3 text-xs text-ink-500">We never see or store your card number, CVV or UPI ID: Cashfree handles them. To change the payment method, authorise a new one here; the old authorisation is closed first, so you are never charged twice.</p>
    </Card>
  );
}

function BillingTerms() {
  return (
    <details className="mt-6 rounded-lg border border-ink-200 bg-white p-4 text-sm text-ink-700">
      <summary className="cursor-pointer font-semibold text-ink">Billing terms</summary>
      <ul className="mt-2 list-disc space-y-1.5 pl-5">
        <li>Plans renew monthly by an authorised recurring payment (UPI AutoPay or card) through Cashfree. We take a refundable ₹1 when you authorise, and return it automatically.</li>
        <li>Your free trial starts when Cashfree confirms the authorisation. The first payment is after the trial, on the date shown above. Nothing is charged before that.</li>
        <li>You are only charged your plan&rsquo;s monthly price. A plan change, up or down, takes effect at your next successful payment, with no proration and nothing extra charged.</li>
        <li>If a payment fails we tell you, your bank tries again, and your access continues for 7 days. If it still has not been paid by then, access pauses; your data is kept.</li>
        <li>Cancelling closes your authorisation with Cashfree, so no further payment can be taken. You keep access until the end of the period you have already paid for (or your trial).</li>
        <li>Receipts: your bank or UPI app lists each debit, and Payment history shows Cashfree&rsquo;s reference for it. FlowQR does not issue tax invoices from this screen.</li>
      </ul>
    </details>
  );
}

export default function SubscriptionPage() {
  const { role } = useAuth();
  const toast = useToast();
  const sub = useFetch<SubscriptionInfo>("/billing/subscription");
  const plans = useFetch<PlansResponse>("/billing/plans");
  const history = useFetch<{ events: SubscriptionEvent[] }>(role === "owner" || role === "admin" ? "/billing/subscription/history" : null);
  const [busy, setBusy] = useState<string | null>(null);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [cfPlan, setCfPlan] = useState<Plan | null>(null);
  const isOwner = role === "owner";
  const s = sub.data;
  const isCf = plans.data?.billing.provider === "cashfree";

  const [retrying, setRetrying] = useState(false);
  async function retry() {
    setRetrying(true);
    try { const r = await api<{ message: string }>("/billing/subscription/retry-payment", { method: "POST" }); toast(r.message); await sub.reload(); }
    catch (e) { toast(errorMessage(e), "error"); } finally { setRetrying(false); }
  }

  async function cancel() {
    setBusy("cancel");
    try { await api("/billing/subscription/cancel", { method: "POST", body: { at_cycle_end: true } }); toast("Cancellation scheduled for the end of your billing period."); setCancelOpen(false); await sub.reload(); }
    catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(null); }
  }

  const statusTone = s?.status === "active" ? "green" : s?.status === "trialing" ? "blue" : s?.status === "past_due" ? "amber" : "red";
  return (
    <>
      <PageHeader eyebrow="Business" title="Billing" subtitle="Your plan, usage and billing." actions={<LinkButton href="/settings/billing/payments" size="sm" variant="secondary" icon={<CreditCard className="h-4 w-4" />}>Payment history</LinkButton>} />
      {plans.data?.billing.mode === "test" && <div className="mb-5"><Alert tone="info" title="Payment test mode">Payments are simulated by the payment provider&rsquo;s test environment. No real money moves.</Alert></div>}
      {s && <CashfreeNotices s={s} isOwner={isOwner} onSetup={() => setCfPlan(plans.data?.plans.find((x) => x.code === (s.pending_plan ?? s.plan)) ?? plans.data?.plans[1] ?? null)} />}
      {s && <CashfreeOverview s={s} isOwner={isOwner} retrying={retrying} onRetry={() => void retry()} onSetup={() => setCfPlan(plans.data?.plans.find((x) => x.code === (s.pending_plan ?? s.plan)) ?? plans.data?.plans[1] ?? null)} />}
      {s && !s.active && <div className="mb-5"><Alert tone="error" title="Your subscription is not active" action={undefined}>{s.inactive_reason === "payment_failed" ? "Your last payment failed. Update your payment method or choose a plan to restore access." : s.inactive_reason === "trial_ended" ? "Your free trial has ended. Choose a plan to keep using reviews, replies and AI." : s.inactive_reason === "plan_expired" ? "Your prepaid plan has ended. Buy another term below to switch everything back on. Your data is kept." : "Choose a plan to continue."} Your QR/NFC cards keep working for customers.</Alert></div>}
      {s?.status === "past_due" && s.grace_until && <div className="mb-5"><Alert tone="warning" title="Payment failed">We couldn&rsquo;t charge your payment method. Access continues until {fmtDate(s.grace_until)} while the payment provider retries.</Alert></div>}

      {s?.promo && <div className="mb-5"><Alert tone="success" title={`Free ${s.promo.plan_name} until ${fmtDate(s.promo.ends_at)}`}>Included with your card purchase. {s.promo.note} Choose a plan whenever you like; you are only charged for a plan you pick yourself.</Alert></div>}
      <Card className="mb-6">
        {!s ? <Skeleton className="h-32" /> : (
          <div className="grid gap-6 lg:grid-cols-[1fr_1.2fr]">
            <div>
              <div className="flex flex-wrap items-center gap-2"><h2 className="text-xl font-semibold">{s.plan_name ?? "No plan"}</h2><Badge tone={statusTone}>{s.status.replace("_", " ")}</Badge>{s.billing.mode === "test" && <Badge tone="amber">test mode</Badge>}</div>
              {s.source === "prepaid" ? <p className="mt-1 text-ink-500">Prepaid plan · one payment, no auto-renewal</p> : s.price_paise && <p className="mt-1 text-ink-500">{rupees(s.price_paise)} / month</p>}
              {s.status === "trialing" && s.trial_ends_at && <p className="mt-3 flex items-center gap-2 text-sm"><CalendarClock className="h-4 w-4 text-brand-600" aria-hidden />Free trial ends {fmtDate(s.trial_ends_at)} ({s.trial_days_left} days left){s.selected_plan_name ? `, then ${s.selected_plan_name}` : ""}</p>}
              {s.current_period_end && s.status !== "trialing" && <p className="mt-3 flex items-center gap-2 text-sm"><CalendarClock className="h-4 w-4 text-brand-600" aria-hidden />{s.source === "prepaid" ? (s.active ? "Active until" : "Ended on") : s.cancel_at_period_end ? "Access until" : "Renews on"} {fmtDate(s.current_period_end)}</p>}
              {s.cancel_at_period_end && <p className="mt-2 flex items-center gap-2 text-sm text-amber-800"><AlertTriangle className="h-4 w-4" aria-hidden />Cancellation scheduled. You won&rsquo;t be charged again.</p>}
              {s.pending_plan && s.status !== "trialing" && <p className="mt-2 text-sm text-ink-500">Switching to <b>{s.pending_plan_name ?? s.pending_plan}</b> {s.pending_plan_effective_at ? <>on <b>{fmtDate(s.pending_plan_effective_at)}</b></> : "at the next renewal"}. Nothing extra is charged.</p>}
              {isOwner && !s.cancel_at_period_end && ((s.has_razorpay_subscription && ["active", "past_due"].includes(s.status)) || (isCf && s.has_cashfree_subscription && ["trialing", "active", "past_due"].includes(s.status) && ["authorized", "bank_pending", "initialized", "paused"].includes(s.authorization_status ?? ""))) && <Button className="mt-4" variant="danger" size="sm" onClick={() => setCancelOpen(true)}>Cancel subscription</Button>}
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <UsageMeter label="Locations" used={s.usage.locations} limit={s.limits.locations} />
              <UsageMeter label="AI review generations this month" used={s.usage.review_generations} limit={s.limits.review_generations} />
              <UsageMeter label="AI review replies this month" used={s.usage.review_replies} limit={s.limits.review_replies} />
              <UsageMeter label="Team members (incl. invites)" used={s.usage.staff} limit={s.limits.staff} />
            </div>
          </div>
        )}
      </Card>

      <PricingExperience plans={plans.data?.plans} terms={plans.data?.terms} sub={s} isOwner={isOwner} trialDays={plans.data?.trial_days ?? null} />
      {s?.provider === "cashfree" && <BillingTerms />}

      {history.data && history.data.events.length > 0 && (
        <section className="mt-16" aria-labelledby="sub-hist"><h2 id="sub-hist" className="mb-3 text-[15px] font-semibold">Subscription history</h2>
          <ul className="panel divide-y divide-line text-sm">{history.data.events.slice(0, 12).map((e, i) => <li key={i} className="flex flex-wrap items-baseline justify-between gap-2 px-4 py-2.5"><span>{EVENT_LABELS[e.kind] ?? e.kind.replace(/_/g, " ")}{e.to_plan && e.from_plan && e.from_plan !== e.to_plan ? ` (${e.from_plan} to ${e.to_plan})` : ""}</span><span className="text-xs text-muted">{fmtDate(e.at)}</span></li>)}</ul>
        </section>
      )}

      {cfPlan && plans.data && <CashfreeCheckoutDialog plan={cfPlan} plans={plans.data} onClose={() => setCfPlan(null)} />}
      <Modal open={cancelOpen} onClose={() => setCancelOpen(false)} title="Cancel subscription?" footer={<><Button variant="secondary" onClick={() => setCancelOpen(false)}>Keep plan</Button><Button variant="danger" loading={busy === "cancel"} onClick={() => void cancel()}>Cancel at period end</Button></>}>
        <p className="text-ink-700">{s?.status === "trialing" ? "No payment will be taken. " : ""}You keep full access until {fmtDate(s?.status === "trialing" ? s?.trial_ends_at : s?.current_period_end)}. After that, dashboards become read-only and AI features stop. Your cards and data are kept.{isCf ? " Cancelling also closes your payment authorisation with Cashfree, so no further payment can be taken." : ""}</p>
      </Modal>
    </>
  );
}
