"use client";
import clsx from "clsx";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Check, Minus } from "lucide-react";
import { useId, useState } from "react";
import { rupees } from "@/lib/billing";
import { trialTerms } from "@/lib/plans";
import { BILLING_NOTE, BILLING_SUFFIX, cardPoints, comparisonRows, periodPrice, POSITION, sellablePlans, yearlySaving, type Billing, type Cell } from "@/lib/plan-compare";
import { effectiveMonthlyPaise } from "@/lib/pricing";
import { MButton } from "./kit";
import { EASE, Rise } from "./motion";
import { TalkToUs, usePlansLive } from "./PlansFromConfig";

/**
 * The public pricing section: Monthly / Yearly (Monthly first), three plans with Growth recommended, and a comparison table.
 * Every price is read from the prepaid price list the server serves, every allowance and feature from the plan rows (see lib/plan-compare.ts); nothing is written here, and a plan
 * without both prices is left out rather than guessed. A yearly price is one payment for 12 months; the AI allowances stay monthly.
 */
function Toggle({ value, onChange }: { value: Billing; onChange: (b: Billing) => void }) {
  const id = useId();
  const opts: [Billing, string][] = [["monthly", "Monthly"], ["yearly", "Yearly"]];
  const move = () => onChange(value === "monthly" ? "yearly" : "monthly");
  return (
    <div role="radiogroup" aria-label="Billing period" className="relative mx-auto flex w-fit rounded-full bg-m-surface p-1 shadow-[var(--shadow-card)]"
      onKeyDown={(e) => { if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)) { e.preventDefault(); move(); } }}>
      {opts.map(([v, label]) => {
        const on = v === value;
        return (
          <button key={v} type="button" role="radio" aria-checked={on} tabIndex={on ? 0 : -1} onClick={() => onChange(v)}
            className={clsx("relative min-h-11 min-w-[116px] rounded-full px-6 text-[15px] font-medium tracking-[-.01em] transition-colors duration-200", on ? "text-white" : "text-m-ink2 hover:text-m-ink")}>
            {on && <motion.span layoutId={`${id}-pill`} aria-hidden className="absolute inset-0 rounded-full bg-m-navy" transition={{ type: "spring", stiffness: 480, damping: 36 }} />}
            <span className="relative">{label}</span>
          </button>
        );
      })}
    </div>
  );
}

function Price({ paise, billing }: { paise: number; billing: Billing }) {
  const reduced = useReducedMotion();
  return (
    <p className="mt-6 flex items-baseline t-number">
      <span className="relative inline-flex overflow-hidden pb-[.12em] -mb-[.12em]">
        <AnimatePresence mode="popLayout" initial={false}>
          <motion.span key={billing} initial={{ y: reduced ? 0 : "55%", opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: reduced ? 0 : "-55%", opacity: 0 }} transition={{ duration: reduced ? 0.15 : 0.32, ease: EASE }}>{rupees(paise)}</motion.span>
        </AnimatePresence>
      </span>
      <span className="ml-1 text-[14px] font-medium tracking-normal opacity-70">{BILLING_SUFFIX[billing]}</span>
    </p>
  );
}

export function PricingPlans() {
  const { data, failed, loading } = usePlansLive();
  const [billing, setBilling] = useState<Billing>("monthly");
  if (failed) return <TalkToUs />;
  if (loading || !data) return <div className="grid gap-3 md:grid-cols-3" aria-busy>{[0, 1, 2].map((i) => <div key={i} className="h-[520px] animate-pulse rounded-[20px] bg-m-surface" />)}</div>;
  const plans = sellablePlans(data.plans, data.terms);
  if (!plans.length) return <TalkToUs />;
  return (
    <>
      <Toggle value={billing} onChange={setBilling} />
      <div className="mt-4 min-h-[44px] text-center">
        <p className="text-[15px] text-m-muted" aria-live="polite">{BILLING_NOTE[billing]}</p>
        <p className="mt-1 text-[14px] text-m-muted">{data.trial_days}-day free trial. {trialTerms(data.billing ? !!data.billing.mandate_required : null)}</p>
      </div>
      <div className="mt-8 grid gap-3 md:grid-cols-3">
        {plans.map((p, i) => {
          const hot = p.code === "growth";
          const paise = periodPrice(data.terms, p.code, billing) as number;
          const save = billing === "yearly" ? yearlySaving(data.terms, p.code) : null;
          return (
            <motion.div key={p.code} data-plan={p.code} initial={{ opacity: 0, y: 24 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: 0.6, ease: EASE, delay: i * 0.1 }}
              className={clsx("flex flex-col rounded-[20px] p-7", hot ? "bg-m-accent text-m-ink md:-my-3 md:py-10" : "bg-m-surface shadow-[var(--shadow-card)]")}>
              <div className="flex items-center justify-between"><h2 className="text-[22px] font-medium tracking-[-.02em]">{p.name}</h2>{hot && <span className="rounded-full bg-white/70 px-2.5 py-0.5 text-[11.5px] font-semibold">Recommended</span>}</div>
              <p className={clsx("mt-2 min-h-[44px] text-[14px] leading-snug", hot ? "text-m-ink/80" : "text-m-muted")}>{POSITION[p.code]}</p>
              <Price paise={paise} billing={billing} />
              <p className={clsx("mt-2 text-[13px]", hot ? "text-m-ink/75" : "text-m-muted")}>+ GST as applicable</p>
              <div className="min-h-[40px]">
                {save && <p className={clsx("mt-1 text-[13px]", hot ? "text-m-ink/85" : "text-m-ink2")}>About {rupees(effectiveMonthlyPaise(paise, 12))} a month. {rupees(save.paise)} less than paying monthly for a year.</p>}
              </div>
              <ul className={clsx("mt-5 space-y-2.5 border-t pt-5 text-[14px]", hot ? "border-m-ink/15" : "border-m-line")}>
                {cardPoints(p).map((pt) => (
                  <li key={pt.text} className="flex gap-2.5">
                    <Check className={clsx("mt-0.5 h-4 w-4 shrink-0", pt.soon && "opacity-40")} strokeWidth={2} aria-hidden />
                    <span>{pt.text}{pt.soon && <span className="ml-2 rounded-full bg-m-ink/10 px-2 py-0.5 text-[11px] font-semibold">Coming soon</span>}</span>
                  </li>
                ))}
              </ul>
              <div className="mt-auto pt-8"><MButton href="/register" variant={hot ? "dark" : "primary"} className="w-full justify-between" event="signup_cta_click">Start free trial</MButton></div>
            </motion.div>
          );
        })}
      </div>
      <p className="mx-auto mt-6 max-w-[640px] text-center text-[13px] text-m-muted">AI allowances are monthly. They reset every month, on yearly plans too, and are not added up across the year.</p>
    </>
  );
}

function CellView({ c }: { c: Cell }) {
  if (c.kind === "yes") return <Check className="mx-auto h-4 w-4" strokeWidth={2.25} aria-label="Included" />;
  if (c.kind === "no") return <Minus className="mx-auto h-4 w-4 text-m-muted" strokeWidth={1.75} aria-label="Not included" />;
  if (c.kind === "soon") return <span className="rounded-full bg-m-ink/10 px-2.5 py-1 text-[12px] font-semibold">Coming soon</span>;
  return <>{c.text}</>;
}

export function PlanComparison() {
  const { data } = usePlansLive();
  if (!data) return null;
  const plans = data.plans;   // the table shows what each plan includes and needs no prices, so it does not wait for them
  const rec = plans.findIndex((p) => p.code === "growth");
  const rows = comparisonRows(plans);
  return (
    <Rise className="overflow-x-auto pb-4">
      <table className="w-full min-w-[680px] border-separate border-spacing-0 text-center text-[14px]">
        <caption className="sr-only">What each plan includes</caption>
        <thead>
          <tr>
            <th scope="col" className="sticky left-0 z-10 bg-m-bg px-4 pb-4 text-left font-medium text-m-muted">What you get</th>
            {plans.map((p, i) => <th key={p.code} scope="col" className={clsx("px-3 pb-4 text-[16px] font-medium", i === rec && "rounded-t-[14px] bg-m-accent pt-3")}>{p.name}{i === rec && <span className="mt-0.5 block text-[11px] font-semibold opacity-80">Recommended</span>}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, ri) => (
            <tr key={r.id}>
              <th scope="row" className="sticky left-0 z-10 border-b border-m-line bg-m-bg px-4 py-3 text-left align-top font-medium text-m-ink2">
                {r.label}{r.note && <span className="mt-0.5 block text-[12.5px] font-normal text-m-muted">{r.note}</span>}
              </th>
              {plans.map((p, i) => (
                <td key={p.code} className={clsx("px-3 py-3 align-middle", i === rec ? "border-b border-white/25 bg-m-accent font-medium" : "border-b border-m-line bg-m-tint/50", i === rec && ri === rows.length - 1 && "rounded-b-[14px]")}>
                  <CellView c={r.cells[p.code]} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </Rise>
  );
}
