"use client";
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { dayGap, runs, type Day } from "@/lib/charts";
import { smoothPath } from "./LineChart";

const PL = 30, PR = 8, PT = 12, PB = 24;
const label = (d: string) => new Date(d + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short" });

function niceTop(v: number) {
  if (v <= 4) return 4;
  const pow = Math.pow(10, Math.floor(Math.log10(v))), n = v / pow;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * pow;
}

/**
 * Stacked areas, one per series, drawn ONLY from days the API returned (`days` comes from dailyStack). A day nobody reported is a gap in the picture, never a zero and never joined across,
 * so the curve (monotone: it cannot rise above a real day) is exact. Hover, touch or the arrow keys read one day's numbers; "Table" gives all of them as text.
 */
export function AreaChart({ days, names, colors, ariaLabel, unit = "" }: { days: Day[]; names: string[]; colors: string[]; ariaLabel: string; unit?: string }) {
  const id = useId().replace(/:/g, "");
  const wrap = useRef<HTMLDivElement>(null);
  const [at, setAt] = useState<number | null>(null);
  const [table, setTable] = useState(false);
  // The drawing is as wide as its box, so text stays a readable 11px on a phone instead of shrinking with a fixed 640-unit canvas.
  const [W, setW] = useState(640);
  useEffect(() => {
    const el = wrap.current; if (!el) return;
    const set = () => setW(Math.max(260, Math.round(el.getBoundingClientRect().width)));
    set(); const ro = new ResizeObserver(set); ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const H = W < 420 ? 180 : 210, pw = W - PL - PR, ph = H - PT - PB, base = PT + ph;
  const rr = useMemo(() => runs(days), [days]);
  const geo = useMemo(() => {
    const first = days[0].date, span = Math.max(1, dayGap(first, days[days.length - 1].date));
    const x = (date: string) => PL + (dayGap(first, date) / span) * pw;
    const cum = (d: Day) => d.values.reduce<number[]>((a, v) => (a.push((a[a.length - 1] ?? 0) + v), a), []);
    const top = niceTop(Math.max(1, ...days.map((d) => cum(d)[d.values.length - 1])));
    const y = (v: number) => PT + ph - (v / top) * ph;
    return { first, span, x, y, top, cum };
  }, [days, pw, ph]);
  const layers = useMemo(() => {
    const out: { k: number; area: string; line: string }[] = [];
    for (let k = names.length - 1; k >= 0; k--) {
      let area = "", line = "";
      for (const run of rr) {
        const upper = run.map((d) => [geo.x(d.date), Math.min(base, geo.y(geo.cum(d)[k]))] as [number, number]);
        const lower = run.map((d) => [geo.x(d.date), k ? Math.min(base, geo.y(geo.cum(d)[k - 1])) : base] as [number, number]);
        if (run.length === 1) continue; // a single day has no line to draw; it is still in the tooltip and the table
        line += (line ? " " : "") + smoothPath(upper);
        area += (area ? " " : "") + smoothPath(upper) + " " + smoothPath([...lower].reverse()).replace(/^M/, "L") + "Z";
      }
      out.push({ k, area, line });
    }
    return out;
  }, [rr, names.length, geo, base]);

  const nearest = (clientX: number) => {
    const el = wrap.current; if (!el) return;
    const r = el.getBoundingClientRect(), vx = ((clientX - r.left) / r.width) * W;
    let best = 0, bd = Infinity;
    days.forEach((d, i) => { const dd = Math.abs(geo.x(d.date) - vx); if (dd < bd) { bd = dd; best = i; } });
    setAt(best);
  };
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "ArrowRight") { e.preventDefault(); setAt((a) => Math.min(days.length - 1, (a ?? -1) + 1)); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); setAt((a) => Math.max(0, (a ?? days.length) - 1)); }
    else if (e.key === "Escape") setAt(null);
  };
  const sel = at !== null ? days[at] : null, px = sel ? (geo.x(sel.date) / W) * 100 : 0;
  const ticks = [0, 0.5, 1];
  const xs = (W < 420 ? [0, 0.5, 1] : [0, 0.25, 0.5, 0.75, 1]).map((f) => { const d = new Date(geo.first + "T00:00:00"); d.setDate(d.getDate() + Math.round(f * geo.span)); return { f, d: d.toISOString().slice(0, 10) }; });

  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-ink-700">{names.map((n, k) => <span key={n} className="inline-flex items-center gap-1.5"><i aria-hidden className="h-2.5 w-2.5 rounded-[3px]" style={{ background: colors[k] }} />{n}</span>)}</div>
      <div ref={wrap} tabIndex={0} role="img" aria-label={`${ariaLabel}. Use the left and right arrow keys to read each day.`} onKeyDown={onKey} onPointerMove={(e: PointerEvent) => nearest(e.clientX)} onPointerLeave={() => setAt(null)} onBlur={() => setAt(null)}
        className="relative cursor-crosshair rounded-[10px] outline-offset-2" style={{ animation: "chart-reveal 1.4s cubic-bezier(.2,.7,.2,1) .2s both" }}>
        <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full overflow-visible" aria-hidden>
          <defs>{names.map((_, k) => <linearGradient key={k} id={`ag${id}${k}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={colors[k]} stopOpacity=".6" /><stop offset="1" stopColor={colors[k]} stopOpacity=".12" /></linearGradient>)}</defs>
          {ticks.map((t) => <g key={t}><line x1={PL} x2={W - PR} y1={geo.y(geo.top * t)} y2={geo.y(geo.top * t)} stroke="rgb(var(--c-line))" strokeDasharray="3 4" /><text x={PL - 6} y={geo.y(geo.top * t) + 4} textAnchor="end" fontSize="11" fill="rgb(var(--c-muted))">{Math.round(geo.top * t)}</text></g>)}
          {layers.map((l) => <g key={l.k}><path d={l.area} fill={`url(#ag${id}${l.k})`} /><path d={l.line} fill="none" stroke={colors[l.k]} strokeWidth="2" strokeLinecap="round" /></g>)}
          {days.length < 40 && days.map((d) => rr.some((r) => r.length === 1 && r[0].date === d.date) && <circle key={d.date} cx={geo.x(d.date)} cy={geo.y(geo.cum(d)[names.length - 1])} r="3" fill={colors[names.length - 1]} />)}
          {sel && <><line x1={geo.x(sel.date)} x2={geo.x(sel.date)} y1={PT} y2={base} stroke="rgb(var(--c-ink-400))" strokeDasharray="3 3" />
            {names.map((_, k) => <circle key={k} cx={geo.x(sel.date)} cy={geo.y(geo.cum(sel)[k])} r="4.5" fill="rgb(var(--c-surface))" stroke={colors[k]} strokeWidth="2.5" />)}</>}
          {xs.map(({ f, d }, i) => <text key={f} x={PL + f * pw} y={H - 6} textAnchor={i === 0 ? "start" : i === xs.length - 1 ? "end" : "middle"} fontSize="11" fill="rgb(var(--c-muted))">{label(d)}</text>)}
        </svg>
        {sel && (
          <div role="status" className="pointer-events-none absolute top-1 z-10 grid min-w-[150px] gap-1 rounded-[12px] bg-ink-solid px-3 py-2 text-[13px] text-ink-on shadow-lift"
            style={{ left: `${px}%`, transform: px > 78 ? "translateX(-100%)" : px < 22 ? "translateX(0)" : "translateX(-50%)" }}>
            <b>{label(sel.date)}</b>
            {names.map((n, k) => <span key={n} className="flex items-center gap-2"><i aria-hidden className="h-2 w-2 rounded-[2px]" style={{ background: colors[k] }} />{n}<b className="num ml-auto pl-4">{sel.values[k]}</b></span>)}
            <span className="flex border-t border-white/20 pt-1">Total<b className="num ml-auto">{sel.values.reduce((a, b) => a + b, 0)}</b></span>
          </div>
        )}
      </div>
      <div className="mt-2 flex items-center justify-between gap-2 text-[13px] text-muted">
        <span>{days.length} {days.length === 1 ? "day" : "days"} reported by Google{unit ? ` · ${unit}` : ""}</span>
        <button type="button" onClick={() => setTable((t) => !t)} aria-expanded={table} className="!min-h-0 font-medium text-ink-600 underline underline-offset-2">{table ? "Hide table" : "Table"}</button>
      </div>
      {table && (
        <div className="mt-2 max-h-56 overflow-auto"><table className="w-full text-left text-[13px]"><thead><tr className="text-muted"><th className="py-1 font-medium">Day</th>{names.map((n) => <th key={n} className="py-1 text-right font-medium">{n}</th>)}</tr></thead>
          <tbody>{days.map((d) => <tr key={d.date} className="border-t border-line"><td className="py-1">{label(d.date)}</td>{d.values.map((v, k) => <td key={k} className="num py-1 text-right">{v}</td>)}</tr>)}</tbody></table></div>
      )}
    </div>
  );
}
