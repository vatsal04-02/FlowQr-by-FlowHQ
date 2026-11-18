"use client";
import { useEffect, useState } from "react";
import { useReducedMotion } from "motion/react";

/**
 * A line that types itself out once, letter by letter, with a caret that blinks a few times and then goes. The full text is always in the page for screen readers and search; the typed copy is
 * decoration. The untyped rest is kept in the layout (invisible), so the line never changes width or jumps while it types. Reduced motion: the whole line, still.
 * Server and browser render the same thing at first (all of it); typing starts after the parent's entrance has faded the line in.
 */
export function Typed({ text, className, start = 650, speed = 62 }: { text: string; className?: string; start?: number; speed?: number }) {
  const reduced = useReducedMotion();
  const [n, setN] = useState(text.length);
  const [done, setDone] = useState(true);
  useEffect(() => {
    if (reduced) { setN(text.length); setDone(true); return; }
    setN(0); setDone(false);
    let i = 0, tick: ReturnType<typeof setInterval> | undefined;
    const go = setTimeout(() => {
      tick = setInterval(() => { i += 1; setN(i); if (i >= text.length) { clearInterval(tick); setDone(true); } }, speed);
    }, start);
    return () => { clearTimeout(go); if (tick) clearInterval(tick); };
  }, [text, reduced, start, speed]);
  return (
    <span className={className}>
      <span className="sr-only">{text}</span>
      <span aria-hidden className="whitespace-pre">
        <span className="relative">{text.slice(0, n)}<span className={`absolute left-full top-[.1em] h-[.82em] w-[.06em] ml-[.06em] rounded-sm bg-m-accent ${done ? "mkt-caret-blink" : ""}`} /></span>
        <span className="invisible">{text.slice(n)}</span>
      </span>
    </span>
  );
}
