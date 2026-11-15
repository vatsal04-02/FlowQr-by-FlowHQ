"use client";
import clsx from "clsx";
import { Check } from "lucide-react";
import { Hint } from "@/components/dashboard/Hint";
import { Alert, Skeleton } from "@/components/ui/Card";
import { Panel, Sparkline } from "@/components/ui/kit";
import type { Health } from "@/lib/agent";
import { useFetch } from "@/lib/use-api";

/** A score is only shown once at least this many of the measures have real data behind them (the backend's own minimum is lower). */
export const MIN_MEASURES_FOR_SCORE = 4;

/**
 * "How your business is doing". With too little real data it says so ("Getting started, 2 of 6 measures available") instead of
 * showing a number that would look perfect or poor on almost no evidence. `strip` is the slim version used on the dashboard.
 */
export function HealthCard({ compact = false, variant = "panel" }: { compact?: boolean; variant?: "panel" | "strip" }) {
  const { data: h, error, loading } = useFetch<Health>("/agent/health");
  if (loading && !h) return <Skeleton className={variant === "strip" ? "h-16" : "h-40"} />;
  if (error || !h) return <Alert tone="error" title="Couldn't load how your business is doing">{error}</Alert>;

  const total = h.components.length, have = h.components.filter((c) => c.available).length;
  const showScore = h.score !== null && have >= MIN_MEASURES_FOR_SCORE;
  const hist = h.history.filter((x) => x.score !== null).map((x) => x.score as number);
  const how = `${h.formula} A measure with no real data is left out instead of counted as zero, and no score is shown until ${MIN_MEASURES_FOR_SCORE} of the ${total} measures have data. The thresholds are FlowQR's own heuristics, not Google's rules, and the score does not predict growth.`;

  const headline = showScore ? (
    <div className="flex items-baseline gap-2">
      <p className="num text-4xl font-bold leading-none text-navy" aria-label={`Score ${h.score} out of 100`}>{h.score}<span className="text-base font-medium text-ink-400">/100</span></p>
      {hist.length > 1 && <Sparkline values={hist} color="rgb(var(--c-accent))" />}
    </div>
  ) : (
    <p className="text-lg font-semibold leading-tight text-navy">Getting started <span className="font-medium text-ink-500">· {have} of {total} business measures available</span></p>
  );
  const line = showScore ? (h.changes[0] ?? "") : have === 0 ? "Connect Google and put a card on your counter. Each one adds a measure here." : "A score appears once more of these have real data behind them.";

  const measures = (
    <ul className={clsx("flex flex-wrap gap-1.5", variant === "strip" ? "mt-3" : "mt-4")} aria-label="Business measures">
      {h.components.map((c) => (
        <li key={c.key} className={clsx("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[13px] font-medium", c.available ? "bg-green-50 text-green-900" : "bg-ink-100/70 text-ink-500")}>
          {c.available ? <Check className="h-3.5 w-3.5" strokeWidth={2.5} aria-hidden /> : <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-ink-300" />}
          {c.label}<span className="sr-only">{c.available ? " (available)" : " (no data yet)"}</span>
        </li>))}
    </ul>
  );

  if (variant === "strip") {
    return (
      <div>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
          <div className="flex items-center gap-1.5"><h3 className="text-sm font-semibold text-navy">How your business is doing</h3>
            <Hint label="How your business is doing" text="A simple check-up built only from numbers FlowQR really has. It stays hidden until there is enough data to be fair." /></div>
          {headline}
        </div>
        <p className="mt-1.5 text-sm text-ink-700">{line}</p>
        {measures}
        <details className="mt-2 text-[13px] text-ink-500"><summary className="inline-flex min-h-11 cursor-pointer items-center font-medium text-ink-700 sm:min-h-8">How this is worked out</summary><p className="max-w-3xl pb-1">{how}</p></details>
      </div>
    );
  }

  return (
    <Panel title="How your business is doing" meta={showScore ? `from ${have} of ${total} measures` : undefined}>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <div className="min-w-[96px]">{headline}</div>
        <p className="min-w-0 flex-1 text-sm text-ink-700">{line}</p>
      </div>
      {measures}
      {!compact && (
        <>
          <ul className="mt-4 divide-y divide-ink-100 border-t border-ink-100 text-sm" aria-label="How the score is made">
            {h.components.map((c) => (
              <li key={c.key} className="py-2.5">
                <div className="flex items-baseline justify-between gap-3"><span className="font-medium">{c.label}</span><span className="num text-ink-500">{c.available ? `${c.points?.toFixed(0)} of ${c.weight}` : `no data yet (${c.weight})`}</span></div>
                <p className="mt-0.5 text-[13px] text-ink-500">{c.detail}</p>
                {c.available && (c.value ?? 1) < 1 && <p className="text-[13px] text-ink-500">To improve: {c.improve}</p>}
              </li>))}
          </ul>
          {showScore && h.changes.length > 1 && <ul className="mt-3 list-disc space-y-1 pl-5 text-[13px] text-ink-700">{h.changes.slice(1).map((c) => <li key={c}>{c}</li>)}</ul>}
          <details className="mt-3 text-[13px] text-ink-500"><summary className="inline-flex min-h-11 cursor-pointer items-center font-medium text-ink-700 sm:min-h-8">How this is worked out</summary><p className="mt-1">{how}</p></details>
        </>)}
    </Panel>
  );
}
