"use client";
import { useEffect, useMemo, useRef, useState } from "react";

export interface Series { key: string; label: string; color: string; dash?: string }
type Point = { date: string; [k: string]: number | string };

function niceMax(v: number) {
  if (v <= 4) return 4;
  const pow = Math.pow(10, Math.floor(Math.log10(v)));
  const n = v / pow;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * pow;
}

function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(0); // 0 until measured, so the SVG never forces the layout wider than its container
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(220, Math.floor(e.contentRect.width))));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

/**
 * Accessible SVG line chart: series differ by colour AND line style (never colour alone), has a legend,
 * a hover/keyboard tooltip (arrow keys) and a collapsible data table as the screen-reader fallback.
 */
export function LineChart({ data, series, height = 230, ariaLabel, yMax: yMaxProp }: { data: Point[]; series: Series[]; height?: number; ariaLabel: string; yMax?: number }) {
  const [ref, width] = useWidth();
  const [active, setActive] = useState<number | null>(null);
  const pad = { l: 36, r: 12, t: 12, b: 26 };
  const iw = width - pad.l - pad.r, ih = height - pad.t - pad.b;

  const yMax = useMemo(() => yMaxProp ?? niceMax(Math.max(0, ...data.flatMap((d) => series.map((s) => Number(d[s.key]) || 0)))), [data, series, yMaxProp]);
  const x = (i: number) => pad.l + (data.length <= 1 ? iw / 2 : (i / (data.length - 1)) * iw);
  const y = (v: number) => pad.t + ih - (v / yMax) * ih;
  const ticks = yMax <= 6 ? Array.from({ length: yMax + 1 }, (_, i) => i) : [0, 0.25, 0.5, 0.75, 1].map((t) => Math.round(t * yMax));
  const xStep = Math.max(1, Math.ceil(data.length / Math.max(2, Math.floor(iw / 80))));
  const label = (iso: string) => new Date(iso + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short" });

  const onMove = (clientX: number, rect: DOMRect) => {
    const rel = clientX - rect.left - pad.l;
    setActive(Math.min(data.length - 1, Math.max(0, Math.round((rel / iw) * (data.length - 1)))));
  };
  const empty = data.length === 0 || series.every((s) => data.every((d) => !Number(d[s.key])));

  return (
    <div>
      <ul className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-ink-700">
        {series.map((s) => (
          <li key={s.key} className="flex items-center gap-2">
            <svg width="26" height="8" aria-hidden><line x1="0" y1="4" x2="26" y2="4" stroke={s.color} strokeWidth="3" strokeDasharray={s.dash} strokeLinecap="round" /></svg>{s.label}
          </li>
        ))}
      </ul>
      <div ref={ref} className="relative w-full min-w-0 overflow-hidden" style={{ minHeight: height }}>
        {width > 0 && <svg width={width} height={height} role="img" aria-label={ariaLabel} tabIndex={0} className="block touch-pan-y rounded-lg"
          onPointerMove={(e) => onMove(e.clientX, e.currentTarget.getBoundingClientRect())} onPointerLeave={() => setActive(null)}
          onKeyDown={(e) => {
            if (e.key === "ArrowRight") { e.preventDefault(); setActive((a) => Math.min(data.length - 1, (a ?? -1) + 1)); }
            if (e.key === "ArrowLeft") { e.preventDefault(); setActive((a) => Math.max(0, (a ?? data.length) - 1)); }
            if (e.key === "Escape") setActive(null);
          }} onBlur={() => setActive(null)}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={pad.l} x2={width - pad.r} y1={y(t)} y2={y(t)} stroke="#E2E8F0" strokeWidth="1" />
              <text x={pad.l - 8} y={y(t) + 4} textAnchor="end" fontSize="11" fill="#64748B">{Number.isInteger(t) ? t : t.toFixed(1)}</text>
            </g>
          ))}
          {data.map((d, i) => i % xStep === 0 && (
            <text key={d.date} x={x(i)} y={height - 6} textAnchor="middle" fontSize="11" fill="#64748B">{label(d.date)}</text>
          ))}
          {series.map((s) => (
            <path key={s.key} fill="none" stroke={s.color} strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" strokeDasharray={s.dash}
              d={data.map((d, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(Number(d[s.key]) || 0).toFixed(1)}`).join(" ")} />
          ))}
          {active !== null && data[active] && (
            <g>
              <line x1={x(active)} x2={x(active)} y1={pad.t} y2={pad.t + ih} stroke="#94A3B8" strokeDasharray="3 3" />
              {series.map((s) => <circle key={s.key} cx={x(active)} cy={y(Number(data[active][s.key]) || 0)} r="4.5" fill="#fff" stroke={s.color} strokeWidth="2.5" />)}
            </g>
          )}
        </svg>}
        {empty && <p className="pointer-events-none absolute inset-0 grid place-items-center text-sm text-ink-400">No data in this period yet</p>}
        {active !== null && data[active] && (
          <div className="pointer-events-none absolute top-2 z-10 min-w-[140px] rounded-xl border border-ink-100 bg-white p-2.5 text-xs shadow-pop"
            style={{ left: Math.min(Math.max(x(active) - 70, 0), width - 150) }}>
            <p className="mb-1 font-semibold text-ink">{label(data[active].date)}</p>
            {series.map((s) => <p key={s.key} className="flex justify-between gap-3 text-ink-700"><span>{s.label}</span><b className="tabular-nums">{String(data[active][s.key] ?? 0)}</b></p>)}
          </div>
        )}
      </div>
      <details className="mt-2 text-sm">
        <summary className="inline-flex min-h-11 items-center text-brand-700 hover:underline sm:min-h-8">View data as table</summary>
        <div className="max-h-56 overflow-auto rounded-xl border border-ink-100">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-ink-50"><tr><th className="px-3 py-2">Date</th>{series.map((s) => <th key={s.key} className="px-3 py-2">{s.label}</th>)}</tr></thead>
            <tbody>{data.map((d) => <tr key={d.date} className="border-t border-ink-100"><td className="px-3 py-1.5">{label(d.date)}</td>{series.map((s) => <td key={s.key} className="px-3 py-1.5 tabular-nums">{String(d[s.key] ?? 0)}</td>)}</tr>)}</tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
