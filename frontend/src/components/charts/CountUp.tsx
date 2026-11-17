"use client";
import { useEffect, useRef, useState } from "react";

const reduced = () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/**
 * A number that counts up from 0 to `value` once, when it first appears (1.1 s, ease-out). The real value is always in the accessible text and is what a reduced-motion
 * visitor sees at once, so the animation never changes what is true; it only changes how it arrives. Re-runs only when `value` itself changes.
 */
export function CountUp({ value, decimals = 0, className }: { value: number; decimals?: number; className?: string }) {
  const [shown, setShown] = useState(() => (reduced() ? value : 0));
  const done = useRef<number | null>(null);
  useEffect(() => {
    if (done.current === value) return;
    if (reduced()) { setShown(value); done.current = value; return; }
    const from = done.current === null ? 0 : shown, t0 = performance.now(), dur = 1100;
    let raf = 0;
    const tick = (t: number) => {
      const p = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - p, 3);
      setShown(from + (value - from) * e);
      if (p < 1) raf = requestAnimationFrame(tick); else { setShown(value); done.current = value; }
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  const fmt = (n: number) => new Intl.NumberFormat("en-IN", { minimumFractionDigits: decimals, maximumFractionDigits: decimals }).format(n);
  return <span className={className}><span aria-hidden>{fmt(shown)}</span><span className="sr-only">{fmt(value)}</span></span>;
}
