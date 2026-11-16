"use client";
import clsx from "clsx";
import { ArrowRight, Check, CheckCircle2, Clock, Lock, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CashfreeCheckoutDialog } from "@/components/billing/CashfreeCheckout";
import { ResendVerification } from "@/components/billing/ResendVerification";
import { useAuth } from "@/lib/auth";
import { Button } from "@/components/ui/Button";
import { Alert, Spinner } from "@/components/ui/Card";
import { api, errorMessage } from "@/lib/api";
import { FEATURE_LABELS, rupees } from "@/lib/billing";
import type { Plan, PlansResponse, SubscriptionInfo } from "@/lib/types";
import { useFetch } from "@/lib/use-api";
import { StepActions, StepCard, StepHeading } from "./Shell";

const date = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : null);

/** What a plan adds over the one below it: the three or four things that tell the plans apart, so the cards are quick to compare. */
const CORE_LABELS: Record<string, string> = { review_generation: "Review writing assistant", qr_campaigns: "QR and NFC campaigns", review_analytics: "Review analytics", gbp_connection: "Google Business connection" };
function highlights(plans: Plan[], i: number): string[] {
  const prev = new Set(i > 0 ? plans[i - 1].features : []);
  const fresh = plans[i].features.filter((f) => !prev.has(f)).map((f) => FEATURE_LABELS[f] ?? CORE_LABELS[f]).filter((l): l is string => !!l);  // a raw feature code is never shown to a customer
  return fresh.slice(0, 4);
}

/**
 * Step 3, "Plan and payment". Where the server says a payment authorisation is required (`billing.mandate_required`) the free trial starts ONLY when the server, having asked Cashfree, reports
 * the authorisation confirmed. This step never decides that: it shows the plans, opens the disclosure, and afterwards asks the server (POST /billing/subscription/sync) what happened.
 * Progress lives on the server, so leaving checkout, closing the tab or failing the authorisation loses nothing: this step shows the right state again, and trying again never creates a second mandate.
 * Where authorisation is not required (Cashfree not configured) it is the original step: the trial simply starts.
 */
export function PlanStep({ onBack, onDone, reason }: { onBack: () => void; onDone: () => void; reason?: string | null }) {
  const { me, refresh } = useAuth();
  const plansQ = useFetch<PlansResponse>("/billing/plans");
  const subQ = useFetch<SubscriptionInfo>("/billing/subscription");
  const [sel, setSel] = useState<string | null>(null);
  const [dialog, setDialog] = useState<Plan | null>(null);
  const [checking, setChecking] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const asked = useRef(false);

  const plans = useMemo(() => plansQ.data?.plans ?? [], [plansQ.data]);
  const s = subQ.data;
  const mandate = !!plansQ.data?.billing.mandate_required;
  const trialDays = plansQ.data?.trial_days ?? 7;
  const auth = s?.authorization_status ?? null;
  const authorised = mandate && s?.status === "trialing" && auth === "authorized";
  const pending = mandate && auth === "bank_pending";
  const open = mandate && !!s?.has_cashfree_subscription && auth === "initialized";
  const failed = mandate && (auth === "expired" || auth === "cancelled");
  const chosen = plans.find((p) => p.code === (sel ?? s?.pending_plan ?? "growth")) ?? plans[0];
  const authPaise = plansQ.data?.billing.authorization_paise ?? 100;
  const unverified = mandate && !!me && !me.user.email_verified_at;  // the server refuses billing actions until the address is verified (403 email_not_verified); this only says why, before the button is pressed

  const check = useCallback(async (n = 0) => {
    setChecking(true);
    try {
      const out = await api<{ authorization_status: string | null; status: string }>("/billing/subscription/sync", { method: "POST" });
      setNote(null);
      await subQ.reload();
      if (out.authorization_status === "bank_pending" && n < 24) timer.current = setTimeout(() => void check(n + 1), 5000);  // the bank approves in its own time: keep asking, politely
    } catch (e) { setNote(errorMessage(e)); }
    finally { setChecking(false); }
  }, [subQ]);

  useEffect(() => {  // arriving with an authorisation already started (back from Cashfree, or the page reopened): ask the server once. The address bar is never trusted.
    if (!s || !mandate || asked.current) return;
    asked.current = true;
    if (s.has_cashfree_subscription && s.status === "incomplete" && (auth === "initialized" || auth === "bank_pending")) void check();
    if (typeof window !== "undefined" && window.location.search.includes("checkout=")) window.history.replaceState(null, "", window.location.pathname);
  }, [s, mandate, auth, check]);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  if (plansQ.loading || subQ.loading) return <StepCard wide><div className="grid place-items-center py-16"><Spinner /></div></StepCard>;
  if (plansQ.error || !chosen) return <StepCard wide><StepHeading step={2} title="Choose your plan" /><div className="mt-6"><Alert tone="error" title="We couldn't load the plans">{plansQ.error ?? "Please refresh the page."}</Alert></div></StepCard>;

  // The original step, unchanged in meaning: no payment authorisation is required, so the trial simply starts.
  if (!mandate) {
    return (
      <StepCard wide>
        <StepHeading step={2} title={`Start your ${trialDays}-day free trial`}>Your {trialDays}-day free trial starts now and nothing is charged automatically. You choose a plan from Billing whenever you are ready.</StepHeading>
        <StepActions onBack={onBack}><Button variant="brand" size="lg" className="w-full sm:w-auto sm:min-w-[220px]" onClick={onDone}>Start my free trial <ArrowRight className="h-4 w-4" aria-hidden /></Button></StepActions>
      </StepCard>
    );
  }

  if (authorised) {
    const first = s?.first_charge_at ?? s?.next_charge_at;
    const selected = plans.find((p) => p.code === s?.selected_plan);
    return (
      <StepCard wide>
        <StepHeading step={2} title="Your free trial has started">Your payment method is confirmed, so your {trialDays}-day free trial is running{s?.trial_ends_at ? <> until <b>{date(s.trial_ends_at)}</b></> : null}, with every Growth feature.</StepHeading>
        {reason && <div className="mt-5"><Alert tone="warning" title="One more step before your dashboard opens">{reason}</Alert></div>}
        <div className="mt-6 rounded-[20px] bg-m-bg p-5">
          <dl className="divide-y divide-m-line text-[14px]">
            <div className="flex items-center justify-between gap-4 py-2.5"><dt className="text-m-ink2">Due today</dt><dd className="font-semibold text-m-ink">{rupees(0)}</dd></div>
            {selected && <div className="flex items-center justify-between gap-4 py-2.5"><dt className="text-m-ink2">Your plan after the trial</dt><dd className="text-right font-medium text-m-ink">{selected.name}, {rupees(selected.price_paise)} + GST / month</dd></div>}
            {first && <div className="flex items-center justify-between gap-4 py-2.5"><dt className="text-m-ink2">First payment</dt><dd className="text-right font-medium text-m-ink">{s?.next_charge_amount_paise ? `${rupees(s.next_charge_amount_paise)} + GST` : "Your plan amount"} on {date(first)}</dd></div>}
            <div className="flex items-center justify-between gap-4 py-2.5"><dt className="text-m-ink2">Payment method</dt><dd className="text-right font-medium text-m-ink">{s?.payment_method === "upi" ? "UPI AutoPay" : s?.payment_method === "card" ? "Card" : "Authorised with Cashfree"}</dd></div>
          </dl>
          <p className="mt-3 text-[13px] leading-relaxed text-m-muted">The refundable {rupees(authPaise)} used to set this up is returned to you automatically. Cancel any time from Billing before the first payment and you pay nothing more.</p>
        </div>
        <StepActions onBack={onBack}><Button variant="brand" size="lg" className="w-full sm:w-auto sm:min-w-[220px]" onClick={onDone}><CheckCircle2 className="h-4 w-4" aria-hidden />Continue</Button></StepActions>
      </StepCard>
    );
  }

  const busy = checking || !!dialog;
  return (
    <StepCard wide>
      <StepHeading step={2} title={`Start your ${trialDays}-day free trial`}>
        Pick the plan you want after the trial, then authorise UPI AutoPay or a card with Cashfree. Your trial starts as soon as Cashfree confirms it, with every Growth feature whichever plan you pick, and you pay for your plan only when the trial ends.
      </StepHeading>

      {reason && <div className="mt-5"><Alert tone="warning" title="One more step before your dashboard opens">{reason}</Alert></div>}
      {unverified && <div className="mt-5"><Alert tone="warning" title="Verify your email to authorise a payment">We need a verified email address before we can set up a payment. Open the link in our email, then continue here.<div className="mt-2"><ResendVerification onCheck={async () => { await refresh(); }} /></div></Alert></div>}
      {note && <div className="mt-5"><Alert tone="warning">{note}</Alert></div>}
      {pending && <div className="mt-5"><Alert tone="info" title="Your bank is approving the authorisation">This can take a day or two. Your trial starts as soon as it is approved and this page updates by itself. Nothing was charged.
        <div className="mt-2"><Button size="sm" variant="secondary" loading={checking} onClick={() => void check()}>Check now</Button></div></Alert></div>}
      {open && <div className="mt-5"><Alert tone="warning" title="We haven't received your authorisation yet">Your trial has not started and nothing was charged. If you completed it, check again; if you left, start again. Starting again never creates a second authorisation.
        <div className="mt-2 flex flex-wrap gap-2"><Button size="sm" loading={checking} onClick={() => void check()}>Check again</Button></div></Alert></div>}
      {failed && <div className="mt-5"><Alert tone="error" title="The authorisation didn't complete">Nothing was charged and your trial has not started. Choose a plan and try again.</Alert></div>}
      {checking && !pending && !open && <div className="mt-5 flex items-center gap-2 text-[14px] text-m-ink2"><Spinner /> Confirming with Cashfree&hellip;</div>}

      <fieldset className="mt-7" disabled={busy || pending}>
        <legend className="sr-only">Plan</legend>
        <div className="grid gap-3 md:grid-cols-3">
          {plans.map((p, i) => {
            const on = chosen.code === p.code;
            const hl = highlights(plans, i);
            return (
              <label key={p.code} className={clsx("relative flex cursor-pointer flex-col rounded-[22px] p-5 ring-1 transition-[box-shadow,background-color,transform] duration-200 focus-within:ring-2 focus-within:ring-m-accentStrong",
                on ? "bg-m-tint ring-2 ring-m-accent shadow-[0_18px_40px_-22px_rgba(254,106,5,.55)]" : "bg-white ring-m-line hover:-translate-y-0.5 hover:ring-m-ink/25", (busy || pending) && !on && "opacity-60")}>
                <input type="radio" name="plan" value={p.code} checked={on} onChange={() => setSel(p.code)} className="sr-only" />
                <span className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-2.5">
                    <span aria-hidden className={clsx("grid h-5 w-5 shrink-0 place-items-center rounded-full ring-1 transition-colors", on ? "bg-m-accent text-m-ink ring-m-accent" : "bg-white ring-m-muted2")}>{on && <Check className="h-3 w-3" strokeWidth={3} />}</span>
                    <span className="text-[16px] font-semibold text-m-ink">{p.name}</span>
                  </span>
                  <span className="absolute -top-3 right-4 whitespace-nowrap rounded-full bg-m-navy px-3 py-1 text-[11px] font-semibold text-white shadow-[0_6px_14px_-6px_rgba(17,23,63,.6)]">{trialDays} days free</span>
                </span>
                <span className="mt-3 flex items-baseline gap-2.5">
                  <span className="text-[30px] font-semibold leading-none tracking-[-.03em] text-m-ink">{rupees(0)}</span>
                  <span className="text-[18px] font-medium leading-none text-m-muted line-through decoration-2" aria-label={`${rupees(p.price_paise)} a month, not charged during the trial`}>{rupees(p.price_paise)}</span>
                </span>
                <span className="mt-1.5 block text-[12.5px] leading-snug text-m-ink2">for {trialDays} days, then {rupees(p.price_paise)} / month</span>
                <span className="mt-0.5 block text-[12px] text-m-muted">+ GST as applicable</span>
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

      <div className="mt-6 rounded-[20px] bg-m-bg p-5">
        <h2 className="text-[15px] font-semibold text-m-ink">What happens next</h2>
        <ol className="mt-3 space-y-2.5 text-[14px] text-m-ink2">
          <li className="flex gap-2.5"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-m-accentStrong" aria-hidden />You authorise UPI AutoPay or a card with Cashfree. Your bank or UPI app takes <b>{rupees(authPaise)}</b> to set it up and returns it automatically.</li>
          <li className="flex gap-2.5"><Clock className="mt-0.5 h-4 w-4 shrink-0 text-m-accentStrong" aria-hidden />Your {trialDays}-day trial starts once the authorisation is confirmed, with <b>every Growth feature</b>{chosen.code === "growth" ? "" : <>, even though you picked {chosen.name}</>}. Nothing else is charged today.</li>
          <li className="flex gap-2.5"><Check className="mt-0.5 h-4 w-4 shrink-0 text-m-accentStrong" aria-hidden />When the trial ends you move to <b>{chosen.name}</b>: the first payment of {rupees(chosen.price_paise)} + GST is taken then, and every month after. Cancel before then from Billing and you pay nothing.</li>
        </ol>
      </div>

      <StepActions onBack={onBack} backDisabled={busy}>
        <Button variant="brand" size="lg" className="w-full sm:w-auto sm:min-w-[280px]" disabled={pending} loading={checking} onClick={() => setDialog(chosen)}>
          {open ? `Start again with ${chosen.name}` : <>Authorise payment and start free trial <ArrowRight className="h-4 w-4" aria-hidden /></>}
        </Button>
      </StepActions>
      <p className="mt-4 flex items-start justify-center gap-2 text-center text-[12.5px] leading-relaxed text-m-muted sm:justify-end"><Lock className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />Secure payment by Cashfree. Your card or UPI details go straight to them; FlowQR never sees or stores them.</p>
      {dialog && plansQ.data && <CashfreeCheckoutDialog plan={dialog} plans={plansQ.data} onClose={() => setDialog(null)} />}
    </StepCard>
  );
}
