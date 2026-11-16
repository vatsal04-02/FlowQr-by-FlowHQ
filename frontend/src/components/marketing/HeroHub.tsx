"use client";
import { motion, useReducedMotion } from "motion/react";
import { BarChart3, CalendarCheck, Camera, MapPin, MessageSquareReply, Star } from "lucide-react";
import type { ReactNode } from "react";
import { GoogleG } from "./kit";
import { EASE } from "./motion";

/**
 * The hero visual: the Google logo in the middle, the six parts of a Google Business Profile that FlowQR manages around it.
 * Each is a built feature (reviews inbox, AI reply drafts, Google Posts, photos, local ranking, insights). One idea, no product cards.
 * Wide screens: three labels each side, joined to the logo by thin lines. Phones: the logo, then the labels in two columns.
 */
const ITEMS: [ReactNode, string][] = [
  [<Star key="s" className="h-4 w-4" strokeWidth={1.75} />, "Reviews inbox"],
  [<MessageSquareReply key="m" className="h-4 w-4" strokeWidth={1.75} />, "AI reply drafts"],
  [<CalendarCheck key="c" className="h-4 w-4" strokeWidth={1.75} />, "Google Posts"],
  [<Camera key="p" className="h-4 w-4" strokeWidth={1.75} />, "Photos"],
  [<MapPin key="l" className="h-4 w-4" strokeWidth={1.75} />, "Local ranking"],
  [<BarChart3 key="i" className="h-4 w-4" strokeWidth={1.75} />, "Insights"],
];
const LEFT = [0, 1, 2], RIGHT = [3, 4, 5];

function Pill({ item, i }: { item: [ReactNode, string]; i: number }) {
  const reduced = useReducedMotion();
  return (
    <motion.span className="inline-flex h-11 items-center gap-2.5 rounded-full bg-m-surface pl-1.5 pr-4 text-[14px] font-medium tracking-[-.01em] text-m-ink shadow-[var(--shadow-card)]"
      initial={{ opacity: 0, y: reduced ? 0 : 10 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: reduced ? 0.2 : 0.5, ease: EASE, delay: 0.3 + i * 0.07 }}>
      <span aria-hidden className="grid h-8 w-8 place-items-center rounded-full bg-m-tint text-m-accentStrong">{item[0]}</span>{item[1]}
    </motion.span>
  );
}

export function HeroHub({ note }: { note: string }) {
  const reduced = useReducedMotion();
  const ys = [50, 150, 250];
  return (
    <div>
      {/* Wide screens */}
      <div className="relative mx-auto hidden h-[300px] w-full max-w-[920px] md:block">
        <svg aria-hidden viewBox="0 0 920 300" className="absolute inset-0 h-full w-full">
          {LEFT.map((n, k) => <motion.path key={n} d={`M276 ${ys[k]} C 340 ${ys[k]}, 340 150, 398 150`} fill="none" stroke="#FE6A05" strokeOpacity=".55" strokeWidth="1.5" strokeDasharray="4 5" initial={{ pathLength: reduced ? 1 : 0 }} whileInView={{ pathLength: 1 }} viewport={{ once: true }} transition={{ duration: reduced ? 0 : 0.9, ease: EASE, delay: 0.2 + k * 0.08 }} />)}
          {RIGHT.map((n, k) => <motion.path key={n} d={`M644 ${ys[k]} C 580 ${ys[k]}, 580 150, 522 150`} fill="none" stroke="#FE6A05" strokeOpacity=".55" strokeWidth="1.5" strokeDasharray="4 5" initial={{ pathLength: reduced ? 1 : 0 }} whileInView={{ pathLength: 1 }} viewport={{ once: true }} transition={{ duration: reduced ? 0 : 0.9, ease: EASE, delay: 0.2 + k * 0.08 }} />)}
        </svg>
        <ul className="absolute left-0 top-0 flex h-full w-[30%] flex-col items-end justify-around">{LEFT.map((n) => <li key={n}><Pill item={ITEMS[n]} i={n} /></li>)}</ul>
        <ul className="absolute right-0 top-0 flex h-full w-[30%] flex-col items-start justify-around">{RIGHT.map((n) => <li key={n}><Pill item={ITEMS[n]} i={n} /></li>)}</ul>
        <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2">
          {[0, 1].map((i) => (
            <motion.span key={i} aria-hidden className="absolute inset-0 rounded-full border border-m-accent"
              animate={reduced ? { opacity: 0.18, scale: 1.3 + i * 0.35 } : { opacity: [0, 0.35, 0], scale: [1, 1.7, 2.1] }} transition={{ duration: 3.2, repeat: Infinity, delay: i * 1.6, ease: "easeOut" }} />
          ))}
          <GoogleG size={128} className="relative shadow-[var(--shadow-float)]" />
        </div>
        <p className="absolute left-1/2 top-[calc(50%+82px)] -translate-x-1/2 whitespace-nowrap text-[13px] font-medium text-m-ink2">Google Business Profile</p>
      </div>

      {/* Phones */}
      <div className="mx-auto max-w-[420px] md:hidden">
        <div className="flex flex-col items-center">
          <GoogleG size={88} className="shadow-[var(--shadow-float)]" />
          <p className="mt-3 text-[13px] font-medium text-m-ink2">Google Business Profile</p>
        </div>
        <ul className="mt-5 grid grid-cols-2 gap-2.5">{ITEMS.map((it, i) => <li key={it[1]} className="flex justify-center"><Pill item={it} i={i} /></li>)}</ul>
      </div>
      <p className="mt-7 text-center text-[14px] text-m-muted md:mt-6">{note}</p>
    </div>
  );
}
