"use client";
import clsx from "clsx";
import { motion, useReducedMotion, useScroll, useTransform, type MotionValue } from "motion/react";
import { Check, Minus } from "lucide-react";
import Image from "next/image";
import { useId, useRef, useState, type ReactNode } from "react";
import { track } from "@/lib/track";
import { Accent, Chip, MButton, SectionHead } from "./kit";
import { HeroBackdrop } from "./Depth";
import { EASE, Rise } from "./motion";

/* ======================================================================= ScrollStatement (05)
   Each word goes from --muted-2 to --ink as it crosses ~60% of the viewport. `{chip}` in the text places the inline icon chip. */
export function ScrollStatement({ text, strong, chip, tight }: { text: string; strong?: string; chip?: ReactNode; tight?: boolean }) {
  const ref = useRef<HTMLParagraphElement>(null);
  const reduced = useReducedMotion();
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start 0.85", "end 0.5"] });
  const tokens = [...text.split(" "), ...(strong ? strong.split(" ").map((w) => `**${w}`) : [])];
  const n = tokens.length;
  return (
    <section className={tight ? "py-14 md:py-20" : "mkt-section"}>
      <div className="mkt-wrap">
        <p ref={ref} className="t-statement mx-auto max-w-[820px] text-center">
          {tokens.map((t, i) => t === "{chip}"
            ? <span key={i} aria-hidden className="mx-1 inline-grid h-[1.1em] w-[1.5em] translate-y-[.12em] place-items-center rounded-[10px] bg-m-tint align-baseline text-m-accentStrong">{chip}</span>
            : <Word key={i} p={scrollYProgress} range={[i / n, (i + 1) / n]} reduced={!!reduced} strong={t.startsWith("**")}>{t.replace(/^\*\*/, "")}</Word>)}
        </p>
      </div>
    </section>
  );
}
function Word({ children, p, range, reduced, strong }: { children: string; p: MotionValue<number>; range: [number, number]; reduced: boolean; strong: boolean }) {
  const color = useTransform(p, range, ["#80849A", strong ? "#C94C00" : "#0B0F2E"]);
  return <motion.span style={{ color: reduced ? (strong ? "#C94C00" : "#0B0F2E") : color }}>{children} </motion.span>;
}

/* ======================================================================= How it works (one row of three numbered steps, above the bento) */
export function HowItWorks({ title, steps }: { title: string; steps: string[] }) {
  return (
    <section aria-labelledby="how-h" className="pb-8 md:pb-10">
      <div className="mkt-wrap">
        <Rise y={20} blur={false} className="mkt-card px-2 py-6 sm:px-8 md:px-12 md:py-8">
          <h2 id="how-h" className="text-center t-small text-m-muted">{title}</h2>
          <ol className="mt-5 grid grid-cols-3 gap-2 sm:gap-4">
            {steps.map((s, i) => (
              <li key={s} className="relative flex flex-col items-center text-center after:absolute after:left-[calc(50%+30px)] after:top-[18px] after:w-[calc(100%-44px)] after:border-t after:border-dashed after:border-m-accent/60 after:content-[''] last:after:hidden sm:after:top-5">
                <span className="relative z-10 grid h-9 w-9 place-items-center rounded-full bg-m-accent text-[15px] font-semibold text-m-ink sm:h-10 sm:w-10">{i + 1}</span>
                <p className="mt-3 max-w-[180px] text-[13px] font-medium leading-snug tracking-[-.01em] text-m-ink sm:text-[16px]">{s}</p>
              </li>
            ))}
          </ol>
        </Rise>
      </div>
    </section>
  );
}

/* ======================================================================= Bento (06) */
export function BentoWide({ chip, title, body, photo, photoAlt, toast }: { chip: ReactNode; title: string; body: string; photo: string; photoAlt: string; toast?: ReactNode }) {
  return (
    <Rise y={24} blur={false} className="mkt-card relative grid overflow-hidden md:grid-cols-[1fr_1.05fr] transition-[transform,box-shadow] duration-300 hover:-translate-y-1 hover:shadow-[var(--shadow-float)]">
      <div className="p-7 md:p-10">
        {chip}
        <h3 className="mt-6 t-h3 text-m-ink">{title}</h3>
        <p className="mt-4 max-w-[400px] text-[15px] text-m-muted">{body}</p>
      </div>
      <div className="relative min-h-[260px]">
        <Image src={photo} alt={photoAlt} fill sizes="(min-width: 768px) 540px, 100vw" className="object-cover" />
        {toast && <motion.div className="absolute right-5 top-5" initial={{ opacity: 0, x: 24 }} whileInView={{ opacity: 1, x: 0 }} viewport={{ once: true }} transition={{ delay: 0.4, duration: 0.6, ease: EASE }}>{toast}</motion.div>}
      </div>
    </Rise>
  );
}

export function BentoCard({ chip, title, body, visual, tone = "white", delay = 0, className }: { chip: ReactNode; title: string; body: string; visual: ReactNode; tone?: "white" | "tint"; delay?: number; className?: string }) {
  return (
    <Rise y={24} blur={false} delay={delay} className={clsx("flex flex-col overflow-hidden rounded-[20px] p-7 transition-[transform,box-shadow] duration-300 hover:-translate-y-1 hover:shadow-[var(--shadow-float)]", tone === "tint" ? "bg-m-tint" : "bg-m-surface shadow-[var(--shadow-card)]", className)}>
      <div>{chip}</div>
      <div className="flex min-h-[250px] flex-1 items-center justify-center py-6">{visual}</div>
      <h3 className="t-h3 text-m-ink">{title}</h3>
      <p className="mt-3 max-w-[420px] text-[15px] text-m-muted">{body}</p>
    </Rise>
  );
}

/* ======================================================================= ComparisonTable (07) */
export type Cell = string | boolean;
export function ComparisonTable({ title, sub, columns, rows, brandIndex = 0, tight }: { title: string; sub?: string; columns: string[]; rows: { feature: string; icon?: ReactNode; cells: Cell[] }[]; brandIndex?: number; tight?: boolean }) {
  const reduced = useReducedMotion();
  const cell = (c: Cell, brand: boolean) => c === true ? <Check className={clsx("mx-auto h-4 w-4", brand ? "text-m-ink" : "text-[#157347]")} strokeWidth={2} aria-label="Yes" /> : c === false ? <Minus className="mx-auto h-4 w-4 text-m-muted2" strokeWidth={1.5} aria-label="No" /> : c;
  return (
    <section className={tight ? "py-12 md:py-16" : "mkt-section"}>
      <div className="mkt-wrap">
        <Rise><SectionHead title={title} sub={sub} /></Rise>
        <ul className="mt-8 space-y-3 md:hidden">
          {rows.map((r) => (
            <li key={r.feature} className="rounded-[16px] bg-m-surface p-4 shadow-[var(--shadow-card)]">
              <p className="flex items-center gap-2.5 text-[15px] font-medium leading-snug text-m-ink">
                {r.icon && <span aria-hidden className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-m-tint text-m-accentStrong">{r.icon}</span>}{r.feature}
              </p>
              <div className="mt-3 flex items-center justify-between gap-3 rounded-[10px] bg-m-accent px-3.5 py-2.5 text-[14px] font-medium text-m-ink">
                <span>{columns[brandIndex]}</span><span className="text-right">{cell(r.cells[brandIndex], true)}</span>
              </div>
              <dl className="mt-2 grid grid-cols-3 gap-2">
                {columns.map((c, i) => i === brandIndex ? null : (
                  <div key={c} className="rounded-[10px] bg-m-tint/60 px-2.5 py-2">
                    <dt className="text-[11px] leading-tight text-m-muted">{c}</dt>
                    <dd className="mt-1 text-[13px] font-medium leading-tight text-m-ink2">{r.cells[i] === true ? "Yes" : r.cells[i] === false ? "No" : r.cells[i]}</dd>
                  </div>
                ))}
              </dl>
            </li>
          ))}
        </ul>
        <div className="relative mt-12 hidden overflow-x-auto pb-4 md:block">
          <table className="w-full min-w-[720px] border-separate border-spacing-0 text-center text-[13px]">
            <thead>
              <tr>
                <th scope="col" className="sticky left-0 z-10 w-[26%] bg-m-bg px-4 pb-4 text-left font-medium text-m-muted">Feature</th>
                {columns.map((c, i) => (
                  <th key={c} scope="col" className={clsx("px-3 pb-4 align-bottom font-medium", i === brandIndex ? "relative text-[15px] text-m-ink" : "text-m-ink2")}>
                    {i === brandIndex && <motion.span aria-hidden className="absolute inset-x-0 -top-2 rounded-t-[14px] bg-m-accent" style={{ bottom: 0 }} initial={{ scaleY: reduced ? 1 : 0.96 }} whileInView={{ scaleY: 1 }} viewport={{ once: true }} transition={{ duration: 0.5, ease: EASE }} />}
                    <span className="relative">{c}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, ri) => (
                <motion.tr key={r.feature} initial={{ opacity: 0 }} whileInView={{ opacity: 1 }} viewport={{ once: true }} transition={{ delay: reduced ? 0 : ri * 0.04 }}>
                  <th scope="row" className={clsx("sticky left-0 z-10 h-14 border-b border-m-line bg-m-bg px-4 text-left font-medium text-m-ink2", ri === 0 && "rounded-tl-[14px]")}>
                    <span className="flex items-center gap-2.5">{r.icon && <span aria-hidden className="grid h-6 w-6 shrink-0 place-items-center rounded-md bg-m-surface text-m-muted">{r.icon}</span>}{r.feature}</span>
                  </th>
                  {r.cells.map((c, i) => (
                    <td key={i} className={clsx("h-14 px-3", i === brandIndex ? "border-b border-white/25 bg-m-accent font-medium text-m-ink" : "border-b border-m-line bg-m-tint/50 text-m-ink2", i === brandIndex && ri === rows.length - 1 && "rounded-b-[14px] border-b-0")}>{cell(c, i === brandIndex)}</td>
                  ))}
                </motion.tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

/* ======================================================================= FAQ (08): the whole row is the button; aria-expanded on it */
export function FAQ({ items, title = "Frequently asked questions", tight }: { items: [string, ReactNode][]; title?: string; tight?: boolean }) {
  const [open, setOpen] = useState<number | null>(null);
  const uid = useId();
  const reduced = useReducedMotion();
  return (
    <section className={tight ? "py-12 md:py-16" : "mkt-section"}>
      <div className="mkt-wrap">
        <Rise><h2 className="t-h2 max-w-[460px] text-m-ink">{title}</h2></Rise>
        <ul className={clsx("space-y-2.5", tight ? "mt-8" : "mt-10")}>
          {items.map(([q, a], i) => (
            <li key={q} className="rounded-[10px] bg-m-surface">
              <button type="button" id={`${uid}-q${i}`} aria-expanded={open === i} aria-controls={`${uid}-a${i}`}
                onClick={() => { const next = open === i ? null : i; setOpen(next); if (next !== null) track("faq_open", { q }); }}
                className="flex min-h-[52px] w-full items-center px-5 py-3 text-left text-[15px] font-medium leading-snug tracking-[-.01em] text-m-ink md:text-[13px]">{q}</button>
              <motion.div id={`${uid}-a${i}`} role="region" aria-labelledby={`${uid}-q${i}`} initial={false} animate={open === i ? { height: "auto", opacity: 1 } : { height: 0, opacity: 0 }}
                transition={{ duration: reduced ? 0.2 : 0.3, ease: EASE }} className="overflow-hidden">
                <div className="max-w-[760px] px-5 pb-5 text-[14px] leading-[1.6] text-m-muted md:text-[13px]">{a}</div>
              </motion.div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

/* ======================================================================= Marquee (09) */
export type MarqueeItem = { kind: "photo"; src: string; alt: string } | { kind: "accent" | "tint"; label: string; title: string; icon?: ReactNode };
export function Marquee({ items }: { items: MarqueeItem[] }) {
  const all = [...items, ...items];
  return (
    <div className="overflow-hidden py-10" style={{ maskImage: "linear-gradient(90deg, transparent, #000 8%, #000 92%, transparent)", WebkitMaskImage: "linear-gradient(90deg, transparent, #000 8%, #000 92%, transparent)" }}>
      <ul className="mkt-marquee flex w-max gap-4">
        {all.map((it, i) => (
          <li key={i} aria-hidden={i >= items.length || undefined} className={clsx("h-[200px] w-[180px] shrink-0 overflow-hidden rounded-[16px] transition-transform duration-300 hover:-translate-y-3 hover:rotate-0", i % 3 === 2 && (i % 2 ? "rotate-[5deg]" : "-rotate-[5deg]"))}>
            {it.kind === "photo"
              ? <Image src={it.src} alt={i >= items.length ? "" : it.alt} width={180} height={200} className="h-full w-full object-cover" />
              : <div className={clsx("flex h-full flex-col justify-between p-4", it.kind === "accent" ? "bg-m-accent text-m-ink" : "bg-m-tint text-m-ink")}>
                  <span aria-hidden className="grid h-8 w-8 place-items-center rounded-lg bg-white/70 text-m-accentStrong">{it.icon}</span>
                  <span><span className="block text-[11px] font-medium opacity-70">{it.label}</span><span className="mt-1 block text-[20px] font-medium leading-[1.05] tracking-[-.03em]">{it.title}</span></span>
                </div>}
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ======================================================================= Final CTA (09) */
export function FinalCTA({ line1, line2, primary = "Book a demo", primaryHref = "/demo", secondary = true }: { line1: string; line2: string; primary?: string; primaryHref?: string; secondary?: boolean }) {
  return (
    <section className="relative isolate overflow-hidden pb-24 pt-16 md:pb-32">
      <HeroBackdrop />
      <div className="relative mkt-wrap text-center">
        <Rise><h2 className="t-statement mx-auto max-w-[680px] text-m-ink">{line1}<br /><span className="text-m-muted">{line2}</span></h2></Rise>
        <Rise delay={0.15} className="mx-auto mt-8 flex max-w-[340px] flex-col items-stretch gap-3 sm:max-w-none sm:flex-row sm:flex-wrap sm:items-center sm:justify-center sm:gap-2.5">
          <MButton href={primaryHref} className="w-full justify-between sm:w-auto" event={primaryHref === "/demo" ? "demo_cta_click" : undefined}>{primary}</MButton>
          {secondary && <MButton href="/about#services" variant="secondary" className="w-full justify-center sm:w-auto" sub="Need something custom?">Talk to FlowHQ</MButton>}
        </Rise>
      </div>
    </section>
  );
}

/* ======================================================================= Stepper (a horizontal strip of numbered steps) */
export function Stepper({ title, sub, steps, note }: { title: string; sub?: string; steps: { title: string; body: string; soon?: boolean }[]; note?: ReactNode }) {
  return (
    <section className="mkt-section">
      <div className="mkt-wrap">
        <Rise><SectionHead title={title} sub={sub} /></Rise>
        <ol className={clsx("mt-12 grid gap-3", steps.length > 4 ? "sm:grid-cols-2 lg:grid-cols-4" : "sm:grid-cols-2 lg:grid-cols-4")}>
          {steps.map((s, i) => (
            <Rise as="li" key={s.title} delay={i * 0.06} y={16} blur={false} className="mkt-card p-6 transition-[transform,box-shadow] duration-300 hover:-translate-y-1 hover:shadow-[var(--shadow-float)]">
              <span className="grid h-8 w-8 place-items-center rounded-full bg-m-tint text-[13px] font-semibold text-m-accentStrong">{i + 1}</span>
              <p className="mt-5 text-[17px] font-medium tracking-[-.02em] text-m-ink">{s.title}{s.soon && <span className="ml-2 align-middle"><Chip className="!h-5 !px-2 !text-[10px]">Coming soon</Chip></span>}</p>
              <p className="mt-2 text-[14px] text-m-muted">{s.body}</p>
            </Rise>
          ))}
        </ol>
        {note && <p className="mx-auto mt-8 max-w-[560px] text-center text-[13px] text-m-muted">{note}</p>}
      </div>
    </section>
  );
}

export { Accent };
