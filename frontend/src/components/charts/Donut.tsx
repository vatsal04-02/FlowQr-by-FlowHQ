"use client";
import clsx from "clsx";
import { useEffect, useState, type ReactNode } from "react";
import { shares } from "@/lib/charts";
import { fmtNum } from "@/lib/format";

export interface Slice { key: string; label: string; value: number; color: string }

/**
 * A share-of-a-whole ring. Each slice is a real count; the percentages are derived from those counts (and add up to 100), never entered by hand. Slices draw in one after another on
 * first view. The centre holds the one number that matters; the legend prints every count so colour is never the only signal.
 */
export function Donut({ slices, size = 132, stroke = 18, centre, sub, label }: { slices: Slice[]; size?: number; stroke?: number; centre: ReactNode; sub?: string; label: string }) {
  const [on, setOn] = useState(false);
  useEffect(() => { const r = requestAnimationFrame(() => setOn(true)); return () => cancelAnimationFrame(r); }, []);
  const r = (size - stroke) / 2, c = 2 * Math.PI * r, m = size / 2, total = slices.reduce((a, s) => a + s.value, 0);
  let acc = 0;
  return (
    <span className="relative inline-grid shrink-0 place-items-center" style={{ width: size, height: size }} role="img" aria-label={label}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden className="-rotate-90">
        <circle cx={m} cy={m} r={r} fill="none" stroke="rgb(var(--c-surface-3))" strokeWidth={stroke} />
        {total > 0 && slices.filter((s) => s.value > 0).map((s, i) => {
          const len = (s.value / total) * c, off = -acc;
          acc += len;
          const gap = slices.filter((x) => x.value > 0).length > 1 ? 2.5 : 0;
          return <circle key={s.key} cx={m} cy={m} r={r} fill="none" stroke={s.color} strokeWidth={stroke} strokeDasharray={on ? `${Math.max(1, len - gap)} ${c}` : `0 ${c}`} strokeDashoffset={off}
            style={{ transition: `stroke-dasharray 1s cubic-bezier(.2,.7,.2,1) ${i * 140 + 150}ms` }}><title>{`${s.label}: ${fmtNum(s.value)}`}</title></circle>;
        })}
      </svg>
      <span className="absolute inset-0 grid place-content-center text-center leading-none"><b className="num text-[26px] font-semibold tracking-[-.03em]">{centre}</b>{sub && <span className="mt-1 text-[13px] text-muted">{sub}</span>}</span>
    </span>
  );
}

/** The legend for a Donut: swatch, name, count, percent. Zero-count slices stay listed (a real zero is information). */
export function Legend({ slices, className }: { slices: Slice[]; className?: string }) {
  const pct = shares(slices.map((s) => s.value));
  return (
    <ul className={clsx("grid min-w-[150px] flex-1 gap-2", className)}>
      {slices.map((s, i) => (
        <li key={s.key} className="grid grid-cols-[10px_minmax(0,1fr)_auto_2.5rem] items-center gap-2 text-[13px] text-ink-700">
          <i aria-hidden className="h-2.5 w-2.5 rounded-[3px]" style={{ background: s.color }} />
          <span className="truncate">{s.label}</span><b className="num font-semibold text-ink">{fmtNum(s.value)}</b><em className="num text-right not-italic text-muted">{pct[i]}%</em>
        </li>
      ))}
    </ul>
  );
}
