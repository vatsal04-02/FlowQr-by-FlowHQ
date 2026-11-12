"use client";
import { Lock } from "lucide-react";
import { useState } from "react";
import { ColumnChart } from "@/components/charts/ColumnChart";
import { LineChart } from "@/components/charts/LineChart";
import { DateRange, presetRange } from "@/components/DateRange";
import { LinkButton } from "@/components/ui/Button";
import { Alert, Badge, PageHeader, Skeleton, Stars } from "@/components/ui/Card";
import { FilterSelect } from "@/components/ui/Form";
import { CellBar, Meter, Panel } from "@/components/ui/kit";
import { fmtHours, fmtNum, fmtPct, fmtRating, timeAgo } from "@/lib/format";
import type { Card as CardT, Insights, Location, Overview } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

function Metric({ label, value, note }: { label: string; value: React.ReactNode; note?: string }) {
  return <div className="min-w-0 px-4 py-3"><dt className="text-xs font-medium text-ink-500">{label}</dt><dd className="num mt-1 text-2xl font-bold leading-none tracking-tight">{value}</dd>{note && <p className="mt-1.5 text-xs text-ink-500">{note}</p>}</div>;
}

export default function AnalyticsPage() {
  const [range, setRange] = useState(presetRange("30"));
  const [loc, setLoc] = useState("");
  const locs = useFetch<Location[]>("/locations");
  const cards = useFetch<CardT[]>("/cards");
  const p = { from: range.from, to: range.to, location_id: loc };
  const ov = useFetch<Overview>("/analytics/overview", p);
  const ins = useFetch<Insights>("/analytics/insights", p);
  const o = ov.data;
  const e = o?.engagement;
  const coverage = o && o.reviews.total_synced ? 1 - o.reviews.awaiting_reply / o.reviews.total_synced : null;
  const locked = ins.error?.toLowerCase().includes("plan") || ins.error?.toLowerCase().includes("subscription");
  const lastScan = new Map((cards.data ?? []).map((c) => [c.card_code, c.last_scan_at]));
  const topCards = [...(o?.cards ?? [])].sort((a, b) => b.scans - a.scans).slice(0, 8);
  const maxCard = Math.max(1, ...topCards.map((c) => c.scans));
  const maxLoc = Math.max(1, ...(o?.locations ?? []).map((l) => l.scans));

  return (
    <>
      <PageHeader eyebrow="Reputation" title="Analytics" subtitle="Reviews, replies, sentiment and card activity. Each number says what it does and doesn't prove."
        actions={<>
          <FilterSelect label="Location" value={loc} onChange={(ev) => setLoc(ev.target.value)}><option value="">All locations</option>{locs.data?.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</FilterSelect>
          <DateRange value={range} onChange={setRange} />
        </>} />
      {ov.error && <Alert tone="error">{ov.error}</Alert>}
      {!o && !ov.error && <Skeleton className="h-60" />}

      {o && e && (
        <div className="space-y-4">
          {/* Two sources, two groups: what cards recorded, and what Google confirms. They are never added together. */}
          <section className="panel grid overflow-hidden lg:grid-cols-[1fr_1.5fr]" aria-label="Summary">
            <div className="border-b border-ink-100 lg:border-b-0 lg:border-r">
              <p className="eyebrow border-b border-ink-100 px-4 py-2 !text-[11px]">From your cards</p>
              <dl className="grid grid-cols-3 divide-x divide-ink-100">
                <Metric label="Scans" value={fmtNum(e.scans)} /><Metric label="Visits" value={fmtNum(e.landing_views)} />
                <Metric label="Clicks to Google" value={fmtNum(e.google_clicks)} note={`${fmtPct(e.click_through_rate)} of visits`} />
              </dl>
            </div>
            <div>
              <p className="eyebrow border-b border-ink-100 px-4 py-2 !text-[11px]">Published on Google{o.reviews.total_synced === 0 && " · no synced reviews yet"}</p>
              <dl className="grid grid-cols-2 divide-x divide-ink-100 sm:grid-cols-4">
                <Metric label="New reviews" value={fmtNum(o.reviews.new_in_range)} note={`${fmtNum(o.reviews.total_synced)} in total`} />
                <Metric label="Average rating" value={fmtRating(o.reviews.average_rating_in_range)} note={`${fmtRating(o.reviews.average_rating_all_time)} all time`} />
                <Metric label="Reply coverage" value={fmtPct(coverage)} note={`${o.reviews.awaiting_reply} waiting`} />
                <Metric label="Avg response" value={fmtHours(o.reviews.avg_response_hours)} note={o.reviews.avg_response_hours === null ? "Not measurable yet" : `Reply rate ${fmtPct(o.reviews.reply_rate_in_range)}`} />
              </dl>
            </div>
          </section>

          <div className="grid gap-4 lg:grid-cols-2">
            <Panel title="New reviews" meta="per day"><ColumnChart data={o.reviews.series} valueKey="count" label="new reviews" ariaLabel="New reviews per day" height={190} /></Panel>
            <Panel title="Average rating" meta="days with reviews"><LineChart ariaLabel="Average rating per day" yMax={5} height={190} gaps data={o.reviews.series} series={[{ key: "avg_rating", label: "Avg rating", color: "#A56A00" }]} /></Panel>
          </div>

          <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
            <Panel title="Card funnel over time"><LineChart ariaLabel="Scans, visits and clicks over time" data={e.series} height={210} series={[{ key: "scan", label: "Scans", color: "#1B46B8" }, { key: "landing_view", label: "Visits", color: "#57554F", dash: "6 4" }, { key: "google_click", label: "Clicks to Google", color: "#0A7D6B", dash: "2 4" }]} /></Panel>
            <Panel title="Rating mix" meta="all synced reviews">
              <ul className="space-y-2.5">{[5, 4, 3, 2, 1].map((n) => { const v = o.reviews.rating_distribution[String(n)] ?? 0; return (
                <li key={n} className="grid grid-cols-[78px_1fr_30px] items-center gap-2 text-sm"><Stars rating={n} size={11} /><CellBar value={v} max={Math.max(1, ...Object.values(o.reviews.rating_distribution))} color="bg-star" /><span className="num text-right font-medium">{v}</span></li>); })}</ul>
            </Panel>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Panel title="Locations compared" flush>
              <div className="overflow-x-auto"><table className="dt min-w-[460px]">
                <thead><tr><th>Location</th><th className="w-[26%]">Scans</th><th className="!text-right">Clicks</th><th className="!text-right">Reviews</th><th className="!text-right">Avg ★</th></tr></thead>
                <tbody>{o.locations.map((l) => (
                  <tr key={l.location}><td className="font-medium">{l.location}</td>
                    <td><div className="flex items-center gap-2"><span className="num w-9 text-right font-semibold">{fmtNum(l.scans)}</span><CellBar value={l.scans} max={maxLoc} /></div></td>
                    <td className="n">{fmtNum(l.google_clicks)}</td><td className="n">{l.new_reviews}</td><td className="n">{l.avg_rating ?? "–"}</td></tr>))}</tbody>
              </table></div>
            </Panel>
            <Panel title="Cards compared" meta="top by scans" flush>
              {topCards.length === 0 ? <p className="p-4 text-sm text-ink-500">No cards assigned yet.</p> : (
                <div className="overflow-x-auto"><table className="dt min-w-[460px]">
                  <thead><tr><th>Card</th><th className="w-[28%]">Scans</th><th className="!text-right">Clicks</th><th>Last scan</th></tr></thead>
                  <tbody>{topCards.map((c) => (
                    <tr key={c.card_code}><td><span className="card-code text-[13px] font-medium">{c.card_code}</span><p className="text-xs text-ink-500">{c.location ?? "–"}</p></td>
                      <td><div className="flex items-center gap-2"><span className="num w-9 text-right font-semibold">{fmtNum(c.scans)}</span><CellBar value={c.scans} max={maxCard} /></div></td>
                      <td className="n">{fmtNum(c.google_clicks)}</td><td className="whitespace-nowrap text-ink-500">{lastScan.get(c.card_code) ? timeAgo(lastScan.get(c.card_code)) : "never"}</td></tr>))}</tbody>
                </table></div>
              )}
            </Panel>
          </div>

          <div className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
            <Panel title="Sentiment and recurring topics" meta="what customers keep mentioning" action={ins.data && <Badge tone="gray">keyword heuristic</Badge>} flush>
              {ins.loading && !ins.data ? <Skeleton className="m-4 h-32" /> : locked ? (
                <div className="flex flex-wrap items-center gap-3 p-4"><Lock className="h-4 w-4 text-ink-500" aria-hidden /><p className="flex-1 text-sm text-ink-700">Sentiment and topic insights are part of the Growth and Multi-location plans (and your free trial).</p><LinkButton href="/subscription" size="sm">View plans</LinkButton></div>
              ) : ins.error ? <div className="p-4"><Alert tone="error">{ins.error}</Alert></div> : ins.data && (ins.data.total_reviews === 0 ? <p className="p-4 text-sm text-ink-500">No synced reviews in this period yet.</p> : (
                <>
                  <dl className="grid grid-cols-3 divide-x divide-ink-100 border-b border-ink-100 text-center">
                    {([["positive", "Positive", "text-green-800"], ["neutral", "Neutral", "text-ink-700"], ["negative", "Negative", "text-red-800"]] as const).map(([k, l, c]) => (
                      <div key={k} className="px-3 py-2.5"><dd className={`num text-xl font-bold ${c}`}>{ins.data!.sentiment[k]}</dd><dt className="text-xs text-ink-500">{l}</dt></div>))}
                  </dl>
                  {ins.data.topics.length === 0 ? <p className="p-4 text-sm text-ink-500">No recurring topics detected yet.</p> : (
                    <div className="overflow-x-auto"><table className="dt min-w-[560px]">
                      <thead><tr><th>Topic</th><th className="!text-right">Mentions</th><th className="!text-right">vs previous</th><th>Mood</th><th className="!text-right">Avg ★</th></tr></thead>
                      <tbody>{ins.data.topics.map((t) => { const d = t.mentions - t.previous_mentions; return (
                        <tr key={t.topic}><td><p className="font-medium">{t.label}</p>{t.sample && <p className="max-w-[300px] truncate text-xs text-ink-500" title={t.sample}>“{t.sample}”</p>}</td>
                          <td className="n font-medium">{t.mentions}</td>
                          <td className="n">{d === 0 ? "–" : <span className={d > 0 ? "text-amber-800" : "text-green-800"}>{d > 0 ? "▲" : "▼"} {Math.abs(d)}</span>}</td>
                          <td className="whitespace-nowrap text-[13px]"><span className="text-green-800">{t.positive} positive</span> · <span className="text-ink-500">{t.neutral} neutral</span> · <span className="text-red-800">{t.negative} negative</span></td>
                          <td className="n">{t.avg_rating}</td></tr>); })}</tbody>
                    </table></div>
                  )}
                  <p className="border-t border-ink-100 px-4 py-2 text-xs text-ink-500">{ins.data.method}</p>
                </>
              ))}
            </Panel>
            <Panel title="AI usage" meta="this calendar month">
              <p className="num text-3xl font-bold leading-none tracking-tight">{o.ai.used_this_month}<span className="text-base font-medium text-ink-500"> / {o.ai.monthly_limit ?? "–"}</span></p>
              {o.ai.monthly_limit ? <div className="mt-3"><Meter label="AI generations used" value={o.ai.used_this_month} max={o.ai.monthly_limit} tone={o.ai.used_this_month / o.ai.monthly_limit >= 0.9 ? "bad" : o.ai.used_this_month / o.ai.monthly_limit >= 0.7 ? "warn" : "info"} /></div> : null}
              {Object.keys(o.ai.in_range_by_kind).length > 0 ? (
                <dl className="mt-4 divide-y divide-ink-100 text-sm">{Object.entries(o.ai.in_range_by_kind).map(([k, v]) => <div key={k} className="flex justify-between py-1.5"><dt className="text-ink-500">{k === "review_assist" ? "Customer writing help" : k === "reply_draft" ? "Reply drafts" : k}</dt><dd className="num font-medium">{v}</dd></div>)}</dl>
              ) : <p className="mt-3 text-[13px] text-ink-500">No AI generations in this period.</p>}
            </Panel>
          </div>
        </div>
      )}
    </>
  );
}
