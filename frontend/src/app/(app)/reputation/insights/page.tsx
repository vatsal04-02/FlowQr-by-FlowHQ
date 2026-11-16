"use client";
import { Lock } from "lucide-react";
import { useEffect, useState } from "react";
import { DateRange, presetRange } from "@/components/DateRange";
import { LinkButton } from "@/components/ui/Button";
import { Alert, Badge, PageHeader, Skeleton } from "@/components/ui/Card";
import { Panel } from "@/components/ui/kit";
import { api, errorMessage } from "@/lib/api";
import type { Insights, Location } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

const pct = (n: number, t: number) => (t ? Math.round((n / t) * 100) : 0);

/** One sentiment bar: positive (ink), neutral (grey), negative (orange), with the numbers as text. */
function SentimentBar({ s }: { s: Insights["sentiment"] }) {
  const t = s.positive + s.neutral + s.negative;
  return (
    <div>
      <div className="flex h-3 gap-[3px]" role="img" aria-label={`${pct(s.positive, t)}% positive, ${pct(s.neutral, t)}% neutral, ${pct(s.negative, t)}% negative`}>
        {s.positive > 0 && <i className="grow-x block rounded-full bg-ink-solid" style={{ width: `${pct(s.positive, t)}%` }} />}
        {s.neutral > 0 && <i className="block rounded-full bg-surface-3" style={{ width: `${pct(s.neutral, t)}%` }} />}
        {s.negative > 0 && <i className="block rounded-full bg-accent" style={{ width: `${pct(s.negative, t)}%` }} />}
      </div>
      <p className="mt-2 text-xs text-muted"><b className="font-semibold text-ink">{pct(s.positive, t)}%</b> positive · {pct(s.neutral, t)}% neutral · {pct(s.negative, t)}% negative</p>
    </div>
  );
}

/**
 * AI › Insights (PRD §6.3): sentiment split, recurring topics with an example line from a real review, and the same split per location.
 * The method is shown as the server reports it (keyword heuristic today), never dressed up as more than it is.
 */
export default function InsightsPage() {
  const [range, setRange] = useState(presetRange("30"));
  const ins = useFetch<Insights>("/analytics/insights", { from: range.from, to: range.to });
  const locs = useFetch<Location[]>("/locations");
  const [byLoc, setByLoc] = useState<{ name: string; data: Insights | null; error: string | null }[] | null>(null);
  const active = (locs.data ?? []).filter((l) => l.is_active);
  const locked = ins.error?.toLowerCase().includes("plan") || ins.error?.toLowerCase().includes("subscription");

  useEffect(() => {
    if (active.length < 2) { setByLoc(null); return; }
    let live = true;
    void Promise.all(active.slice(0, 8).map(async (l) => {
      try { return { name: l.name, data: await api<Insights>("/analytics/insights", { params: { from: range.from, to: range.to, location_id: l.id } }), error: null }; }
      catch (e) { return { name: l.name, data: null, error: errorMessage(e) }; }
    })).then((r) => { if (live) setByLoc(r); });
    return () => { live = false; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [range.from, range.to, active.map((l) => l.id).join()]);

  const d = ins.data;
  return (
    <>
      <PageHeader title="What customers are saying" subtitle="The things customers mention most in their reviews, and how they feel about them." actions={<DateRange value={range} onChange={setRange} />} />
      {ins.loading && !d ? <Skeleton className="h-64" /> : locked ? (
        <div className="panel flex flex-wrap items-center gap-3 p-6"><Lock className="h-5 w-5 text-muted" aria-hidden /><p className="flex-1 text-sm">Sentiment and topic insights are part of the Growth and Multi-location plans (and your free trial).</p><LinkButton href="/settings/billing" size="sm">View plans</LinkButton></div>
      ) : ins.error ? <Alert tone="error" title="We couldn't load insights">{ins.error}</Alert> : d && (
        <div className="space-y-6">
          <div className="grid gap-6 lg:grid-cols-[1fr_2fr]">
            <Panel title="Sentiment" meta={`${d.reviews_with_text} of ${d.total_reviews} reviews have text`}>
              {d.total_reviews === 0 ? <p className="text-sm text-muted">No synced reviews in this period yet.</p> : <SentimentBar s={d.sentiment} />}
              <dl className="mt-5 grid grid-cols-3 gap-3 text-center">
                {([["positive", "Positive", "text-pos"], ["neutral", "Neutral", "text-ink"], ["negative", "Negative", "text-neg"]] as const).map(([k, l, c]) => (
                  <div key={k} className="rounded-tile bg-surface-2 p-3"><dd className={`num text-2xl font-semibold ${c}`}>{d.sentiment[k]}</dd><dt className="text-xs text-muted">{l}</dt></div>))}
              </dl>
            </Panel>
            <Panel title="Recurring topics" meta="with a line from a real review" action={<Badge tone="gray">{d.method.length > 40 ? "keyword heuristic" : d.method}</Badge>}>
              {d.topics.length === 0 ? <p className="text-sm text-muted">No recurring topics detected yet.</p> : (
                <ul className="divide-y divide-line">{d.topics.map((t) => { const diff = t.mentions - t.previous_mentions; const good = t.positive >= t.negative; return (
                  <li key={t.topic} className="grid gap-1 py-3 sm:grid-cols-[1fr_auto] sm:items-center sm:gap-4">
                    <div className="min-w-0"><p className="font-semibold">{t.label} <span className={`ml-1 text-xs font-semibold ${good ? "text-pos" : "text-neg"}`}>{t.mentions} mentions</span>
                      {diff !== 0 && <span className="ml-2 text-xs text-muted">{diff > 0 ? "▲" : "▼"} {Math.abs(diff)} vs previous period</span>}</p>
                      {t.sample && <p className="mt-0.5 truncate text-[13px] text-muted" title={t.sample}>&ldquo;{t.sample}&rdquo;</p>}</div>
                    <p className="whitespace-nowrap text-[13px]"><span className="text-pos">{t.positive} positive</span> · <span className="text-muted">{t.neutral} neutral</span> · <span className="text-neg">{t.negative} negative</span> · ★ {t.avg_rating}</p>
                  </li>); })}</ul>
              )}
              <p className="mt-3 text-xs text-muted">{d.method}</p>
            </Panel>
          </div>
          {byLoc && (
            <Panel title="By location" meta="same period">
              <ul className="grid gap-4 md:grid-cols-2">{byLoc.map((l) => (
                <li key={l.name} className="rounded-tile bg-surface-2 p-4">
                  <p className="font-semibold">{l.name}</p>
                  {l.error ? <p className="mt-1 text-sm text-neg">{l.error}</p> : !l.data || l.data.total_reviews === 0 ? <p className="mt-1 text-sm text-muted">No reviews in this period.</p> : (
                    <div className="mt-3 space-y-3"><SentimentBar s={l.data.sentiment} />
                      {l.data.topics.length > 0 && <p className="text-[13px] text-muted">Most mentioned: {[...l.data.topics].sort((a, b) => b.mentions - a.mentions).slice(0, 3).map((t) => t.label).join(", ")}</p>}</div>
                  )}
                </li>))}</ul>
            </Panel>
          )}
        </div>
      )}
    </>
  );
}
