"use client";
import { AlertTriangle, CalendarClock, CreditCard } from "lucide-react";
import { useState } from "react";
import { PlanCards } from "@/components/PlanCards";
import { Button, LinkButton } from "@/components/ui/Button";
import { Alert, Badge, Card, CardHeader, PageHeader, Skeleton } from "@/components/ui/Card";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api, ApiError, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { openCheckout, rupees } from "@/lib/billing";
import { fmtDate } from "@/lib/format";
import type { Plan, PlansResponse, SubscriptionInfo } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

function Meter({ label, used, limit }: { label: string; used: number; limit: number }) {
  const pct = limit ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  return (
    <div>
      <div className="flex justify-between text-sm"><span className="font-semibold text-ink-700">{label}</span><span className="tabular-nums text-ink-500">{used.toLocaleString("en-IN")} / {limit.toLocaleString("en-IN")}</span></div>
      <div className="mt-1.5 h-2.5 overflow-hidden rounded-full bg-ink-50" role="progressbar" aria-valuenow={used} aria-valuemin={0} aria-valuemax={limit} aria-label={label}>
        <div className={`h-full rounded-full ${pct >= 90 ? "bg-red-500" : pct >= 70 ? "bg-g-yellow" : "bg-brand-500"}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export default function SubscriptionPage() {
  const { me, role } = useAuth();
  const toast = useToast();
  const sub = useFetch<SubscriptionInfo>("/billing/subscription");
  const plans = useFetch<PlansResponse>("/billing/plans");
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
      <PageHeader title="Subscription" subtitle="Your plan, usage and billing." actions={<LinkButton href="/payments" variant="secondary" icon={<CreditCard className="h-4 w-4" />}>Payment history</LinkButton>} />
      {plans.data && !plans.data.billing.configured && <div className="mb-5"><Alert tone="warning" title="Online payments: configuration pending">Razorpay isn&rsquo;t configured on this server yet, so plans can&rsquo;t be purchased. Your trial and all features keep working meanwhile.</Alert></div>}
      {plans.data?.billing.mode === "test" && <div className="mb-5"><Alert tone="info" title="Razorpay test mode">Payments are simulated by Razorpay&rsquo;s test environment. No real money moves.</Alert></div>}
      {err && <div className="mb-5"><Alert tone="error" title="Couldn't complete that">{err.message}</Alert></div>}
      {s && !s.active && <div className="mb-5"><Alert tone="error" title="Your subscription is not active" action={undefined}>{s.inactive_reason === "payment_failed" ? "Your last payment failed. Update your payment method or choose a plan to restore access." : s.inactive_reason === "trial_ended" ? "Your free trial has ended. Choose a plan to keep using reviews, replies and AI." : "Choose a plan to continue."} Your QR/NFC cards keep working for customers.</Alert></div>}
      {s?.status === "past_due" && s.grace_until && <div className="mb-5"><Alert tone="warning" title="Payment failed">We couldn&rsquo;t charge your payment method. Access continues until {fmtDate(s.grace_until)} while Razorpay retries.</Alert></div>}

      <Card className="mb-6">
        {!s ? <Skeleton className="h-32" /> : (
          <div className="grid gap-6 lg:grid-cols-[1fr_1.2fr]">
            <div>
              <div className="flex flex-wrap items-center gap-2"><h2 className="text-xl font-semibold">{s.plan_name ?? "No plan"}</h2><Badge tone={statusTone}>{s.status.replace("_", " ")}</Badge>{s.billing.mode === "test" && <Badge tone="orange">test mode</Badge>}</div>
              {s.price_paise && <p className="mt-1 text-ink-500">{rupees(s.price_paise)} / month</p>}
              {s.status === "trialing" && s.trial_ends_at && <p className="mt-3 flex items-center gap-2 text-sm"><CalendarClock className="h-4 w-4 text-brand-600" aria-hidden />Free trial ends {fmtDate(s.trial_ends_at)} ({s.trial_days_left} days left)</p>}
              {s.current_period_end && s.status !== "trialing" && <p className="mt-3 flex items-center gap-2 text-sm"><CalendarClock className="h-4 w-4 text-brand-600" aria-hidden />{s.cancel_at_period_end ? "Access until" : "Renews on"} {fmtDate(s.current_period_end)}</p>}
              {s.cancel_at_period_end && <p className="mt-2 flex items-center gap-2 text-sm text-amber-800"><AlertTriangle className="h-4 w-4" aria-hidden />Cancellation scheduled. You won&rsquo;t be charged again.</p>}
              {s.pending_plan && <p className="mt-2 text-sm text-ink-500">Switching to <b>{s.pending_plan}</b> at the next renewal.</p>}
              {isOwner && s.has_razorpay_subscription && ["active", "past_due"].includes(s.status) && !s.cancel_at_period_end && <Button className="mt-4" variant="danger" size="sm" onClick={() => setCancelOpen(true)}>Cancel subscription</Button>}
            </div>
            <div className="space-y-4">
              <Meter label="Locations" used={s.usage.locations} limit={s.limits.locations} />
              <Meter label="AI generations this month" used={s.usage.ai_generations} limit={s.limits.ai_generations} />
              <Meter label="Team members (incl. invites)" used={s.usage.staff} limit={s.limits.staff} />
            </div>
          </div>
        )}
      </Card>

      <h2 className="mb-3 text-lg font-semibold">{s?.has_razorpay_subscription && s.status === "active" ? "Change plan" : "Choose a plan"}</h2>
      {!isOwner && <div className="mb-4"><Alert tone="info">Only the business owner can change the subscription.</Alert></div>}
      {plans.data ? (
        <PlanCards plans={plans.data.plans} current={s?.plan} action={(p) => (
          <Button className="w-full" variant={p.code === "growth" ? "primary" : "secondary"} loading={busy === p.code} disabled={!isOwner || !plans.data!.billing.configured || s?.plan === p.code || !!busy}
            onClick={() => void choose(p)}>{s?.plan === p.code ? "Current plan" : s?.has_razorpay_subscription && s.status === "active" ? `Switch to ${p.name}` : `Choose ${p.name}`}</Button>
        )} />
      ) : <Skeleton className="h-64" />}
      <p className="mt-4 text-xs text-ink-500">Subscriptions renew monthly via Razorpay. A plan becomes active only after Razorpay confirms your payment. Physical cards are billed separately under Payments.</p>

      <Modal open={cancelOpen} onClose={() => setCancelOpen(false)} title="Cancel subscription?" footer={<><Button variant="secondary" onClick={() => setCancelOpen(false)}>Keep plan</Button><Button variant="danger" loading={busy === "cancel"} onClick={() => void cancel()}>Cancel at period end</Button></>}>
        <p className="text-ink-700">You keep full access until {fmtDate(s?.current_period_end)}. After that, dashboards become read-only and AI features stop. Your cards and data are kept.</p>
      </Modal>
    </>
  );
}
