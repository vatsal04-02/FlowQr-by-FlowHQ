import { smoothPath } from "./LineChart";

/** A tiny trend line for a tile. Decorative: the number beside it carries the meaning, so it is hidden from screen readers. */
/** `fit` scales the line between the lowest and highest value instead of from zero, so a slow climb (a competitor's review count) is visible. Without it the line is honest about size. */
export function Sparkline({ values, width = 64, height = 28, color = "currentColor", id, fit = false }: { values: number[]; width?: number; height?: number; color?: string; id: string; fit?: boolean }) {
  if (values.length < 2 || values.every((v) => v === 0)) return null;
  const max = Math.max(...values, 1), min = fit ? Math.min(...values) : 0, span = Math.max(1e-9, max - min), pad = 3;
  const pts = values.map((v, i) => [pad + (i / (values.length - 1)) * (width - pad * 2), height - pad - ((v - min) / span) * (height - pad * 2)] as [number, number]);
  const line = smoothPath(pts), last = pts[pts.length - 1];
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden className="block overflow-visible">
      <defs><linearGradient id={id} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={color} stopOpacity=".28" /><stop offset="100%" stopColor={color} stopOpacity="0" /></linearGradient></defs>
      <path d={line} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={last[0]} cy={last[1]} r="3" fill={color} />
    </svg>
  );
}
