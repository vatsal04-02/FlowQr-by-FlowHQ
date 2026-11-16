"use client";
import { Segmented } from "@/components/ui/kit";
import { DAY_OPTIONS, type Days } from "@/lib/dashboard";

/** 7 / 30 / 90 days. One piece of state on the dashboard drives every number and chart, so the page never disagrees with itself. */
export function RangePicker({ days, onChange, label = "Show the last" }: { days: Days; onChange: (d: Days) => void; label?: string }) {
  return <Segmented label={label} value={String(days)} options={DAY_OPTIONS.map(([d, l]) => [String(d), l] as const)} onChange={(v) => onChange(Number(v) as Days)} />;
}
