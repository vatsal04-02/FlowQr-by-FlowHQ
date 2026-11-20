"use client";
import clsx from "clsx";
import { Play } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

const STEPS: { href: string; text: string }[] = [
  { href: "/overview", text: "Home: your growth score, the numbers that matter and what to do this week" },
  { href: "/gbp/reviews", text: "Reviews: every review, its status, and the reply waiting for your approval" },
  { href: "/seo/profile", text: "GBP › Profile: how complete your Google profile is, with the reason for each gap" },
  { href: "/seo/rankings", text: "GBP › Rankings: the words you track and what people really search" },
  { href: "/growth", text: "Growth: this month's goal, and the steps from card scan to Google" },
];
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * A 30-second tour that only NAVIGATES: an animated pointer moves to each sidebar item and opens that page with your own data. It never clicks a button that changes anything,
 * so it cannot approve, send or save. Any click or Escape stops it. Desktop and tablet (the sidebar must be visible); reduced motion jumps without the pointer.
 */
export function Tour({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const [i, setI] = useState(0);
  const cur = useRef<HTMLDivElement>(null);
  const token = useRef(0);
  const [press, setPress] = useState(false);
  // onClose is a new function on every render of the shell; keeping it in a ref stops the tour restarting each time a page change re-renders it
  const close = useRef(onClose);
  useEffect(() => { close.current = onClose; });
  const stop = useCallback(() => { token.current++; close.current(); }, []);

  useEffect(() => {
    if (!open) return;
    const my = ++token.current, calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const alive = () => token.current === my;
    (async () => {
      for (let n = 0; n < STEPS.length && alive(); n++) {
        setI(n);
        const link = document.querySelector<HTMLElement>(`aside[aria-label="Main navigation"] a[href="${STEPS[n].href}"]`);
        if (link && cur.current && !calm) {
          const r = link.getBoundingClientRect();
          cur.current.style.transform = `translate(${r.left + Math.min(r.width * 0.5, 90)}px, ${r.top + r.height / 2}px)`;
          await wait(950); if (!alive()) return;
          setPress(true); await wait(150); setPress(false);
        }
        router.push(STEPS[n].href);
        await wait(calm ? 2600 : 3400);
      }
      if (alive()) close.current();
    })();
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") stop(); };
    const down = (e: PointerEvent) => { if (e.isTrusted && !(e.target as Element).closest("[data-tour]")) stop(); };
    window.addEventListener("keydown", key); document.addEventListener("pointerdown", down, true);
    return () => { token.current++; window.removeEventListener("keydown", key); document.removeEventListener("pointerdown", down, true); };
  }, [open, router, stop]);

  if (!open) return null;
  return (
    <>
      <div ref={cur} aria-hidden className="pointer-events-none fixed left-0 top-0 z-[100] motion-reduce:hidden" style={{ transform: "translate(60vw, 70vh)", transition: "transform .9s cubic-bezier(.45,.05,.2,1)" }}>
        <svg width="22" height="26" viewBox="0 0 22 26" className={clsx("drop-shadow-md transition-transform duration-150", press && "scale-[.86]")}><path d="M2 1.5v19.2l5.2-4.6 3.4 7.6 3.3-1.5-3.4-7.4 7.1-.4z" fill="#111" stroke="#fff" strokeWidth="1.6" strokeLinejoin="round" /></svg>
      </div>
      <div data-tour role="status" aria-live="polite" className="fq-enter fixed bottom-6 left-1/2 z-[100] flex max-w-[92vw] -translate-x-1/2 items-center gap-3 rounded-full bg-ink-solid py-2 pl-5 pr-2 text-[13.5px] font-medium text-ink-on shadow-float">
        <span className="min-w-0 truncate">{STEPS[i].text}</span>
        <span aria-hidden className="hidden gap-1 sm:flex">{STEPS.map((_, n) => <i key={n} className={clsx("h-1 w-5 rounded-full", n <= i ? "bg-accent" : "bg-white/25")} />)}</span>
        <button type="button" onClick={stop} className="!min-h-8 rounded-full bg-white/15 px-3 text-[13px] font-semibold">Stop</button>
      </div>
    </>
  );
}

export const TourIcon = Play;
