"use client";
import { useState } from "react";
import { PerfTab } from "@/components/gbp/tools";
import { DateRange, presetRange } from "@/components/DateRange";
import { GbpFrame } from "@/components/gbp/GbpFrame";
import { KeywordsPanel, MetricGlossary, MonthlyTrend } from "@/components/gbp/Insights";
import { GoogleHistory } from "@/components/analytics/GoogleHistory";
import { PageHeader } from "@/components/ui/Card";

export default function PerformancePage() {
  const [range, setRange] = useState(presetRange("30"));
  return (
    <>
      <PageHeader title="Google activity" subtitle="How people found and used your Google profile. Google reports a few days late. This is not the same as card scans."
        actions={<DateRange value={range} onChange={setRange} />} />
      <div className="space-y-4">
        {/* One source for these numbers: what FlowQR stored from Google. The live detail below appears only once Google has really shared data, so a page never says
            "not shared yet" next to numbers. */}
        <GoogleHistory range={range} extra={(
          <details className="group rounded-[16px] bg-surface p-4 shadow-card">
            <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 text-[15px] font-semibold">More detail from Google<span aria-hidden className="text-ink-400 transition-transform group-open:rotate-180">&#9662;</span></summary>
            <div className="mt-3 space-y-4">
              <GbpFrame>{(gid) => <div className="space-y-4"><PerfTab key={gid} gid={gid} /><div className="grid gap-4 xl:grid-cols-2"><MonthlyTrend key={`m-${gid}`} gid={gid} /><KeywordsPanel key={`k-${gid}`} gid={gid} /></div><MetricGlossary /></div>}</GbpFrame>
            </div>
          </details>
        )} />
      </div>
    </>
  );
}
