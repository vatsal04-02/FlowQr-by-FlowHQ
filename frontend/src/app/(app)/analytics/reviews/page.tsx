"use client";
import { useState } from "react";
import { GoalCard } from "@/components/overview/widgets";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { ColumnChart } from "@/components/charts/ColumnChart";
import { LineChart } from "@/components/charts/LineChart";
import { DateRange, presetRange } from "@/components/DateRange";
import { Alert, PageHeader, Skeleton, Stars } from "@/components/ui/Card";
import { CellBar, Panel } from "@/components/ui/kit";
import { useLocationScope } from "@/lib/location-scope";
import { fmtHours, fmtNum, fmtPct, fmtRating } from "@/lib/format";
import type { Overview } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

function Metric({ label, value, note }: { label: string; value: React.ReactNode; note?: string }) {
  return <div className="min-w-0 rounded-tile bg-surface-2 p-4"><dt className="text-sm font-medium text-muted">{label}</dt><dd className="num mt-2 text-[28px] font-semibold leading-none tracking-[-.02em]">{value}</dd>{note && <p className="mt-2 text-xs text-muted">{note}</p>}</div>;
}

/**
 * Overview › Reviews (PRD §5.1): what Google confirms about your reviews, and nothing from the cards (that is Customer funnel).
 * Sentiment and topics moved to AI › Insights; AI usage to AI › Usage & limits; location comparison to Overview › Locations.
 */
export default function ReviewsOverviewPage() {
  const [range, setRange] = useState(presetRange("30"));
  const { tenant, isAdmin, refresh } = useAuth();
  const toast = useToast();
  const { locationId } = useLocationScope();
  const ov = useFetch<Overview>("/analytics/overview", { from: range.from, to: range.to, location_id: locationId ?? "" });
  const o = ov.data;
  const coverage = o && o.reviews.total_synced ? 1 - o.reviews.awaiting_reply / o.reviews.total_synced : null;
  const dist = o?.reviews.rating_distribution ?? {};
  const maxDist = Math.max(1, ...Object.values(dist));

  return (
    <>
      <PageHeader title="Review results" subtitle="Your rating, how many reviews you got, and how fast you reply." actions={<DateRange value={range} onChange={setRange} />} />
      {ov.error && <Alert tone="error" title="We couldn't load your reviews">{ov.error}</Alert>}
      {!o && !ov.error && <Skeleton className="h-60" />}
      {o && (
        <div className="space-y-6">
          <section className="panel p-5 sm:p-6" aria-label="Summary">
            <p className="mb-4 text-sm text-muted">Published on Google{o.reviews.total_synced === 0 ? " · no synced reviews yet" : ""}</p>
            <dl className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
              <Metric label="New reviews" value={fmtNum(o.reviews.new_in_range)} note={`${fmtNum(o.reviews.total_synced)} in total`} />
              <Metric label="Average rating" value={fmtRating(o.reviews.average_rating_in_range)} note={`${fmtRating(o.reviews.average_rating_all_time)} all time`} />
              <Metric label="Answered" value={fmtPct(coverage)} note={`${fmtNum(o.reviews.awaiting_reply)} waiting for a reply`} />
              <Metric label="Average reply time" value={fmtHours(o.reviews.avg_response_hours)} note={o.reviews.avg_response_hours === null ? "Not measurable yet" : `Reply rate ${fmtPct(o.reviews.reply_rate_in_range)} this period`} />
            </dl>
          </section>
          <GoalCard i={1} goal={tenant?.review_goal} canEdit={isAdmin} onSave={async (g) => {
            try { await api("/tenant", { method: "PATCH", body: { review_goal: g } }); await refresh(); toast(g ? "Goal saved." : "Goal cleared."); }
            catch (e) { toast(errorMessage(e), "error"); }
          }} />
          <div className="grid gap-6 lg:grid-cols-2">
            <Panel title="New reviews" meta="per day"><ColumnChart data={o.reviews.series} valueKey="count" label="new reviews" ariaLabel="New reviews per day" height={200} /></Panel>
            <Panel title="Average rating" meta="days with reviews"><LineChart ariaLabel="Average rating per day" yMax={5} height={200} gaps data={o.reviews.series} series={[{ key: "avg_rating", label: "Avg rating", color: "rgb(var(--c-ink-solid))" }]} /></Panel>
          </div>
          <Panel title="Rating mix" meta="all synced reviews">
            <ul className="space-y-3">{[5, 4, 3, 2, 1].map((n) => { const v = dist[String(n)] ?? 0; return (
              <li key={n} className="grid grid-cols-[84px_1fr_48px] items-center gap-3 text-sm"><Stars rating={n} size={12} /><CellBar value={v} max={maxDist} color={n >= 4 ? "bg-ink-solid" : "bg-accent"} /><span className="num text-right font-semibold">{fmtNum(v)}</span></li>); })}</ul>
          </Panel>
        </div>
      )}
    </>
  );
}
