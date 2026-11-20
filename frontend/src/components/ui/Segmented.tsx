"use client";
import clsx from "clsx";
import { motion } from "motion/react";
import { useId } from "react";

/**
 * A pill switch whose highlight slides to the chosen option (a spring, so it feels physical; reduced motion jumps). It is a real radio group: one tab stop per option with the chosen
 * one marked, arrow keys move the choice, and each option keeps a 44px touch height on phones.
 */
export function Segmented<T extends string | number>({ options, value, onChange, label, className }: { options: readonly (readonly [T, string])[]; value: T; onChange: (v: T) => void; label: string; className?: string }) {
  const id = useId();
  const move = (dir: 1 | -1) => { const i = options.findIndex(([v]) => v === value); onChange(options[(i + dir + options.length) % options.length][0]); };
  return (
    <div role="radiogroup" aria-label={label} className={clsx("relative flex rounded-full bg-surface-2 p-1", className)}
      onKeyDown={(e) => { if (e.key === "ArrowRight" || e.key === "ArrowDown") { e.preventDefault(); move(1); } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") { e.preventDefault(); move(-1); } }}>
      {options.map(([v, l]) => {
        const on = v === value;
        return (
          <button key={String(v)} type="button" role="radio" aria-checked={on} tabIndex={on ? 0 : -1} onClick={() => onChange(v)}
            className={clsx("relative min-w-11 rounded-full px-3 text-[13px] font-semibold transition-colors md:!min-h-8", on ? "text-ink" : "text-muted hover:text-ink")}>
            {on && <motion.span layoutId={`${id}-seg`} aria-hidden className="absolute inset-0 rounded-full bg-surface shadow-pill" transition={{ type: "spring", stiffness: 520, damping: 38 }} />}
            <span className="relative">{l}</span>
          </button>
        );
      })}
    </div>
  );
}
