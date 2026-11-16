"use client";
import clsx from "clsx";
import type { ReactNode } from "react";

export interface Col<T> {
  key: string; header: string;
  cell: (row: T) => ReactNode;
  align?: "right";
  /** the one column that becomes the card's title on a phone (the first column by default) */
  title?: boolean;
  /** leave this column out of the phone card (it stays in the table) */
  tableOnly?: boolean;
}

/**
 * A table on tablet and desktop, a list of compact cards on a phone. No wide table ever forces sideways scrolling on a small screen: each row becomes a card whose first column is
 * the title and whose other columns are short "label  value" lines. Only one of the two is rendered by the browser at a time (the other is display:none), so screen readers hear it once.
 */
export function DataTable<T>({ rows, cols, rowKey, label, className }: { rows: T[]; cols: Col<T>[]; rowKey: (r: T) => string; label: string; className?: string }) {
  const titleCol = cols.find((c) => c.title) ?? cols[0];
  const rest = cols.filter((c) => c !== titleCol && !c.tableOnly);
  return (
    <div className={className}>
      <div className="hidden overflow-x-auto sm:block">
        <table className="dt w-full" aria-label={label}>
          <thead><tr>{cols.map((c) => <th key={c.key} className={clsx(c.align === "right" && "!text-right")}>{c.header}</th>)}</tr></thead>
          <tbody>{rows.map((r) => <tr key={rowKey(r)}>{cols.map((c) => <td key={c.key} className={clsx(c.align === "right" && "!text-right")}>{c.cell(r)}</td>)}</tr>)}</tbody>
        </table>
      </div>
      <ul aria-label={label} className="space-y-2 sm:hidden">
        {rows.map((r) => (
          <li key={rowKey(r)} className="rounded-xl bg-surface-2 p-3">
            <div className="text-[15px] font-semibold leading-5">{titleCol.cell(r)}</div>
            <dl className="mt-2 grid grid-cols-[auto_minmax(0,1fr)] items-baseline gap-x-4 gap-y-1 text-[13px]">
              {rest.map((c) => (<div key={c.key} className="contents"><dt className="text-muted">{c.header}</dt><dd className="min-w-0 text-right font-medium">{c.cell(r)}</dd></div>))}
            </dl>
          </li>
        ))}
      </ul>
    </div>
  );
}
