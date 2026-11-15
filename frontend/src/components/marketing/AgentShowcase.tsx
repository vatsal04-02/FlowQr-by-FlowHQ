"use client";
import { motion, useInView, useReducedMotion } from "motion/react";
import { BarChart3, Check, ClipboardList, ListChecks, MessageSquareReply, Nfc, Search, Sparkles, Star } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { LogoMark } from "../ui/Brand";
import { MButton, SampleTag } from "./kit";
import { Rise } from "./motion";

/**
 * The GBP AI Manager Agent, one product, on a light warm band: text, six feature tiles and one button on the left; one phone showing a
 * Google search result for the business on the right, with soft shapes and two floating badges behind it. The phone plays its little
 * story (`step` 0..3) once it scrolls into view. Below lg everything stacks.
 */
const I = (Icon: typeof Search) => <Icon className="h-5 w-5" strokeWidth={1.5} aria-hidden />;

const CTA: [string, string] = ["See Google Business", "/google-business"];

/** Two per job (finding, reviews, repeat customers), in column order, so the 3 x 2 grid reads by job. Nothing repeated. */
const TILES: [ReactNode, string, string][] = [
  [I(Search), "Profile check", "Spot what's missing, fix it fast"], [I(Nfc), "Tap or scan", "QR + NFC on one card"], [I(ClipboardList), "Daily plan", "What to do today"],
  [I(MessageSquareReply), "Review replies", "Every review answered, you approve"], [I(Sparkles), "AI Review Assistant", "Their words, said clearly"], [I(ListChecks), "Approvals", "Nothing public without you"],
];

function Tick({ on, children }: { on: boolean; children: ReactNode }) {
  return (
    <motion.li className="flex items-center gap-2.5 text-[13px]" animate={{ opacity: on ? 1 : 0.35 }} transition={{ duration: 0.4 }}>
      <motion.span className="grid h-5 w-5 shrink-0 place-items-center rounded-full" animate={{ backgroundColor: on ? "#157347" : "#E9E6E1", scale: on ? [0.8, 1.1, 1] : 1 }} transition={{ duration: 0.4 }}>
        <Check className="h-3 w-3 text-white" strokeWidth={3} aria-hidden />
      </motion.span>
      {children}
    </motion.li>
  );
}

/** What a customer sees on Google, and the three jobs ticking off underneath it. */
function GbpScreen({ step }: { step: number }) {
  return (
    <div className="px-4 pt-12 text-left">
      <div className="flex items-center gap-2 rounded-full border border-m-line bg-white px-3 py-2 text-[12.5px] text-m-ink"><Search className="h-3.5 w-3.5 text-m-muted" strokeWidth={1.5} aria-hidden />physio near me</div>
      <div className="mt-3 flex gap-4 border-b border-m-line pb-2 text-[11.5px] text-m-muted"><span>All</span><span className="font-medium text-m-accentStrong">Maps</span><span>Images</span></div>
      <div className="mt-3 rounded-[14px] border border-m-line bg-white p-3">
        <div className="flex items-center gap-2.5">
          <span className="grid h-[30px] w-[30px] place-items-center rounded-lg bg-m-navy text-[13px] font-semibold text-white">S</span>
          <span className="leading-tight"><span className="block text-[13px] font-semibold text-m-ink">Sunrise Physio</span><span className="flex items-center gap-1 text-[11px] text-m-muted">4.7 <Star className="h-3 w-3 fill-m-gold text-m-gold" aria-hidden /> · Physiotherapy · Open now</span></span>
        </div>
        <div className="mt-2 grid grid-cols-3 gap-1.5 text-center text-[10.5px] font-medium text-m-ink2">{["Call", "Directions", "Website"].map((t) => <span key={t} className="rounded-full bg-m-bg py-1.5">{t}</span>)}</div>
      </div>
      <p className="mt-4 text-[11px] font-semibold text-m-ink">FlowQR is working on your profile</p>
      <ul className="mt-2 space-y-2.5"><Tick on={step >= 1}>Complete business information</Tick><Tick on={step >= 2}>Post updates and photos</Tick><Tick on={step >= 3}>Reply to every review</Tick></ul>
      <p className="mt-4 text-[10.5px] text-m-muted">You approve anything that goes public.</p>
    </div>
  );
}

function FloatBadge({ children, className, dir = 1 }: { children: ReactNode; className: string; dir?: 1 | -1 }) {
  const reduced = useReducedMotion();
  return (
    <motion.span aria-hidden className={`absolute z-10 grid h-14 w-14 place-items-center rounded-[16px] bg-m-surface text-m-accentStrong shadow-[var(--shadow-float)] ${className}`}
      animate={reduced ? {} : { y: [0, -8 * dir, 0] }} transition={{ duration: 3.4, repeat: Infinity, ease: "easeInOut" }}>{children}</motion.span>
  );
}

export function AgentShowcase({ title, sub }: { title: string; sub: string }) {
  const reduced = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  const seen = useInView(ref, { once: true, amount: 0.3 });
  const [step, setStep] = useState(reduced ? 3 : 0);
  useEffect(() => {
    if (reduced) { setStep(3); return; }
    if (!seen) return;
    const ts = [700, 1900, 3100].map((ms, i) => setTimeout(() => setStep(i + 1), ms));
    return () => ts.forEach(clearTimeout);
  }, [seen, reduced]);
  // The last word of the heading carries the accent colour.
  const cut = title.lastIndexOf(" ");
  return (
    <section id="agents" aria-labelledby="agents-h" className="scroll-mt-24 overflow-hidden bg-m-tint py-14 md:py-24">
      <div className="mkt-wrap">
        <div ref={ref} className="grid items-center gap-12 lg:grid-cols-[1.05fr_.95fr] lg:gap-10">
          <div>
            <Rise y={20} blur={false}>
              <div className="flex items-center gap-3">
                <span className="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-m-surface shadow-[var(--shadow-card)] ring-4 ring-white/60"><LogoMark size={28} /></span>
                <p className="flex items-center gap-1.5 text-[14px] font-medium text-m-ink2"><Sparkles className="h-4 w-4 text-m-accentStrong" strokeWidth={1.5} aria-hidden />by FlowQR</p>
              </div>
              <h2 id="agents-h" className="t-display mt-6 text-m-ink [text-wrap:wrap] max-sm:!text-[length:min(10vw,40px)]">{title.slice(0, cut)} <span className="text-m-accentText">{title.slice(cut + 1)}</span></h2>
              <p className="mt-5 max-w-[560px] text-pretty text-[16px] leading-relaxed text-m-ink2 md:text-[17px]">{sub}</p>
            </Rise>
            <ul className="mt-8 grid grid-cols-2 gap-3 sm:grid-cols-3">
              {TILES.map(([icon, t, d], i) => (
                <Rise as="li" key={t} delay={0.1 + i * 0.05} y={14} blur={false} className="rounded-[16px] bg-m-surface p-4 shadow-[var(--shadow-card)]">
                  <span className="text-m-accentStrong">{icon}</span>
                  <span className="mt-3 block text-[15px] font-medium tracking-[-.01em] text-m-ink">{t}</span>
                  <span className="mt-1 block text-[13px] leading-snug text-m-muted">{d}</span>
                </Rise>
              ))}
            </ul>
            <div className="mt-8"><MButton href={CTA[1]} icon="arrow">{CTA[0]}</MButton></div>
          </div>

          {/* The phone is drawn at 270 x 500 and scaled so its text stays crisp; the wrapper holds the scaled size. */}
          <Rise delay={0.2} y={20} blur={false} className="relative mx-auto w-full max-w-[420px] py-4">
            <span aria-hidden className="absolute left-1/2 top-1/2 h-[380px] w-[380px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-white/70 md:h-[460px] md:w-[460px]" />
            <span aria-hidden className="absolute -right-4 bottom-2 h-[150px] w-[150px] rounded-full bg-m-accent300/35" />
            <span aria-hidden className="absolute left-0 top-10 h-24 w-20 opacity-60 [background-image:radial-gradient(rgba(254,106,5,.55)_1.6px,transparent_1.8px)] [background-size:16px_16px]" />
            <div className="relative mx-auto h-[450px] w-[243px] lg:h-[555px] lg:w-[300px]">
              <div className="absolute left-0 top-0 w-[270px] origin-top-left scale-[.9] rounded-[40px] bg-m-navy p-[8px] shadow-[0_30px_60px_-20px_rgba(11,15,46,.45)] lg:scale-[1.11]">
                <div className="relative h-[500px] overflow-hidden rounded-[33px] bg-white text-m-ink">
                  <span aria-hidden className="absolute left-1/2 top-2.5 z-10 h-[20px] w-[76px] -translate-x-1/2 rounded-full bg-m-navy" />
                  <GbpScreen step={step} />
                  <SampleTag className="absolute bottom-3 left-1/2 -translate-x-1/2" />
                </div>
              </div>
            </div>
            <FloatBadge className="left-2 top-[30%] sm:left-8"><Check className="h-6 w-6" strokeWidth={2} /></FloatBadge>
            <FloatBadge className="right-2 top-[64%] sm:right-8" dir={-1}><BarChart3 className="h-6 w-6" strokeWidth={1.5} /></FloatBadge>
          </Rise>
        </div>
      </div>
    </section>
  );
}
