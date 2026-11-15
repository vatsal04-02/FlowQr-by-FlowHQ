"use client";
import { useEffect, useRef, useState } from "react";

type Point = { date: string; [k: string]: number | string };

/**
 * Daily columns for counts (e.g. new reviews). Every column has a native tooltip and the total is in the label,
 * so nothing depends on colour or hover alone.
 */
export function ColumnChart({ data, valueKey, label, color = "rgb(var(--c-accent))", height = 170, ariaLabel }: { data: Point[]; valueKey: string; label: string; color?: string; height?: number; ariaLabel: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(220, Math.floor(e.contentRect.width))));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  const vals = data.map((d) => Number(d[valueKey]) || 0);
  const total = vals.reduce((a, b) => a + b, 0);
  const max = Math.max(4, ...vals);
  const pad = { l: 28, r: 4, t: 8, b: 20 };
  const iw = w - pad.l - pad.r, ih = height - pad.t - pad.b;
  const slot = data.length ? iw / data.length : 0;
  const bw = Math.max(2, Math.min(18, slot * 0.68));
  const fmt = (iso: string) => new Date(iso + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  const ticks = [0, Math.round(max / 2), max];
  const step = Math.max(1, Math.ceil(data.length / Math.max(2, Math.floor(iw / 72))));
  return (
    <div ref={ref} className="w-full" style={{ minHeight: height }}>
      {w > 0 && (
        <svg width={w} height={height} role="img" aria-label={`${ariaLabel}: ${total} in total`} className="block">
          {ticks.map((t) => (
            <g key={t}>
              <line x1={pad.l} x2={w - pad.r} y1={pad.t + ih - (t / max) * ih} y2={pad.t + ih - (t / max) * ih} stroke="rgb(var(--c-ink-100))" strokeDasharray={t === 0 ? undefined : "2 4"} />
              <text x={pad.l - 6} y={pad.t + ih - (t / max) * ih + 4} textAnchor="end" fontSize="11" fill="rgb(var(--c-ink-500))">{t}</text>
            </g>
          ))}
          {data.map((d, i) => {
            const v = vals[i], bh = (v / max) * ih, x = pad.l + slot * i + (slot - bw) / 2;
            return (
              <g key={d.date}>
                <rect x={x} y={pad.t + ih - bh} width={bw} height={Math.max(v ? 2 : 0, bh)} rx={1.5} fill={color}><title>{`${fmt(d.date)}: ${v} ${label}`}</title></rect>
                {i % step === 0 && <text x={x + bw / 2} y={height - 5} textAnchor="middle" fontSize="11" fill="rgb(var(--c-ink-500))">{fmt(d.date)}</text>}
              </g>
            );
          })}
        </svg>
      )}
    </div>
  );
}
