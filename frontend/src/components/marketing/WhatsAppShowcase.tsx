"use client";
import { motion, useInView, useReducedMotion } from "motion/react";
import { ArrowRight, BarChart3, Bot, CalendarCheck, CalendarClock, Check, CheckCheck, Megaphone, ShieldCheck, Sparkles } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { en } from "@/content/marketing/en";
import { track } from "@/lib/track";
import { LogoMark } from "../ui/Brand";
import { SampleTag, SoonChip, WhatsAppLogo } from "./kit";
import { Rise } from "./motion";
import { Parallax, ScrollSettle } from "./scroll";

/**
 * The WhatsApp Marketing AI Agent, on a light green band. It is the sibling of AgentShowcase (the GBP AI Agent): text, six tiles and one button on the left, one phone on the
 * right with two floating badges and a soft circle behind it. Below lg everything stacks. Copy lives in content/marketing/en.ts (`whatsapp`); colours are the `--wa-*` tokens in
 * globals.css. Nothing here says the product is live, official, verified or approved by Meta: it is built but switched off, the two "soon" tiles are not built, and the phone is sample data.
 * `as` is "h1" on the page of its own and "h2" where it sits on the home page below the GBP band.
 */
const c = en.whatsapp;
const ICONS = [Megaphone, CalendarClock, Bot, CalendarCheck, ShieldCheck, CheckCheck];
const green = "text-[color:var(--wa-green)]";

function Tick({ on, children }: { on: boolean; children: ReactNode }) {
  return (
    <li className="flex items-center gap-2.5 text-[12.5px] leading-snug">
      <motion.span className="grid h-5 w-5 shrink-0 place-items-center rounded-full" animate={{ backgroundColor: on ? "#128C4A" : "#E9E6E1", scale: on ? [0.8, 1.1, 1] : 1 }} transition={{ duration: 0.4 }}>
        <Check className="h-3 w-3 text-white" strokeWidth={3} aria-hidden />
      </motion.span>
      {children}
    </li>
  );
}

/** The sample chat, and the three jobs ticking off underneath it. */
function ChatScreen({ step }: { step: number }) {
  const ch = c.chat;
  return (
    <div className="flex h-full flex-col px-3.5 pb-9 pt-11 text-left">
      <div className="flex items-center gap-2.5 border-b border-m-line pb-2.5">
        <span aria-hidden className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-m-navy text-[13px] font-semibold text-white">{ch.initial}</span>
        <span className="min-w-0 leading-tight"><span className="block text-[13px] font-semibold text-m-ink">{ch.name}</span><span className="block text-[10.5px] text-m-muted">{ch.role}</span></span>
      </div>
      <ul className="mt-3 flex flex-col gap-1.5">
        {ch.messages.map(([who, text], i) => (
          <li key={i} className={`max-w-[84%] rounded-[14px] px-3 py-2 text-[11.5px] leading-[1.4] text-m-ink ${who === "in" ? "self-start rounded-bl-[4px] bg-[color:var(--wa-bubble-in)]" : "self-end rounded-br-[4px] bg-[color:var(--wa-bubble)]"}`}>{text}</li>
        ))}
      </ul>
      <div className="mt-auto border-t border-m-line pt-2.5">
        <p className="text-[11px] font-semibold text-m-ink">{ch.working}</p>
        <ul className="mt-2 space-y-1.5">{ch.checks.map((t, i) => <Tick key={t} on={step >= i + 1}>{t}</Tick>)}</ul>
        <p className="mt-2.5 text-[10.5px] text-m-muted">{ch.approve}</p>
      </div>
    </div>
  );
}

function FloatBadge({ children, className, dir = 1 }: { children: ReactNode; className: string; dir?: 1 | -1 }) {
  const reduced = useReducedMotion();
  return (
    <motion.span aria-hidden className={`absolute z-10 grid h-14 w-14 place-items-center rounded-[16px] bg-m-surface shadow-[var(--shadow-float)] ${green} ${className}`}
      animate={reduced ? {} : { y: [0, -8 * dir, 0] }} transition={{ duration: 3.4, repeat: Infinity, ease: "easeInOut" }}>{children}</motion.span>
  );
}

export function WhatsAppShowcase({ as = "h2", learnMoreHref }: { as?: "h1" | "h2"; learnMoreHref?: string }) {
  const Heading = as;
  const reduced = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  const seen = useInView(ref, { once: true, amount: 0.3 });
  const [step, setStep] = useState(reduced ? 3 : 0);
  useEffect(() => {
    if (reduced) { setStep(3); return; }
    if (!seen) return;
    const ts = [900, 2100, 3300].map((ms, i) => setTimeout(() => setStep(i + 1), ms));
    return () => ts.forEach(clearTimeout);
  }, [seen, reduced]);
  return (
    <section id="whatsapp-agent" aria-labelledby="wa-agent-h" className={`scroll-mt-24 overflow-hidden bg-[linear-gradient(180deg,var(--wa-wash-top),var(--wa-wash-bottom))] ${as === "h1" ? "pb-14 pt-8 md:pb-24 md:pt-10" : "py-14 md:py-24"}`}>
      <div className="mkt-wrap">
        <div ref={ref} className="grid items-center gap-12 lg:grid-cols-[1.15fr_.85fr] lg:gap-10">
          <div className="flex flex-col">
            <Rise y={20} blur={false}>
              <div className="flex items-center gap-3">
                <span className="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-m-surface shadow-[var(--shadow-card)] ring-4 ring-white/60"><LogoMark size={28} /></span>
                <p className="flex items-center gap-1.5 text-[14px] font-medium text-m-ink2"><Sparkles className={`h-4 w-4 ${green}`} strokeWidth={1.5} aria-hidden />by FlowQR</p>
                <SoonChip />
              </div>
              <Heading id="wa-agent-h" className="t-display mt-6 text-m-ink [text-wrap:wrap] !text-[length:clamp(32px,3.7vw,54px)] max-sm:!text-[length:min(9.4vw,38px)]">
                <WhatsAppLogo size="0.82em" className="mr-[.22em] translate-y-[-.06em] align-middle shadow-[var(--shadow-card)]" />
                WhatsApp Marketing{" "}<br />AI <span className={green}>Agent</span>
              </Heading>
              <p className="mt-5 max-w-[560px] text-pretty text-[16px] leading-relaxed text-m-ink2 md:text-[17px]">{c.sub}</p>
            </Rise>
            <div className="order-2 mt-8 flex flex-wrap items-center gap-x-6 gap-y-2 lg:order-3">
              <Link href={c.ctaHref} onClick={() => track("signup_cta_click")}
                className="group inline-flex min-h-11 items-center gap-2 rounded-full bg-[color:var(--wa-cta)] px-5 text-[14px] font-normal tracking-[-.01em] text-white transition-colors duration-200 hover:bg-[color:var(--wa-cta-hover)]">
                {c.cta}<ArrowRight aria-hidden className="h-4 w-4 transition-transform duration-300 group-hover:translate-x-[3px]" strokeWidth={1.75} />
              </Link>
              {learnMoreHref && <Link href={learnMoreHref} className="inline-flex min-h-11 items-center text-[14px] font-medium text-m-ink underline decoration-m-ink/30 underline-offset-4 hover:decoration-m-ink">{c.learnMore}</Link>}
            </div>
            <ul className="order-3 mt-8 grid grid-cols-2 gap-3 lg:order-2 lg:grid-cols-3">
              {c.tiles.map((t, i) => { const Icon = ICONS[i]; return (
                <Rise as="li" key={t.title} delay={0.1 + i * 0.05} y={14} blur={false} className="relative rounded-[16px] bg-m-surface p-4 shadow-[var(--shadow-card)]">
                  <span className={green}><Icon className="h-5 w-5" strokeWidth={1.5} aria-hidden /></span>
                  {t.soon && <SoonChip className="absolute right-3 top-3" />}
                  <span className="mt-3 block text-[15px] font-medium tracking-[-.01em] text-m-ink">{t.title}</span>
                  <span className="mt-1 block text-[13px] leading-snug text-m-muted">{t.body}</span>
                </Rise>
              ); })}
            </ul>
          </div>

          {/* The phone is drawn at 270 x 500 and scaled so its text stays crisp; the wrapper holds the scaled size (same frame as the GBP phone). */}
          <Rise delay={0.2} y={20} blur={false} className="relative mx-auto w-full max-w-[420px] py-4">
            <ScrollSettle from={0.95}>
            <span aria-hidden className="absolute left-1/2 top-1/2 h-[380px] w-[380px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-[color:var(--wa-circle)] md:h-[460px] md:w-[460px]" />
            <div role="group" aria-label="Example WhatsApp chat on a phone (sample data)" className="relative mx-auto h-[450px] w-[243px] lg:h-[555px] lg:w-[300px]">
              <div className="absolute left-0 top-0 w-[270px] origin-top-left scale-[.9] rounded-[40px] bg-m-navy p-[8px] shadow-[0_30px_60px_-20px_rgba(11,15,46,.45)] lg:scale-[1.11]">
                <div data-ui className="relative h-[500px] overflow-hidden rounded-[33px] bg-white text-m-ink">
                  <span aria-hidden className="absolute left-1/2 top-2.5 z-10 h-[20px] w-[76px] -translate-x-1/2 rounded-full bg-m-navy" />
                  <ChatScreen step={step} />
                  <SampleTag className="absolute bottom-3 left-1/2 -translate-x-1/2" />
                </div>
              </div>
            </div>
            <Parallax speed={26} className="pointer-events-none absolute inset-0"><FloatBadge className="left-2 top-[30%] sm:left-8"><Check className="h-6 w-6" strokeWidth={2} /></FloatBadge></Parallax>
            <Parallax speed={-26} className="pointer-events-none absolute inset-0"><FloatBadge className="right-2 top-[64%] sm:right-8" dir={-1}><BarChart3 className="h-6 w-6" strokeWidth={1.5} /></FloatBadge></Parallax>
            </ScrollSettle>
          </Rise>
        </div>
        <p className="mt-10 max-w-[36em] text-[13px] leading-relaxed text-m-muted">{c.fine}</p>
      </div>
    </section>
  );
}
