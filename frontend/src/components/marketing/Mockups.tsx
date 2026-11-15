"use client";
import clsx from "clsx";
import { animate, motion, useInView, useReducedMotion } from "motion/react";
import { ArrowDown, ArrowRight, Check, CheckCircle2, Clock, Mic, PenLine, Smile, Star, X } from "lucide-react";
import Image from "next/image";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Poster } from "./Poster";
import { SampleTag, SoonChip } from "./kit";
import { EASE } from "./motion";

/* Every mockup here is an illustrated FlowQR screen with sample numbers, tagged "Sample data". Business names are fictional. */

export function CountUp({ to, format = (n) => String(Math.round(n)), className }: { to: number; format?: (n: number) => string; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const seen = useInView(ref, { once: true, amount: 0.6 });
  const reduced = useReducedMotion();
  const [v, setV] = useState(reduced ? to : 0);
  useEffect(() => {
    if (!seen) return;
    if (reduced) { setV(to); return; }
    const c = animate(0, to, { duration: 1.2, ease: EASE, onUpdate: setV });
    return () => c.stop();
  }, [seen, to, reduced]);
  return <span ref={ref} className={className}>{format(v)}</span>;
}

/** A line that draws itself in (stroke-dashoffset), used for sparklines and arcs. */
function DrawPath({ d, stroke, width = 3, delay = 0.4, className }: { d: string; stroke: string; width?: number; delay?: number; className?: string }) {
  const reduced = useReducedMotion();
  return <motion.path d={d} fill="none" stroke={stroke} strokeWidth={width} strokeLinecap="round" className={className}
    initial={{ pathLength: reduced ? 1 : 0 }} whileInView={{ pathLength: 1 }} viewport={{ once: true }} transition={{ duration: reduced ? 0 : 1.2, ease: EASE, delay }} />;
}

/* ---------------------------------------------------------------- Home hero card */
export function HomeHeroCard() {
  return (
    <div className="relative w-[248px] sm:w-[268px]">
      <div className="absolute -left-14 top-[22px] z-10 inline-flex items-center rounded-full bg-m-navy p-[3px] pl-3 text-[11.5px] font-medium text-white shadow-[var(--shadow-float)]">
        This month <span className="ml-2 rounded-full bg-white px-2.5 py-1 text-m-ink">Nov</span>
      </div>
      <div className="relative overflow-hidden rounded-[18px] bg-m-surface p-5 pb-5 shadow-[var(--shadow-card)]">
        <svg viewBox="0 0 220 96" className="h-[96px] w-full" aria-hidden>
          <defs><linearGradient id="hc-g" x1="0" x2="1"><stop offset="0" stopColor="#FFB27A" /><stop offset="1" stopColor="#FE6A05" /></linearGradient></defs>
          {[24, 48, 72].map((y) => <line key={y} x1="0" x2="220" y1={y} y2={y} stroke="#E9E6E1" strokeDasharray="2 4" />)}
          <DrawPath d="M10 82 C40 82 52 40 78 52 S118 88 140 56 S170 22 196 14" stroke="url(#hc-g)" width={4} />
          <motion.path d="M184 8 L198 12 L190 25" fill="none" stroke="#FE6A05" strokeWidth={4} strokeLinecap="round" strokeLinejoin="round" initial={{ opacity: 0 }} whileInView={{ opacity: 1 }} viewport={{ once: true }} transition={{ delay: 1.4 }} />
        </svg>
        <p className="mt-3 t-number text-m-ink">+<CountUp to={18} /></p>
        <p className="mt-2 max-w-[150px] text-[13px] leading-snug text-m-muted">New Google reviews this month</p>
        <span className="absolute bottom-5 right-5 h-11 w-11 overflow-hidden rounded-full ring-4 ring-m-tint">
          <Image src="/marketing/owner-avatar.jpg" alt="" width={88} height={88} className="h-full w-full object-cover" />
        </span>
        <SampleTag className="absolute right-3 top-3" />
      </div>
      <div className="mt-2.5 flex items-center gap-3 rounded-[14px] bg-m-surface p-3 shadow-[var(--shadow-card)]">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-m-tint text-m-accentStrong" aria-hidden><Smile className="h-4 w-4" strokeWidth={1.5} /></span>
        <span className="text-left leading-tight"><span className="block text-[12.5px] font-medium text-m-ink">Reply drafted, waiting for you</span><span className="block text-[11.5px] text-m-muted">Approve in one tap</span></span>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- Reviews inbox with an AI draft */
export function InboxCard({ className, compact }: { className?: string; compact?: boolean }) {
  return (
    <div className={clsx("w-[300px] rounded-[18px] bg-m-surface p-4 text-left shadow-[var(--shadow-card)]", className)}>
      <div className="flex items-center justify-between"><p className="text-[13px] font-medium text-m-ink">Reviews</p><SampleTag /></div>
      {!compact && [["Meera D.", 5, "Replied"], ["Arjun S.", 4, "Replied"]].map(([n, r, s]) => (
        <div key={n as string} className="mt-3 flex items-center gap-2.5 border-b border-m-line pb-3">
          <span className="grid h-7 w-7 place-items-center rounded-full bg-[#E8D5C4] text-[11px] font-semibold text-m-ink2">{(n as string)[0]}</span>
          <span className="text-[12px] font-medium text-m-ink">{n}</span>
          <Stars n={r as number} />
          <span className="ml-auto text-[11px] font-medium text-[#157347]">{s}</span>
        </div>
      ))}
      <div className="mt-3 flex items-center gap-2.5">
        <span className="grid h-7 w-7 place-items-center rounded-full bg-[#D9E4D8] text-[11px] font-semibold text-m-ink2">P</span>
        <span className="text-[12px] font-medium text-m-ink">Priya S.</span><Stars n={5} />
        <span className="ml-auto text-[11px] font-medium text-m-accentStrong">Needs reply</span>
      </div>
      <p className="mt-2 text-[12px] text-m-ink2">Seen on time, and everything was explained clearly.</p>
      <div className="mt-3 rounded-[12px] bg-m-bg p-3">
        <p className="text-[10.5px] font-semibold uppercase tracking-[.04em] text-m-accentStrong">AI draft</p>
        <p className="mt-1 text-[12px] leading-snug text-m-ink">Thank you, Priya. We&rsquo;re glad everything was clear, and we look forward to seeing you again.</p>
        <div className="mt-3 flex gap-2">
          <span className="inline-flex h-8 items-center gap-1 rounded-full bg-m-accent px-3 text-[11.5px] font-medium text-m-ink"><Check className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />Approve</span>
          <span className="inline-flex h-8 items-center gap-1 rounded-full border border-m-line bg-m-surface px-3 text-[11.5px] font-medium text-m-ink"><PenLine className="h-3.5 w-3.5" strokeWidth={1.5} aria-hidden />Edit</span>
        </div>
      </div>
    </div>
  );
}

export const Stars = ({ n, size = 11 }: { n: number; size?: number }) => (
  <span role="img" className="inline-flex gap-px" aria-label={`${n} stars`}>{[0, 1, 2, 3, 4].map((i) => <Star key={i} style={{ width: size, height: size }} className={i < n ? "fill-m-gold text-m-gold" : "fill-m-line text-m-line"} aria-hidden />)}</span>
);

/* ---------------------------------------------------------------- The physical card, with an NFC wave */
export function CardRender({ className }: { className?: string }) {
  const reduced = useReducedMotion();
  return (
    <div className={clsx("relative w-[230px]", className)}>
      {[0, 1, 2].map((i) => (
        <motion.span key={i} aria-hidden className="absolute left-[-18px] top-[38%] h-14 w-14 rounded-full border-2 border-m-accent"
          initial={{ opacity: 0, scale: 0.4 }} animate={reduced ? { opacity: 0 } : { opacity: [0, 0.7, 0], scale: [0.4, 1.6, 2.2] }} transition={{ duration: 2.4, repeat: Infinity, delay: i * 0.8, ease: "easeOut" }} />
      ))}
      <div className="-rotate-[3deg]" style={{ filter: "drop-shadow(0 24px 30px rgba(11,15,46,.22))" }}><Poster alt="The FlowQR review card: Review us on Google, a QR code, Tap to Review and Scan to Review." /></div>
    </div>
  );
}

/* ---------------------------------------------------------------- Before / after: the same Google profile, unanswered then answered */
const BA_ROWS: [string, number][] = [["Meera D.", 5], ["Arjun S.", 4], ["Priya S.", 5]];
function ProfilePanel({ after }: { after?: boolean }) {
  const reduced = useReducedMotion();
  return (
    <div className={clsx("flex flex-col rounded-[16px] p-3.5 text-left", after ? "bg-m-surface shadow-[var(--shadow-card)] ring-1 ring-m-accent/50" : "border border-m-line bg-white/70")}>
      <div className="flex items-center justify-between">
        <span className={clsx("inline-flex h-6 items-center rounded-full px-2.5 text-[11px] font-semibold uppercase tracking-[.05em]", after ? "bg-m-accent text-m-ink" : "bg-m-ink/[.08] text-m-ink2")}>{after ? "After" : "Before"}</span>
        <SampleTag />
      </div>
      <div className="mt-3 flex items-center gap-2">
        <span className="grid h-7 w-7 place-items-center rounded-lg bg-m-navy text-[12px] font-semibold text-white" aria-hidden>S</span>
        <span className="leading-tight">
          <span className="block text-[12.5px] font-semibold text-m-ink">Sunrise Physio</span>
          <span className="flex items-center gap-1 text-[11.5px] text-m-ink2">
            {after ? <><span className="font-semibold">4.7</span><Star className="h-3 w-3 fill-m-gold text-m-gold" aria-hidden /> · 124 reviews</> : "3 reviews"}
          </span>
        </span>
      </div>
      <ul className="mt-3 space-y-2">
        {BA_ROWS.map(([n, r]) => (
          <li key={n} className="flex items-center gap-1.5 whitespace-nowrap text-[11px]">
            <span className="font-medium text-m-ink">{n}</span>
            <Stars n={r} size={10} />
            <span className={clsx("ml-auto whitespace-nowrap font-medium", after ? "text-[#157347]" : "text-m-accentStrong")}>{after ? "Replied" : "Needs reply"}</span>
          </li>
        ))}
      </ul>
      <div className="mt-auto pt-3">
        <p className="flex items-center gap-1.5 text-[12px] font-medium text-m-ink">
          {after ? <CheckCircle2 className="h-3.5 w-3.5 text-[#157347]" strokeWidth={2} aria-hidden /> : <X className="h-3.5 w-3.5 text-m-muted" strokeWidth={2} aria-hidden />}
          {after ? "All replied" : "None answered"}
        </p>
        <span className="mt-1.5 block h-1.5 overflow-hidden rounded-full bg-m-line">
          <motion.span className="block h-full rounded-full bg-[#157347]" initial={{ width: after && reduced ? "100%" : "0%" }} whileInView={{ width: after ? "100%" : "0%" }} viewport={{ once: true }} transition={{ duration: 1, ease: EASE, delay: 0.5 }} />
        </span>
      </div>
    </div>
  );
}
export function ProfileBeforeAfter() {
  return (
    <div className="grid w-full max-w-[470px] items-stretch gap-2 lg:grid-cols-[1fr_auto_1fr]">
      <ProfilePanel />
      <span aria-hidden className="grid place-items-center"><span className="grid h-8 w-8 place-items-center rounded-full bg-m-accent text-m-ink"><ArrowDown className="h-4 w-4 lg:hidden" strokeWidth={2} /><ArrowRight className="hidden h-4 w-4 lg:block" strokeWidth={2} /></span></span>
      <ProfilePanel after />
    </div>
  );
}

/* ---------------------------------------------------------------- Today's plan (AI Growth Agent) */
export function PlanCard({ className }: { className?: string }) {
  const tasks: [string, string, "todo" | "wait" | "done"][] = [
    ["Reply to a 3-star review", "Draft ready", "wait"], ["Post a weekend update", "Draft ready", "wait"], ["Add opening hours for Sunday", "Done", "done"],
  ];
  return (
    <div className={clsx("w-[290px] rounded-[18px] bg-m-surface p-4 text-left shadow-[var(--shadow-card)]", className)}>
      <div className="flex items-center justify-between"><p className="text-[13px] font-medium text-m-ink">Today&rsquo;s plan</p><SampleTag /></div>
      <ul className="mt-3 space-y-2">
        {tasks.map(([t, s, k]) => (
          <li key={t} className="flex items-center gap-2.5 rounded-[12px] bg-m-bg px-3 py-2.5">
            <span className={clsx("grid h-5 w-5 shrink-0 place-items-center rounded-full", k === "done" ? "bg-[#157347] text-white" : "border border-m-muted2")}>{k === "done" && <Check className="h-3 w-3" strokeWidth={3} aria-hidden />}</span>
            <span className="min-w-0 flex-1"><span className={clsx("block truncate text-[12px] font-medium", k === "done" ? "text-m-muted line-through" : "text-m-ink")}>{t}</span><span className="block text-[11px] text-m-muted">{s}</span></span>
            {k === "wait" && <span className="rounded-full bg-m-tint px-2 py-0.5 text-[10.5px] font-medium text-m-accentStrong">Approve</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ---------------------------------------------------------------- Arc diagram: one card, every corner of the shop */
export function ArcDiagram() {
  const nodes = ["Counter card", "Table tent", "Poster", "Bill QR", "WhatsApp link", "Staff badge"];
  const reduced = useReducedMotion();
  return (
    <div className="relative mx-auto h-[230px] w-full max-w-[380px]" aria-hidden>
      <svg viewBox="0 0 380 210" className="absolute inset-0 h-full w-full">
        <defs><linearGradient id="arc-g" x1="0" x2="1"><stop offset="0" stopColor="#FE6A05" /><stop offset="1" stopColor="#FFB27A" /></linearGradient></defs>
        <DrawPath d="M30 200 A160 160 0 0 1 350 200" stroke="url(#arc-g)" width={16} delay={0.2} />
        <path d="M80 200 A110 110 0 0 1 300 200" fill="none" stroke="#E9E6E1" strokeDasharray="3 5" />
      </svg>
      {nodes.map((n, i) => {
        const a = Math.PI * (0.88 - (i * 0.76) / (nodes.length - 1));
        const x = 190 + (i % 2 ? 118 : 138) * Math.cos(a), y = 200 - (i % 2 ? 118 : 138) * Math.sin(a);
        return (
          <motion.span key={n} className="absolute -translate-x-1/2 -translate-y-1/2 whitespace-nowrap rounded-full bg-m-surface px-2.5 py-1 text-[11px] font-medium text-m-ink2 shadow-[0_1px_2px_rgba(11,15,46,.08),0_4px_12px_rgba(11,15,46,.06)]"
            style={{ left: `${(x / 380) * 100}%`, top: `${(y / 210) * 100}%` }}
            initial={{ opacity: 0, scale: reduced ? 1 : 0.8 }} whileInView={{ opacity: 1, scale: 1 }} viewport={{ once: true }} transition={{ delay: 0.6 + i * 0.12, duration: 0.4, ease: EASE }}>{n}</motion.span>
        );
      })}
      <div className="absolute bottom-0 left-1/2 flex -translate-x-1/2 flex-col items-center">
        <span className="grid h-12 w-12 place-items-center rounded-full bg-m-navy text-[12px] font-semibold text-white ring-4 ring-m-surface">Shop</span>
        <span className="mt-1 text-[12px] font-medium text-m-ink">Your business</span>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- Phone frame and screens */
export function PhoneFrame({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={clsx("relative w-[260px] rounded-[44px] bg-m-navy p-[9px] shadow-[0_30px_60px_-20px_rgba(11,15,46,.45)]", className)}>
      <div className="relative h-[530px] overflow-hidden rounded-[36px] bg-m-bg">
        <span aria-hidden className="absolute left-1/2 top-2.5 z-20 h-[22px] w-[82px] -translate-x-1/2 rounded-full bg-m-navy" />
        <div className="absolute inset-x-0 top-0 z-10 flex h-11 items-center justify-between px-6 text-[11px] font-semibold text-white"><span>9:41</span><span className="h-2.5 w-5 rounded-[3px] border border-white/80" /></div>
        {children}
      </div>
    </div>
  );
}

const BARS = [3, 5, 4, 7, 6, 9, 8, 11, 10, 13, 12, 15];
export function OverviewScreen() {
  return (
    <>
      <div className="bg-gradient-to-b from-m-accent to-m-accent300 px-5 pb-10 pt-14 text-m-ink">
        <div className="flex items-center gap-2"><span className="grid h-8 w-8 place-items-center rounded-full bg-white/90 text-[12px] font-semibold">S</span><span className="leading-tight"><span className="block text-[12.5px] font-semibold">Sunrise Physio</span><span className="block text-[11px] opacity-80">Indiranagar</span></span></div>
        <p className="mt-4 text-[30px] font-medium leading-none tracking-[-.04em]">4.7 <span className="text-[13px] font-medium tracking-normal">rating</span></p>
        <p className="mt-1 flex items-center gap-2 text-[11.5px] opacity-80">124 Google reviews <SampleTag className="!bg-white/50 !text-m-ink" /></p>
      </div>
      <div className="relative -mt-6 mx-3 rounded-[18px] bg-m-surface p-3 shadow-[var(--shadow-card)]">
        <div className="flex items-center justify-between"><p className="text-[11.5px] font-medium text-m-ink">New reviews</p><SampleTag /></div>
        <div className="mt-3 flex h-[120px] items-end gap-[5px]">{BARS.map((b, i) => <span key={i} className="flex-1 rounded-t-[3px]" style={{ height: `${b * 6.5}%`, background: i > 8 ? "#FE6A05" : "#FFE3CC" }} />)}</div>
      </div>
      <div className="absolute inset-x-0 bottom-6 flex justify-center gap-2">
        {["Reviews", "Posts"].map((t, i) => <span key={t} className={clsx("rounded-full px-4 py-2 text-[11.5px] font-medium", i === 0 ? "bg-m-navy text-white" : "bg-m-surface text-m-ink")}>{t}</span>)}
      </div>
    </>
  );
}

/** The customer's review page, in the real page's words. Voice input is not built, so its button carries "Coming soon". */
export function ReviewPageScreen() {
  return (
    <div className="px-4 pt-14 text-left">
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-2"><span className="grid h-7 w-7 place-items-center rounded-lg bg-m-navy text-[11px] font-semibold text-white">S</span><span className="text-[12px] font-semibold text-m-ink">Sunrise Physio</span></span>
        <span className="flex rounded-full bg-m-surface p-0.5 text-[10.5px] font-medium"><span className="rounded-full bg-m-navy px-2 py-0.5 text-white">EN</span><span className="px-2 py-0.5 text-m-ink">हिं</span></span>
      </div>
      <p className="mt-4 text-[18px] font-medium leading-tight tracking-[-.03em] text-m-ink">Share your experience</p>
      <div className="mt-3"><Stars n={5} size={22} /></div>
      <p className="mt-4 text-[11.5px] font-medium text-m-ink2">What stood out? (optional)</p>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {["Friendly staff", "On time", "Explained clearly", "Clean"].map((t, i) => <span key={t} className={clsx("rounded-full px-2.5 py-1 text-[11px] font-medium", i < 3 ? "bg-m-navy text-white" : "bg-m-surface text-m-ink2")}>{t}</span>)}
      </div>
      <div className="mt-3 rounded-[14px] border border-m-line bg-m-tint p-3 text-[12px] leading-snug text-m-ink">The staff were friendly, I was seen on time and everything was explained clearly.</div>
      <div className="mt-2 flex items-center justify-between">
        <span className="text-[10.5px] font-medium text-m-accentStrong">Written from your answers · edit freely</span>
        <span className="inline-flex items-center gap-1 text-[10.5px] text-m-muted"><Mic className="h-3 w-3" strokeWidth={1.5} aria-hidden /><SoonChip className="!h-4 !px-1.5 !text-[9px]" /></span>
      </div>
      <span className="mt-3 flex h-10 items-center justify-center rounded-[12px] bg-m-navy text-[12px] font-medium text-white">Copy &amp; continue to Google</span>
      <p className="mt-2 text-center text-[10px] text-m-muted">You post it on Google yourself.</p>
    </div>
  );
}

/* ---------------------------------------------------------------- Small UI cards used in orbits, bento and marquee */
export function MiniCard({ icon, title, sub, className, tone = "white" }: { icon?: ReactNode; title: string; sub?: string; className?: string; tone?: "white" | "accent" | "tint" }) {
  return (
    <div className={clsx("rounded-[14px] p-3 text-left shadow-[var(--shadow-float)]", tone === "accent" ? "bg-m-accent text-m-ink" : tone === "tint" ? "bg-m-tint text-m-ink" : "bg-m-surface text-m-ink", className)}>
      {icon && <span aria-hidden className={clsx("mb-2 grid h-7 w-7 place-items-center rounded-lg", tone === "accent" ? "bg-white/70" : "bg-m-tint", "text-m-accentStrong")}>{icon}</span>}
      <p className="text-[12.5px] font-medium leading-tight">{title}</p>
      {sub && <p className="mt-0.5 text-[11px] opacity-70">{sub}</p>}
    </div>
  );
}

export const Icons = { Check, CheckCircle2, Clock, Smile, Star, X };
