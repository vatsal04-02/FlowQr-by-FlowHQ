"use client";
import clsx from "clsx";
import { animate, motion, useMotionValue, useReducedMotion, useTransform } from "motion/react";
import { Check } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { rupees } from "@/lib/billing";

/** Matches a CSS media query, false on the server and until the browser says otherwise (so the markup is the same for everyone on first render). */
export function useMedia(query: string) {
  const [on, setOn] = useState(false);
  useEffect(() => {
    const m = window.matchMedia(query), f = () => setOn(m.matches);
    f(); m.addEventListener("change", f);
    return () => m.removeEventListener("change", f);
  }, [query]);
  return on;
}

/** A rupee amount that counts to its new value when it changes (the server's whole-rupee prices; formatting is the same as everywhere else on the site). */
export function AnimatedPrice({ paise }: { paise: number }) {
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

/** The big call-to-action on a plan card: filled orange on the recommended plan, outlined on the others. */
export const tileButtonClass = (hot: boolean) => clsx(
  "group relative inline-flex min-h-12 w-full items-center justify-center overflow-hidden rounded-full text-[17px] font-semibold tracking-[-.02em] transition-all duration-300 ease-out disabled:pointer-events-none disabled:opacity-55",
  hot ? "bg-m-accent text-m-ink hover:bg-[#F06000]" : "border border-m-ink/70 bg-m-surface text-m-ink hover:bg-m-accent hover:text-m-ink hover:ring-2 hover:ring-m-accent hover:ring-offset-1");

/** On a phone a card shows this many features and folds the rest behind a button; from md up the whole list is open. */
const PHONE_POINTS = 5;

/**
 * One plan card. The single design for the public pricing section (components/marketing/PricingPlans.tsx) and the signed-in billing page (components/billing/BillingPlans.tsx): the recommended
 * card raised with an accent border and a badge, the outer cards a little smaller and tucked toward it on a wide screen. It only draws what it is given; every price and feature comes from the caller.
 * It uses the marketing colour tokens (m-*), which exist inside a `.mkt` element.
 */
export function PlanTile({ code, name, hot, index, count, wide, badge, paise, suffix, fine, extra, points, cta, below, footnote, className }: {
  code: string; name: string; hot: boolean; index: number; count: number; wide: boolean;
  badge?: ReactNode; paise: number; suffix: string; fine: string; extra?: ReactNode;
  points: { text: string; soon?: boolean }[]; cta: ReactNode; below?: ReactNode; footnote?: string; className?: string;
}) {
  const reduced = useReducedMotion();
  const [open, setOpen] = useState(false);
  const side = index === 0 ? 1 : index === count - 1 ? -1 : 0;
  return (
    <motion.div data-plan={code} initial={{ y: 40 }}
      whileInView={wide && !reduced ? { y: hot ? -20 : 0, x: side * 14, scale: hot ? 1 : 0.95 } : { y: 0 }} viewport={{ once: true }}
      transition={{ duration: 1.1, type: "spring", stiffness: 100, damping: 26, delay: 0.25 + index * 0.08 }}
      style={{ transformOrigin: side === 1 ? "right center" : side === -1 ? "left center" : "center" }}
      className={clsx("relative flex flex-col rounded-2xl bg-m-surface p-5 text-center sm:p-6 md:p-7", hot ? "z-10 border-2 border-m-accent shadow-[var(--shadow-float)]" : "z-0 border border-m-line", className)}>
      {badge}
      <h2 className="text-[13px] font-semibold uppercase tracking-[.08em] text-m-muted">{name}</h2>
      <p className="mt-5 flex flex-wrap items-baseline justify-center gap-x-2 text-m-ink t-number md:mt-6"><AnimatedPrice paise={paise} /><span className="text-[14px] font-semibold tracking-normal text-m-muted">{suffix}</span></p>
      <p className="mt-1 text-[12.5px] leading-5 text-m-muted">{fine}</p>
      <div className="min-h-[44px]">{extra}</div>
      <ul className="mt-4 flex flex-col gap-2.5 text-left text-[14.5px]">
        {points.map((pt, i) => (
          <li key={pt.text} className={clsx("items-start gap-2.5", i >= PHONE_POINTS && !open ? "hidden md:flex" : "flex")}>
            <Check className={clsx("mt-1 h-4 w-4 shrink-0 text-m-accentText", pt.soon && "opacity-40")} strokeWidth={2.25} aria-hidden />
            <span className="min-w-0">{pt.text}{pt.soon && <span className="ml-2 rounded-full bg-m-ink/10 px-2 py-0.5 text-[11px] font-semibold">Coming soon</span>}</span>
          </li>
        ))}
      </ul>
      {points.length > PHONE_POINTS && (
        <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)} className="mt-3 inline-flex min-h-11 items-center justify-center self-start text-[14px] font-semibold text-m-accentText underline-offset-4 hover:underline md:hidden">
          {open ? "Show less" : `Show all ${points.length} features`}
        </button>
      )}
      <hr className="my-5 border-m-line" />
      {cta}
      {below}
      {footnote && <p className="mt-5 text-[12.5px] leading-5 text-m-muted">{footnote}</p>}
    </motion.div>
  );
}
