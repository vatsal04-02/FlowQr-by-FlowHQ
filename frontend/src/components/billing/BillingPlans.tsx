"use client";
import clsx from "clsx";
import { LayoutGroup, motion } from "motion/react";
import { Star } from "lucide-react";
import { useId, useRef, type KeyboardEvent } from "react";
import { PlanTile, tileButtonClass, useMedia } from "@/components/marketing/PlanTile";
import { rupees } from "@/lib/billing";
import { cardPoints, POSITION } from "@/lib/plan-compare";
import { effectiveMonthlyPaise, monthsLabel, RECOMMENDED, termPrice, termSaving, termTabLabel } from "@/lib/pricing";
import type { Plan, PrepaidOffer, PrepaidTerms } from "@/lib/types";

export type CurrentState = "none" | "current" | "trial";

const NAME: Record<string, string> = { starter: "Launch", growth: "Growth", pro: "Scale" };
const focus = "outline-none focus-visible:ring-2 focus-visible:ring-m-accent focus-visible:ring-offset-2";

/** A row of choices where one is selected, moved with the arrow keys. The term (Monthly / 3 / 6 / 12 months) and, on a phone, the plan. */
function Choice<T extends string | number>({ label, value, onChange, options, className, group }: {
  label: string; value: T; onChange: (v: T) => void; options: { value: T; text: string; hint?: string }[]; className?: string; group: string;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const move = (e: KeyboardEvent, i: number) => {
    const d = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!d) return;
    e.preventDefault();
    const n = (i + d + options.length) % options.length;
    onChange(options[n].value); refs.current[n]?.focus();
  };
  return (
    <LayoutGroup id={group}>
      <div role="radiogroup" aria-label={label} className={clsx("grid gap-1 rounded-full bg-m-tint p-1", className)} style={{ gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` }}>
        {options.map((o, i) => {
          const on = o.value === value;
          return (
            <button key={String(o.value)} ref={(el) => { refs.current[i] = el; }} type="button" role="radio" aria-checked={on} tabIndex={on ? 0 : -1} onClick={() => onChange(o.value)} onKeyDown={(e) => move(e, i)}
              className={clsx("relative min-h-11 rounded-full px-1 text-center text-[14px] font-semibold tracking-[-.01em] transition-colors sm:px-3 sm:text-[15px]", focus, on ? "text-m-ink" : "text-m-muted hover:text-m-ink")}>
              {on && <motion.span layoutId={`${group}-pill`} className="absolute inset-0 rounded-full bg-m-accent shadow-[0_1px_3px_rgba(11,15,46,.18)]" transition={{ type: "spring", stiffness: 520, damping: 42 }} />}
              <span className="relative inline-flex flex-col items-center leading-tight">{o.text}{o.hint && <span className="text-[10.5px] font-medium opacity-70">{o.hint}</span>}</span>
            </button>
          );
        })}
      </div>
    </LayoutGroup>
  );
}

/**
 * The plans on the signed-in billing page, drawn with the same card as the public pricing section (PlanTile). Above: how long to pay for. Below, a phone shows one plan at a time behind a
 * three-way switch (the recommended plan first, its long feature list folded); from md up all three cards sit side by side, the recommended one raised. Prices come from the prepaid list (or this
 * business's own offer); nothing is invented here. It owns no payment code: choosing a plan calls `onChoose`, and the order summary does the rest.
 */
export function BillingPlans({ plans, terms, months, onMonths, shown, onShown, stateOf, endsOn, isOwner, locked, offers, onChoose }: {
  plans: Plan[]; terms: PrepaidTerms; months: number; onMonths: (m: number) => void; shown: string; onShown: (code: string) => void;
  stateOf: (code: string) => CurrentState; endsOn: string | null; isOwner: boolean; locked: string | null; offers: PrepaidOffer[]; onChoose: (p: Plan, months: number) => void;
}) {
  const wide = useMedia("(min-width: 768px)");
  const termId = useId(), planId = useId();
  const best = Math.max(0, ...plans.map((p) => termSaving(terms, p.code, months)?.percent ?? 0));
  return (
    <div className="mkt rounded-[28px] px-3 pb-6 pt-5 sm:px-8 sm:pb-12 sm:pt-8">
      <p className="text-center text-[15px] font-medium text-m-ink2">How long do you want to pay for?</p>
      <div className="mx-auto mt-3 max-w-[30rem]">
        <Choice group={termId} label="How long do you want to pay for?" value={months} onChange={onMonths} options={terms.months.map((m) => ({ value: m, text: termTabLabel(m) }))} />
      </div>
      <p className="mt-3 min-h-6 text-center text-[14px] text-m-muted" aria-live="polite">
        {best > 0 ? <>Up to <b className="font-semibold text-m-ink">{best}% less</b> than paying month by month</> : "Pay one month at a time"}
      </p>

      <Choice group={planId} label="Plan" value={shown} onChange={onShown} className="mt-5 md:hidden" options={plans.map((p) => ({ value: p.code, text: NAME[p.code] ?? p.name, hint: p.code === RECOMMENDED ? "Recommended" : undefined }))} />

      <div className="mt-5 grid grid-cols-1 items-start gap-4 md:mt-12 md:grid-cols-3 md:items-stretch">
        {plans.map((p, i) => {
          const hot = p.code === RECOMMENDED;
          const offer = offers.find((o) => o.plan === p.code && o.months === months);
          const list = termPrice(terms, p.code, months);
          const total = offer ? offer.amount_paise : list;
          const state = stateOf(p.code);
          const name = NAME[p.code] ?? p.name;
          const save = offer ? null : termSaving(terms, p.code, months);
          const off = total === null || !isOwner || state === "current" || !!locked;
          const badge = state === "current" ? <span className="absolute right-0 top-0 inline-flex items-center rounded-bl-xl rounded-tr-[14px] bg-m-ink px-2.5 py-1 text-[12.5px] font-semibold text-white">Current plan</span>
            : state === "trial" ? <span className="absolute right-0 top-0 inline-flex items-center rounded-bl-xl rounded-tr-[14px] bg-m-tint px-2.5 py-1 text-[12.5px] font-semibold text-m-ink">In your free trial</span>
            : hot ? <span className="absolute right-0 top-0 inline-flex items-center rounded-bl-xl rounded-tr-[14px] bg-m-accent px-2.5 py-1 text-[12.5px] font-semibold text-m-ink"><Star className="mr-1 h-3.5 w-3.5 fill-current" aria-hidden />Recommended</span> : null;
          if (total === null) return null;
          return (
            <PlanTile key={p.code} code={p.code} name={name} hot={hot} index={i} count={plans.length} wide={wide} badge={badge} paise={total}
              className={p.code === shown ? "flex" : "hidden md:flex"}
              suffix={months === 1 ? "/ month" : `for ${monthsLabel(months)}`}
              fine={`${months === 1 ? "one payment, no auto-renewal" : `one payment for ${monthsLabel(months)}, no auto-renewal`} · + GST as applicable`}
              extra={offer ? <p className="mt-2 text-[13px] leading-snug text-m-ink2"><b className="font-semibold">{offer.label}</b> · normally {rupees(offer.list_price_paise)}</p>
                : months > 1 ? <p className="mt-2 text-[13px] leading-snug text-m-ink2">About {rupees(effectiveMonthlyPaise(total, months))} a month.{save && <> {rupees(save.paise)} less than paying monthly.</>}</p> : null}
              points={cardPoints(p)} footnote={POSITION[p.code]}
              cta={<button type="button" className={tileButtonClass(hot)} disabled={off} onClick={() => onChoose(p, months)} aria-label={state === "current" ? `${name} is your current plan` : `Choose ${name} for ${monthsLabel(months)}`}>{state === "current" ? "Current plan" : `Choose ${name}`}</button>}
              below={<>
                {state === "current" && endsOn && <p className="mt-2 text-[12.5px] text-m-muted">Active until {endsOn}</p>}
                {!isOwner && state !== "current" && <p className="mt-2 text-[12.5px] text-m-muted">Only the business owner can buy a plan.</p>}
                {isOwner && locked && state !== "current" && <p className="mt-2 text-[12.5px] text-m-muted">{locked}</p>}
              </>} />
          );
        })}
      </div>
    </div>
  );
}
