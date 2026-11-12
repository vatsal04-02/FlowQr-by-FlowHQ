"use client";
import { Sparkline } from "@/components/ui/kit";
import { Alert, Skeleton } from "@/components/ui/Card";
import { Panel } from "@/components/ui/kit";
import type { Health } from "@/lib/agent";
import { useFetch } from "@/lib/use-api";

export function HealthCard({ compact = false }: { compact?: boolean }) {
  const { data: h, error, loading } = useFetch<Health>("/agent/health");
  if (loading && !h) return <Skeleton className="h-40" />;
  if (error || !h) return <Alert tone="error" title="Couldn't load the health score">{error}</Alert>;
  const hist = h.history.filter((x) => x.score !== null).map((x) => x.score as number);
  return (
    <Panel title="Business health" meta={h.score !== null ? `based on ${h.components.filter((c) => c.available).length} of ${h.components.length} measures` : undefined}>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <div className="min-w-[96px]">
          {h.score !== null ? <><p className="num text-5xl font-bold leading-none" aria-label={`Health score ${h.score} out of 100`}>{h.score}<span className="text-lg font-medium text-ink-400">/100</span></p>{hist.length > 1 && <div className="mt-2"><Sparkline values={hist} /></div>}</>
            : <p className="text-lg font-semibold text-ink-500">No score yet</p>}
        </div>
        <p className="min-w-0 flex-1 text-sm text-ink-700">{h.score !== null ? (h.changes[0] ?? "") : h.message}</p>
      </div>
      {!compact && (
        <>
          <ul className="mt-4 divide-y divide-ink-100 border-t border-ink-100 text-sm" aria-label="How the score is made">
            {h.components.map((c) => (
              <li key={c.key} className="py-2.5">
                <div className="flex items-baseline justify-between gap-3"><span className="font-medium">{c.label}</span><span className="num text-ink-500">{c.available ? `${c.points?.toFixed(0)} of ${c.weight}` : `no data (${c.weight})`}</span></div>
                <p className="mt-0.5 text-[13px] text-ink-500">{c.detail}</p>
                {c.available && (c.value ?? 1) < 1 && <p className="text-[13px] text-ink-500">To improve: {c.improve}</p>}
              </li>))}
          </ul>
          {h.changes.length > 1 && <ul className="mt-3 list-disc space-y-1 pl-5 text-[13px] text-ink-700">{h.changes.slice(1).map((c) => <li key={c}>{c}</li>)}</ul>}
          <details className="mt-3 text-[13px] text-ink-500"><summary className="cursor-pointer font-medium text-ink-700">How this is calculated</summary><p className="mt-1">{h.formula} A measure with no real data is left out instead of counted as zero. The 4-a-month and 4-reviews thresholds are FlowQR&rsquo;s own heuristics, not Google&rsquo;s rules, and the score does not predict growth.</p></details>
        </>)}
    </Panel>
  );
}
