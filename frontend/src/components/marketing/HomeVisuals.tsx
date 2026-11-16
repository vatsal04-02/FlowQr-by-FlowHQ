"use client";
import { motion, useReducedMotion } from "motion/react";
import { Check, Link2, Nfc, QrCode, Sparkles, Store, TrendingUp } from "lucide-react";
import { LogoMark } from "../ui/Brand";
import { SampleTag } from "./kit";
import { EASE } from "./motion";
import { Stars } from "./Mockups";
import { Poster } from "./Poster";

/* Illustrations for the home page's step cards and touchpoint cards. Everything here is drawn from the product's own parts (the real poster
   artwork, the review page's wording) or from plain shapes. Names and numbers are fictional and sit under a "Sample" tag where they appear.
   All of it is decorative (aria-hidden); the text next to it carries the meaning. */

/* ---------------------------------------------------------------- Step 1: connect Google */
export function StepConnectArt() {
  const reduced = useReducedMotion();
  return (
    <div aria-hidden className="relative flex h-full items-center justify-center px-3 pb-9">
      <div className="w-[100px] shrink-0 rounded-[14px] bg-m-surface p-3 text-center shadow-[var(--shadow-card)]">
        <span className="mx-auto grid h-10 w-10 place-items-center rounded-xl bg-m-navy"><LogoMark size={24} variant="onDark" /></span>
        <p className="mt-2 text-[12px] font-semibold text-m-ink">FlowQR</p>
      </div>
      <div className="relative mx-1 h-6 w-[44px] shrink-0">
        <motion.span className="absolute left-0 top-1/2 h-0 border-t-2 border-dashed border-m-accent" style={{ width: "100%" }}
          initial={{ scaleX: reduced ? 1 : 0 }} whileInView={{ scaleX: 1 }} viewport={{ once: true }} transition={{ duration: reduced ? 0 : 0.7, ease: EASE, delay: 0.3 }} />
        <motion.span className="absolute left-1/2 top-1/2 grid h-6 w-6 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-m-accent text-m-ink"
          initial={{ scale: reduced ? 1 : 0 }} whileInView={{ scale: 1 }} viewport={{ once: true }} transition={{ duration: reduced ? 0 : 0.4, ease: EASE, delay: 0.8 }}><Link2 className="h-3.5 w-3.5" strokeWidth={2} /></motion.span>
      </div>
      <div className="w-[116px] shrink-0 rounded-[14px] bg-m-surface p-3 shadow-[var(--shadow-card)]">
        <span className="grid h-10 w-10 place-items-center rounded-xl bg-m-tint text-m-accentStrong"><Store className="h-5 w-5" strokeWidth={1.5} /></span>
        <p className="mt-2 text-[12px] font-semibold leading-tight text-m-ink">Your business</p>
        <p className="mt-0.5 text-[10.5px] leading-tight text-m-muted">Google Business Profile</p>
      </div>
      <motion.span className="absolute bottom-3.5 left-1/2 inline-flex h-6 -translate-x-1/2 items-center gap-1 rounded-full bg-[#157347] px-2.5 text-[11px] font-medium text-white"
        initial={{ opacity: 0, y: reduced ? 0 : 6 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: reduced ? 0.2 : 0.4, delay: 1 }}>
        <Check className="h-3 w-3" strokeWidth={3} />Connected
      </motion.span>
    </div>
  );
}

/* ---------------------------------------------------------------- Step 2: the card at the counter, a phone scanning it */
export function StepCounterArt() {
  const reduced = useReducedMotion();
  return (
    <div aria-hidden className="relative h-full overflow-hidden">
      <span className="absolute inset-x-0 bottom-0 h-8 bg-m-navy" />
      <span className="absolute inset-x-0 bottom-8 h-1 bg-m-accent300" />
      <div className="absolute bottom-[36px] left-[16%] w-[70px] -rotate-[4deg]" style={{ filter: "drop-shadow(0 8px 10px rgba(11,15,46,.25))" }}><Poster alt="" className="rounded-[5px]" /></div>
      <motion.span className="absolute bottom-[72px] left-[calc(16%+35px)] h-10 w-10 -translate-x-1/2 rounded-full border-2 border-m-accent"
        animate={reduced ? { opacity: 0 } : { opacity: [0, 0.8, 0], scale: [0.6, 1.5, 1.9] }} transition={{ duration: 2.2, repeat: Infinity, ease: "easeOut" }} />
      <div className="absolute right-[13%] top-4 h-[108px] w-[60px] rotate-[10deg] rounded-[13px] border-[3px] border-m-navy bg-m-surface p-1.5 shadow-[var(--shadow-float)]">
        <span className="mx-auto block h-1 w-5 rounded-full bg-m-navy/80" />
        <span className="mt-2 grid h-[52px] place-items-center rounded-[6px] bg-m-tint"><Nfc className="h-5 w-5 text-m-accentStrong" strokeWidth={1.5} /></span>
        <span className="mt-1.5 block text-center text-[8.5px] font-semibold leading-tight text-m-ink">Review us on Google</span>
        <Stars n={5} size={7} />
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- Step 3: reviews and replies in one place */
export function StepReviewsArt() {
  const rows: [string, number, string, string, boolean][] = [["Anita V.", 5, "Fresh kaju katli, quick billing.", "Replied", true], ["Rohit M.", 3, "Waited long at the counter.", "Reply ready", false]];
  return (
    <div aria-hidden className="relative flex h-full flex-col justify-center gap-2 px-3.5 pt-5">
      <SampleTag className="absolute right-2.5 top-2.5" />
      {rows.map(([n, r, t, s, done], i) => (
        <motion.div key={n} className="rounded-[12px] bg-m-surface p-2.5 shadow-[var(--shadow-card)]" initial={{ opacity: 0, y: 8 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: 0.5, ease: EASE, delay: 0.3 + i * 0.2 }}>
          <div className="flex items-center gap-2">
            <span className="grid h-6 w-6 place-items-center rounded-full bg-[#E8D5C4] text-[10.5px] font-semibold text-m-ink2">{n[0]}</span>
            <span className="text-[11.5px] font-medium text-m-ink">{n}</span><Stars n={r} size={10} />
            <span className={done ? "ml-auto inline-flex items-center gap-1 text-[10.5px] font-medium text-[#157347]" : "ml-auto rounded-full bg-m-tint px-2 py-0.5 text-[10.5px] font-medium text-m-accentStrong"}>{done && <Check className="h-3 w-3" strokeWidth={3} />}{s}</span>
          </div>
          <p className="mt-1.5 truncate text-[11px] text-m-ink2">{t}</p>
        </motion.div>
      ))}
    </div>
  );
}

/* ---------------------------------------------------------------- Feature-strip tiles (190 x 216). Drawn illustrations of the features next to them. */
export function StripCardArt() {
  const reduced = useReducedMotion();
  return (
    <div aria-hidden className="relative grid h-full place-items-center bg-m-tint2">
      {[0, 1].map((i) => (
        <motion.span key={i} className="absolute h-24 w-24 rounded-full border-2 border-m-accent"
          animate={reduced ? { opacity: 0.25, scale: 1 + i * 0.5 } : { opacity: [0, 0.6, 0], scale: [0.6, 1.5, 2] }} transition={{ duration: 2.6, repeat: Infinity, delay: i * 1.3, ease: "easeOut" }} />
      ))}
      <div className="relative w-[96px] rotate-[-5deg]" style={{ filter: "drop-shadow(0 12px 14px rgba(11,15,46,.28))" }}><Poster alt="" className="rounded-[6px]" /></div>
      <span className="absolute bottom-3 left-3 inline-flex h-6 items-center gap-1 rounded-full bg-m-surface px-2.5 text-[11px] font-medium text-m-ink shadow-[var(--shadow-card)]"><Nfc className="h-3 w-3 text-m-accentStrong" strokeWidth={2} />Tap or scan</span>
    </div>
  );
}

export function StripReplyArt() {
  return (
    <div aria-hidden className="flex h-full flex-col justify-center gap-1.5 bg-m-surface px-3 py-3 shadow-[var(--shadow-card)]">
      <SampleTag className="self-end" />
      <div className="rounded-[12px] rounded-tl-[3px] bg-m-bg p-2">
        <p className="flex items-center gap-1.5 text-[11px] font-medium text-m-ink"><Stars n={5} size={9} />Anita V.</p>
        <p className="mt-1 text-[11px] leading-snug text-m-ink2">Fresh kaju katli and quick billing.</p>
      </div>
      <div className="rounded-[12px] rounded-tr-[3px] bg-m-tint p-2">
        <p className="flex items-center gap-1 text-[10px] font-semibold text-m-ink2"><Sparkles className="h-3 w-3 text-m-accentStrong" strokeWidth={1.75} />AI-suggested reply</p>
        <p className="mt-1 text-[11px] leading-snug text-m-ink">Thank you, Anita! Please visit us again.</p>
        <span className="mt-1.5 inline-flex h-6 items-center gap-1 rounded-full bg-m-accent px-2.5 text-[11px] font-medium text-m-ink"><Check className="h-3 w-3" strokeWidth={2.5} />Approve</span>
      </div>
    </div>
  );
}

const STRIP_BARS = [4, 6, 5, 8, 7, 10, 9, 12];
export function StripInsightsArt() {
  return (
    <div aria-hidden className="relative flex h-full flex-col justify-between bg-m-tint2 p-3.5 text-m-ink">
      <div className="flex items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-[12px] font-medium text-m-ink2"><TrendingUp className="h-3.5 w-3.5 text-m-accentStrong" strokeWidth={1.75} />Views</p>
        <SampleTag />
      </div>
      <div className="flex h-[96px] items-end gap-[5px]">
        {STRIP_BARS.map((b, i) => <span key={i} className="flex-1 rounded-t-[3px]" style={{ height: `${b * 7.5}%`, background: i > 5 ? "#FE6A05" : "rgba(17,23,63,.22)" }} />)}
      </div>
      <p className="flex gap-3 text-[11px] text-m-ink2"><span className="inline-flex items-center gap-1"><QrCode className="h-3 w-3" strokeWidth={1.75} />Scans</span><span className="inline-flex items-center gap-1"><Nfc className="h-3 w-3" strokeWidth={1.75} />Taps</span></p>
    </div>
  );
}
