"use client";
// The prepaid pricing screen: a short editorial page (hero, term selector, three plans, comparison, how billing works, questions).
//
// What it will NOT do, by design:
//  * start a subscription, an AutoPay mandate or a Rs 1 authorisation: it contains no payment-provider code at all;
//  * claim anything the backend does not enforce: limits and features are read from the plan rows the API serves (see lib/pricing.ts for the few deliberately omitted keys);
//  * show a crossed-out "MRP" or a percentage that was typed in: a saving is the difference to the plan's own 1-month price on the server's list;
//  * pretend a payment worked. Until the server says `terms.checkout_open`, the pay button is disabled and says so. The seam for the real one-time checkout is `PayButton`.
import { animate, AnimatePresence, LayoutGroup, motion, useReducedMotion } from "motion/react";
import { Check, ChevronDown, Info, Minus } from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { Alert, Skeleton } from "@/components/ui/Card";
import { rupees } from "@/lib/billing";
import { fmtDate } from "@/lib/format";
import {
  ALL_FEATURE_ROWS, LIMIT_ROWS, PLAN_ORDER, POSITIONING, RECOMMENDED, effectiveMonthlyPaise, monthsLabel, newFeatureGroups, termPrice, termSaving, termTabLabel,
} from "@/lib/pricing";
import type { Plan, PrepaidTerms, SubscriptionInfo } from "@/lib/types";

const EASE = [0.22, 1, 0.36, 1] as const;
const PLAN_NAME: Record<string, string> = { starter: "Launch", growth: "Growth", pro: "Scale" };

/** A number that glides to its new value (0.45 s) and shows it at once for anyone who asked for reduced motion. The real value is always the accessible text. */
function Glide({ value, className }: { value: number; className?: string }) {
  const reduce = useReducedMotion();
  const [shown, setShown] = useState(value);
  const from = useRef(value);
  useEffect(() => {
    if (reduce || from.current === value) { from.current = value; setShown(value); return; }
    const c = animate(from.current, value, { duration: 0.45, ease: EASE, onUpdate: (v) => { from.current = v; setShown(v); }, onComplete: () => { from.current = value; setShown(value); } });
    return () => c.stop();
  }, [value, reduce]);
  const fmt = (n: number) => new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(Math.round(n));
  return <span className={className}><span aria-hidden>{fmt(shown)}</span><span className="sr-only">{fmt(value)}</span></span>;
}

// ------------------------------------------------------------------------------------------------------------------------------------------ A. hero

function Hero({ trialDays }: { trialDays: number | null }) {
  const facts = ["One payment per term, no auto-renewal", "Prices in Indian rupees", "Your data and QR cards are kept if a plan ends", ...(trialDays ? [`${trialDays}-day free trial for new businesses`] : [])];
  return (
    <header className="pb-10 pt-4 sm:pb-14 sm:pt-8">
      <motion.p initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, ease: EASE }} className="font-mono text-[11px] uppercase tracking-[.16em] text-muted">Plans</motion.p>
      <motion.h2 initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.55, delay: 0.05, ease: EASE }}
        className="mt-4 max-w-[18ch] text-balance font-display text-[2.4rem] font-semibold leading-[1.04] tracking-[-0.03em] text-ink sm:max-w-[22ch] sm:text-5xl lg:text-[3.6rem]">
        Grow your local business. Without the operational overhead.
      </motion.h2>
      <motion.p initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay: 0.14, ease: EASE }} className="mt-5 max-w-xl text-[15px] leading-7 text-muted sm:text-base">
        Collect more Google reviews, answer them quickly, and keep your business profile active from one place. Pick the plan that fits your business and the term that fits your budget.
      </motion.p>
      <motion.ul initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.5, delay: 0.25 }} className="mt-8 grid gap-x-8 gap-y-2 border-t border-line pt-5 text-[13px] text-ink-700 sm:grid-cols-2 lg:flex lg:flex-wrap">
        {facts.map((f) => <li key={f} className="flex items-center gap-2"><Check className="h-3.5 w-3.5 shrink-0 text-pos" aria-hidden />{f}</li>)}
      </motion.ul>
    </header>
  );
}

// ------------------------------------------------------------------------------------------------------------------------------------------ B. duration

function TermSelector({ terms, plans, value, onChange }: { terms: PrepaidTerms; plans: Plan[]; value: number; onChange: (m: number) => void }) {
  const id = useId();
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const months = terms.months;
  // "up to N%" is the biggest saving any shown plan really gets on that term, read from the same list as the prices.
  const bestSaving = (m: number) => Math.max(0, ...plans.map((p) => termSaving(terms, p.code, m)?.percent ?? 0));
  const move = (e: KeyboardEvent, i: number) => {
    const d = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!d) return;
    e.preventDefault();
    const n = (i + d + months.length) % months.length;
    onChange(months[n]); refs.current[n]?.focus();
  };
  return (
    <div className="sticky top-[var(--fq-topbar,0px)] z-10 -mx-4 border-y border-line bg-canvas/95 px-4 py-3 backdrop-blur-sm sm:static sm:mx-0 sm:border-0 sm:bg-transparent sm:p-0 sm:backdrop-blur-none">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p id={id} className="font-mono text-[11px] uppercase tracking-[.16em] text-muted">Choose how long</p>
          <p className="mt-1 hidden text-sm text-muted sm:block">The longer the term, the less each month costs.</p>
        </div>
        <LayoutGroup id={id}>
          <div role="radiogroup" aria-labelledby={id} className="grid w-full grid-cols-4 border border-line sm:w-auto sm:min-w-[26rem]">
            {months.map((m, i) => {
              const on = m === value, best = bestSaving(m);
              return (
                <button key={m} ref={(el) => { refs.current[i] = el; }} type="button" role="radio" aria-checked={on} tabIndex={on ? 0 : -1} onClick={() => onChange(m)} onKeyDown={(e) => move(e, i)}
                  className={`relative min-h-[3.25rem] px-1 text-center outline-none transition-colors focus-visible:z-10 focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1 ${i ? "border-l border-line" : ""} ${on ? "text-ink-on" : "text-ink hover:bg-surface-2"}`}>
                  {on && <motion.span layoutId="term-pill" className="absolute inset-0 bg-ink-solid" transition={{ type: "spring", stiffness: 520, damping: 42 }} />}
                  <span className="relative block text-[13px] font-medium sm:text-sm">{termTabLabel(m)}</span>
                  <span className={`relative block h-3.5 text-[10.5px] ${on ? "text-ink-on/70" : "text-muted"}`}>{best > 0 ? `up to ${best}% less` : ""}</span>
                </button>
              );
            })}
          </div>
        </LayoutGroup>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------------------------------------------------ C. plans

type CurrentState = "none" | "current" | "trial";

function PlanColumn({ plan, below, terms, months, state, endsOn, isOwner, onChoose, index }: {
  plan: Plan; below: Plan | null; terms: PrepaidTerms; months: number; state: CurrentState; endsOn: string | null; isOwner: boolean; onChoose: (p: Plan, months: number) => void; index: number;
}) {
  const total = termPrice(terms, plan.code, months);
  const monthly = total === null ? null : effectiveMonthlyPaise(total, months);
  const saving = termSaving(terms, plan.code, months);
  const groups = useMemo(() => newFeatureGroups(plan, below), [plan, below]);
  const recommended = plan.code === RECOMMENDED;
  const name = PLAN_NAME[plan.code] ?? plan.name;
  const disabled = total === null || !isOwner || state === "current";
  return (
    <motion.article initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay: 0.08 * index, ease: EASE }} aria-labelledby={`plan-${plan.code}`}
      className={`relative flex flex-col px-5 py-7 sm:px-6 lg:px-8 lg:py-9 ${recommended ? "bg-surface" : ""}`}>
      {recommended && <span aria-hidden className="absolute inset-x-0 top-0 h-[2px] bg-accent" />}
      <div className="flex min-h-7 items-center justify-between gap-2">
        <h3 id={`plan-${plan.code}`} className="font-display text-lg font-semibold tracking-tight text-ink">{name}</h3>
        {state === "current" ? <span className="rounded-full border border-pos/40 bg-pos-tint px-2.5 py-0.5 text-[11px] font-medium text-pos">Current plan</span>
          : state === "trial" ? <span className="rounded-full border border-line px-2.5 py-0.5 text-[11px] font-medium text-muted">In your free trial</span>
          : recommended ? <span className="rounded-full bg-accent-tint px-2.5 py-0.5 text-[11px] font-medium text-accent-ink">Recommended</span> : null}
      </div>
      <p className="mt-1 text-sm text-muted">{POSITIONING[plan.code]}</p>

      <div className="mt-7">
        {total === null ? <p className="font-display text-4xl font-semibold text-muted">Unavailable</p> : (
          <>
            <p className="flex items-baseline gap-1 font-display text-ink"><span className="text-2xl font-medium text-muted">₹</span><Glide value={total / 100} className="num text-[3.1rem] font-semibold leading-none tracking-[-0.04em] sm:text-[3.4rem]" /></p>
            <p className="mt-2 text-sm text-muted">for {monthsLabel(months)} · one-time payment</p>
            <div className="mt-4 min-h-[3.25rem] border-t border-line pt-3 text-sm">
              <p className="text-ink-700"><span className="num font-medium text-ink">₹<Glide value={(monthly ?? 0) / 100} /></span>{" "}<span className="text-muted">a month</span></p>
              {saving ? <p className="mt-0.5 text-pos">You save {rupees(saving.paise)} ({saving.percent}%) against paying month by month</p> : months > 1 ? null : <p className="mt-0.5 text-muted">Pay for one month at a time</p>}
            </div>
          </>
        )}
      </div>

      <div className="mt-6">
        <Button className="w-full" variant={recommended ? "primary" : "secondary"} disabled={disabled} onClick={() => onChoose(plan, months)}
          aria-label={state === "current" ? `${name} is your current plan` : `Choose ${name} for ${monthsLabel(months)}`}>
          {state === "current" ? "Current plan" : `Choose ${name}`}
        </Button>
        {state === "current" && endsOn && <p className="mt-2 text-xs text-muted">Active until {endsOn}</p>}
        {!isOwner && state !== "current" && <p className="mt-2 text-xs text-muted">Only the business owner can buy a plan.</p>}
      </div>

      <dl className="mt-8 border-t border-line">
        {LIMIT_ROWS.map((r) => (
          <div key={r.id} className="flex items-baseline justify-between gap-4 border-b border-line py-2.5 text-sm"><dt className="text-muted">{r.label}</dt><dd className="num font-medium text-ink">{r.value(plan).toLocaleString("en-IN")}</dd></div>
        ))}
      </dl>

      <div className="mt-6 space-y-5">
        <p className="font-mono text-[11px] uppercase tracking-[.14em] text-muted">{below ? `Everything in ${PLAN_NAME[below.code] ?? below.name}, plus` : "Includes"}</p>
        {groups.map((g) => (
          <div key={g.id}>
            <p className="text-[13px] font-semibold text-ink">{g.title}</p>
            <ul className="mt-1.5 space-y-1.5">{g.items.map((it) => <li key={it} className="flex gap-2 text-sm leading-5 text-ink-700"><Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-pos" aria-hidden />{it}</li>)}</ul>
          </div>
        ))}
      </div>
    </motion.article>
  );
}

// ------------------------------------------------------------------------------------------------------------------------------------------ D. comparison

function Comparison({ plans }: { plans: Plan[] }) {
  const has = (p: Plan, k: string) => p.features.includes(k);
  const groups = Array.from(new Set(ALL_FEATURE_ROWS.map(([g]) => g)));
  const cell = "px-2 py-2.5 text-center sm:px-4";
  return (
    <section aria-labelledby="cmp-h" className="mt-20 sm:mt-28">
      <h2 id="cmp-h" className="font-display text-2xl font-semibold tracking-tight sm:text-3xl">Compare plans</h2>
      <p className="mt-2 max-w-xl text-sm text-muted">Every line below is what the plan actually includes in your account.</p>
      <div className="mt-8 border-t border-ink">
        <table className="w-full table-fixed border-collapse text-sm">
          <caption className="sr-only">What each plan includes</caption>
          <thead>
            <tr className="border-b border-line"><th scope="col" className="w-[42%] py-3 pr-2 text-left text-[11px] font-normal uppercase tracking-[.12em] text-muted sm:w-[40%]"><span className="sr-only">Feature</span></th>
              {plans.map((p) => <th key={p.code} scope="col" className={`${cell} text-[12.5px] font-semibold text-ink sm:text-sm`}>{PLAN_NAME[p.code] ?? p.name}</th>)}</tr>
          </thead>
          <tbody>
            <tr><th colSpan={4} scope="colgroup" className="pb-1 pt-6 text-left font-mono text-[11px] font-normal uppercase tracking-[.14em] text-muted">Limits</th></tr>
            {LIMIT_ROWS.map((r) => (
              <tr key={r.id} className="border-b border-line"><th scope="row" className="py-2.5 pr-2 text-left text-[13px] font-normal text-ink-700 sm:text-sm">{r.label}</th>{plans.map((p) => <td key={p.code} className={`${cell} num font-medium text-ink`}>{r.value(p).toLocaleString("en-IN")}</td>)}</tr>
            ))}
            {groups.map((g) => (
              [<tr key={`h-${g}`}><th colSpan={4} scope="colgroup" className="pb-1 pt-6 text-left font-mono text-[11px] font-normal uppercase tracking-[.14em] text-muted">{g}</th></tr>,
                ...ALL_FEATURE_ROWS.filter(([gg]) => gg === g).map(([, k, label]) => (
                  <tr key={k} className="border-b border-line"><th scope="row" className="py-2.5 pr-2 text-left text-[13px] font-normal text-ink-700 sm:text-sm">{label}</th>
                    {plans.map((p) => <td key={p.code} className={cell}>{has(p, k) ? <><Check className="mx-auto h-4 w-4 text-pos" aria-hidden /><span className="sr-only">Included</span></> : <><Minus className="mx-auto h-4 w-4 text-ink-300" aria-hidden /><span className="sr-only">Not included</span></>}</td>)}</tr>
                ))]
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-muted">AI allowances renew at the start of each calendar month and do not carry over.</p>
    </section>
  );
}

// ------------------------------------------------------------------------------------------------------------------------------------------ E. billing, F. questions

const HOW_IT_WORKS: readonly [string, string][] = [
  ["Prepaid", "You pay up front for the term you choose: 1, 3, 6 or 12 months."],
  ["One payment, nothing recurring", "It is a single payment. We do not set up AutoPay or any standing instruction, so nothing renews on its own."],
  ["The term sets the end date", "Your plan runs for the number of months you paid for, counted from the day the payment is confirmed."],
  ["Confirmed payment starts the plan", "Your plan switches on only after the payment is confirmed."],
  ["Failed or pending payments change nothing", "If a payment fails or is still pending, your account stays exactly as it was."],
  ["You decide about the next term", "When your plan ends, nothing is charged. Buy another term whenever you are ready."],
];

function HowBillingWorks() {
  return (
    <section aria-labelledby="how-h" className="mt-20 grid gap-10 sm:mt-28 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)] lg:gap-16">
      <div><h2 id="how-h" className="font-display text-2xl font-semibold tracking-tight sm:text-3xl">How billing works</h2><p className="mt-2 max-w-sm text-sm text-muted">Simple on purpose. No subscription to cancel, no surprise charge.</p></div>
      <ol className="border-t border-ink">
        {HOW_IT_WORKS.map(([t, d], i) => (
          <motion.li key={t} initial={{ opacity: 0, y: 10 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: "-40px" }} transition={{ duration: 0.4, delay: 0.04 * i, ease: EASE }}
            className="grid grid-cols-[2.5rem_1fr] gap-x-3 border-b border-line py-4"><span className="num font-mono text-xs text-muted">{String(i + 1).padStart(2, "0")}</span><div><p className="text-[15px] font-medium text-ink">{t}</p><p className="mt-0.5 text-sm leading-6 text-muted">{d}</p></div></motion.li>
        ))}
      </ol>
    </section>
  );
}

const FAQ: readonly { q: string; a: ReactNode }[] = [
  { q: "Can I change my plan?", a: "Choose any plan and term when you buy. Changing plan in the middle of a term is not automatic yet: contact support and we will sort it out with you. Nothing changes without your say." },
  { q: "What happens when my plan expires?", a: "Your dashboards become read-only and AI features pause. Your data is kept and your QR and NFC cards keep working for customers. Buying a new term switches everything back on." },
  { q: "Will my plan renew automatically?", a: "No. Each purchase is a single payment for the term you chose. We do not take any further payment unless you buy again." },
  { q: "Can I choose a longer duration later?", a: "Yes. When your current term ends you can buy any term, longer or shorter. Extending a term that is still running is not available yet." },
  { q: "What happens to unused AI credits?", a: "Your plan's AI allowances renew at the start of every calendar month and do not carry over. Unused allowance from one month is not added to the next, whatever term you bought." },
  { q: "How do I reach support?", a: <>Open the <Link href="/help" className="font-medium text-ink underline underline-offset-2">Help page</Link> from the menu and send us a message. Include your business name and we will reply there.</> },
];

function Questions() {
  const [open, setOpen] = useState<number | null>(null);
  const reduce = useReducedMotion();
  const uid = useId();
  return (
    <section aria-labelledby="faq-h" className="mt-20 grid gap-10 sm:mt-28 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)] lg:gap-16">
      <h2 id="faq-h" className="font-display text-2xl font-semibold tracking-tight sm:text-3xl">Questions</h2>
      <div className="border-t border-ink">
        {FAQ.map((f, i) => {
          const on = open === i;
          return (
            <div key={f.q} className="border-b border-line">
              <h3><button type="button" aria-expanded={on} aria-controls={`${uid}-${i}`} onClick={() => setOpen(on ? null : i)}
                className="flex min-h-12 w-full items-center justify-between gap-4 py-4 text-left text-[15px] font-medium text-ink outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1">
                {f.q}<ChevronDown className={`h-4 w-4 shrink-0 text-muted transition-transform duration-200 ${on ? "rotate-180" : ""}`} aria-hidden /></button></h3>
              <AnimatePresence initial={false}>
                {on && (
                  <motion.div id={`${uid}-${i}`} role="region" aria-label={f.q} initial={reduce ? false : { height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={reduce ? { opacity: 0 } : { height: 0, opacity: 0 }} transition={{ duration: reduce ? 0 : 0.28, ease: EASE }} className="overflow-hidden">
                    <p className="pb-5 pr-8 text-sm leading-6 text-muted">{f.a}</p>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          );
        })}
      </div>
    </section>
  );
}

// ------------------------------------------------------------------------------------------------------------------------------------------ order summary + the one seam for real checkout

/** THE SEAM. When a one-time Cashfree Payment Gateway order exists on the server, this is the only place that changes: ask the server to create the order for (plan, months), then open the
 *  hosted page with the session it returns. The amount is read by the server from its own list; this component never sends a price. Until then it cannot be pressed and says why. */
function PayButton({ open, label }: { open: boolean; label: string }) {
  return <Button disabled={!open} aria-describedby="pay-note">{open ? label : "Payment opens soon"}</Button>;
}

function OrderSummary({ plan, months, terms, onClose }: { plan: Plan | null; months: number; terms: PrepaidTerms; onClose: () => void }) {
  const total = plan ? termPrice(terms, plan.code, months) : null;
  const name = plan ? (PLAN_NAME[plan.code] ?? plan.name) : "";
  const rows: [string, string][] = plan && total !== null ? [["Plan", name], ["Term", monthsLabel(months)], ["Per month", rupees(effectiveMonthlyPaise(total, months))], ["Total, paid once", rupees(total)]] : [];
  return (
    <Modal open={!!plan && total !== null} onClose={onClose} title="Review your plan" footer={<><Button variant="secondary" onClick={onClose}>Close</Button><PayButton open={terms.checkout_open} label={total !== null ? `Pay ${rupees(total)}` : "Pay"} /></>}>
      <dl className="border-t border-line text-sm">
        {rows.map(([k, v], i) => <div key={k} className={`flex justify-between gap-4 border-b border-line py-3 ${i === rows.length - 1 ? "font-semibold text-ink" : "text-ink-700"}`}><dt>{k}</dt><dd className="num">{v}</dd></div>)}
      </dl>
      <p className="mt-4 text-sm text-muted">One payment. Your plan runs for {monthsLabel(months)} from the day the payment is confirmed, and does not renew by itself.</p>
      {!terms.checkout_open && <div id="pay-note" className="mt-4"><Alert tone="info" title="Online payment is not open yet">Nothing has been charged and your account has not changed. We will switch prepaid plans on soon; until then everything you have today keeps working.</Alert></div>}
    </Modal>
  );
}

// ------------------------------------------------------------------------------------------------------------------------------------------ the whole screen

export function PricingExperience({ plans, terms, sub, isOwner, trialDays }: { plans: Plan[] | undefined; terms: PrepaidTerms | undefined; sub: SubscriptionInfo | null | undefined; isOwner: boolean; trialDays: number | null }) {
  const [months, setMonths] = useState(1);
  const [picked, setPicked] = useState<{ plan: Plan; months: number } | null>(null);
  const [announce, setAnnounce] = useState("");
  const ordered = useMemo(() => (plans ? PLAN_ORDER.map((c) => plans.find((p) => p.code === c)).filter((p): p is Plan => !!p) : []), [plans]);
  const ready = ordered.length > 0 && !!terms && terms.months.length > 0;
  const choose = (m: number) => { setMonths(m); setAnnounce(`Prices shown for ${monthsLabel(m)}`); };
  const stateOf = (code: string): CurrentState => (sub?.status === "active" && sub.plan === code ? "current" : sub?.status === "trialing" && sub.trial_entitlement === code ? "trial" : "none");
  const endsOn = sub?.current_period_end ? fmtDate(sub.current_period_end) : null;

  return (
    <div className="mt-10 border-t border-ink pt-6 sm:mt-14">
      <Hero trialDays={trialDays} />
      {!plans ? <div className="space-y-4" aria-busy="true" aria-label="Loading plans"><Skeleton className="h-16" /><div className="grid gap-px md:grid-cols-3"><Skeleton className="h-[34rem]" /><Skeleton className="h-[34rem]" /><Skeleton className="h-[34rem]" /></div></div>
        : !ready ? <Alert tone="warning" title="Plan prices are unavailable right now">We could not load the price list, so we are not showing any. Please refresh in a moment. Nothing about your account has changed.</Alert>
        : (
          <>
            <TermSelector terms={terms!} plans={ordered} value={months} onChange={choose} />
            <p className="sr-only" role="status" aria-live="polite">{announce}</p>
            {!terms!.checkout_open && (
              <p className="mt-5 flex items-start gap-2 text-[13px] text-muted"><Info className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />Online payment for prepaid plans is not open yet. You can compare prices and plans now; the buy buttons open when payment is ready.</p>
            )}
            <div className="mt-6 grid divide-y divide-line border border-line md:grid-cols-3 md:divide-x md:divide-y-0">
              {ordered.map((p, i) => <PlanColumn key={p.code} plan={p} below={i ? ordered[i - 1] : null} terms={terms!} months={months} state={stateOf(p.code)} endsOn={endsOn} isOwner={isOwner} index={i} onChoose={(pl, m) => setPicked({ plan: pl, months: m })} />)}
            </div>
            <Comparison plans={ordered} />
          </>
        )}
      <HowBillingWorks />
      <Questions />
      {terms && <OrderSummary plan={picked?.plan ?? null} months={picked?.months ?? months} terms={terms} onClose={() => setPicked(null)} />}
    </div>
  );
}
