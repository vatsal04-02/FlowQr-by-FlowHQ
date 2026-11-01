"use client";
import { Lock } from "lucide-react";
import { useState } from "react";
import { BarList } from "@/components/charts/BarList";
import { LineChart } from "@/components/charts/LineChart";
import { DateRange, presetRange } from "@/components/DateRange";
import { LinkButton } from "@/components/ui/Button";
import { Alert, Badge, Card, CardHeader, PageHeader, Skeleton, Stat } from "@/components/ui/Card";
import { FilterSelect } from "@/components/ui/Form";
import { ApiError } from "@/lib/api";
import { fmtHours, fmtNum, fmtPct } from "@/lib/format";
import type { Insights, Location, Overview } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

export default function AnalyticsPage() {
  const [range, setRange] = useState(presetRange("30"));
  const [loc, setLoc] = useState("");
  const locs = useFetch<Location[]>("/locations");
  const p = { from: range.from, to: range.to, location_id: loc };
  const ov = useFetch<Overview>("/analytics/overview", p);
  const ins = useFetch<Insights>("/analytics/insights", p);
  const o = ov.data;
  const coverage = o && o.reviews.total_synced ? 1 - o.reviews.awaiting_reply / o.reviews.total_synced : null;
  const locked = ins.error?.toLowerCase().includes("plan") || ins.error?.toLowerCase().includes("subscription");

  return (
    <>
      <PageHeader title="Analytics" subtitle="Reviews, replies, sentiment and card activity. Each number is labelled with what it does and doesn't prove." actions={<>
        <FilterSelect label="Location" value={loc} onChange={(e) => setLoc(e.target.value)}><option value="">All locations</option>{locs.data?.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</FilterSelect>
        <DateRange value={range} onChange={setRange} /></>} />
      {ov.error && <Alert tone="error">{ov.error}</Alert>}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {!o ? Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-28" />) : <>
          <Stat label="Total reviews" value={fmtNum(o.reviews.total_synced)} hint={`${o.reviews.new_in_range} new in range`} />
          <Stat label="Average rating" value={o.reviews.average_rating_all_time ?? "–"} hint={`In range: ${o.reviews.average_rating_in_range ?? "–"}`} tone="yellow" />
          <Stat label="Reply coverage" value={fmtPct(coverage)} hint={`${o.reviews.awaiting_reply} pending · avg ${fmtHours(o.reviews.avg_response_hours)}`} tone="green" />
          <Stat label="Pending replies" value={fmtNum(o.reviews.awaiting_reply)} hint={`${o.reviews.drafts_pending_approval} drafts await approval`} tone="red" />
        </>}
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <Card><CardHeader title="Review trend" subtitle="New reviews per day" />{o ? <LineChart ariaLabel="New reviews per day" data={o.reviews.series} series={[{ key: "count", label: "New reviews", color: "#2F6FE4" }]} /> : <Skeleton className="h-60" />}</Card>
        <Card><CardHeader title="Average rating trend" subtitle="Days with reviews only" />{o ? <LineChart ariaLabel="Average rating per day" yMax={5} data={o.reviews.series} series={[{ key: "avg_rating", label: "Avg rating", color: "#F26B1D", dash: "6 4" }]} /> : <Skeleton className="h-60" />}</Card>
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-3">
        <Card><CardHeader title="Rating mix" />{o && <BarList color="bg-g-yellow" rows={[5, 4, 3, 2, 1].map((n) => ({ label: `${n} star${n > 1 ? "s" : ""}`, value: o.reviews.rating_distribution[String(n)] ?? 0 }))} />}</Card>
        <Card className="lg:col-span-2"><CardHeader title="Customer funnel (cards)" subtitle="These are not reviews" />
          {o && <><BarList color="bg-flow-500" rows={[{ label: "QR/NFC scans", value: o.engagement.scans }, { label: "Landing visits", value: o.engagement.landing_views }, { label: "Clicks to Google", value: o.engagement.google_clicks }, { label: "AI assists", value: o.engagement.ai_assists }]} />
            <dl className="mt-4 grid gap-2 text-xs text-ink-500 sm:grid-cols-2">{Object.entries(o.engagement.definitions).map(([k, v]) => <div key={k} className="rounded-lg bg-ink-50 p-2.5"><dt className="font-semibold text-ink-700">{k.replace(/_/g, " ")}</dt><dd>{v}</dd></div>)}</dl></>}
        </Card>
      </div>

      <Card className="mt-5"><CardHeader title="Sentiment & recurring topics" subtitle="What customers keep mentioning" action={ins.data && <Badge tone="gray">keyword heuristic</Badge>} />
        {ins.loading && !ins.data ? <Skeleton className="h-40" /> : locked ? (
          <div className="flex flex-wrap items-center gap-4 rounded-xl bg-ink-50 p-5"><Lock className="h-5 w-5 text-ink-500" aria-hidden /><p className="flex-1 text-sm text-ink-700">Sentiment and topic insights are part of the Growth and Multi-location plans (and your free trial).</p><LinkButton href="/subscription" size="sm">View plans</LinkButton></div>
        ) : ins.error ? <Alert tone="error">{ins.error}</Alert> : ins.data && (ins.data.total_reviews === 0 ? <p className="text-sm text-ink-500">No synced reviews in this period yet.</p> : (
          <>
            <div className="mb-5 grid grid-cols-3 gap-3 text-center">
              {([["positive", "Positive", "text-green-700 bg-green-50"], ["neutral", "Neutral", "text-ink-700 bg-ink-50"], ["negative", "Negative", "text-red-700 bg-red-50"]] as const).map(([k, l, c]) => (
                <div key={k} className={`rounded-xl p-3 ${c}`}><p className="font-display text-2xl font-semibold tabular-nums">{ins.data!.sentiment[k]}</p><p className="text-sm font-semibold">{l}</p></div>))}
            </div>
            {ins.data.topics.length === 0 ? <p className="text-sm text-ink-500">No recurring topics detected yet.</p> : (
              <div className="overflow-x-auto"><table className="w-full min-w-[560px] text-left text-sm">
                <thead className="text-xs uppercase tracking-wide text-ink-500"><tr><th className="py-2">Topic</th><th>Mentions</th><th>vs previous</th><th>Mood</th><th>Avg ★</th><th>Example</th></tr></thead>
                <tbody>{ins.data.topics.map((t) => {
                  const delta = t.mentions - t.previous_mentions;
                  return (<tr key={t.topic} className="border-t border-ink-100 align-top">
                    <td className="py-2.5 pr-3 font-semibold">{t.label}</td><td className="tabular-nums">{t.mentions}</td>
                    <td className="tabular-nums">{delta === 0 ? "–" : <span className={delta > 0 ? "text-amber-700" : "text-green-700"}>{delta > 0 ? "▲" : "▼"} {Math.abs(delta)}</span>}</td>
                    <td><span className="text-green-700">{t.positive}+</span> <span className="text-ink-500">{t.neutral}·</span> <span className="text-red-700">{t.negative}−</span></td>
                    <td className="tabular-nums">{t.avg_rating}</td><td className="max-w-[260px] truncate text-ink-500" title={t.sample ?? ""}>{t.sample ? `“${t.sample}”` : ""}</td></tr>);
                })}</tbody>
              </table></div>
            )}
            <p className="mt-3 text-xs text-ink-500">{ins.data.method}</p>
          </>
        ))}
      </Card>

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <Card><CardHeader title="Location performance" />{o && (o.locations.length ? (
          <div className="overflow-x-auto"><table className="w-full min-w-[420px] text-left text-sm"><thead className="text-xs uppercase tracking-wide text-ink-500"><tr><th className="py-2">Location</th><th>Scans</th><th>Clicks</th><th>New reviews</th><th>Avg ★</th></tr></thead>
            <tbody>{o.locations.map((l) => <tr key={l.location} className="border-t border-ink-100"><td className="py-2.5 font-semibold">{l.location}</td><td className="tabular-nums">{l.scans}</td><td className="tabular-nums">{l.google_clicks}</td><td className="tabular-nums">{l.new_reviews}</td><td className="tabular-nums">{l.avg_rating ?? "–"}</td></tr>)}</tbody></table></div>) : <p className="text-sm text-ink-500">No locations.</p>)}</Card>
        <Card><CardHeader title="AI usage" subtitle="This calendar month" />
          {o && <><p className="font-display text-3xl font-semibold tabular-nums">{o.ai.used_this_month}<span className="text-lg text-ink-500"> / {o.ai.monthly_limit ?? "–"}</span></p>
            <div className="mt-3"><BarList color="bg-brand-500" rows={Object.entries(o.ai.in_range_by_kind).map(([k, v]) => ({ label: k === "review_assist" ? "Customer writing help" : k === "reply_draft" ? "Reply drafts" : k, value: v }))} /></div></>}
        </Card>
      </div>
    </>
  );
}
