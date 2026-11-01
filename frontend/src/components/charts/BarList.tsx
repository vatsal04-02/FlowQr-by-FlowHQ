import clsx from "clsx";

/** Horizontal bars with the value printed as text (colour is never the only signal). */
export function BarList({ rows, color = "bg-brand-500" }: { rows: { label: string; value: number; sub?: string }[]; color?: string }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <ul className="space-y-2.5">
      {rows.map((r) => (
        <li key={r.label} className="grid grid-cols-[84px_1fr_auto] items-center gap-3 text-sm sm:grid-cols-[120px_1fr_auto]">
          <span className="truncate text-ink-700" title={r.label}>{r.label}</span>
          <span className="h-2.5 overflow-hidden rounded-full bg-ink-50"><span className={clsx("block h-full rounded-full", color)} style={{ width: `${(r.value / max) * 100}%` }} /></span>
          <span className="tabular-nums font-semibold">{r.value}{r.sub && <span className="ml-1 font-normal text-ink-400">{r.sub}</span>}</span>
        </li>
      ))}
    </ul>
  );
}
