"use client";
import clsx from "clsx";
import { motion, useReducedMotion, useScroll, useTransform, type MotionValue } from "motion/react";
import { ArrowRight, Check, Minus } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useId, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { track } from "@/lib/track";
import { Accent, Chip, GoogleG, MButton, SectionHead } from "./kit";
import { GrowthCard, ReplyCard } from "./HeroFloaters";
import { TrialNote } from "./TrialNote";
import { HeroBackdrop } from "./Depth";
import { EASE, Rise } from "./motion";
import { Draw, PopIn } from "./scroll";

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

/* ======================================================================= How it works (three connected, numbered cards with a small illustration each) */
export function HowItWorks({ title, sub, steps, art }: { title: string; sub?: string; steps: [string, string][]; art: ReactNode[] }) {
  return (
    <section id="how-it-works" aria-labelledby="how-h" className="scroll-mt-24 py-14 md:py-20">
      <div className="mkt-wrap">
        <Rise><SectionHead id="how-h" title={title} sub={sub} /></Rise>
        <ol className="mt-12 grid gap-8 md:grid-cols-3">
          {steps.map(([t, b], i) => (
            <Rise as="li" key={t} delay={i * 0.12} y={20} blur={false}
              className="relative flex flex-col rounded-[20px] bg-m-surface p-3.5 shadow-[var(--shadow-card)] transition-[transform,box-shadow] duration-300 hover:-translate-y-1 hover:shadow-[var(--shadow-float)]">
              <div className="h-[184px] overflow-hidden rounded-[14px] bg-m-tint">{art[i]}</div>
              <div className="px-2 pb-2 pt-5">
                <span className="inline-flex items-center gap-2 text-[12px] font-semibold uppercase tracking-[.08em] text-m-ink2">Step<span className="grid h-7 w-7 place-items-center rounded-full bg-m-accent text-[13px] tracking-normal text-m-ink">{i + 1}</span></span>
                <h3 className="mt-3 text-[22px] font-medium leading-tight tracking-[-.025em] text-m-ink">{t}</h3>
                <p className="mt-2 text-[15px] leading-relaxed text-m-muted">{b}</p>
              </div>
              {i < steps.length - 1 && (
                <>
                  <Draw delay={0.5 + i * 0.12} className="absolute left-full top-[92px] hidden h-0 w-8 border-t-2 border-dashed border-m-accent md:block" />
                  <PopIn delay={0.8 + i * 0.12} className="absolute left-full top-[92px] z-10 ml-[2px] hidden h-7 w-7 -translate-y-1/2 place-items-center rounded-full bg-m-accent text-m-ink md:grid"><ArrowRight className="h-4 w-4" strokeWidth={2} /></PopIn>
                  <Draw vertical delay={0.5 + i * 0.12} className="absolute left-1/2 top-full h-8 w-0 -translate-x-1/2 border-l-2 border-dashed border-m-accent md:hidden" />
                </>
              )}
            </Rise>
          ))}
        </ol>
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

/* ======================================================================= ComparisonTable (07)
   One compact table at every width (no horizontal scroll, no stacked cards on phones): feature | brand | the others. The brand column is the orange highlight. */
export type Cell = string | boolean;
export function ComparisonTable({ title, sub, columns, rows, brandIndex = 0, tight, note }: { title: string; sub?: string; columns: string[]; rows: { feature: string; icon?: ReactNode; cells: Cell[] }[]; brandIndex?: number; tight?: boolean; note?: string }) {
  const reduced = useReducedMotion();
  const cell = (c: Cell, brand: boolean) => c === true
    ? <>{brand
        ? <span aria-hidden className="mx-auto grid h-6 w-6 place-items-center rounded-full bg-m-accentStrong text-white"><Check className="h-3.5 w-3.5" strokeWidth={3} /></span>
        : <Check className="mx-auto h-5 w-5 text-[#157347]" strokeWidth={2.25} aria-hidden />}<span className="sr-only">Yes</span></>
    : c === false
      ? <><Minus className="mx-auto h-4 w-4 text-m-muted" strokeWidth={1.75} aria-hidden /><span className="sr-only">No</span></>
      : c;
  return (
    <section className={tight ? "py-12 md:py-16" : "mkt-section"}>
      <div className="mkt-wrap">
        <Rise><SectionHead title={title} sub={sub} /></Rise>
        <Rise delay={0.1} y={14} blur={false} className="mt-8 md:mt-10">
          <div className="relative [--f:36%] md:[--f:30%]" style={{ "--n": columns.length, "--bi": brandIndex } as CSSProperties}>
          {/* The FlowQR column is one white card behind the table (a single piece, so its top, sides and corners always line up with the cells), with an orange top edge. */}
          <motion.span aria-hidden className="absolute -top-3 bottom-0 z-0 origin-top rounded-[20px] border border-m-line border-t-[3px] border-t-m-accent bg-white shadow-[0_28px_60px_-28px_rgba(11,15,46,.28),0_2px_6px_rgba(11,15,46,.04)]"
            style={{ left: "calc(var(--f) + var(--bi) * (100% - var(--f)) / var(--n))", width: "calc((100% - var(--f)) / var(--n))" }}
            initial={{ scaleY: reduced ? 1 : 0.94, opacity: reduced ? 1 : 0 }} whileInView={{ scaleY: 1, opacity: 1 }} viewport={{ once: true }} transition={{ duration: 0.6, ease: EASE }} />
          <table className="relative z-[1] w-full table-fixed border-separate border-spacing-0 text-center text-[13px] md:text-[14px]">
            <caption className="sr-only">{title}</caption>
            <thead>
              <tr>
                <th scope="col" className="w-[36%] px-1 pb-3 text-left text-[12px] font-medium text-m-muted sm:px-4 md:w-[30%] md:text-[13px]">Feature</th>
                {columns.map((c, i) => (
                  <th key={c} scope="col" className={clsx("px-1 pb-3 align-bottom text-[12px] font-medium md:text-[14px]", i === brandIndex ? "text-[14px] font-semibold text-m-ink md:text-[16px]" : "text-m-ink2")}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, ri) => {
                const last = ri === rows.length - 1;
                return (
                  <tr key={r.feature}>
                    <th scope="row" className="h-12 border-b border-m-line px-1 text-left text-[13px] font-medium leading-tight text-m-ink2 sm:px-4 md:h-[52px] md:text-[14px]">
                      <span className="flex items-center gap-2.5">{r.icon && <span aria-hidden className="hidden h-6 w-6 shrink-0 place-items-center rounded-md bg-m-surface text-m-muted md:grid">{r.icon}</span>}{r.feature}</span>
                    </th>
                    {r.cells.map((c, i) => (
                      <td key={i} className={clsx("h-12 px-1 leading-tight md:h-[52px]", i === brandIndex ? clsx("border-b border-m-line font-medium text-m-ink", last && "border-b-0") : "border-b border-m-line text-m-ink2", last && i !== brandIndex && "border-b-0")}>{cell(c, i === brandIndex)}</td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
          </div>
        </Rise>
        {note && <p className="mx-auto mt-4 max-w-[640px] text-center text-[12.5px] leading-relaxed text-m-muted md:text-[13px]">{note}</p>}
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
const CLOSE_POINTS = ["Every Google review and reply in one inbox", "AI drafts the reply, you approve it", "QR and NFC cards for your counter"];

/**
 * The closing call to action: one large navy panel. Left: the closing line, three plain points (the same facts as the rest of the page), the two buttons and the trial terms. Right: two small pieces of the
 * product (a drafted reply waiting for approval, and the Growth score, marked as sample data) floating over a warm glow, with a "Google Business Profile, connected" pill. Used at the foot of every public page.
 */
export function FinalCTA({ line1, line2, primary = "Sign up", primaryHref = "/register", secondary = true }: { line1: string; line2: string; primary?: string; primaryHref?: string; secondary?: boolean }) {
  return (
    <section className="relative px-3 pb-6 pt-10 sm:px-5 md:pb-8 md:pt-14">
      <Rise y={24} blur={false}>
        <div className="relative isolate mx-auto max-w-[1180px] overflow-hidden rounded-[28px] bg-m-navy px-6 py-10 text-white sm:px-10 md:rounded-[36px] md:px-14 md:py-16">
          <div aria-hidden className="pointer-events-none absolute -right-24 -top-24 -z-10 h-[520px] w-[520px] rounded-full bg-[radial-gradient(closest-side,rgba(254,106,5,.42),rgba(254,106,5,0))]" />
          <div aria-hidden className="pointer-events-none absolute -bottom-40 left-[20%] -z-10 h-[420px] w-[420px] rounded-full bg-[radial-gradient(closest-side,rgba(255,178,122,.16),rgba(255,178,122,0))]" />
          <div aria-hidden className="pointer-events-none absolute inset-0 -z-10 opacity-[.5]" style={{ backgroundImage: "radial-gradient(rgba(255,255,255,.10) 1px, transparent 1px)", backgroundSize: "26px 26px", maskImage: "linear-gradient(90deg, #000, transparent 70%)", WebkitMaskImage: "linear-gradient(90deg, #000, transparent 70%)" }} />
          <div className="grid items-center gap-10 lg:grid-cols-[1.05fr_1fr] lg:gap-6">
            <div>
              <h2 className="t-h2 max-w-[560px] text-white">{line1} <span className="text-m-accent300">{line2}</span></h2>
              <ul className="mt-6 space-y-2.5">
                {CLOSE_POINTS.map((t) => (
                  <li key={t} className="flex items-start gap-3 text-[15px] leading-snug text-white/80 md:text-[16px]">
                    <span aria-hidden className="mt-[2px] grid h-5 w-5 shrink-0 place-items-center rounded-full bg-m-accent text-m-ink"><Check className="h-3 w-3" strokeWidth={3} /></span>{t}
                  </li>
                ))}
              </ul>
              <div className="mt-8 flex flex-col items-stretch gap-3 sm:flex-row sm:flex-wrap sm:items-center sm:gap-2.5">
                <MButton href={primaryHref} className="w-full justify-center sm:w-auto" event={primaryHref === "/register" ? "signup_cta_click" : undefined}>{primary}</MButton>
                {secondary && <Link href="/login" className="inline-flex min-h-11 w-full items-center justify-center rounded-full border border-white/40 px-5 text-[14px] font-normal tracking-[-.01em] text-white transition-colors duration-200 hover:bg-white/10 focus-visible:!outline-white sm:w-auto">Log in</Link>}
              </div>
              {primaryHref === "/register" && <TrialNote className="mt-4 text-[14px] text-white/60" />}
            </div>

            <div aria-hidden className="relative mx-auto h-[250px] w-full max-w-[420px] sm:h-[330px] lg:h-[340px] lg:max-w-none">
              <div className="fc-float absolute left-0 top-0 w-[84%] max-w-[300px] sm:left-[4%]" style={{ "--fd": "7.5s", "--fl": "0s", "--fr": "0.4deg" } as CSSProperties}><ReplyCard /></div>
              <div className="fc-float absolute bottom-0 right-0 w-[64%] max-w-[240px] sm:right-[6%]" style={{ "--fd": "8.5s", "--fl": "-2s", "--fr": "-0.5deg" } as CSSProperties}><GrowthCard /></div>
              <div className="fc-float absolute left-[6%] top-[58%] hidden lg:block" style={{ "--fd": "6.5s", "--fl": "-1s", "--fr": "0.6deg" } as CSSProperties}>
                <span className="inline-flex items-center gap-2 rounded-full bg-white/95 py-1.5 pl-1.5 pr-3.5 text-[12.5px] font-medium text-m-ink shadow-[0_18px_36px_-16px_rgba(0,0,0,.5)]"><GoogleG size={26} />Google Business Profile<span className="h-1.5 w-1.5 rounded-full bg-[#157347]" /></span>
              </div>
            </div>
          </div>
        </div>
      </Rise>
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
