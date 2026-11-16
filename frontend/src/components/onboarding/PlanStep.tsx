"use client";
import clsx from "clsx";
import { ArrowRight, Check, CheckCircle2, CreditCard, Lock } from "lucide-react";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Spinner } from "@/components/ui/Card";
import { api, errorMessage } from "@/lib/api";
import { FEATURE_LABELS, openCheckout, rupees } from "@/lib/billing";
import type { Plan, PlansResponse, SubscriptionInfo } from "@/lib/types";
import { useFetch } from "@/lib/use-api";
import { useAuth } from "@/lib/auth";
import { StepActions, StepCard, StepHeading } from "./Shell";

const date = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : null);

/** What a plan adds over the one below it: the three or four things that tell the plans apart, so the cards are quick to compare. */
const CORE_LABELS: Record<string, string> = { review_generation: "Review writing assistant", qr_campaigns: "QR and NFC campaigns", review_analytics: "Review analytics", gbp_connection: "Google Business connection" };
function highlights(plans: Plan[], i: number): string[] {
  const prev = new Set(i > 0 ? plans[i - 1].features : []);
  // only features that have a proper name: a raw code like "qr_campaigns" is never shown to a customer
  const fresh = plans[i].features.filter((f) => !prev.has(f)).map((f) => FEATURE_LABELS[f] ?? CORE_LABELS[f]).filter((l): l is string => !!l);
  return fresh.slice(0, 4);
}

export function PlanStep({ onBack, onDone }: { onBack: () => void; onDone: () => void }) {
  const { me } = useAuth();
  const plansQ = useFetch<PlansResponse>("/billing/plans");
  const subQ = useFetch<SubscriptionInfo>("/billing/subscription");
  const [sel, setSel] = useState("growth");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const plans = useMemo(() => plansQ.data?.plans ?? [], [plansQ.data]);
  const sub = subQ.data;
  const chosen = plans.find((p) => p.code === sel) ?? plans[0];
  const payments = !!plansQ.data?.billing.configured;
  const needsCard = !!sub?.card_required;
  const cardOn = !!sub?.card_on_file;
  const trialDays = plansQ.data?.trial_days ?? 7;
  const ends = date(sub?.trial_ends_at);
  const onFilePlan = plans.find((p) => p.code === sub?.pending_plan);

  async function addCard() {
    if (!chosen) return;
    setBusy(true); setErr(null);
    try {
      const c = await api<{ subscription_id: string; key_id: string }>("/billing/subscription/checkout", { method: "POST", body: { plan: chosen.code } });
      await openCheckout({
        key: c.key_id, subscription_id: c.subscription_id, description: `FlowQR ${chosen.name}: ${trialDays}-day free trial`, prefill: { name: me?.user.full_name, email: me?.user.email },
        onDismiss: () => setBusy(false),
        onSuccess: async (r) => {
          try {
            await api("/billing/subscription/verify", { method: "POST", body: { razorpay_payment_id: r.razorpay_payment_id, razorpay_subscription_id: r.razorpay_subscription_id, razorpay_signature: r.razorpay_signature } });
            await subQ.reload();
          } catch (e) { setErr(errorMessage(e)); }
          setBusy(false);
        },
      });
    } catch (e) { setErr(errorMessage(e)); setBusy(false); }
  }

  if (plansQ.loading || subQ.loading) return <StepCard wide><div className="grid place-items-center py-16"><Spinner /></div></StepCard>;
  if (plansQ.error || !chosen) return <StepCard wide><StepHeading step={2} title="Choose your plan" /><div className="mt-6"><Alert tone="error" title="We couldn't load the plans">{plansQ.error ?? "Please refresh the page."}</Alert></div></StepCard>;

  return (
    <StepCard wide>
      <StepHeading step={2} title={needsCard || cardOn ? `Start your ${trialDays}-day free trial` : "Choose your plan"}>
        {payments && (needsCard || cardOn)
          ? "Pick the plan you want after the trial and add a card. You pay nothing today, and you can cancel before the trial ends."
          : `Your ${trialDays}-day free trial starts now. Pick the plan you would like to continue with.`}
      </StepHeading>

      {err && <div className="mt-5"><Alert tone="error" title="Couldn't complete that">{err}</Alert></div>}

      <fieldset className="mt-7" disabled={cardOn || busy}>
        <legend className="sr-only">Plan</legend>
        <div className="grid gap-3 md:grid-cols-3">
          {plans.map((p, i) => {
            const on = (cardOn ? onFilePlan?.code : sel) === p.code;
            const hl = highlights(plans, i);
            return (
              <label key={p.code} className={clsx("relative flex cursor-pointer flex-col rounded-[22px] p-5 ring-1 transition-[box-shadow,background-color,transform] duration-200 focus-within:ring-2 focus-within:ring-m-accentStrong",
                on ? "bg-m-tint ring-2 ring-m-accent shadow-[0_18px_40px_-22px_rgba(254,106,5,.55)]" : "bg-white ring-m-line hover:-translate-y-0.5 hover:ring-m-ink/25", (cardOn || busy) && !on && "opacity-60")}>
                <input type="radio" name="plan" value={p.code} checked={on} onChange={() => setSel(p.code)} className="sr-only" />
                <span className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-2.5">
                    <span aria-hidden className={clsx("grid h-5 w-5 shrink-0 place-items-center rounded-full ring-1 transition-colors", on ? "bg-m-accent text-m-ink ring-m-accent" : "bg-white ring-m-muted2")}>{on && <Check className="h-3 w-3" strokeWidth={3} />}</span>
                    <span className="text-[16px] font-semibold text-m-ink">{p.name}</span>
                  </span>
                  {p.code === "growth" && <span className="absolute -top-3 right-4 whitespace-nowrap rounded-full bg-m-navy px-3 py-1 text-[11px] font-semibold text-white shadow-[0_6px_14px_-6px_rgba(17,23,63,.6)]">Most popular</span>}
                </span>
                <span className="mt-3 block text-[30px] font-semibold leading-none tracking-[-.03em] text-m-ink">{rupees(p.price_paise)}<span className="text-[14px] font-normal tracking-normal text-m-muted"> / month</span></span>
                <span className="mt-1 block text-[12.5px] text-m-muted">+ GST as applicable</span>
                <ul className="mt-4 space-y-2 border-t border-m-line pt-4 text-[13.5px] text-m-ink2">
                  <li className="flex gap-2"><Check className="mt-0.5 h-4 w-4 shrink-0 text-[#157347]" aria-hidden />{p.max_locations} location{p.max_locations === 1 ? "" : "s"}, {p.max_staff} team members</li>
                  <li className="flex gap-2"><Check className="mt-0.5 h-4 w-4 shrink-0 text-[#157347]" aria-hidden />{p.review_replies.toLocaleString("en-IN")} AI review replies a month</li>
                  {hl.map((h) => <li key={h} className="flex gap-2"><Check className="mt-0.5 h-4 w-4 shrink-0 text-[#157347]" aria-hidden />{h}</li>)}
                </ul>
              </label>
            );
          })}
        </div>
      </fieldset>

      {/* what will actually happen, in plain words */}
      <div className="mt-6 rounded-[20px] bg-m-bg p-5">
        <h2 className="text-[15px] font-semibold text-m-ink">{cardOn ? "Your trial is set up" : "What happens next"}</h2>
        <dl className="mt-3 divide-y divide-m-line text-[14px]">
          <div className="flex items-center justify-between gap-4 py-2.5"><dt className="text-m-ink2">Due today</dt><dd className="font-semibold text-m-ink">₹0</dd></div>
          <div className="flex items-center justify-between gap-4 py-2.5"><dt className="text-m-ink2">Free trial</dt><dd className="text-right font-medium text-m-ink">{trialDays} days{ends ? `, until ${ends}` : ""}</dd></div>
          {(cardOn ? onFilePlan : chosen) && payments && (needsCard || cardOn) && (
            <div className="flex items-center justify-between gap-4 py-2.5"><dt className="text-m-ink2">Then, from {ends ?? "the end of the trial"}</dt><dd className="text-right font-medium text-m-ink">{rupees((cardOn ? onFilePlan : chosen)!.price_paise)} + GST / month</dd></div>
          )}
        </dl>
        <p className="mt-3 text-[13px] leading-relaxed text-m-muted">
          {cardOn ? "Your card is on file with our payment provider. Cancel any time before the trial ends from Billing and you pay nothing."
            : needsCard ? "Your card is charged for the plan above only when the trial ends. Cancel before then from Billing and you pay nothing."
              : payments ? "Nothing is charged automatically. You choose whether to continue when the trial ends." : "Online payments are not switched on yet, so no card is needed. Nothing is charged."}
        </p>
      </div>

      <StepActions onBack={onBack} backDisabled={busy}>
        {cardOn || !needsCard
          ? <Button variant="brand" size="lg" className="w-full sm:w-auto sm:min-w-[220px]" onClick={onDone}>{cardOn ? <><CheckCircle2 className="h-4 w-4" aria-hidden />Card added. Continue</> : <>Start my free trial <ArrowRight className="h-4 w-4" aria-hidden /></>}</Button>
          : <Button variant="brand" size="lg" className="w-full sm:w-auto sm:min-w-[260px]" loading={busy} onClick={() => void addCard()} icon={<CreditCard className="h-4 w-4" aria-hidden />}>Add card and start free trial</Button>}
      </StepActions>
      {needsCard && !cardOn && (
        <p className="mt-4 flex items-start justify-center gap-2 text-center text-[12.5px] leading-relaxed text-m-muted sm:justify-end"><Lock className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />Secure payment by Razorpay. Your card details go straight to them; FlowQR never sees or stores them.</p>
      )}
    </StepCard>
  );
}
