"use client";
import clsx from "clsx";
import { useReducedMotion } from "motion/react";
import { BarChart3, CalendarCheck, Clock, MapPin, MessageSquareReply, Nfc, Pause, Play, Search, Star } from "lucide-react";
import { useState, type ReactNode } from "react";
import type { en } from "@/content/marketing/en";
import { StripCardArt, StripInsightsArt, StripReplyArt } from "./HomeVisuals";
import { GoogleG, MButton, SampleTag } from "./kit";
import { Stars } from "./Mockups";
import { Rise } from "./motion";
import { Parallax, ScrollSettle } from "./scroll";

type Home = typeof en.home;
/** One vertical rhythm for the home sections below the hero: 56px on phones, 80px from md. */
const SECTION = "py-14 md:py-20";

/* ======================================================================= G. Local storytelling: people check Google first */
/** A Google-style reviews panel with sample data: one low review nobody has answered, one answered. Illustration only. */
function ReviewScreenshot() {
  return (
    <div className="w-full max-w-[440px] rounded-[18px] bg-m-surface p-4 shadow-[var(--shadow-float)] sm:p-5">
      <div className="flex items-start gap-3">
        <GoogleG size={32} />
        <div className="min-w-0 flex-1 leading-tight">
          <p className="text-[15px] font-semibold text-m-ink">Mithai Mahal</p>
          <p className="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-[13px] text-m-muted"><span className="font-semibold text-m-ink">3.9</span><Stars n={4} size={12} /><span>(218 reviews)</span></p>
        </div>
        <SampleTag />
      </div>
      <div className="mt-3 flex gap-2 text-[12.5px] font-medium">
        <span className="rounded-full bg-m-navy px-3 py-1 text-white">Most relevant</span>
        <span className="rounded-full bg-m-bg px-3 py-1 text-m-ink2">Newest</span>
      </div>

      {/* A low review nobody has answered */}
      <div className="mt-4 rounded-[14px] bg-m-bg p-3.5 ring-2 ring-m-accent/70">
        <div className="flex items-center gap-2.5">
          <span aria-hidden className="grid h-8 w-8 place-items-center rounded-full bg-[#E8D5C4] text-[12px] font-semibold text-m-ink2">R</span>
          <span className="leading-tight"><span className="block text-[14px] font-medium text-m-ink">Rohit M.</span><span className="block text-[12px] text-m-muted">2 weeks ago</span></span>
        </div>
        <div className="mt-2 flex items-center gap-2"><Stars n={2} size={13} /></div>
        <p className="mt-1.5 text-[14px] leading-snug text-m-ink">Waited 40 minutes at the counter on Sunday. Nobody even said sorry.</p>
        <p className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-m-accent px-2.5 py-1 text-[12px] font-semibold text-m-ink"><Clock className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />No reply from the owner yet</p>
      </div>

      {/* A happy review with the owner's reply */}
      <div className="mt-3 rounded-[14px] bg-m-bg p-3.5">
        <div className="flex items-center gap-2.5">
          <span aria-hidden className="grid h-8 w-8 place-items-center rounded-full bg-[#D9E4D8] text-[12px] font-semibold text-m-ink2">A</span>
          <span className="leading-tight"><span className="block text-[14px] font-medium text-m-ink">Anita V.</span><span className="block text-[12px] text-m-muted">3 weeks ago</span></span>
        </div>
        <div className="mt-2 flex items-center gap-2"><Stars n={5} size={13} /></div>
        <p className="mt-1.5 text-[14px] leading-snug text-m-ink">Fresh kaju katli and quick billing. Packing was neat.</p>
        <div className="mt-2.5 rounded-[10px] border-l-[3px] border-[#157347] bg-m-surface p-2.5">
          <p className="text-[12px] font-semibold text-m-ink2">Response from the owner</p>
          <p className="mt-0.5 text-[13.5px] leading-snug text-m-ink">Thank you, Anita! We&rsquo;re happy you liked the kaju katli. Please visit us again.</p>
        </div>
      </div>
    </div>
  );
}

export function StorySection({ c }: { c: Home["story"] }) {
  return (
    <section aria-labelledby="story-h" className={SECTION}>
      <div className="mkt-wrap">
        <div className="grid items-center gap-10 lg:grid-cols-[1.1fr_.9fr] lg:gap-12">
          <div>
            <Rise>
              <h2 id="story-h" className="t-h2 text-m-ink">{c.title}</h2>
              <p className="mt-5 max-w-[520px] text-[20px] font-medium leading-snug tracking-[-.02em] text-m-ink2 md:text-[22px]">{c.lead}</p>
              <p className="mt-3 max-w-[480px] text-[16px] leading-relaxed text-m-muted">{c.body}</p>
              <div className="mt-7"><MButton href="#how-it-works" variant="secondary">See how it works</MButton></div>
            </Rise>
          </div>

          {/* What they see: a Google-style review panel over a real shopping street */}
          <Rise y={20} blur={false} delay={0.1}>
            <ScrollSettle><div className="relative overflow-hidden rounded-[24px] bg-m-navy px-4 py-6 sm:px-6 sm:py-8">
              <Parallax speed={36} className="absolute -left-16 -top-16 h-64 w-64 rounded-full bg-[radial-gradient(closest-side,rgba(254,106,5,.45),rgba(254,106,5,0))]" />
              <Parallax speed={-30} className="absolute -bottom-20 -right-16 h-72 w-72 rounded-full bg-[radial-gradient(closest-side,rgba(255,178,122,.35),rgba(255,178,122,0))]" />
              <span aria-hidden className="absolute inset-0 opacity-50 [background-image:radial-gradient(rgba(255,255,255,.16)_1px,transparent_1.2px)] [background-size:20px_20px]" />
              <div className="relative flex justify-center"><ReviewScreenshot /></div>
            </div></ScrollSettle>
            <p className="mt-3 text-center text-[13px] text-m-muted">Sample data. An illustration of how reviews can look on Google.</p>
          </Rise>
        </div>
      </div>
    </section>
  );
}

/* ======================================================================= F. Scrolling feature strip */
type Tone = "navy" | "orange" | "white" | "peach";
const TONE: Record<Tone, { card: string; icon: string; body: string }> = {
  navy: { card: "bg-m-navy text-white", icon: "bg-white/12 text-m-accent300", body: "text-white/80" },
  orange: { card: "bg-m-accent text-m-ink", icon: "bg-white/70 text-m-ink", body: "text-m-ink/85" },
  white: { card: "bg-m-surface text-m-ink shadow-[var(--shadow-card)]", icon: "bg-m-tint text-m-accentStrong", body: "text-m-muted" },
  peach: { card: "bg-m-tint2 text-m-ink", icon: "bg-white/70 text-m-accentStrong", body: "text-m-ink2" },
};
const STRIP_ICONS = [Star, MessageSquareReply, Nfc, CalendarCheck, BarChart3, MapPin, Search];
const STRIP_TONES: Tone[] = ["navy", "orange", "white", "peach", "navy", "orange", "white"];
type StripItem = { kind: "card"; i: number } | { kind: "art"; node: ReactNode };
// Feature cards in order, with a drawn illustration between some of them so the rhythm never repeats two like cards side by side (also across the loop seam).
const STRIP: StripItem[] = [
  { kind: "card", i: 0 }, { kind: "card", i: 1 },
  { kind: "art", node: <StripCardArt /> },
  { kind: "card", i: 2 }, { kind: "card", i: 3 },
  { kind: "art", node: <StripReplyArt /> },
  { kind: "card", i: 4 },
  { kind: "art", node: <StripInsightsArt /> },
  { kind: "card", i: 5 }, { kind: "card", i: 6 },
];

export function FeatureStrip({ c }: { c: Home["strip"] }) {
  const [paused, setPaused] = useState(false);
  const reduced = useReducedMotion();
  const cell = (it: StripItem, k: string, dup: boolean) => {
    const base = "h-[216px] shrink-0 overflow-hidden rounded-[20px] transition-transform duration-300 hover:-translate-y-1.5";
    if (it.kind === "art") {
      return <li key={k} aria-hidden className={clsx(base, "relative w-[190px]", dup && "motion-reduce:hidden")}>{it.node}</li>;
    }
    const tone = TONE[STRIP_TONES[it.i]], Icon = STRIP_ICONS[it.i], [t, b] = c.cards[it.i];
    return (
      <li key={k} aria-hidden={dup || undefined} className={clsx(base, "flex w-[270px] flex-col justify-between p-5", tone.card, dup && "motion-reduce:hidden")}>
        <span aria-hidden className={clsx("grid h-10 w-10 place-items-center rounded-xl", tone.icon)}><Icon className="h-5 w-5" strokeWidth={1.5} /></span>
        <span>
          <span className="block text-[21px] font-medium leading-[1.1] tracking-[-.025em]">{t}</span>
          <span className={clsx("mt-2 block text-[14px] leading-snug", tone.body)}>{b}</span>
        </span>
      </li>
    );
  };
  return (
    <section aria-label="What FlowQR gives you" className="py-10 md:py-14">
      <div className="overflow-hidden motion-reduce:overflow-x-auto" style={{ maskImage: "linear-gradient(90deg, transparent, #000 6%, #000 94%, transparent)", WebkitMaskImage: "linear-gradient(90deg, transparent, #000 6%, #000 94%, transparent)" }}>
        <ul className="mkt-marquee flex w-max gap-4 px-4 py-2" style={{ animationPlayState: paused ? "paused" : undefined, animationDuration: "51s" }}>
          {STRIP.map((it, i) => cell(it, `a${i}`, false))}
          {STRIP.map((it, i) => cell(it, `b${i}`, true))}
        </ul>
      </div>
      {!reduced && (
        <div className="mt-3 flex justify-center motion-reduce:hidden">
          <button type="button" aria-pressed={paused} onClick={() => setPaused((p) => !p)} className="inline-flex min-h-11 items-center gap-2 rounded-full px-4 text-[13px] font-medium text-m-muted hover:text-m-ink">
            {paused ? <Play className="h-4 w-4" strokeWidth={1.75} aria-hidden /> : <Pause className="h-4 w-4" strokeWidth={1.75} aria-hidden />}{paused ? c.play : c.pause}
          </button>
        </div>
      )}
    </section>
  );
}
