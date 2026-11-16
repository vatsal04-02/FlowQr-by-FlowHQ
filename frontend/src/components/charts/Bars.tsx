"use client";
import clsx from "clsx";
import { useId, useState } from "react";

export interface BarDatum { key: string; label: string; cur: number; prev?: number | null; tip?: string }

/**
 * Counts as bars, never a smoothed line. This period is solid ink; the period before is a grey outline beside it; an optional goal is one dashed line. Every bar can be reached
 * with the keyboard (Tab, then the value shows) and tapped on a phone; "View as table" gives the same numbers as text.
 */
export function Bars({ data, goal, goalLabel, height = 168, label, unit = "reviews" }: { data: BarDatum[]; goal?: number | null; goalLabel?: string; height?: number; label: string; unit?: string }) {
  const [on, setOn] = useState<number | null>(null);
  const [table, setTable] = useState(false);
  const id = useId();
  const max = Math.max(1, goal ?? 0, ...data.map((d) => Math.max(d.cur, d.prev ?? 0)));
  const top = max <= 4 ? 4 : Math.ceil(max / 2) * 2;
  const hasPrev = data.some((d) => d.prev !== undefined && d.prev !== null);
  const pct = (v: number) => `${(v / top) * 100}%`;
  return (
    <div>
      <div className="relative" style={{ height }} role="img" aria-label={label}>
        {[0, 0.5, 1].map((t) => (
          <div key={t} aria-hidden className="absolute inset-x-0 flex items-center gap-2" style={{ bottom: `${t * 100}%`, transform: "translateY(50%)" }}>
            <span className="num w-5 text-right text-[11px] text-muted">{Math.round(top * t)}</span><span className="h-px flex-1 bg-line" />
          </div>
        ))}
        {goal ? (
          <div aria-hidden className="absolute left-7 right-0 border-t-[1.5px] border-dashed border-ink-500" style={{ bottom: pct(goal) }}>
            <span className="absolute -top-[18px] right-0 bg-surface pl-1 text-[11px] font-medium text-ink-600">{goalLabel ?? "Goal"} {goal % 1 ? goal.toFixed(1) : goal}</span>
          </div>
        ) : null}
        <div className="absolute inset-y-0 left-7 right-0 flex items-end justify-around gap-1">
          {data.map((d, i) => (
            <button key={d.key} type="button" aria-describedby={on === i ? `${id}-tip` : undefined} onFocus={() => setOn(i)} onBlur={() => setOn(null)} onMouseEnter={() => setOn(i)} onMouseLeave={() => setOn(null)} onClick={() => setOn(on === i ? null : i)}
              aria-label={`${d.label}: ${d.cur} ${unit}${hasPrev && d.prev !== null && d.prev !== undefined ? `, ${d.prev} before` : ""}`}
              className={clsx("relative flex h-full !min-h-0 !min-w-0 flex-1 items-end justify-center gap-[3px] rounded-[6px] outline-offset-2", on === i && "bg-surface-2")}>
              {hasPrev && <span aria-hidden className="w-[38%] max-w-[16px] rounded-t-[3px] border border-ink-400 bg-surface" style={{ height: d.prev ? pct(d.prev) : 0 }} />}
              <span aria-hidden className="fq-bar w-[38%] max-w-[16px] rounded-t-[3px] bg-ink-solid" style={{ height: d.cur ? pct(d.cur) : "2px", opacity: d.cur ? 1 : 0.25 }} />
            </button>
          ))}
        </div>
        {on !== null && data[on] && (
          <div id={`${id}-tip`} role="tooltip" className="pointer-events-none absolute -top-2 z-10 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-[10px] bg-ink-solid px-2.5 py-1.5 text-[12px] text-ink-on"
            style={{ left: `calc(1.75rem + (100% - 1.75rem) * ${(on + 0.5) / data.length})` }}>
            <b className="num">{data[on].cur}</b> {unit} · {data[on].tip ?? data[on].label}{hasPrev && data[on].prev !== null && data[on].prev !== undefined ? <span className="opacity-70"> · before {data[on].prev}</span> : null}
          </div>
        )}
      </div>
      <div aria-hidden className="ml-7 mt-1.5 flex justify-around gap-1 overflow-hidden">{data.map((d, i) => <span key={d.key} className="min-w-0 flex-1 overflow-visible whitespace-nowrap text-center text-[11px] text-muted">{i % Math.max(1, Math.ceil(data.length / 5)) ? "" : d.label}</span>)}</div>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        {hasPrev ? <p className="flex items-center gap-3 text-[12px] text-muted"><span className="flex items-center gap-1.5"><i aria-hidden className="h-2.5 w-2.5 rounded-[2px] bg-ink-solid" />This period</span><span className="flex items-center gap-1.5"><i aria-hidden className="h-2.5 w-2.5 rounded-[2px] border border-ink-400" />Before</span></p> : <span />}
        <button type="button" onClick={() => setTable((t) => !t)} aria-expanded={table} className="!min-h-0 text-[12px] font-medium text-ink-600 underline underline-offset-2">{table ? "Hide table" : "Table"}</button>
      </div>
      {table && (
        <table className="mt-2 w-full text-left text-[13px]"><thead><tr className="text-muted"><th className="py-1 font-medium">Period</th><th className="py-1 text-right font-medium">This</th>{hasPrev && <th className="py-1 text-right font-medium">Before</th>}</tr></thead>
          <tbody>{data.map((d) => <tr key={d.key} className="border-t border-line"><td className="py-1">{d.tip ?? d.label}</td><td className="num py-1 text-right">{d.cur}</td>{hasPrev && <td className="num py-1 text-right text-muted">{d.prev ?? "–"}</td>}</tr>)}</tbody></table>
      )}
    </div>
  );
}

/** A 0-100 ring. The number sits inside; the ring is a picture of the same number. */
export function Ring({ value, size = 104, stroke = 10, children, label }: { value: number | null; size?: number; stroke?: number; children?: React.ReactNode; label: string }) {
  const r = (size - stroke) / 2, c = 2 * Math.PI * r, v = value === null ? 0 : Math.max(0, Math.min(100, value));
  return (
    <span className="relative inline-grid shrink-0 place-items-center" style={{ width: size, height: size }} role="img" aria-label={label}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgb(var(--c-surface-3))" strokeWidth={stroke} strokeDasharray={value === null ? "3 5" : undefined} />
        {value !== null && <circle className="fq-ring" cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgb(var(--c-ink-solid))" strokeWidth={stroke} strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - v / 100)} style={{ ["--c" as string]: c }} />}
      </svg>
      <span className="absolute inset-0 grid place-items-center text-center">{children}</span>
    </span>
  );
}

/** A thin horizontal bar for one part of a whole (0..1). Dashes when there is no data. */
export function Meter({ value, tone = "ink", className }: { value: number | null; tone?: "ink" | "watch"; className?: string }) {
  return (
    <span aria-hidden className={clsx("block h-2 overflow-hidden rounded-full", value === null ? "bg-[repeating-linear-gradient(90deg,rgb(var(--c-surface-3))_0_6px,transparent_6px_10px)]" : "bg-surface-3", className)}>
      {value !== null && <span className={clsx("fq-bar-x block h-full rounded-full", tone === "watch" ? "bg-warn" : "bg-ink-solid")} style={{ width: `${Math.max(2, value * 100)}%` }} />}
    </span>
  );
}
