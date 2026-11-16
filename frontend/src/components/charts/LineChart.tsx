"use client";
import { useEffect, useId, useMemo, useRef, useState } from "react";

export interface Series { key: string; label: string; color: string; dash?: string; /** fill under the first series (defaults to its line colour) */ area?: string }
type Point = { date: string; [k: string]: number | string };

function niceMax(v: number) {
  if (v <= 4) return 4;
  const pow = Math.pow(10, Math.floor(Math.log10(v)));
  const n = v / pow;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * pow;
}

/** Smooth line through the points (monotone cubic, so it never dips below a real value or overshoots between two days). */
export function smoothPath(pts: [number, number][]) {
  const n = pts.length;
  if (n === 0) return "";
  if (n < 3) return pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
  const dx: number[] = [], m: number[] = [];
  for (let i = 0; i < n - 1; i++) { dx[i] = pts[i + 1][0] - pts[i][0] || 1; m[i] = (pts[i + 1][1] - pts[i][1]) / dx[i]; }
  const t: number[] = [m[0]];
  for (let i = 1; i < n - 1; i++) t[i] = m[i - 1] * m[i] <= 0 ? 0 : (m[i - 1] + m[i]) / 2;
  t[n - 1] = m[n - 2];
  for (let i = 0; i < n - 1; i++) {
    if (m[i] === 0) { t[i] = 0; t[i + 1] = 0; continue; }
    const a = t[i] / m[i], b = t[i + 1] / m[i], h = Math.hypot(a, b);
    if (h > 3) { t[i] = (3 * a / h) * m[i]; t[i + 1] = (3 * b / h) * m[i]; }
  }
  let d = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < n - 1; i++) {
    const h = dx[i] / 3;
    d += ` C${(pts[i][0] + h).toFixed(1)},${(pts[i][1] + t[i] * h).toFixed(1)} ${(pts[i + 1][0] - h).toFixed(1)},${(pts[i + 1][1] - t[i + 1] * h).toFixed(1)} ${pts[i + 1][0].toFixed(1)},${pts[i + 1][1].toFixed(1)}`;
  }
  return d;
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
export function LineChart({ data, series, height = 230, ariaLabel, yMax: yMaxProp, gaps = false }: { data: Point[]; series: Series[]; height?: number; ariaLabel: string; yMax?: number; gaps?: boolean }) {
  const [ref, width] = useWidth();
  const gid = useId().replace(/:/g, "");
  const [active, setActive] = useState<number | null>(null);
  const pad = { l: 36, r: 12, t: 12, b: 26 };
  const iw = width - pad.l - pad.r, ih = height - pad.t - pad.b;

  const yMax = useMemo(() => yMaxProp ?? niceMax(Math.max(0, ...data.flatMap((d) => series.map((s) => Number(d[s.key]) || 0)))), [data, series, yMaxProp]);
  const x = (i: number) => pad.l + (data.length <= 1 ? iw / 2 : (i / (data.length - 1)) * iw);
  const y = (v: number) => pad.t + ih - (v / yMax) * ih;
  // whole-number ticks only: quarters when they divide evenly, halves otherwise
  const ticks = yMax <= 6 && Number.isInteger(yMax) ? Array.from({ length: yMax + 1 }, (_, i) => i) : (yMax % 4 === 0 ? [0, 0.25, 0.5, 0.75, 1] : [0, 0.5, 1]).map((t) => t * yMax);
  const xStep = Math.max(1, Math.ceil(data.length / Math.max(2, Math.floor(iw / 80))));
  const label = (iso: string) => new Date(iso + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short" });

  const onMove = (clientX: number, rect: DOMRect) => {
    const rel = clientX - rect.left - pad.l;
    setActive(Math.min(data.length - 1, Math.max(0, Math.round((rel / iw) * (data.length - 1)))));
  };
  const empty = data.length === 0 || series.every((s) => data.every((d) => !Number(d[s.key])));
  // With `gaps`, a zero means "no data that day" (e.g. average rating), so the line breaks instead of plunging to 0.
  const pathFor = (key: string) => {
    if (!gaps) return smoothPath(data.map((row, i) => [x(i), y(Number(row[key]) || 0)] as [number, number]));
    let d = "", pen = false;
    data.forEach((row, i) => {
      const v = Number(row[key]) || 0;
      if (gaps && v <= 0) { pen = false; return; }
      d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)} `; pen = true;
    });
    return d.trim();
  };

  return (
    <div>
      <ul className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-[13px] font-medium text-ink-700">
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
              <line x1={pad.l} x2={width - pad.r} y1={y(t)} y2={y(t)} stroke="rgb(var(--c-ink-100))" strokeWidth="1" strokeDasharray="2 4" />
              <text x={pad.l - 8} y={y(t) + 4} textAnchor="end" fontSize="12" fill="rgb(var(--c-ink-500))">{Number.isInteger(t) ? t : t.toFixed(1)}</text>
            </g>
          ))}
          {data.map((d, i) => i % xStep === 0 && (
            <text key={d.date} x={x(i)} y={height - 6} textAnchor="middle" fontSize="12" fill="rgb(var(--c-ink-500))">{label(d.date)}</text>
          ))}
          <defs>
            {series.map((s) => (
              <linearGradient key={s.key} id={`${gid}-${s.key}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={s.area ?? s.color} stopOpacity=".32" /><stop offset="100%" stopColor={s.area ?? s.color} stopOpacity="0" />
              </linearGradient>
            ))}
          </defs>
          {/* Keyed on the data so the left-to-right reveal replays when the range or location changes. */}
          <g key={`${data.length}-${data[0]?.date}-${data[data.length - 1]?.date}`} style={{ animation: "chart-reveal .7s cubic-bezier(.22,1,.36,1) both" }}>
            {series.length > 0 && data.length > 1 && !gaps && (
              <path fill={`url(#${gid}-${series[0].key})`} stroke="none"
                d={`${pathFor(series[0].key)} L${x(data.length - 1).toFixed(1)},${y(0)} L${x(0).toFixed(1)},${y(0)} Z`} />
            )}
            {series.map((s) => (
              <g key={s.key}>
                <path fill="none" stroke={s.color} strokeWidth={s.dash ? 1.75 : 2.75} strokeLinejoin="round" strokeLinecap="round" strokeDasharray={s.dash} d={pathFor(s.key)} />
                {gaps && data.map((d, i) => Number(d[s.key]) > 0 && <circle key={d.date} cx={x(i)} cy={y(Number(d[s.key]))} r="2.5" fill={s.color} />)}
              </g>
            ))}
            {/* the latest value, marked so the eye lands on where things stand now */}
            {!gaps && !empty && data.length > 1 && (
              <g>
                <circle cx={x(data.length - 1)} cy={y(Number(data[data.length - 1][series[0].key]) || 0)} r="9" fill={series[0].color} opacity=".16" />
                <circle cx={x(data.length - 1)} cy={y(Number(data[data.length - 1][series[0].key]) || 0)} r="4.5" fill={series[0].color} stroke="rgb(var(--c-surface))" strokeWidth="2" />
              </g>
            )}
          </g>
          {active !== null && data[active] && (
            <g>
              <rect x={x(active) - 9} y={pad.t} width="18" height={ih} rx="9" fill="rgb(var(--c-ink) / .05)" />
              <line x1={x(active)} x2={x(active)} y1={pad.t} y2={pad.t + ih} stroke="rgb(var(--c-ink-300))" strokeDasharray="3 3" />
              {series.map((s) => <circle key={s.key} cx={x(active)} cy={y(Number(data[active][s.key]) || 0)} r="5" fill="rgb(var(--c-surface))" stroke={s.color} strokeWidth="3" />)}
            </g>
          )}
        </svg>}
        {empty && <p className="pointer-events-none absolute inset-0 grid place-items-center text-sm text-ink-400">No data in this period yet</p>}
        {active !== null && data[active] && (
          <div className="pointer-events-none absolute top-2 z-10 min-w-[150px] rounded-xl bg-surface p-3 text-xs text-ink shadow-lift ring-1 ring-ink-100"
            style={{ left: Math.min(Math.max(x(active) - 75, 0), width - 160) }}>
            <p className="mb-1.5 font-semibold text-ink-500">{label(data[active].date)}</p>
            {series.map((s) => (
              <p key={s.key} className="flex items-center justify-between gap-4 py-0.5">
                <span className="flex items-center gap-2"><svg width="14" height="6" aria-hidden><line x1="0" y1="3" x2="14" y2="3" stroke={s.color} strokeWidth="3" strokeDasharray={s.dash ? "3 2" : undefined} strokeLinecap="round" /></svg>{s.label}</span>
                <b className="text-[13px] tabular-nums">{String(data[active][s.key] ?? 0)}</b>
              </p>
            ))}
          </div>
        )}
      </div>
      <details className="mt-2 text-sm">
        <summary className="inline-flex min-h-11 items-center font-medium text-accent-ink hover:underline sm:min-h-8">View data as table</summary>
        <div className="max-h-56 overflow-auto rounded-inner bg-surface-2">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-surface-3"><tr><th className="px-3 py-2">Date</th>{series.map((s) => <th key={s.key} className="px-3 py-2">{s.label}</th>)}</tr></thead>
            <tbody>{data.map((d) => <tr key={d.date} className="border-t border-ink-100"><td className="px-3 py-1.5">{label(d.date)}</td>{series.map((s) => <td key={s.key} className="px-3 py-1.5 tabular-nums">{String(d[s.key] ?? 0)}</td>)}</tr>)}</tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
