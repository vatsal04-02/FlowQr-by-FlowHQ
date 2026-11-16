"use client";
import { useEffect, useId, useRef, useState, type CSSProperties } from "react";

type Row = { date: string; [k: string]: number | string | null | undefined };

/** Daily columns with rounded tops, a soft gradient, a hover/focus highlight and a tooltip. Native titles stay as the fallback for assistive tech. */
export function ColumnChart({ data, valueKey, label, color = "rgb(var(--c-ink-solid))", height = 170, ariaLabel }: { data: Row[]; valueKey: string; label: string; color?: string; height?: number; ariaLabel: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(0);
  const [hover, setHover] = useState<number | null>(null);
  const gid = useId().replace(/:/g, "");
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(220, Math.floor(e.contentRect.width))));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  const pad = { l: 30, r: 6, t: 10, b: 24 };
  const vals = data.map((d) => Number(d[valueKey]) || 0);
  const maxRaw = Math.max(0, ...vals);
  const max = maxRaw <= 4 ? 4 : Math.ceil(maxRaw / 4) * 4;
  const iw = w - pad.l - pad.r, ih = height - pad.t - pad.b;
  const pitch = iw / Math.max(1, data.length), bw = Math.max(3, Math.min(22, pitch * 0.66));
  const y = (v: number) => pad.t + ih - (v / max) * ih;
  const ticks = [0, 0.5, 1].map((t) => Math.round(t * max));
  const every = Math.max(1, Math.ceil(data.length / Math.max(2, Math.floor(iw / 64))));
  const fmt = (iso: string, long = false) => new Date(iso + "T00:00:00").toLocaleDateString("en-IN", long ? { weekday: "short", day: "numeric", month: "short" } : { day: "numeric", month: "short" });
  const cx = (i: number) => pad.l + i * pitch + pitch / 2;
  return (
    <div ref={ref} className="relative w-full min-w-0" style={{ minHeight: height }}>
      {w > 0 && (
        <svg width={w} height={height} role="img" aria-label={ariaLabel} className="block overflow-visible" onPointerLeave={() => setHover(null)}>
          <defs>
            <linearGradient id={`${gid}-bar`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={color} stopOpacity="1" /><stop offset="100%" stopColor={color} stopOpacity="1" /></linearGradient>
          </defs>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={pad.l} x2={w - pad.r} y1={y(t)} y2={y(t)} stroke="rgb(var(--c-ink-100))" strokeDasharray={t === 0 ? undefined : "2 4"} />
              <text x={pad.l - 8} y={y(t) + 4} textAnchor="end" fontSize="11" fill="rgb(var(--c-ink-500))">{t}</text>
            </g>
          ))}
          {data.map((d, i) => {
            const v = vals[i], on = hover === i;
            const h = Math.max(v > 0 ? 4 : 0, (ih * v) / max);
            return (
              <g key={d.date} onPointerEnter={() => setHover(i)}>
                <title>{`${fmt(d.date, true)}: ${v} ${label}`}</title>
                <rect x={pad.l + i * pitch} y={pad.t} width={pitch} height={ih} fill={on ? "rgb(var(--c-ink) / .05)" : "transparent"} rx="6" />
                {v > 0
                  ? <rect className="grow-y" style={{ "--d": `${Math.min(i * 12, 360)}ms`, opacity: hover === null || on ? 1 : 0.55, transition: "opacity .15s" } as CSSProperties} x={cx(i) - bw / 2} y={pad.t + ih - h} width={bw} height={h} rx={Math.min(6, bw / 2)} fill={`url(#${gid}-bar)`} />
                  : <rect x={cx(i) - bw / 2} y={pad.t + ih - 2} width={bw} height={2} rx="1" fill="rgb(var(--c-ink-200))" />}
                {i % every === 0 && <text x={cx(i)} y={height - 6} textAnchor="middle" fontSize="11" fill="rgb(var(--c-ink-500))">{fmt(d.date)}</text>}
              </g>
            );
          })}
        </svg>
      )}
      {hover !== null && data[hover] && w > 0 && (
        <div className="pointer-events-none absolute z-10 -translate-x-1/2 whitespace-nowrap rounded-xl bg-surface px-3 py-1.5 text-xs shadow-lift ring-1 ring-ink-100"
          style={{ left: Math.min(Math.max(cx(hover), 56), w - 56), top: Math.max(0, y(vals[hover]) - 46) }}>
          <span className="text-ink-500">{fmt(data[hover].date, true)}</span><br /><b className="text-[13px] tabular-nums">{vals[hover]}</b> {label}
        </div>
      )}
    </div>
  );
}
