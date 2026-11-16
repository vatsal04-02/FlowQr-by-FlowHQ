"use client";
import { ArrowDown, ArrowRight, CheckCircle2, Star } from "lucide-react";
import type { ReactNode } from "react";
import { SampleTag } from "./kit";
import { CardRender, Stars } from "./Mockups";
import { Pop, Rise } from "./motion";

/**
 * The home hero's one visual story: [QR card] -> [review page on a phone] -> [review live on Google].
 * --cw (the card width, set by .hero-flow in globals.css) is sized from the viewport height at desktop widths so the whole card
 * sits above the fold; the phone is as tall as the card. Below lg the three steps stack, with a down arrow between them.
 * Every number on the mock screens is sample data and is tagged.
 */
export function HeroFlow({ note, chips, captions }: { note: string; chips: ReactNode[]; captions: [string, string, string] }) {
  return (
    <div className="hero-flow">
      <div className="flex flex-col items-center lg:flex-row lg:items-start lg:justify-center">
        <Step delay={0.45} caption={captions[0]}><CardRender className="!w-[var(--cw)]" /></Step>
        <FlowArrow delay={0.65} />
        <Step delay={0.6} caption={captions[1]}><HeroPhone /></Step>
        <FlowArrow delay={0.8} />
        <Step delay={0.75} caption={captions[2]}><GoogleReview /></Step>
      </div>
      <p className="mx-auto mt-6 max-w-[420px] text-center t-small text-m-ink2">{note}</p>
      <div className="mt-3 flex flex-wrap items-center justify-center gap-2">{chips}</div>
    </div>
  );
}

function Step({ children, caption, delay }: { children: ReactNode; caption: string; delay: number }) {
  return (
    <Rise delay={delay} className="flex flex-col items-center">
      <div className="flex items-center justify-center lg:h-[calc(var(--cw)*1.456)]">{children}</div>
      <p className="mt-3 text-center t-small text-m-muted">{caption}</p>
    </Rise>
  );
}

/** A dashed connector with an arrow chip: right-pointing in the row, down-pointing in the stack. */
function FlowArrow({ delay }: { delay: number }) {
  return (
    <Pop delay={delay} className="flex justify-center py-1 lg:h-[calc(var(--cw)*1.456)] lg:w-20 lg:items-center lg:py-0 xl:w-28">
      <span aria-hidden className="flex flex-col items-center lg:w-full lg:flex-row">
        <span className="h-5 border-l border-dashed border-m-accent/70 lg:h-0 lg:flex-1 lg:border-l-0 lg:border-t" />
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-m-accent text-m-ink shadow-[var(--shadow-card)]">
          <ArrowDown className="h-4 w-4 lg:hidden" strokeWidth={2} /><ArrowRight className="hidden h-4 w-4 lg:block" strokeWidth={2} />
        </span>
        <span className="h-5 border-l border-dashed border-m-accent/70 lg:h-0 lg:flex-1 lg:border-l-0 lg:border-t" />
      </span>
    </Pop>
  );
}

/** The customer's review page, in the real page's words. */
function HeroPhone() {
  return (
    <div className="relative h-[330px] w-[196px] rounded-[30px] bg-m-ink p-[6px] shadow-[0_30px_60px_-20px_rgba(11,15,46,.45)] lg:h-[calc(var(--cw)*1.456)] lg:w-[calc(var(--cw)*.8)]">
      <div className="relative flex h-full flex-col overflow-hidden rounded-[24px] bg-m-bg px-3 pb-2.5 pt-6 text-left">
        <span aria-hidden className="absolute left-1/2 top-1.5 h-[9px] w-9 -translate-x-1/2 rounded-full bg-m-ink" />
        <div className="flex items-center gap-1.5"><span aria-hidden className="grid h-5 w-5 place-items-center rounded-md bg-m-navy text-[10px] font-semibold text-white">S</span><span className="text-[11px] font-semibold text-m-ink">Sunrise Physio</span></div>
        <p className="mt-2.5 text-[14px] font-medium leading-tight tracking-[-.03em] text-m-ink">Share your experience</p>
        <div className="mt-1.5"><Stars n={5} size={15} /></div>
        <div className="mt-2 flex flex-wrap gap-1">{["Friendly staff", "On time", "Explained clearly"].map((t) => <span key={t} className="rounded-full bg-m-navy px-2 py-[3px] text-[9.5px] font-medium text-white">{t}</span>)}</div>
        <div className="mt-2 rounded-[10px] border border-m-line bg-m-tint p-2 text-[10px] leading-snug text-m-ink">The staff were friendly, I was seen on time and everything was explained clearly.</div>
        <p className="mt-1.5 text-[9.5px] font-medium text-m-accentStrong [@media(max-height:760px)]:hidden">Written from your answers · edit freely</p>
        <span className="mt-auto flex h-8 items-center justify-center rounded-[10px] bg-m-navy text-[10px] font-medium text-white">Copy &amp; continue to Google</span>
        <SampleTag className="mt-2 self-center" />
      </div>
    </div>
  );
}

/** The finished review, live on the business's Google profile. */
function GoogleReview() {
  return (
    <div className="w-[240px] rounded-[18px] bg-m-surface p-4 text-left shadow-[var(--shadow-float)] lg:w-[calc(var(--cw)*1.05)] lg:min-w-[215px]">
      <div className="flex items-center gap-2.5">
        <span aria-hidden className="grid h-8 w-8 place-items-center rounded-lg bg-m-navy text-[13px] font-semibold text-white">S</span>
        <span className="leading-tight"><span className="block text-[13px] font-semibold text-m-ink">Sunrise Physio</span><span className="flex items-center gap-1 text-[11px] text-m-ink2">4.7 <Star className="h-3 w-3 fill-m-gold text-m-gold" aria-hidden /> · 124 Google reviews</span></span>
      </div>
      <div className="mt-3.5 border-t border-m-line pt-3.5">
        <div className="flex items-center gap-2"><span aria-hidden className="grid h-6 w-6 place-items-center rounded-full bg-[#D9E4D8] text-[11px] font-semibold text-m-ink2">P</span><span className="text-[12px] font-medium text-m-ink">Priya S.</span><Stars n={5} /></div>
        <p className="mt-2 text-[12px] leading-snug text-m-ink2">The staff were friendly, I was seen on time and everything was explained clearly.</p>
      </div>
      <div className="mt-3 rounded-[12px] bg-m-bg p-2.5">
        <p className="inline-flex items-center gap-1 text-[11px] font-medium text-[#157347]"><CheckCircle2 className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />Replied</p>
        <p className="mt-1 text-[11.5px] leading-snug text-m-ink">Thank you, Priya. We&rsquo;re glad everything was clear, and we look forward to seeing you again.</p>
      </div>
      <div className="mt-2.5 flex justify-end"><SampleTag /></div>
    </div>
  );
}
