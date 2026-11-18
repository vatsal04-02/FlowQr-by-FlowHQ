"use client";
import clsx from "clsx";
import { animate, motion, useMotionValue, useReducedMotion, useTransform } from "motion/react";
import { Check, Minus, Star } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { rupees } from "@/lib/billing";
import { trialTerms } from "@/lib/plans";
import { BILLING_NOTE, BILLING_SUFFIX, cardPoints, comparisonRows, periodPrice, POSITION, sellablePlans, yearlySaving, type Billing, type Cell } from "@/lib/plan-compare";
import { effectiveMonthlyPaise } from "@/lib/pricing";
import { track } from "@/lib/track";
import { Rise } from "./motion";
import { SignupDialog } from "./SignupDialog";
import { TalkToUs, usePlansLive } from "./PlansFromConfig";

/**
 * The public pricing section, in the layout of the "Pricing" block the owner chose: a switch above three centred cards, the recommended card raised with an accent border and a badge, the
 * outer cards a little smaller and tucked toward it on a wide screen, prices that roll to their new value, and a small burst of confetti when the switch goes to yearly.
 * Monthly is selected first. Every price is read from the prepaid price list the server serves, every allowance and feature from lib/plan-compare.ts; nothing is written here, and a plan
 * without both prices is left out rather than guessed. A yearly price is one payment for 12 months (no automatic renewal); the AI allowances stay monthly.
 */

/** Matches a CSS media query, false on the server and until the browser says otherwise (so the markup is the same for everyone on first render). */
function useMedia(query: string) {
  const [on, setOn] = useState(false);
  useEffect(() => {
    const m = window.matchMedia(query), f = () => setOn(m.matches);
    f(); m.addEventListener("change", f);
    return () => m.removeEventListener("change", f);
  }, [query]);
  return on;
}

/** A small burst of round confetti from a point (the switch), in the brand's colours. Skipped for people who asked for reduced motion. Draws on its own throwaway canvas, then removes it. */
function confetti(x: number, y: number) {
  if (typeof window === "undefined" || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const c = document.createElement("canvas"), dpr = Math.min(2, window.devicePixelRatio || 1);
  c.setAttribute("aria-hidden", "true");
  Object.assign(c.style, { position: "fixed", inset: "0", width: "100vw", height: "100vh", pointerEvents: "none", zIndex: "70" });
  c.width = innerWidth * dpr; c.height = innerHeight * dpr;
  document.body.appendChild(c);
  const g = c.getContext("2d");
  if (!g) { c.remove(); return; }
  g.scale(dpr, dpr);
  const colours = ["#FE6A05", "#0B0F2E", "#FFB27A", "#C94C00", "#FFE3CC"];
  const bits = Array.from({ length: 50 }, () => {
    const a = (-90 + (Math.random() - 0.5) * 70) * (Math.PI / 180), v = 7 + Math.random() * 6;
    return { x, y, vx: Math.cos(a) * v, vy: Math.sin(a) * v, r: 2.5 + Math.random() * 2.5, col: colours[(Math.random() * colours.length) | 0], life: 0 };
  });
  const t0 = performance.now();
  const frame = (t: number) => {
    const el = t - t0;
    g.clearRect(0, 0, innerWidth, innerHeight);
    for (const b of bits) {
      b.vx *= 0.97; b.vy = b.vy * 0.97 + 0.42; b.x += b.vx; b.y += b.vy;
      g.globalAlpha = Math.max(0, 1 - el / 1500); g.fillStyle = b.col;
      g.beginPath(); g.arc(b.x, b.y, b.r, 0, Math.PI * 2); g.fill();
    }
    if (el < 1500) requestAnimationFrame(frame); else c.remove();
  };
  requestAnimationFrame(frame);
}

/** A rupee amount that counts to its new value when it changes (the server's whole-rupee prices; formatting is the same as everywhere else on the site). */
function AnimatedPrice({ paise }: { paise: number }) {
  const reduced = useReducedMotion();
  const mv = useMotionValue(paise / 100);
  const text = useTransform(mv, (v) => rupees(Math.round(v) * 100));
  useEffect(() => {
    if (reduced) { mv.set(paise / 100); return; }
    const a = animate(mv, paise / 100, { duration: 0.55, ease: [0.22, 1, 0.36, 1] });
    return () => a.stop();
  }, [paise, reduced, mv]);
  return <motion.span className="tabular-nums">{text}</motion.span>;
}

function Switch({ yearly, onChange, savePct }: { yearly: boolean; onChange: (yearly: boolean, el: HTMLElement) => void; savePct: string | null }) {
  const ref = useRef<HTMLButtonElement>(null);
  return (
    <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-2">
      <button type="button" onClick={() => ref.current && yearly && onChange(false, ref.current)} className={clsx("min-h-11 px-1 text-[16px] font-medium tracking-[-.01em] transition-colors", yearly ? "text-m-muted hover:text-m-ink" : "text-m-ink")}>Monthly</button>
      <button ref={ref} type="button" role="switch" aria-checked={yearly} aria-label="Bill yearly" onClick={() => ref.current && onChange(!yearly, ref.current)}
        className={clsx("relative h-[30px] w-[54px] shrink-0 rounded-full p-[3px] transition-colors duration-300", yearly ? "bg-m-accent" : "bg-m-ink/20")}>
        <motion.span aria-hidden className="block h-6 w-6 rounded-full bg-white shadow-[0_1px_3px_rgba(11,15,46,.3)]" animate={{ x: yearly ? 24 : 0 }} transition={{ type: "spring", stiffness: 520, damping: 34 }} />
      </button>
      <button type="button" onClick={() => ref.current && !yearly && onChange(true, ref.current)} className={clsx("min-h-11 px-1 text-[16px] font-medium tracking-[-.01em] transition-colors", yearly ? "text-m-ink" : "text-m-muted hover:text-m-ink")}>
        Yearly{savePct && <span className="ml-2 text-m-accentText">({savePct})</span>}
      </button>
    </div>
  );
}

export function PricingPlans() {
  const { data, failed, loading } = usePlansLive();
  const [billing, setBilling] = useState<Billing>("monthly");
  const wide = useMedia("(min-width: 768px)");
  const [signup, setSignup] = useState(false);
  const reduced = useReducedMotion();
  if (failed) return <TalkToUs />;
  if (loading || !data) return <div className="grid gap-4 md:grid-cols-3" aria-busy>{[0, 1, 2].map((i) => <div key={i} className="h-[560px] animate-pulse rounded-2xl bg-m-surface" />)}</div>;
  const plans = sellablePlans(data.plans, data.terms);
  if (!plans.length) return <TalkToUs />;
  const yearly = billing === "yearly";
  // "Save N%" comes from the list itself (12 months against twelve of the plan's own months); one figure when every plan agrees, a range when they do not
  const pcts = plans.map((p) => yearlySaving(data.terms, p.code)?.percent).filter((v): v is number => typeof v === "number");
  const lo = pcts.length ? Math.min(...pcts) : 0, hi = pcts.length ? Math.max(...pcts) : 0;
  const savePct = pcts.length ? `Save ${lo === hi ? `${lo}%` : `${lo}–${hi}%`}` : null;
  const setYearly = (y: boolean, el: HTMLElement) => {
    setBilling(y ? "yearly" : "monthly");
    if (y) { const r = el.getBoundingClientRect(); confetti(r.left + r.width / 2, r.top + r.height / 2); }
  };
  return (
    <>
      <Switch yearly={yearly} onChange={setYearly} savePct={savePct} />
      <div className="mt-3 min-h-[44px] text-center">
        <p className="text-[15px] text-m-muted" aria-live="polite">{BILLING_NOTE[billing]}</p>
        <p className="mt-1 text-[14px] text-m-muted">{data.trial_days}-day free trial. {trialTerms(data.billing ? !!data.billing.mandate_required : null)}</p>
      </div>
      <div className="mt-10 grid grid-cols-1 gap-4 md:grid-cols-3">
        {plans.map((p, i) => {
          const hot = p.code === "growth";
          const paise = periodPrice(data.terms, p.code, billing) as number;
          const save = yearly ? yearlySaving(data.terms, p.code) : null;
          const side = i === 0 ? 1 : i === plans.length - 1 ? -1 : 0;
          return (
            <motion.div key={p.code} data-plan={p.code} initial={{ y: 40 }}
              whileInView={wide && !reduced ? { y: hot ? -20 : 0, x: side * 14, scale: hot ? 1 : 0.95 } : { y: 0 }} viewport={{ once: true }}
              transition={{ duration: 1.1, type: "spring", stiffness: 100, damping: 26, delay: 0.25 + i * 0.08 }}
              style={{ transformOrigin: side === 1 ? "right center" : side === -1 ? "left center" : "center" }}
              className={clsx("relative flex flex-col rounded-2xl bg-m-surface p-6 text-center md:p-7", hot ? "z-10 border-2 border-m-accent shadow-[var(--shadow-float)]" : "z-0 border border-m-line")}>
              {hot && (
                <span className="absolute right-0 top-0 inline-flex items-center rounded-bl-xl rounded-tr-[14px] bg-m-accent px-2.5 py-1 text-[12.5px] font-semibold text-m-ink">
                  <Star className="mr-1 h-3.5 w-3.5 fill-current" aria-hidden />Recommended
                </span>
              )}
              <h2 className="text-[13px] font-semibold uppercase tracking-[.08em] text-m-muted">{p.name}</h2>
              <p className="mt-6 flex items-baseline justify-center gap-x-2 text-m-ink t-number"><AnimatedPrice paise={paise} /><span className="text-[14px] font-semibold tracking-normal text-m-muted">{BILLING_SUFFIX[billing].replace("/", "/ ")}</span></p>
              <p className="mt-1 text-[12.5px] leading-5 text-m-muted">{yearly ? "billed once for 12 months, no auto-renewal" : "billed monthly"} · + GST as applicable</p>
              <div className="min-h-[44px]">
                {save && <p className="mt-2 text-[13px] leading-snug text-m-ink2">About {rupees(effectiveMonthlyPaise(paise, 12))} a month. {rupees(save.paise)} less than paying monthly for a year.</p>}
              </div>
              <ul className="mt-4 flex flex-col gap-2.5 text-left text-[14.5px]">
                {cardPoints(p).map((pt) => (
                  <li key={pt.text} className="flex items-start gap-2.5">
                    <Check className={clsx("mt-1 h-4 w-4 shrink-0 text-m-accentText", pt.soon && "opacity-40")} strokeWidth={2.25} aria-hidden />
                    <span>{pt.text}{pt.soon && <span className="ml-2 rounded-full bg-m-ink/10 px-2 py-0.5 text-[11px] font-semibold">Coming soon</span>}</span>
                  </li>
                ))}
              </ul>
              <hr className="my-5 border-m-line" />
              <Link href="/register" onClick={(e) => { track("signup_cta_click"); if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey) { e.preventDefault(); setSignup(true); } }}
                className={clsx("group relative inline-flex min-h-12 w-full items-center justify-center overflow-hidden rounded-full text-[17px] font-semibold tracking-[-.02em] transition-all duration-300 ease-out",
                  hot ? "bg-m-accent text-m-ink hover:bg-[#F06000]" : "border border-m-ink/70 bg-m-surface text-m-ink hover:bg-m-accent hover:text-m-ink hover:ring-2 hover:ring-m-accent hover:ring-offset-1")}>
                Start free trial
              </Link>
              <p className="mt-5 text-[12.5px] leading-5 text-m-muted">{POSITION[p.code]}</p>
            </motion.div>
          );
        })}
      </div>
      <SignupDialog open={signup} onClose={() => setSignup(false)} />
      <p className="mx-auto mt-8 max-w-[640px] text-center text-[13px] text-m-muted">AI allowances are monthly. They reset every month, on yearly plans too, and are not added up across the year.</p>
    </>
  );
}

function CellView({ c }: { c: Cell }) {
  if (c.kind === "yes") return <Check className="mx-auto h-4 w-4" strokeWidth={2.25} aria-label="Included" />;
  if (c.kind === "no") return <Minus className="mx-auto h-4 w-4 text-m-muted" strokeWidth={1.75} aria-label="Not included" />;
  return <>{c.text}{c.soon && <span className="mt-1 block"><span className="rounded-full bg-m-ink/10 px-2.5 py-0.5 text-[11.5px] font-semibold">Coming soon</span></span>}</>;
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
