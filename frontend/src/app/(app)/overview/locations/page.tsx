"use client";
import Link from "next/link";
import { useState } from "react";
import { DateRange, presetRange } from "@/components/DateRange";
import { Alert, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { CellBar, Panel, Status } from "@/components/ui/kit";
import { fmtNum, fmtRating, timeAgo } from "@/lib/format";
import type { Overview } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

/**
 * Overview › Locations (PRD §5.1): every branch side by side for the same period. Card numbers (scans, clicks) and Google numbers
 * (reviews, rating) sit in separate columns and are never added together.
 */
export default function LocationsOverviewPage() {
  const [range, setRange] = useState(presetRange("30"));
  const ov = useFetch<Overview>("/analytics/overview", { from: range.from, to: range.to });
  const o = ov.data;
  const rows = [...(o?.locations ?? [])].sort((a, b) => b.new_reviews - a.new_reviews || b.scans - a.scans);
  const maxScans = Math.max(1, ...rows.map((r) => r.scans));
  const maxReviews = Math.max(1, ...rows.map((r) => r.new_reviews));
  const sync = new Map((o?.sync ?? []).map((s) => [s.location, s]));
  return (
    <>
      <PageHeader title="Compare branches" subtitle="Compare your branches for the same period." actions={<DateRange value={range} onChange={setRange} />} />
      {ov.error && <Alert tone="error" title="We couldn't load your locations">{ov.error}</Alert>}
      {!o && !ov.error && <Skeleton className="h-60" />}
      {o && rows.length === 0 && <EmptyState title="No locations yet" action={<Link className="font-semibold text-accent-ink hover:underline" href="/gbp/locations">Add a location</Link>}>Each branch gets its own cards, review link and numbers.</EmptyState>}
      {o && rows.length > 0 && (
        <Panel title="Locations compared" meta={`${rows.length} ${rows.length === 1 ? "location" : "locations"}`} flush>
          <div className="overflow-x-auto"><table className="dt min-w-[720px]">
            <thead><tr><th>Location</th><th className="w-[22%]">New Google reviews</th><th className="!text-right">Avg ★</th><th className="w-[22%]">Card scans</th><th className="!text-right">Clicks to Google</th><th>Google sync</th></tr></thead>
            <tbody>{rows.map((l) => {
              const s = sync.get(l.location);
              const bad = s?.status && s.status !== "ok" && s.status !== "running";
              return (
                <tr key={l.location}>
                  <td className="font-semibold">{l.location}</td>
                  <td><div className="flex items-center gap-2"><span className="num w-9 text-right font-semibold">{fmtNum(l.new_reviews)}</span><CellBar value={l.new_reviews} max={maxReviews} color="bg-accent" /></div></td>
                  <td className="n">{l.avg_rating === null ? "–" : fmtRating(l.avg_rating)}</td>
                  <td><div className="flex items-center gap-2"><span className="num w-12 text-right font-semibold">{fmtNum(l.scans)}</span><CellBar value={l.scans} max={maxScans} color="bg-ink-solid" /></div></td>
                  <td className="n">{fmtNum(l.google_clicks)}</td>
                  <td>{!s ? <Status tone="idle">Not connected</Status> : bad ? <Status tone="bad">Needs reconnect</Status> : <Status tone="ok">Updated {timeAgo(s.last_synced_at)}</Status>}</td>
                </tr>
              );
            })}</tbody>
          </table></div>
          <p className="px-3 pb-2 pt-3 text-[13px] text-muted">Clicks to Google are not reviews: we can&rsquo;t tell which scan led to a review.</p>
        </Panel>
      )}
    </>
  );
}
