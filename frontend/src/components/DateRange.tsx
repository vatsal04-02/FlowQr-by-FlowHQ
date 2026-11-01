"use client";
import { FilterSelect } from "./ui/Form";
import { isoDay } from "@/lib/format";

export type Range = { from: string; to: string; preset: string };
export function presetRange(preset: string): Range {
  const days = Number(preset);
  const to = new Date(), from = new Date();
  from.setDate(to.getDate() - (days - 1));
  return { from: isoDay(from), to: isoDay(to), preset };
}

export function DateRange({ value, onChange }: { value: Range; onChange: (r: Range) => void }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <FilterSelect label="Date range" value={value.preset} onChange={(e) => e.target.value !== "custom" && onChange(presetRange(e.target.value))}>
        <option value="7">Last 7 days</option><option value="30">Last 30 days</option><option value="90">Last 90 days</option><option value="365">Last 12 months</option>
        {value.preset === "custom" && <option value="custom">Custom</option>}
      </FilterSelect>
      <input type="date" aria-label="From date" value={value.from} max={value.to} onChange={(e) => onChange({ ...value, from: e.target.value, preset: "custom" })} className="min-h-11 rounded-xl border border-ink-200 px-3 text-sm sm:min-h-10" />
      <span className="text-ink-400" aria-hidden>→</span>
      <input type="date" aria-label="To date" value={value.to} min={value.from} max={isoDay(new Date())} onChange={(e) => onChange({ ...value, to: e.target.value, preset: "custom" })} className="min-h-11 rounded-xl border border-ink-200 px-3 text-sm sm:min-h-10" />
    </div>
  );
}
