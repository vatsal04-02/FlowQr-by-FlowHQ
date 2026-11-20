"use client";
import { Lock } from "lucide-react";
import { useState } from "react";
import { LineChart } from "@/components/charts/LineChart";
import { DateRange, presetRange } from "@/components/DateRange";
import { CountUp } from "@/components/charts/CountUp";
import { Donut, Legend, type Slice } from "@/components/charts/Donut";
import { Ring } from "@/components/charts/Bars";
import { Card, Title } from "@/components/home/v2";
import { LinkButton } from "@/components/ui/Button";
import { Alert, Skeleton } from "@/components/ui/Card";
import { ratingMix } from "@/lib/charts";
import { useLocationScope } from "@/lib/location-scope";
import type { Insights, Overview } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

const pct = (n: number, t: number) => (t ? Math.round((n / t) * 100) : 0);

/**
 * Reviews › Insights: what customers talk about (topics from review text, a keyword method, not AI), the rating mix, reply speed and the rating over time.
 * Counts are bars; the rating is the one line. Every chart prints its numbers.
 */
export default function InsightsPage() {
  const [range, setRange] = useState(presetRange("30"));
  const { locationId } = useLocationScope();
  const loc = locationId ?? "";
  const ins = useFetch<Insights>("/analytics/insights", { from: range.from, to: range.to, location_id: loc });
  const ov = useFetch<Overview>("/analytics/overview", { from: range.from, to: range.to, location_id: loc });
  const d = ins.data, r = ov.data?.reviews;
  const locked = ins.error?.toLowerCase().includes("plan") || ins.error?.toLowerCase().includes("subscription");
  const topics = [...(d?.topics ?? [])].sort((a, b) => b.mentions - a.mentions).slice(0, 8);
  const topT = Math.max(1, ...topics.map((t) => t.mentions));
  const STAR: Record<number, string> = { 5: "rgb(var(--c-pos))", 4: "rgb(var(--c-tone-teal))", 3: "rgb(var(--c-caution))", 2: "rgb(var(--c-tone-rose))", 1: "rgb(var(--c-neg))" };
  const mixSlices: Slice[] = ratingMix(r?.rating_distribution).map((x) => ({ key: String(x.star), label: `${x.star} ${x.star === 1 ? "star" : "stars"}`, value: x.count, color: STAR[x.star] }));
  const mixTotal = mixSlices.reduce((a, x) => a + x.value, 0);
  const sentSlices: Slice[] = d ? [{ key: "pos", label: "Good", value: d.sentiment.positive, color: "rgb(var(--c-pos))" }, { key: "neu", label: "Neutral", value: d.sentiment.neutral, color: "rgb(var(--c-ink-300))" }, { key: "neg", label: "Bad", value: d.sentiment.negative, color: "rgb(var(--c-neg))" }] : [];
  const sentTotal = sentSlices.reduce((a, x) => a + x.value, 0);
  const hrs = r?.avg_response_hours ?? null;
  const rate = r?.reply_rate_in_range ?? null;

  return (
    <>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-[22px] font-semibold leading-7 sm:text-[26px]">Insights</h1>
        <DateRange value={range} onChange={setRange} />
      </div>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-12 lg:gap-4">
        <Card label="Topics from review text" tone="ok" className="lg:col-span-7">
          <Title>Topics from review text</Title>
          {ins.loading && !d ? <Skeleton className="mt-3 h-48" /> : locked ? (
            <div className="mt-3 flex flex-wrap items-center gap-3"><Lock className="h-4 w-4 text-muted" aria-hidden /><p className="flex-1 text-[14px] text-muted">Part of the Growth plan.</p><LinkButton href="/settings/billing" variant="secondary" size="sm">See plans</LinkButton></div>
          ) : ins.error ? <Alert tone="error">{ins.error}</Alert> : !d || topics.length === 0 ? <p className="mt-3 text-[14px] text-muted">Shown once reviews have text.</p> : (
            <>
            {sentSlices.some((x) => x.value > 0) && (
              <div className="mt-3 flex flex-wrap items-center gap-5 rounded-[12px] bg-surface-2/60 p-3">
                <Donut slices={sentSlices} size={104} stroke={14} label="How the mentions split between good, neutral and bad" centre={<CountUp value={sentTotal} />} sub="mentions" />
                <Legend slices={sentSlices} />
              </div>
            )}
            <ul className="mt-3 space-y-3">
              {topics.map((t) => {
                const tot = t.positive + t.neutral + t.negative || 1;
                return (
                  <li key={t.topic}>
                    <div className="flex items-baseline justify-between gap-3 text-[14px]"><span className="font-medium">{t.label}</span><b className="num font-semibold">{t.mentions}</b></div>
                    <div aria-hidden className="mt-1 flex h-2.5 overflow-hidden rounded-full bg-surface-3" style={{ width: `${Math.max(8, (t.mentions / topT) * 100)}%` }}>
                      <span className="bg-pos" style={{ width: `${pct(t.positive, tot)}%` }} /><span className="bg-ink-300" style={{ width: `${pct(t.neutral, tot)}%` }} /><span className="bg-neg" style={{ width: `${pct(t.negative, tot)}%` }} />
                    </div>
                    <span className="sr-only">{t.positive} positive, {t.neutral} neutral, {t.negative} negative</span>
                  </li>
                );
              })}
              <li className="flex gap-4 pt-1 text-[13px] text-muted"><span className="flex items-center gap-1.5"><i aria-hidden className="h-2 w-2 rounded-full bg-pos" />Good</span><span className="flex items-center gap-1.5"><i aria-hidden className="h-2 w-2 rounded-full bg-ink-300" />Neutral</span><span className="flex items-center gap-1.5"><i aria-hidden className="h-2 w-2 rounded-full bg-neg" />Bad</span></li>
            </ul>
            </>
          )}
        </Card>

        <div className="space-y-3 lg:col-span-5 lg:space-y-4">
          <Card label="Rating mix" tone="amber" tilt>
            <Title right={mixTotal ? <span className="rounded-full bg-surface-2 px-2.5 py-0.5 text-[13px] font-medium text-ink-700">{mixTotal} reviews</span> : null}>Rating mix</Title>
            {ov.loading && !r ? <Skeleton className="mt-3 h-32" /> : mixTotal === 0 ? <p className="mt-3 text-[14px] text-muted">Shown once reviews have been synced.</p> : (
              <div className="mt-3 flex flex-wrap items-center gap-5">
                <Donut slices={mixSlices} size={116} stroke={16} label={`Rating mix of ${mixTotal} reviews`} centre={r?.average_rating_all_time == null ? "–" : <CountUp value={r.average_rating_all_time} decimals={1} />} sub="average" />
                <Legend slices={mixSlices} />
              </div>
            )}
          </Card>
          <Card label="Reply speed" tone="teal" tilt>
            <Title>Reply speed</Title>
            {ov.loading && !r ? <Skeleton className="mt-3 h-20" /> : (
              <div className="mt-3 grid grid-cols-2 gap-4">
                <div><p className="text-[13px] text-muted">Replied</p><div className="flex items-center gap-3"><p className="num text-[24px] font-semibold">{rate === null ? "–" : <><CountUp value={Math.round(rate * 100)} />%</>}</p>{rate !== null && <Ring value={rate * 100} size={40} stroke={5} label={`${Math.round(rate * 100)} percent replied`}><span /></Ring>}</div>
                  <span aria-hidden className="mt-1 block h-2 overflow-hidden rounded-full bg-surface-3"><span className={`block h-full rounded-full ${rate === null ? "" : rate >= 0.75 ? "bg-pos" : rate >= 0.4 ? "bg-caution" : "bg-neg"}`} style={{ width: `${(rate ?? 0) * 100}%` }} /></span></div>
                <div><p className="text-[13px] text-muted">Time to reply</p><p className="num text-[24px] font-semibold">{hrs === null ? "–" : hrs < 48 ? `${Math.round(hrs)} h` : `${Math.round(hrs / 24)} d`}</p>
                  <span aria-hidden className="relative mt-1 block h-2 rounded-full bg-surface-3">{hrs !== null && <span className={`absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface ${hrs <= 24 ? "bg-pos" : hrs <= 72 ? "bg-caution" : "bg-neg"}`} style={{ left: `${Math.min(100, (Math.log10(Math.max(1, hrs)) / Math.log10(168)) * 100)}%` }} />}</span></div>
              </div>
            )}
          </Card>
        </div>

        <Card label="Rating over time" tone="sky" className="lg:col-span-12">
          <Title>Rating over time</Title>
          <div className="mt-3">{ov.loading && !r ? <Skeleton className="h-48" /> : r && r.series.some((p) => Number(p.avg_rating) > 0)
            ? <LineChart ariaLabel="Average rating of reviews per day" data={r.series} series={[{ key: "avg_rating", label: "Average rating", color: "rgb(var(--c-ink-solid))" }]} yMax={5} gaps height={180} />
            : <p className="text-[14px] text-muted">No rated reviews in this period.</p>}</div>
        </Card>
      </div>
    </>
  );
}
