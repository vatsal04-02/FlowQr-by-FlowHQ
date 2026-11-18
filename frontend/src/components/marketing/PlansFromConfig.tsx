"use client";
import clsx from "clsx";
import { Check, Minus } from "lucide-react";
import { FEATURE_LABELS, rupees } from "@/lib/billing";
import type { PlansResponse } from "@/lib/types";
import { useFetch } from "@/lib/use-api";
import { trialTerms } from "@/lib/plans";
import { MButton } from "./kit";
import { EASE, Rise } from "./motion";
import { motion } from "motion/react";

/**
 * Plans read live from the app's subscription config (/billing/plans). There are deliberately no fallback numbers here:
 * if the config can't be read, the page says "Talk to us for pricing" (PRD §4.6).
 */
export function usePlansLive() {
  const { data, error, loading } = useFetch<PlansResponse>("/billing/plans");
  return { data: data && data.plans.length ? data : null, failed: !!error || (!!data && !data.plans.length), loading };
}

export function TalkToUs() {
  return (
    <div className="mkt-card mx-auto max-w-[520px] p-8 text-center">
      <p className="t-h3 text-m-ink">Talk to us for pricing</p>
      <p className="mt-3 text-[15px] text-m-muted">We couldn&rsquo;t load the current plans just now. Please try again in a moment, or sign up to get started.</p>
      <MButton href="/register" event="signup_cta_click" className="mt-6">Sign up</MButton>
    </div>
  );
}

export function PlanCards() {
  const { data, failed, loading } = usePlansLive();
  if (failed) return <TalkToUs />;
  if (loading || !data) return <div className="grid gap-3 md:grid-cols-3" aria-busy>{[0, 1, 2].map((i) => <div key={i} className="h-[420px] animate-pulse rounded-[20px] bg-m-surface" />)}</div>;
  const plans = data.plans;
  const rec = plans.find((p) => p.code === "growth")?.code ?? plans[Math.floor(plans.length / 2)]?.code;
  return (
    <>
      <p className="mb-8 text-center text-[15px] text-m-muted">{data.trial_days}-day free trial. {trialTerms(data.billing ? !!data.billing.mandate_required : null)}</p>
      {data.billing?.provider === "cashfree" && <p className="-mt-5 mb-8 text-center text-[13px] text-m-muted">Plans renew monthly. When you choose a plan you authorise a recurring payment (UPI AutoPay or card) through Cashfree: we take ₹1 to set it up and return it automatically, and your first payment is after your free trial. Cancel any time before then.</p>}
      <div className="grid gap-3 md:grid-cols-3">
        {plans.map((p, i) => {
          const hot = p.code === rec;
          return (
            <motion.div key={p.code} data-plan={p.code} initial={{ opacity: 0, y: 24 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: 0.6, ease: EASE, delay: i * 0.1 }}
              className={clsx("flex flex-col rounded-[20px] p-7", hot ? "bg-m-accent text-m-ink" : "bg-m-surface shadow-[var(--shadow-card)]")}>
              <div className="flex items-center justify-between"><h2 className="text-[20px] font-medium tracking-[-.02em]">{p.name}</h2>{hot && <span className="rounded-full bg-white/70 px-2.5 py-0.5 text-[11.5px] font-semibold">Recommended</span>}</div>
              <p className="mt-6 t-number">{rupees(p.price_paise)}<span className="ml-1 text-[14px] font-medium tracking-normal opacity-70">/month</span></p>
              <p className={clsx("mt-2 text-[13px]", hot ? "text-m-ink/75" : "text-m-muted")}>+ GST as applicable</p>
              <ul className={clsx("mt-6 space-y-2 border-t pt-5 text-[14px]", hot ? "border-m-ink/15" : "border-m-line")}>
                <li>{p.max_locations} location{p.max_locations === 1 ? "" : "s"}</li>
                <li>{p.max_staff} team members</li>
                <li>{p.monthly_ai_generations.toLocaleString("en-IN")} AI drafts a month</li>
                {p.features.map((f) => FEATURE_LABELS[f] && <li key={f} className="flex gap-2"><Check className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={2} aria-hidden />{FEATURE_LABELS[f]}</li>)}
              </ul>
              <div className="mt-auto pt-8"><MButton href="/register" variant={hot ? "dark" : "primary"} className="w-full justify-between">Start free trial</MButton></div>
            </motion.div>
          );
        })}
      </div>
    </>
  );
}

export function PlanCompare() {
  const { data } = usePlansLive();
  if (!data) return null;
  const plans = data.plans;
  const rec = plans.findIndex((p) => p.code === "growth");
  const feats = Object.keys(FEATURE_LABELS).filter((k) => plans.some((p) => p.features.includes(k)));
  const rows: [string, (p: (typeof plans)[number]) => React.ReactNode][] = [
    ["Locations", (p) => p.max_locations], ["Team members", (p) => p.max_staff], ["AI drafts a month", (p) => p.monthly_ai_generations.toLocaleString("en-IN")], ["QR/NFC scans", () => "Unlimited"],
    ...feats.map((k): [string, (p: (typeof plans)[number]) => React.ReactNode] => [FEATURE_LABELS[k], (p) => p.features.includes(k) ? <Check className="mx-auto h-4 w-4" strokeWidth={2} aria-label="Included" /> : <Minus className="mx-auto h-4 w-4 text-m-muted2" strokeWidth={1.5} aria-label="Not included" />]),
  ];
  return (
    <Rise className="overflow-x-auto pb-4">
      <table className="w-full min-w-[620px] border-separate border-spacing-0 text-center text-[13px]">
        <thead><tr><th scope="col" className="sticky left-0 bg-m-bg px-4 pb-4 text-left font-medium text-m-muted">Plan features</th>
          {plans.map((p, i) => <th key={p.code} scope="col" className={clsx("px-3 pb-4 text-[15px] font-medium", i === rec && "rounded-t-[14px] bg-m-accent pt-3")}>{p.name}</th>)}</tr></thead>
        <tbody>{rows.map(([label, cell], ri) => (
          <tr key={label}><th scope="row" className="sticky left-0 h-14 border-b border-m-line bg-m-bg px-4 text-left font-medium text-m-ink2">{label}</th>
            {plans.map((p, i) => <td key={p.code} className={clsx("h-14 px-3", i === rec ? "border-b border-white/25 bg-m-accent font-medium" : "border-b border-m-line bg-m-tint/50", i === rec && ri === rows.length - 1 && "rounded-b-[14px]")}>{cell(p)}</td>)}</tr>
        ))}</tbody>
      </table>
    </Rise>
  );
}

/** Cards & print add-on: the card price comes from config; without one, "Contact us for pricing". */
export function CardAddOn() {
  const { data, failed } = usePlansLive();
  const price = data?.card_price_paise;
  return (
    <div className="mkt-card grid gap-6 p-7 md:grid-cols-[1fr_auto] md:items-center">
      <div><p className="t-h3 text-m-ink">Cards &amp; print</p><p className="mt-2 max-w-[520px] text-[15px] text-m-muted">Printed QR and NFC cards are sold separately from the subscription, per order. Posters and table tents can be downloaded from the app.</p></div>
      <div className="text-left md:text-right">
        {price && !failed ? <><p className="t-number text-m-ink">{rupees(price)}</p><p className="mt-1 text-[13px] text-m-muted">per card, + GST as applicable</p></> : <p className="text-[17px] font-medium text-m-ink">Contact us for pricing</p>}
        <MButton href="/demo" variant="secondary" className="mt-4" event="card_enquiry_submit">Ask about cards</MButton>
      </div>
    </div>
  );
}

export function CardOrderNote() {
  const { data } = usePlansLive();
  return <>Cards are sold separately from the subscription{data?.card_price_paise ? <> at {rupees(data.card_price_paise)} per card, + GST as applicable</> : <>; contact us for pricing</>}.</>;
}
