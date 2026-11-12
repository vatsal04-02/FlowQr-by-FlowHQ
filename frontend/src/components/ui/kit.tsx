"use client";
import clsx from "clsx";
import { useId, type ReactNode } from "react";

/** Panel with an optional header bar. The header is separated by a hairline, so dense content below needs no extra cards. */
export function Panel({ title, meta, action, children, className, flush }: { title?: ReactNode; meta?: ReactNode; action?: ReactNode; children: ReactNode; className?: string; flush?: boolean }) {
  return (
    <section className={clsx("panel min-w-0 overflow-hidden", className)}>
      {(title || action) && (
        <header className="flex min-h-11 flex-wrap items-center justify-between gap-2 border-b border-ink-100 px-4 py-2">
          <div className="flex min-w-0 items-baseline gap-2"><h2 className="text-sm font-semibold">{title}</h2>{meta && <span className="truncate text-xs text-ink-500">{meta}</span>}</div>
          {action}
        </header>
      )}
      <div className={flush ? "" : "p-4"}>{children}</div>
    </section>
  );
}

type Tone = "ok" | "warn" | "bad" | "info" | "idle" | "gold";
const dotTone: Record<Tone, string> = { ok: "bg-ok", warn: "bg-amber-500", bad: "bg-red-600", info: "bg-brand-600", idle: "bg-ink-300", gold: "bg-gold-400" };
const textTone: Record<Tone, string> = { ok: "text-green-800", warn: "text-amber-900", bad: "text-red-800", info: "text-brand-800", idle: "text-ink-500", gold: "text-gold-700" };

/** Status as a dot plus words (never colour alone). Quieter than a filled pill, so tables stay readable. */
export function Status({ tone = "idle", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return <span className={clsx("inline-flex items-center gap-1.5 whitespace-nowrap text-[13px] font-medium", textTone[tone], className)}><span aria-hidden className={clsx("h-1.5 w-1.5 shrink-0 rounded-full", dotTone[tone])} />{children}</span>;
}

/** Segmented control for filters and ranges (a radio group underneath). */
export function Segmented<T extends string>({ value, onChange, options, label, className }: { value: T; onChange: (v: T) => void; options: readonly (readonly [T, string])[]; label: string; className?: string }) {
  return (
    <div role="radiogroup" aria-label={label} className={clsx("inline-flex rounded-lg bg-ink-100/70 p-0.5", className)}>
      {options.map(([v, l]) => (
        <button key={v} type="button" role="radio" aria-checked={value === v} onClick={() => onChange(v)}
          className={clsx("min-h-11 rounded-md px-3 text-[13px] font-medium transition-colors sm:min-h-7", value === v ? "bg-white text-ink shadow-panel" : "text-ink-500 hover:text-ink")}>{l}</button>
      ))}
    </div>
  );
}

/** Horizontal meter with the value as text next to it. */
export function Meter({ value, max, tone = "info", label }: { value: number; max: number; tone?: "info" | "ok" | "warn" | "bad" | "gold"; label: string }) {
  const pct = max ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  const fill = { info: "bg-brand-600", ok: "bg-ok", warn: "bg-amber-500", bad: "bg-red-600", gold: "bg-gold-400" }[tone];
  return (
    <div className="h-1.5 overflow-hidden rounded-full bg-ink-100" role="progressbar" aria-label={label} aria-valuenow={value} aria-valuemin={0} aria-valuemax={max}>
      <div className={clsx("h-full rounded-full", fill)} style={{ width: `${pct}%` }} />
    </div>
  );
}

/** Label / value rows for details. */
export function KV({ rows, className }: { rows: [ReactNode, ReactNode][]; className?: string }) {
  return (
    <dl className={clsx("divide-y divide-ink-100 text-sm", className)}>
      {rows.map(([k, v], i) => <div key={i} className="flex items-baseline justify-between gap-4 py-2"><dt className="shrink-0 text-ink-500">{k}</dt><dd className="min-w-0 text-right font-medium">{v}</dd></div>)}
    </dl>
  );
}

/** Tiny trend line. Decorative; the number it sits beside carries the information. */
export function Sparkline({ values, width = 96, height = 28, color = "#1B46B8", area = true }: { values: number[]; width?: number; height?: number; color?: string; area?: boolean }) {
  const id = useId().replace(/:/g, "");
  if (values.length < 2) return <span aria-hidden className="inline-block" style={{ width, height }} />;
  const max = Math.max(1, ...values), min = Math.min(...values, 0);
  const x = (i: number) => (i / (values.length - 1)) * (width - 2) + 1;
  const y = (v: number) => height - 2 - ((v - min) / (max - min || 1)) * (height - 4);
  const line = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden className="shrink-0 overflow-visible">
      {area && <><defs><linearGradient id={id} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={color} stopOpacity=".18" /><stop offset="1" stopColor={color} stopOpacity="0" /></linearGradient></defs>
        <path d={`${line} L${x(values.length - 1)},${height} L${x(0)},${height} Z`} fill={`url(#${id})`} /></>}
      <path d={line} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** A thin horizontal bar used inside table cells for relative comparison. The number is always printed beside it. */
export function CellBar({ value, max, color = "bg-brand-600" }: { value: number; max: number; color?: string }) {
  return <span aria-hidden className="block h-1.5 w-full overflow-hidden rounded-full bg-ink-100"><span className={clsx("block h-full rounded-full", color)} style={{ width: `${max ? (value / max) * 100 : 0}%` }} /></span>;
}
