"use client";
import clsx from "clsx";
import { useId, type ReactNode } from "react";

/** Card with an optional title row (DESIGN.md "Card"). `flush` keeps a small inset so a table's rounded header row sits inside the card. */
export function Panel({ title, meta, action, children, className, flush, dense }: { title?: ReactNode; meta?: ReactNode; action?: ReactNode; children: ReactNode; className?: string; flush?: boolean; dense?: boolean }) {
  // `dense` is for data-heavy cards (Local SEO, Performance): a 16px radius and tighter padding so more numbers fit on a screen. The default stays the 28px card.
  return (
    <section className={clsx("panel min-w-0 overflow-hidden", dense && "!rounded-[16px]", className)}>
      {(title || action) && (
        <header className={clsx("flex flex-wrap items-center justify-between gap-2", dense ? "min-h-11 px-4 pb-0.5 pt-3.5" : "min-h-12 px-5 pb-1 pt-4 sm:px-6 sm:pt-5")}>
          <div className="flex min-w-0 flex-wrap items-baseline gap-x-2"><h2 className={clsx("font-semibold", dense ? "text-[15px] leading-5" : "text-lg leading-6")}>{title}</h2>{meta && <span className="truncate text-[13px] text-muted">{meta}</span>}</div>
          {action}
        </header>
      )}
      <div className={flush ? "px-2 pb-2 sm:px-3 sm:pb-3" : dense ? "p-4" : "p-5 sm:p-6"}>{children}</div>
    </section>
  );
}

type Tone = "ok" | "warn" | "bad" | "info" | "idle" | "gold";
const dotTone: Record<Tone, string> = { ok: "bg-pos", warn: "bg-warn", bad: "bg-neg", info: "bg-accent", idle: "bg-muted-soft", gold: "bg-gold-400" };
const textTone: Record<Tone, string> = { ok: "text-pos", warn: "text-warn", bad: "text-neg", info: "text-accent-ink", idle: "text-muted", gold: "text-gold-700" };

/** Status as a dot plus words (never colour alone). Quieter than a filled pill, so tables stay readable. */
export function Status({ tone = "idle", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return <span className={clsx("inline-flex items-center gap-1.5 whitespace-nowrap text-[13px] font-medium", textTone[tone], className)}><span aria-hidden className={clsx("h-1.5 w-1.5 shrink-0 rounded-full", dotTone[tone])} />{children}</span>;
}

/**
 * Segmented control for filters and ranges (a radio group underneath). `soft` = grey track, white active segment (inside cards).
 * `solid` = white pill track, black active segment (page header range picker, as in the reference).
 */
export function Segmented<T extends string>({ value, onChange, options, label, className, tone = "soft" }: { value: T; onChange: (v: T) => void; options: readonly (readonly [T, string])[]; label: string; className?: string; tone?: "soft" | "solid" }) {
  const solid = tone === "solid";
  return (
    <div role="radiogroup" aria-label={label} className={clsx("inline-flex max-w-full overflow-x-auto rounded-full p-1 no-scrollbar", solid ? "bg-surface shadow-pill" : "bg-surface-2", className)}>
      {options.map(([v, l]) => (
        <button key={v} type="button" role="radio" aria-checked={value === v} onClick={() => onChange(v)}
          className={clsx("min-h-11 shrink-0 whitespace-nowrap rounded-full px-4 text-[13px] font-medium transition-colors sm:min-h-9 sm:text-sm",
            value === v ? (solid ? "bg-ink-solid text-ink-on" : "bg-surface text-ink shadow-pill") : "text-muted hover:text-ink")}>{l}</button>
      ))}
    </div>
  );
}

/** Horizontal meter with the value as text next to it. */
export function Meter({ value, max, tone = "info", label }: { value: number; max: number; tone?: "info" | "ok" | "warn" | "bad" | "gold"; label: string }) {
  const pct = max ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  const fill = { info: "bg-accent", ok: "bg-pos", warn: "bg-warn", bad: "bg-neg", gold: "bg-gold-400" }[tone];
  return (
    <div className="hatch h-2.5 overflow-hidden rounded-full" role="progressbar" aria-label={label} aria-valuenow={value} aria-valuemin={0} aria-valuemax={max}>
      <div className={clsx("grow-x h-full rounded-full", fill)} style={{ width: `${pct}%` }} />
    </div>
  );
}

/** Label / value rows for details. */
export function KV({ rows, className }: { rows: [ReactNode, ReactNode][]; className?: string }) {
  return (
    <dl className={clsx("divide-y divide-line text-sm", className)}>
      {rows.map(([k, v], i) => <div key={i} className="flex items-baseline justify-between gap-4 py-2"><dt className="shrink-0 text-muted">{k}</dt><dd className="min-w-0 text-right font-medium">{v}</dd></div>)}
    </dl>
  );
}

/** Tiny trend line. Decorative; the number it sits beside carries the information. */
export function Sparkline({ values, width = 96, height = 28, color = "rgb(var(--c-accent))", area = true }: { values: number[]; width?: number; height?: number; color?: string; area?: boolean }) {
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
export function CellBar({ value, max, color = "bg-accent" }: { value: number; max: number; color?: string }) {
  return <span aria-hidden className="block h-2 w-full overflow-hidden rounded-full bg-surface-2"><span className={clsx("block h-full rounded-full", color)} style={{ width: `${max ? (value / max) * 100 : 0}%` }} /></span>;
}

/** DESIGN.md "Toggle": 52×30 pill, accent when on, 44px hit area. A real switch for assistive tech. */
export function Toggle({ on, onChange, label, disabled }: { on: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} disabled={disabled} onClick={() => onChange(!on)}
      className="grid h-11 w-[60px] shrink-0 place-items-center disabled:opacity-50">
      <span className={clsx("relative h-[30px] w-[52px] rounded-full transition-colors duration-300", on ? "bg-set-switch-on" : "bg-set-switch-off")}>
        <span className={clsx("absolute top-[3px] h-6 w-6 rounded-full bg-pure-white shadow transition-[left] duration-300 ease-spring", on ? "left-[25px]" : "left-[3px]")} />
      </span>
    </button>
  );
}
