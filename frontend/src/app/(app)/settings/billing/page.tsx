"use client";
import { AlertTriangle, CalendarClock, CreditCard } from "lucide-react";
import { useState } from "react";
import { PlanCards } from "@/components/PlanCards";
import { Button, LinkButton } from "@/components/ui/Button";
import { Alert, Badge, Card, CardHeader, PageHeader, Skeleton } from "@/components/ui/Card";
import { Meter } from "@/components/ui/kit";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api, ApiError, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { EVENT_LABELS, openCheckout, rupees } from "@/lib/billing";
import { fmtDate } from "@/lib/format";
import type { Plan, PlansResponse, SubscriptionEvent, SubscriptionInfo } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

function UsageMeter({ label, used, limit }: { label: string; used: number; limit: number }) {
  const pct = limit ? (used / limit) * 100 : 0;
  return (
    <div>
      <div className="mb-1.5 flex justify-between text-[13px]"><span className="font-medium text-ink-700">{label}</span><span className="num text-ink-500">{used.toLocaleString("en-IN")} / {limit.toLocaleString("en-IN")}</span></div>
      <Meter label={label} value={used} max={limit} tone={pct >= 90 ? "bad" : pct >= 70 ? "warn" : "info"} />
    </div>
  );
}

export default function SubscriptionPage() {
  const { me, role } = useAuth();
  const toast = useToast();
  const sub = useFetch<SubscriptionInfo>("/billing/subscription");
  const plans = useFetch<PlansResponse>("/billing/plans");
  const history = useFetch<{ events: SubscriptionEvent[] }>(role === "owner" || role === "admin" ? "/billing/subscription/history" : null);
  const [busy, setBusy] = useState<string | null>(null);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [err, setErr] = useState<{ message: string; code?: string } | null>(null);
  const isOwner = role === "owner";
  const s = sub.data;

  async function choose(p: Plan) {
    setBusy(p.code); setErr(null);
    try {
      if (s?.has_razorpay_subscription && s.status === "active") {
        await api("/billing/subscription/change-plan", { method: "POST", body: { plan: p.code } });
        toast("Plan change requested."); await sub.reload(); return;
      }
      const c = await api<{ subscription_id: string; key_id: string }>("/billing/subscription/checkout", { method: "POST", body: { plan: p.code } });
      await openCheckout({
        key: c.key_id, subscription_id: c.subscription_id, description: `FlowQR ${p.name}`, prefill: { name: me?.user.full_name, email: me?.user.email },
        onDismiss: () => setBusy(null),
        onSuccess: async (r) => {
          try {
            const v = await api<{ message: string }>("/billing/subscription/verify", { method: "POST", body: { razorpay_payment_id: r.razorpay_payment_id, razorpay_subscription_id: r.razorpay_subscription_id, razorpay_signature: r.razorpay_signature } });
            toast(v.message);
          } catch (e) { setErr({ message: errorMessage(e) }); }
          await sub.reload(); setBusy(null);
        },
      });
      return;
    } catch (e) { setErr({ message: errorMessage(e), code: e instanceof ApiError ? e.code : undefined }); }
    setBusy(null);
  }

  async function cancel() {
    setBusy("cancel");
    try { await api("/billing/subscription/cancel", { method: "POST", body: { at_cycle_end: true } }); toast("Cancellation scheduled for the end of your billing period."); setCancelOpen(false); await sub.reload(); }
    catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(null); }
  }

  const statusTone = s?.status === "active" ? "green" : s?.status === "trialing" ? "blue" : s?.status === "past_due" ? "amber" : "red";
  return (
    <>
      <PageHeader eyebrow="Business" title="Subscription" subtitle="Your plan, usage and billing." actions={<LinkButton href="/settings/billing/payments" size="sm" variant="secondary" icon={<CreditCard className="h-4 w-4" />}>Payment history</LinkButton>} />
      {plans.data && !plans.data.billing.configured && <div className="mb-5"><Alert tone="warning" title="Online payments are not switched on yet">Paying online isn&rsquo;t available on this server yet, so plans can&rsquo;t be purchased here. Your trial and all features keep working meanwhile.</Alert></div>}
      {plans.data?.billing.mode === "test" && <div className="mb-5"><Alert tone="info" title="Payment test mode">Payments are simulated by the payment provider&rsquo;s test environment. No real money moves.</Alert></div>}
      {err && <div className="mb-5"><Alert tone="error" title="Couldn't complete that">{err.message}</Alert></div>}
      {s && !s.active && <div className="mb-5"><Alert tone="error" title="Your subscription is not active" action={undefined}>{s.inactive_reason === "payment_failed" ? "Your last payment failed. Update your payment method or choose a plan to restore access." : s.inactive_reason === "trial_ended" ? "Your free trial has ended. Choose a plan to keep using reviews, replies and AI." : "Choose a plan to continue."} Your QR/NFC cards keep working for customers.</Alert></div>}
      {s?.status === "past_due" && s.grace_until && <div className="mb-5"><Alert tone="warning" title="Payment failed">We couldn&rsquo;t charge your payment method. Access continues until {fmtDate(s.grace_until)} while the payment provider retries.</Alert></div>}

      {s?.promo && <div className="mb-5"><Alert tone="success" title={`Free ${s.promo.plan_name} until ${fmtDate(s.promo.ends_at)}`}>Included with your card purchase. {s.promo.note} Choose a plan whenever you like; you are only charged for a plan you pick yourself.</Alert></div>}
      <Card className="mb-6">
        {!s ? <Skeleton className="h-32" /> : (
          <div className="grid gap-6 lg:grid-cols-[1fr_1.2fr]">
            <div>
              <div className="flex flex-wrap items-center gap-2"><h2 className="text-xl font-semibold">{s.plan_name ?? "No plan"}</h2><Badge tone={statusTone}>{s.status.replace("_", " ")}</Badge>{s.billing.mode === "test" && <Badge tone="amber">test mode</Badge>}</div>
              {s.price_paise && <p className="mt-1 text-ink-500">{rupees(s.price_paise)} / month</p>}
              {s.status === "trialing" && s.trial_ends_at && <p className="mt-3 flex items-center gap-2 text-sm"><CalendarClock className="h-4 w-4 text-brand-600" aria-hidden />Free trial ends {fmtDate(s.trial_ends_at)} ({s.trial_days_left} days left)</p>}
              {s.current_period_end && s.status !== "trialing" && <p className="mt-3 flex items-center gap-2 text-sm"><CalendarClock className="h-4 w-4 text-brand-600" aria-hidden />{s.cancel_at_period_end ? "Access until" : "Renews on"} {fmtDate(s.current_period_end)}</p>}
              {s.cancel_at_period_end && <p className="mt-2 flex items-center gap-2 text-sm text-amber-800"><AlertTriangle className="h-4 w-4" aria-hidden />Cancellation scheduled. You won&rsquo;t be charged again.</p>}
              {s.pending_plan && <p className="mt-2 text-sm text-ink-500">Switching to <b>{s.pending_plan}</b> at the next renewal.</p>}
              {isOwner && s.has_razorpay_subscription && ["active", "past_due"].includes(s.status) && !s.cancel_at_period_end && <Button className="mt-4" variant="danger" size="sm" onClick={() => setCancelOpen(true)}>Cancel subscription</Button>}
            </div>
            <div className="space-y-4">
              <UsageMeter label="Locations" used={s.usage.locations} limit={s.limits.locations} />
              <UsageMeter label="AI review generations this month" used={s.usage.review_generations} limit={s.limits.review_generations} />
              <UsageMeter label="AI review replies this month" used={s.usage.review_replies} limit={s.limits.review_replies} />
              <UsageMeter label="Team members (incl. invites)" used={s.usage.staff} limit={s.limits.staff} />
            </div>
          </div>
        )}
      </Card>

      <h2 className="mb-3 text-[15px] font-semibold">{s?.has_razorpay_subscription && s.status === "active" ? "Change plan" : "Choose a plan"}</h2>
      {!isOwner && <div className="mb-4"><Alert tone="info">Only the business owner can change the subscription.</Alert></div>}
      {plans.data ? (
        <PlanCards plans={plans.data.plans} current={s?.plan} action={(p) => (
          <Button className="w-full" variant={p.code === "growth" ? "primary" : "secondary"} loading={busy === p.code} disabled={!isOwner || !plans.data!.billing.configured || s?.plan === p.code || !!busy}
            onClick={() => void choose(p)}>{s?.plan === p.code ? "Current plan" : s?.has_razorpay_subscription && s.status === "active" ? `Switch to ${p.name}` : `Choose ${p.name}`}</Button>
        )} />
      ) : <Skeleton className="h-64" />}
      <p className="mt-4 text-xs text-ink-500">Subscriptions renew monthly through our payment provider. A plan becomes active only after the provider confirms your payment. Physical cards are billed separately under Payments.</p>

      {history.data && history.data.events.length > 0 && (
        <section className="mt-8" aria-labelledby="sub-hist"><h2 id="sub-hist" className="mb-3 text-[15px] font-semibold">Subscription history</h2>
          <ul className="panel divide-y divide-line text-sm">{history.data.events.slice(0, 12).map((e, i) => <li key={i} className="flex flex-wrap items-baseline justify-between gap-2 px-4 py-2.5"><span>{EVENT_LABELS[e.kind] ?? e.kind.replace(/_/g, " ")}{e.to_plan && e.from_plan && e.from_plan !== e.to_plan ? ` (${e.from_plan} to ${e.to_plan})` : ""}</span><span className="text-xs text-muted">{fmtDate(e.at)}</span></li>)}</ul>
        </section>
      )}

      <Modal open={cancelOpen} onClose={() => setCancelOpen(false)} title="Cancel subscription?" footer={<><Button variant="secondary" onClick={() => setCancelOpen(false)}>Keep plan</Button><Button variant="danger" loading={busy === "cancel"} onClick={() => void cancel()}>Cancel at period end</Button></>}>
        <p className="text-ink-700">You keep full access until {fmtDate(s?.current_period_end)}. After that, dashboards become read-only and AI features stop. Your cards and data are kept.</p>
      </Modal>
    </>
  );
}
