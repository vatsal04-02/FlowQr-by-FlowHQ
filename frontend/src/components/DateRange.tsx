"use client";
import { useState } from "react";
import { Segmented } from "./ui/kit";
import { isoDay } from "@/lib/format";

export type Range = { from: string; to: string; preset: string };
export function presetRange(preset: string): Range {
  const days = Number(preset);
  const to = new Date(), from = new Date();
  from.setDate(to.getDate() - (days - 1));
  return { from: isoDay(from), to: isoDay(to), preset };
}

const input = "min-h-11 rounded-lg border border-ink-300 bg-white px-2.5 text-sm text-ink sm:min-h-8";

/** Presets as a segmented control; "Custom" reveals the two date inputs. */
export function DateRange({ value, onChange }: { value: Range; onChange: (r: Range) => void }) {
  const [custom, setCustom] = useState(value.preset === "custom");
  const current = custom || value.preset === "custom" ? "custom" : value.preset;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Segmented label="Date range" value={current} options={[["7", "7d"], ["30", "30d"], ["90", "90d"], ["365", "12m"], ["custom", "Custom"]] as const}
        onChange={(v) => { if (v === "custom") { setCustom(true); onChange({ ...value, preset: "custom" }); } else { setCustom(false); onChange(presetRange(v)); } }} />
      {current === "custom" && (
        <span className="flex items-center gap-1.5">
          <input type="date" aria-label="From date" value={value.from} max={value.to} onChange={(e) => onChange({ ...value, from: e.target.value, preset: "custom" })} className={input} />
          <span className="text-ink-400" aria-hidden>–</span>
          <input type="date" aria-label="To date" value={value.to} min={value.from} max={isoDay(new Date())} onChange={(e) => onChange({ ...value, to: e.target.value, preset: "custom" })} className={input} />
        </span>
      )}
    </div>
  );
}
