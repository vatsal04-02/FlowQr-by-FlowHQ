"use client";
// The prepaid pricing screen: hero, term selector, three plans, comparison, how billing works, questions.
// Phone first: one plan at a time behind a plan switcher, compact rounded cards, the long lists folded away. From md up all three plans sit side by side.
//
// What it will NOT do, by design:
//  * start a subscription, an AutoPay mandate or a Rs 1 authorisation: it contains no payment-provider code at all;
//  * claim anything the backend does not enforce: limits and features are read from the plan rows the API serves (see lib/pricing.ts for the few deliberately omitted keys);
//  * show a crossed-out "MRP" or a percentage that was typed in: a saving is the difference to the plan's own 1-month price on the server's list;
//  * pretend a payment worked. Until the server says `terms.checkout_open`, the pay button is disabled and says so. The seam for the real one-time checkout is `PayButton`.
import { animate, AnimatePresence, LayoutGroup, motion, useReducedMotion } from "motion/react";
import { BadgeCheck, Building2, CalendarClock, Check, ChevronDown, Hourglass, Info, Minus, Rocket, ShieldCheck, TrendingUp, Wallet, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { Alert, Skeleton } from "@/components/ui/Card";
import { api, errorMessage } from "@/lib/api";
import { openCashfreePayment, rupees } from "@/lib/billing";
import { fmtDate } from "@/lib/format";
import {
  ALL_FEATURE_ROWS, LIMIT_ROWS, PLAN_ORDER, POSITIONING, RECOMMENDED, effectiveMonthlyPaise, monthsLabel, newFeatureGroups, termPrice, termSaving, termTabLabel,
} from "@/lib/pricing";
import type { Plan, PrepaidOffer, PrepaidTerms, SubscriptionInfo } from "@/lib/types";

const EASE = [0.22, 1, 0.36, 1] as const;
const PLAN_NAME: Record<string, string> = { starter: "Launch", growth: "Growth", pro: "Scale" };
const pill = "!rounded-full";
/** Each plan has its own flat colour (brand tokens only: sky, orange, teal). Used for the header band, the icon, the limit tiles and the monthly chip; never for text that must be read on it. */
const THEME: Record<string, { icon: LucideIcon; band: string; chipIcon: string; tile: string; chip: string; dot: string }> = {
  starter: { icon: Rocket, band: "bg-tone-sky/15", chipIcon: "bg-tone-sky text-white", tile: "bg-tone-sky/10", chip: "bg-tone-sky/15", dot: "bg-tone-sky" },
  growth: { icon: TrendingUp, band: "bg-accent-tint", chipIcon: "bg-accent-ink text-on-accent", tile: "bg-accent-tint", chip: "bg-accent-tint", dot: "bg-accent" },
  pro: { icon: Building2, band: "bg-tone-teal/15", chipIcon: "bg-tone-teal text-white", tile: "bg-tone-teal/10", chip: "bg-tone-teal/15", dot: "bg-tone-teal" },
};
const ring = "outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-canvas";

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

/** On a phone a long block folds behind a button; from md up it is simply open. */
function Fold({ label, children, className = "" }: { label: string; children: ReactNode; className?: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div className={className}>
      <button type="button" aria-expanded={open} aria-controls={id} onClick={() => setOpen((o) => !o)}
        className={`flex min-h-11 w-full items-center justify-between rounded-full bg-surface-2 px-4 text-[13px] font-medium text-ink transition-colors hover:bg-surface-3 md:hidden ${ring}`}>
        {label}<ChevronDown className={`h-4 w-4 text-muted transition-transform duration-200 ${open ? "rotate-180" : ""}`} aria-hidden />
      </button>
      <div id={id} className={`${open ? "mt-4 block" : "hidden"} md:mt-0 md:block`}>{children}</div>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------------------------------------------------ A. hero

function Hero({ trialDays }: { trialDays: number | null }) {
  const facts: [string, string][] = [["One payment per term", "bg-tone-sky/15"], ["No auto-renewal", "bg-tone-teal/15"], ["Prices in rupees", "bg-tone-amber/20"], ...(trialDays ? [[`${trialDays}-day free trial`, "bg-accent-tint"] as [string, string]] : [])];
  return (
    <header className="pb-6 pt-2 sm:pb-9 sm:pt-4">
      <motion.p initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, ease: EASE }} className="inline-flex rounded-full bg-accent-tint px-3 py-1 text-[11px] font-medium text-accent-ink">Plans</motion.p>
      <motion.h2 initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay: 0.05, ease: EASE }}
        className="mt-3 max-w-[24ch] text-balance font-display text-[1.65rem] font-semibold leading-[1.12] tracking-[-0.02em] text-ink sm:max-w-[28ch] sm:text-[2.2rem] lg:text-[2.6rem]">
        Grow your local business. Without the operational overhead.
      </motion.h2>
      <motion.p initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45, delay: 0.12, ease: EASE }} className="mt-3 max-w-xl text-[13.5px] leading-6 text-muted sm:text-[15px] sm:leading-7">
        Collect more Google reviews, answer them quickly and keep your business profile active from one place. Pick the plan that fits your business and the term that fits your budget.
      </motion.p>
      <motion.ul initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.5, delay: 0.22 }} className="mt-4 flex flex-wrap gap-2">
        {facts.map(([f, tint]) => <li key={f} className="flex items-center gap-2 rounded-full bg-surface py-1.5 pl-1.5 pr-3 text-[12px] text-ink-700 shadow-pill"><span className={`grid h-5 w-5 place-items-center rounded-full ${tint}`}><Check className="h-3 w-3 text-ink" aria-hidden /></span>{f}</li>)}
      </motion.ul>
    </header>
  );
}

// ------------------------------------------------------------------------------------------------------------------------------------------ B. duration

function TermSelector({ terms, plans, value, onChange }: { terms: PrepaidTerms; plans: Plan[]; value: number; onChange: (m: number) => void }) {
  const id = useId();
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const months = terms.months;
  const best = Math.max(0, ...plans.map((p) => termSaving(terms, p.code, value)?.percent ?? 0));
  const move = (e: KeyboardEvent, i: number) => {
    const d = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!d) return;
    e.preventDefault();
    const n = (i + d + months.length) % months.length;
    onChange(months[n]); refs.current[n]?.focus();
  };
  return (
    <>
      <div className="sticky top-[4.6rem] z-10 -mx-4 bg-canvas px-4 py-2 sm:static sm:mx-0 sm:bg-transparent sm:p-0">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
          <p id={id} className="hidden text-sm font-medium text-ink sm:block">How long do you want to pay for?</p>
          <LayoutGroup id={id}>
            <div role="radiogroup" aria-label="How long do you want to pay for?" className="grid w-full grid-cols-4 rounded-full bg-surface-2 p-1 shadow-pill sm:w-auto sm:min-w-[24rem] sm:shadow-none">
              {months.map((m, i) => {
                const on = m === value;
                return (
                  <button key={m} ref={(el) => { refs.current[i] = el; }} type="button" role="radio" aria-checked={on} tabIndex={on ? 0 : -1} onClick={() => onChange(m)} onKeyDown={(e) => move(e, i)}
                    className={`relative min-h-10 rounded-full px-1 text-center text-[12.5px] font-medium transition-colors sm:text-[13px] ${ring} ${on ? "text-on-accent" : "text-muted hover:text-ink"}`}>
                    {on && <motion.span layoutId="term-pill" className="absolute inset-0 rounded-full bg-accent-ink shadow-pill" transition={{ type: "spring", stiffness: 520, damping: 42 }} />}
                    <span className="relative">{termTabLabel(m)}</span>
                  </button>
                );
              })}
            </div>
          </LayoutGroup>
        </div>
      </div>
      <p className="mt-1.5 flex min-h-6 items-center gap-2 px-1 text-[12px] text-muted sm:justify-end" aria-hidden>{best > 0 ? <><span className="rounded-full bg-pos-tint px-2 py-0.5 font-medium text-pos">Up to {best}% less</span>than paying month by month</> : "Pay one month at a time"}</p>
    </>
  );
}

// ------------------------------------------------------------------------------------------------------------------------------------------ C. plans

type CurrentState = "none" | "current" | "trial";

function PlanSwitcher({ plans, value, onChange }: { plans: Plan[]; value: string; onChange: (c: string) => void }) {
  const id = useId();
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const move = (e: KeyboardEvent, i: number) => {
    const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!d) return;
    e.preventDefault();
    const n = (i + d + plans.length) % plans.length;
    onChange(plans[n].code); refs.current[n]?.focus();
  };
  return (
    <LayoutGroup id={id}>
      <div role="radiogroup" aria-label="Plan" className="mt-3 grid grid-cols-3 gap-1.5 md:hidden">
        {plans.map((p, i) => {
          const on = p.code === value;
          return (
            <button key={p.code} ref={(el) => { refs.current[i] = el; }} type="button" role="radio" aria-checked={on} tabIndex={on ? 0 : -1} onClick={() => onChange(p.code)} onKeyDown={(e) => move(e, i)}
              className={`relative min-h-11 rounded-full border px-2 text-[13px] font-semibold transition-colors ${ring} ${on ? "border-transparent text-ink-on" : "border-line bg-surface text-ink hover:bg-surface-2"}`}>
              {on && <motion.span layoutId="plan-pill" className="absolute inset-0 rounded-full bg-ink-solid" transition={{ type: "spring", stiffness: 520, damping: 42 }} />}
              <span className="relative inline-flex items-center gap-1.5"><span className={`h-2 w-2 rounded-full ${THEME[p.code]?.dot ?? "bg-muted"}`} aria-hidden />{PLAN_NAME[p.code] ?? p.name}</span>
            </button>
          );
        })}
      </div>
    </LayoutGroup>
  );
}

function PlanCard({ plan, below, terms, months, state, endsOn, isOwner, locked, offer, onChoose, index, active }: {
  plan: Plan; below: Plan | null; terms: PrepaidTerms; months: number; state: CurrentState; endsOn: string | null; isOwner: boolean; locked: string | null; offer: PrepaidOffer | undefined; onChoose: (p: Plan, months: number) => void; index: number; active: boolean;
}) {
  const total = offer ? offer.amount_paise : termPrice(terms, plan.code, months);  // a temporary price for THIS business, if the server says there is one; otherwise the list
  const monthly = total === null ? null : effectiveMonthlyPaise(total, months);
  const saving = termSaving(terms, plan.code, months);
  const groups = useMemo(() => newFeatureGroups(plan, below), [plan, below]);
  const recommended = plan.code === RECOMMENDED;
  const th = THEME[plan.code] ?? THEME.starter;
  const name = PLAN_NAME[plan.code] ?? plan.name;
  const disabled = total === null || !isOwner || state === "current" || !!locked;
  return (
    <div className={`${active ? "block" : "hidden"} md:block`}>
      <motion.article key={active ? "on" : "off"} initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} whileHover={{ y: -2 }} transition={{ duration: 0.4, delay: 0.07 * index, ease: EASE }} aria-labelledby={`plan-${plan.code}`}
        className={`flex h-full flex-col overflow-hidden rounded-[22px] bg-surface shadow-card ${recommended ? "ring-2 ring-accent/70" : "ring-1 ring-line"}`}>
        <div className={`px-5 pb-4 pt-5 sm:px-6 ${th.band}`}>
        <div className="flex min-h-8 items-center justify-between gap-2">
          <div className="flex items-center gap-2.5"><span className={`grid h-8 w-8 place-items-center rounded-xl ${th.chipIcon}`}><th.icon className="h-4 w-4" aria-hidden /></span>
          <h3 id={`plan-${plan.code}`} className="font-display text-[17px] font-semibold tracking-tight text-ink">{name}</h3></div>
          {state === "current" ? <span className="rounded-full bg-pos-tint px-2.5 py-1 text-[11px] font-medium text-pos">Current plan</span>
            : state === "trial" ? <span className="rounded-full bg-surface px-2.5 py-1 text-[11px] font-medium text-muted shadow-pill">In your free trial</span>
            : recommended ? <span className="rounded-full bg-surface px-2.5 py-1 text-[11px] font-medium text-accent-ink shadow-pill">Recommended</span> : null}
        </div>
        <p className="mt-2 text-[13px] text-ink-700">{POSITIONING[plan.code]}</p>
        </div>
        <div className="flex flex-1 flex-col p-5 sm:p-6">

        <div>
          {total === null ? <p className="font-display text-2xl font-semibold text-muted">Unavailable</p> : (
            <>
              <p className="flex items-baseline gap-1.5 font-display text-ink"><span className="text-xl font-medium text-muted">₹</span><Glide value={total / 100} className="num text-[2.4rem] font-semibold leading-none tracking-[-0.03em] sm:text-[2.7rem]" /><span className="text-[13px] font-normal text-muted">for {monthsLabel(months)}</span></p>
              <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1.5 text-[12.5px]">
                <span className={`rounded-full px-2.5 py-1 text-ink-700 ${th.chip}`}><span className="num font-medium text-ink">₹<Glide value={(monthly ?? 0) / 100} /></span> a month</span>
                {saving && !offer && <span className="rounded-full bg-pos-tint px-2.5 py-1 font-medium text-pos">Save {rupees(saving.paise)} ({saving.percent}%)</span>}
                {offer && <span className="rounded-full bg-accent-tint px-2.5 py-1 font-medium text-accent-ink">{offer.label} · normally {rupees(offer.list_price_paise)}</span>}
              </div>
            </>
          )}
        </div>

        <Button className={`mt-5 w-full ${pill}`} variant={recommended ? "brand" : "primary"} disabled={disabled} onClick={() => onChoose(plan, months)}
          aria-label={state === "current" ? `${name} is your current plan` : `Choose ${name} for ${monthsLabel(months)}`}>
          {state === "current" ? "Current plan" : `Choose ${name}`}
        </Button>
        {state === "current" && endsOn && <p className="mt-2 text-center text-xs text-muted">Active until {endsOn}</p>}
        {!isOwner && state !== "current" && <p className="mt-2 text-center text-xs text-muted">Only the business owner can buy a plan.</p>}
        {isOwner && locked && state !== "current" && <p className="mt-2 text-center text-xs text-muted">{locked}</p>}

        <dl className="mt-5 grid grid-cols-2 gap-2">
          {LIMIT_ROWS.map((r) => (
            <div key={r.id} className={`rounded-2xl px-3 py-2.5 ${th.tile}`}><dd className="num font-display text-lg font-semibold leading-6 text-ink">{r.value(plan).toLocaleString("en-IN")}</dd><dt className="mt-0.5 text-[11.5px] leading-4 text-muted">{r.label}</dt></div>
          ))}
        </dl>

        <Fold label={below ? `What's included · everything in ${PLAN_NAME[below.code] ?? below.name}, plus` : "What's included"} className="mt-4">
          <div className="space-y-4 md:pt-1">
            <p className="hidden text-[11.5px] font-medium uppercase tracking-[.08em] text-muted md:block">{below ? `Everything in ${PLAN_NAME[below.code] ?? below.name}, plus` : "Includes"}</p>
            {groups.map((g) => (
              <div key={g.id}>
                <p className="text-[12.5px] font-semibold text-ink">{g.title}</p>
                <ul className="mt-1.5 space-y-1.5">{g.items.map((it) => <li key={it} className="flex gap-2 text-[13px] leading-5 text-ink-700"><Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-pos" aria-hidden />{it}</li>)}</ul>
              </div>
            ))}
          </div>
        </Fold>
        </div>
      </motion.article>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------------------------------------------------ D. comparison

function Comparison({ plans }: { plans: Plan[] }) {
  const has = (p: Plan, k: string) => p.features.includes(k);
  const groups = Array.from(new Set(ALL_FEATURE_ROWS.map(([g]) => g)));
  const cell = "px-1.5 py-2 text-center sm:px-4";
  return (
    <section aria-labelledby="cmp-h" className="mt-14 sm:mt-20">
      <h2 id="cmp-h" className="font-display text-xl font-semibold tracking-tight sm:text-2xl">Compare plans</h2>
      <p className="mt-1 max-w-xl text-[13px] text-muted sm:text-sm">Every line is what the plan actually includes in your account.</p>
      <Fold label="Show the full comparison" className="mt-4">
        <div className="rounded-[22px] bg-surface p-3 shadow-card ring-1 ring-line sm:p-5">
          <table className="w-full table-fixed border-collapse text-[13px] sm:text-sm">
            <caption className="sr-only">What each plan includes</caption>
            <thead>
              <tr><th scope="col" className="w-[44%] py-2 pr-2 text-left sm:w-[40%]"><span className="sr-only">Feature</span></th>
                {plans.map((p) => <th key={p.code} scope="col" className={`${cell} text-[12.5px] font-semibold text-ink sm:text-sm`}>{PLAN_NAME[p.code] ?? p.name}</th>)}</tr>
            </thead>
            <tbody>
              <tr><th colSpan={4} scope="colgroup" className="pb-1 pt-4 text-left text-[11px] font-medium uppercase tracking-[.08em] text-muted">Limits</th></tr>
              {LIMIT_ROWS.map((r) => (
                <tr key={r.id} className="border-t border-line"><th scope="row" className="py-2 pr-2 text-left text-[12.5px] font-normal text-ink-700 sm:text-sm">{r.label}</th>{plans.map((p) => <td key={p.code} className={`${cell} num font-medium text-ink`}>{r.value(p).toLocaleString("en-IN")}</td>)}</tr>
              ))}
              {groups.map((g) => (
                [<tr key={`h-${g}`}><th colSpan={4} scope="colgroup" className="pb-1 pt-4 text-left text-[11px] font-medium uppercase tracking-[.08em] text-muted">{g}</th></tr>,
                  ...ALL_FEATURE_ROWS.filter(([gg]) => gg === g).map(([, k, label]) => (
                    <tr key={k} className="border-t border-line"><th scope="row" className="py-2 pr-2 text-left text-[12.5px] font-normal text-ink-700 sm:text-sm">{label}</th>
                      {plans.map((p) => <td key={p.code} className={cell}>{has(p, k) ? <><Check className="mx-auto h-4 w-4 text-pos" aria-hidden /><span className="sr-only">Included</span></> : <><Minus className="mx-auto h-4 w-4 text-ink-300" aria-hidden /><span className="sr-only">Not included</span></>}</td>)}</tr>
                  ))]
              ))}
            </tbody>
          </table>
          <p className="mt-3 text-xs text-muted">AI allowances renew at the start of each calendar month and do not carry over.</p>
        </div>
      </Fold>
    </section>
  );
}

// ------------------------------------------------------------------------------------------------------------------------------------------ E. billing, F. questions

const HOW_IT_WORKS: readonly [LucideIcon, string, string, string][] = [
  [Wallet, "Prepaid", "You pay up front for the term you choose: 1, 3, 6 or 12 months.", "bg-tone-sky text-white"],
  [ShieldCheck, "One payment, nothing recurring", "No AutoPay and no standing instruction, so nothing renews on its own.", "bg-tone-teal text-white"],
  [CalendarClock, "The term sets the end date", "Your plan runs for the months you paid for, counted from the day payment is confirmed.", "bg-accent-ink text-on-accent"],
  [BadgeCheck, "Confirmed payment starts the plan", "Your plan switches on only after the payment is confirmed.", "bg-tone-teal text-white"],
  [Info, "Failed or pending changes nothing", "If a payment fails or is still pending, your account stays exactly as it was.", "bg-tone-rose text-white"],
  [Hourglass, "You decide about the next term", "When your plan ends nothing is charged. Buy another term when you are ready.", "bg-tone-amber text-ink"],
];

function HowBillingWorks() {
  return (
    <section aria-labelledby="how-h" className="mt-14 sm:mt-20">
      <h2 id="how-h" className="font-display text-xl font-semibold tracking-tight sm:text-2xl">How billing works</h2>
      <p className="mt-1 max-w-sm text-[13px] text-muted sm:text-sm">Simple on purpose. No subscription to cancel, no surprise charge.</p>
      <ol className="mt-4 grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
        {HOW_IT_WORKS.map(([Icon, t, d, tone], i) => (
          <motion.li key={t} initial={{ opacity: 0, y: 10 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: "-30px" }} transition={{ duration: 0.4, delay: 0.04 * (i % 3), ease: EASE }} whileHover={{ y: -2 }}
            className="flex gap-3 rounded-[18px] bg-surface p-4 shadow-card ring-1 ring-line">
            <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl ${tone}`}><Icon className="h-4 w-4" aria-hidden /></span>
            <div className="min-w-0"><p className="text-[13.5px] font-semibold text-ink">{t}</p><p className="mt-0.5 text-[12.5px] leading-5 text-muted">{d}</p></div>
          </motion.li>
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
    <section aria-labelledby="faq-h" className="mt-14 sm:mt-20">
      <h2 id="faq-h" className="font-display text-xl font-semibold tracking-tight sm:text-2xl">Questions</h2>
      <div className="mt-4 space-y-2 lg:max-w-3xl">
        {FAQ.map((f, i) => {
          const on = open === i;
          return (
            <div key={f.q} className="rounded-[18px] bg-surface shadow-card ring-1 ring-line">
              <h3><button type="button" aria-expanded={on} aria-controls={`${uid}-${i}`} onClick={() => setOpen(on ? null : i)}
                className={`flex min-h-12 w-full items-center justify-between gap-3 rounded-[18px] px-4 py-3 text-left text-[13.5px] font-medium text-ink sm:text-sm ${ring}`}>
                {f.q}<span className={`grid h-7 w-7 shrink-0 place-items-center rounded-full transition-colors ${on ? "bg-ink-solid text-ink-on" : "bg-surface-2 text-muted"}`}><ChevronDown className={`h-4 w-4 transition-transform duration-200 ${on ? "rotate-180" : ""}`} aria-hidden /></span></button></h3>
              <AnimatePresence initial={false}>
                {on && (
                  <motion.div id={`${uid}-${i}`} role="region" aria-label={f.q} initial={reduce ? false : { height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={reduce ? { opacity: 0 } : { height: 0, opacity: 0 }} transition={{ duration: reduce ? 0 : 0.26, ease: EASE }} className="overflow-hidden">
                    <p className="px-4 pb-4 pr-6 text-[13px] leading-6 text-muted">{f.a}</p>
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

const phoneOk = (v: string) => /^[6-9]\d{9}$/.test(v.replace(/\D/g, "").replace(/^91(?=\d{10}$)/, "").replace(/^0(?=\d{10}$)/, ""));

/** The pay button. It asks the SERVER to create a one-time Cashfree order for (plan, months, phone): the request carries NO amount, the server prices it. It then sends the browser to Cashfree's
 *  payment page. Nothing is granted here: the plan starts only after the server has asked Cashfree and been told the order is paid (the return page, the webhook and the hourly check all do that). */
function PayButton({ open, label, disabled, busy, onClick }: { open: boolean; label: string; disabled: boolean; busy: boolean; onClick: () => void }) {
  return <Button className={pill} disabled={!open || disabled} loading={busy} onClick={onClick} aria-describedby="pay-note">{open ? label : "Payment opens soon"}</Button>;
}

function OrderSummary({ plan, months, terms, offers, onClose }: { plan: Plan | null; months: number; terms: PrepaidTerms; offers: PrepaidOffer[]; onClose: () => void }) {
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const phoneId = useId();
  const offer = plan ? offers.find((o) => o.plan === plan.code && o.months === months) : undefined;
  const total = plan ? (offer ? offer.amount_paise : termPrice(terms, plan.code, months)) : null;
  async function pay() {
    if (!plan || !phoneOk(phone)) return;
    setBusy(true); setErr(null);
    try {
      const c = await api<{ payment_session_id: string; environment: string }>("/billing/prepaid/checkout", { method: "POST", body: { plan: plan.code, months, phone } });
      await openCashfreePayment(c.payment_session_id, c.environment);  // the browser leaves for Cashfree here; it comes back to the payment return page
    } catch (e) { setErr(errorMessage(e)); setBusy(false); }
  }
  const name = plan ? (PLAN_NAME[plan.code] ?? plan.name) : "";
  const rows: [string, string][] = plan && total !== null ? [["Plan", name], ["Term", monthsLabel(months)], ["Per month", rupees(effectiveMonthlyPaise(total, months))], ...(offer ? [[`${offer.label} (normally ${rupees(offer.list_price_paise)})`, "only for your business"] as [string, string]] : []), ["Total, paid once", rupees(total)]] : [];
  return (
    <Modal open={!!plan && total !== null} onClose={onClose} title="Review your plan" footer={<><Button className={pill} variant="secondary" onClick={onClose} disabled={busy}>Close</Button><PayButton open={terms.checkout_open} label={total !== null ? `Pay ${rupees(total)}` : "Pay"} disabled={!phoneOk(phone)} busy={busy} onClick={() => void pay()} /></>}>
      <dl className="overflow-hidden rounded-2xl bg-surface-2 text-sm">
        {rows.map(([k, v], i) => <div key={k} className={`flex justify-between gap-4 px-4 py-3 ${i ? "border-t border-line" : ""} ${i === rows.length - 1 ? "font-semibold text-ink" : "text-ink-700"}`}><dt>{k}</dt><dd className="num">{v}</dd></div>)}
      </dl>
      {terms.checkout_open && (
        <div className="mt-4">
          <label htmlFor={phoneId} className="text-[13px] font-medium text-ink">Mobile number</label>
          <input id={phoneId} type="tel" inputMode="numeric" autoComplete="tel" placeholder="98765 43210" value={phone} onChange={(e) => setPhone(e.target.value)} maxLength={16}
            aria-invalid={phone.length > 0 && !phoneOk(phone)} aria-describedby={`${phoneId}-h`}
            className="mt-1.5 min-h-11 w-full rounded-full border border-transparent bg-surface-2 px-4 text-base text-ink outline-none placeholder:text-muted-soft hover:border-ink-200 focus-visible:border-accent sm:text-sm" />
          <p id={`${phoneId}-h`} className={`mt-1.5 text-xs ${phone.length > 0 && !phoneOk(phone) ? "text-neg" : "text-muted"}`}>{phone.length > 0 && !phoneOk(phone) ? "Enter a 10-digit Indian mobile number." : "The payment provider needs it for this payment. We do not keep it."}</p>
        </div>
      )}
      <p className="mt-4 text-sm text-muted">One payment. Your plan runs for {monthsLabel(months)} from the day the payment is confirmed, and does not renew by itself.</p>
      {err && <div className="mt-4"><Alert tone="error" title="Couldn't start the payment">{err}{/charged/i.test(err) ? "" : " Nothing was charged."}</Alert></div>}
      {!terms.checkout_open && <div id="pay-note" className="mt-4"><Alert tone="info" title="Online payment is not open yet">Nothing has been charged and your account has not changed. We will switch prepaid plans on soon; until then everything you have today keeps working.</Alert></div>}
    </Modal>
  );
}

// ------------------------------------------------------------------------------------------------------------------------------------------ the whole screen

export function PricingExperience({ plans, terms, sub, isOwner, trialDays, offers = [] }: { plans: Plan[] | undefined; terms: PrepaidTerms | undefined; sub: SubscriptionInfo | null | undefined; isOwner: boolean; trialDays: number | null; offers?: PrepaidOffer[] }) {
  const [months, setMonths] = useState(1);
  const [shown, setShown] = useState<string>(RECOMMENDED);  // the plan a phone shows; wider screens show all three
  const [picked, setPicked] = useState<{ plan: Plan; months: number } | null>(null);
  const [announce, setAnnounce] = useState("");
  const ordered = useMemo(() => (plans ? PLAN_ORDER.map((c) => plans.find((p) => p.code === c)).filter((p): p is Plan => !!p) : []), [plans]);
  const ready = ordered.length > 0 && !!terms && terms.months.length > 0;
  const choose = (m: number) => { setMonths(m); setAnnounce(`Prices shown for ${monthsLabel(m)}`); };
  const stateOf = (code: string): CurrentState => (sub?.status === "active" && sub.plan === code ? "current" : sub?.status === "trialing" && sub.trial_entitlement === code ? "trial" : "none");
  const endsOn = sub?.current_period_end ? fmtDate(sub.current_period_end) : null;
  // A running prepaid term blocks a second purchase (the server enforces it too): say why instead of letting the person hit an error.
  const locked = sub?.source === "prepaid" && sub.active && endsOn ? `Your plan is active until ${endsOn}. You can buy another term then.` : sub?.has_cashfree_subscription || sub?.has_razorpay_subscription ? "You already have a monthly payment set up. Contact support to move to a prepaid plan." : null;

  return (
    <div className="mt-8 sm:mt-12">
      <Hero trialDays={trialDays} />
      {!plans ? <div className="space-y-3" aria-busy="true" aria-label="Loading plans"><Skeleton className="h-12 rounded-full" /><div className="grid gap-3 md:grid-cols-3"><Skeleton className="h-[26rem] rounded-[22px]" /><Skeleton className="hidden h-[26rem] rounded-[22px] md:block" /><Skeleton className="hidden h-[26rem] rounded-[22px] md:block" /></div></div>
        : !ready ? <Alert tone="warning" title="Plan prices are unavailable right now">We could not load the price list, so we are not showing any. Please refresh in a moment. Nothing about your account has changed.</Alert>
        : (
          <>
            <TermSelector terms={terms!} plans={ordered} value={months} onChange={choose} />
            <p className="sr-only" role="status" aria-live="polite">{announce}</p>
            {!terms!.checkout_open && (
              <p className="mt-2 flex items-start gap-2 rounded-2xl bg-surface-2 px-3.5 py-2.5 text-[12.5px] leading-5 text-muted"><Info className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />Online payment for prepaid plans is not open yet. Compare prices and plans now; the buy buttons work once payment is ready.</p>
            )}
            <PlanSwitcher plans={ordered} value={shown} onChange={setShown} />
            <div className="mt-4 grid items-stretch gap-4 md:grid-cols-3">
              {ordered.map((p, i) => <PlanCard key={p.code} plan={p} below={i ? ordered[i - 1] : null} terms={terms!} months={months} state={stateOf(p.code)} endsOn={endsOn} isOwner={isOwner} locked={locked} offer={offers.find((o) => o.plan === p.code && o.months === months)} index={i} active={p.code === shown} onChoose={(pl, m) => setPicked({ plan: pl, months: m })} />)}
            </div>
            <Comparison plans={ordered} />
          </>
        )}
      <HowBillingWorks />
      <Questions />
      {terms && <OrderSummary plan={picked?.plan ?? null} months={picked?.months ?? months} terms={terms} offers={offers} onClose={() => setPicked(null)} />}
    </div>
  );
}
