"use client";
import clsx from "clsx";
import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

export interface Col<T> {
  key: string; header: string;
  cell: (row: T) => ReactNode;
  align?: "right";
  /** the one column that becomes the card's title on a phone (the first column by default) */
  title?: boolean;
  /** leave this column out of the phone card (it stays in the table) */
  tableOnly?: boolean;
  /** makes the header a sort button: compare two rows, ascending */
  sort?: (a: T, b: T) => number;
}
export interface BulkAction<T> { label: string; run: (rows: T[]) => void | Promise<void>; danger?: boolean }

/**
 * A table on tablet and desktop, a list of compact cards on a phone. No wide table ever forces sideways scrolling on a small screen: each row becomes a card whose first column is
 * the title and whose other columns are short "label  value" lines. Only one of the two is rendered by the browser at a time (the other is display:none), so screen readers hear it once.
 * Optional: `sort` on a column makes its header sortable; `bulk` adds row checkboxes, a select-all, and a bar of actions for the chosen rows.
 */
export function DataTable<T>({ rows, cols, rowKey, label, className, bulk }: { rows: T[]; cols: Col<T>[]; rowKey: (r: T) => string; label: string; className?: string; bulk?: BulkAction<T>[] }) {
  const titleCol = cols.find((c) => c.title) ?? cols[0];
  const rest = cols.filter((c) => c !== titleCol && !c.tableOnly);
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);

  const shown = useMemo(() => {
    const c = sort && cols.find((x) => x.key === sort.key)?.sort;
    return c && sort ? [...rows].sort((a, b) => c(a, b) * sort.dir) : rows;
  }, [rows, cols, sort]);
  // a row that is no longer in the list can't stay selected
  const live = useMemo(() => new Set(rows.map(rowKey)), [rows, rowKey]);
  const chosen = shown.filter((r) => picked.has(rowKey(r)) && live.has(rowKey(r)));
  const all = shown.length > 0 && chosen.length === shown.length;
  const toggle = (k: string) => setPicked((p) => { const n = new Set(p); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  const toggleAll = () => setPicked(all ? new Set() : new Set(shown.map(rowKey)));
  const nextSort = (key: string) => setSort((s) => (!s || s.key !== key ? { key, dir: 1 } : s.dir === 1 ? { key, dir: -1 } : null));
  const run = async (a: BulkAction<T>) => { setBusy(true); try { await a.run(chosen); setPicked(new Set()); } finally { setBusy(false); } };
  const box = "h-[18px] w-[18px] rounded-md";

  return (
    <div className={className}>
      {bulk && chosen.length > 0 && (
        <div role="region" aria-label="Actions for selected rows" className="fq-enter mb-3 flex flex-wrap items-center gap-2 rounded-full bg-ink-solid px-4 py-2 text-ink-on shadow-lift">
          <span className="mr-auto text-sm font-semibold">{chosen.length} selected</span>
          {bulk.map((a) => (
            <button key={a.label} type="button" disabled={busy} onClick={() => void run(a)} className={clsx("tap rounded-full px-4 text-[13px] font-semibold disabled:opacity-60 sm:min-h-9", a.danger ? "bg-neg text-pure-white" : "bg-white/15 hover:bg-white/25")}>{a.label}</button>
          ))}
          <button type="button" onClick={() => setPicked(new Set())} className="tap rounded-full px-3 text-[13px] font-medium opacity-80 hover:opacity-100 sm:min-h-9">Clear</button>
        </div>
      )}
      <div className="hidden overflow-x-auto sm:block">
        <table className="dt w-full" aria-label={label}>
          <thead><tr>
            {bulk && <th className="w-10"><input type="checkbox" aria-label="Select all rows" checked={all} ref={(el) => { if (el) el.indeterminate = chosen.length > 0 && !all; }} onChange={toggleAll} className={box} /></th>}
            {cols.map((c) => {
              const on = sort?.key === c.key;
              return (
                <th key={c.key} className={clsx(c.align === "right" && "!text-right")} aria-sort={on ? (sort!.dir === 1 ? "ascending" : "descending") : c.sort ? "none" : undefined}>
                  {c.sort
                    ? <button type="button" onClick={() => nextSort(c.key)} className={clsx("inline-flex items-center gap-1 rounded-md font-[inherit] hover:text-ink", on && "text-ink")}>{c.header}{on ? (sort!.dir === 1 ? <ArrowUp className="h-3 w-3" aria-hidden /> : <ArrowDown className="h-3 w-3" aria-hidden />) : <ChevronsUpDown className="h-3 w-3 opacity-40" aria-hidden />}</button>
                    : c.header}
                </th>
              );
            })}
          </tr></thead>
          <tbody>{shown.map((r) => {
            const k = rowKey(r);
            return (
              <tr key={k} className={clsx(picked.has(k) && "bg-accent-tint/40")}>
                {bulk && <td><input type="checkbox" aria-label="Select row" checked={picked.has(k)} onChange={() => toggle(k)} className={box} /></td>}
                {cols.map((c) => <td key={c.key} className={clsx(c.align === "right" && "!text-right")}>{c.cell(r)}</td>)}
              </tr>
            );
          })}</tbody>
        </table>
      </div>
      <ul aria-label={label} className="space-y-2 sm:hidden">
        {shown.map((r) => {
          const k = rowKey(r);
          return (
            <li key={k} className={clsx("rounded-xl bg-surface-2 p-3", picked.has(k) && "ring-2 ring-accent")}>
              <div className="flex items-start gap-3">
                {bulk && <input type="checkbox" aria-label="Select row" checked={picked.has(k)} onChange={() => toggle(k)} className={clsx(box, "mt-0.5 shrink-0")} />}
                <div className="min-w-0 flex-1 text-[15px] font-semibold leading-5">{titleCol.cell(r)}</div>
              </div>
              <dl className="mt-2 grid grid-cols-[auto_minmax(0,1fr)] items-baseline gap-x-4 gap-y-1 text-[13px]">
                {rest.map((c) => (<div key={c.key} className="contents"><dt className="text-muted">{c.header}</dt><dd className="min-w-0 text-right font-medium">{c.cell(r)}</dd></div>))}
              </dl>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
