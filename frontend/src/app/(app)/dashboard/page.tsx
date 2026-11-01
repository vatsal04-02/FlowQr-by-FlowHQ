"use client";
import { Clock, Eye, MessageSquareReply, MousePointerClick, ScanLine, Sparkles, Star, Reply } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { BarList } from "@/components/charts/BarList";
import { LineChart } from "@/components/charts/LineChart";
import { DateRange, presetRange } from "@/components/DateRange";
import { LinkButton } from "@/components/ui/Button";
import { Alert, Badge, Card, CardHeader, PageHeader, Skeleton, Stat } from "@/components/ui/Card";
import { FilterSelect } from "@/components/ui/Form";
import { useAuth } from "@/lib/auth";
import { fmtDate, fmtHours, fmtNum, fmtPct, timeAgo } from "@/lib/format";
import type { Location, Overview } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

export default function Dashboard() {
  const { tenant, me } = useAuth();
  const [range, setRange] = useState(presetRange("30"));
  const [loc, setLoc] = useState("");
  const locs = useFetch<Location[]>("/locations");
  const { data, error, loading } = useFetch<Overview>("/analytics/overview", { from: range.from, to: range.to, location_id: loc });
  const noCards = data && data.cards.length === 0;

  return (
    <>
      <PageHeader title={`Hello, ${tenant?.name ?? ""}`} subtitle="Your reputation at a glance." actions={
        <>
          <FilterSelect label="Location" value={loc} onChange={(e) => setLoc(e.target.value)}>
            <option value="">All locations</option>{locs.data?.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </FilterSelect>
          <DateRange value={range} onChange={setRange} />
        </>} />

      {error && <Alert tone="error" title="Couldn't load analytics">{error}</Alert>}
      {noCards && <div className="mb-5"><Alert tone="info" title="No QR/NFC card assigned yet" action={<LinkButton href="/cards" size="sm" variant="secondary">View cards</LinkButton>}>Cards are assigned to your locations by the FlowQR team. Until then you can still manage your review link.</Alert></div>}
      {data && !me?.integrations.google_configured && data.reviews.total_synced === 0 && (
        <div className="mb-5"><Alert tone="info" title="Review sync is in manual-link mode" action={<LinkButton href="/google" size="sm" variant="secondary">Google connection</LinkButton>}>Connect Google Business Profile to sync reviews and draft replies. Card scans and the AI writing assistant work now.</Alert></div>
      )}

      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-500">Customer funnel · cards</h2>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {loading || !data ? Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-28" />) : (<>
          <Stat label="QR/NFC scans" value={fmtNum(data.engagement.scans)} icon={<ScanLine className="h-5 w-5" />} hint="Card scanned or tapped" tone="flow" />
          <Stat label="Landing page visits" value={fmtNum(data.engagement.landing_views)} icon={<Eye className="h-5 w-5" />} hint="Review page loaded" />
          <Stat label="Clicks to Google" value={fmtNum(data.engagement.google_clicks)} icon={<MousePointerClick className="h-5 w-5" />} hint={`${fmtPct(data.engagement.click_through_rate)} of visits`} tone="green" />
          <Stat label="AI assistant uses" value={fmtNum(data.engagement.ai_assists)} icon={<Sparkles className="h-5 w-5" />} hint={data.ai.monthly_limit ? `${data.ai.used_this_month}/${data.ai.monthly_limit} this month` : undefined} tone="yellow" />
        </>)}
      </div>
      <p className="mt-2 text-xs text-ink-500">A click to Google doesn't prove a review was posted. Reviews that actually landed are counted separately below.</p>

      <h2 className="mb-3 mt-8 text-sm font-semibold uppercase tracking-wide text-ink-500">Reviews · from Google</h2>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {loading || !data ? Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-28" />) : (<>
          <Stat label="Synced reviews" value={fmtNum(data.reviews.total_synced)} icon={<Star className="h-5 w-5" />} hint={`${data.reviews.new_in_range} new in range`} />
          <Stat label="Average rating" value={data.reviews.average_rating_all_time ?? "–"} icon={<Star className="h-5 w-5" />} hint="All time" tone="yellow" />
          <Stat label="Awaiting reply" value={fmtNum(data.reviews.awaiting_reply)} icon={<MessageSquareReply className="h-5 w-5" />} hint={`${data.reviews.drafts_pending_approval} drafts to approve`} tone="red" />
          <Stat label="Reply rate" value={fmtPct(data.reviews.reply_rate_in_range)} icon={<Reply className="h-5 w-5" />} hint={`Avg response ${fmtHours(data.reviews.avg_response_hours)}`} tone="green" />
        </>)}
      </div>

      <div className="mt-6 grid gap-5 lg:grid-cols-2">
        <Card><CardHeader title="Card activity" subtitle="Scans, visits and clicks over time" />
          {data ? <LineChart ariaLabel="Card activity over time" data={data.engagement.series} series={[
            { key: "scan", label: "Scans", color: "#F26B1D" }, { key: "landing_view", label: "Visits", color: "#2F6FE4", dash: "6 4" }, { key: "google_click", label: "Clicks to Google", color: "#34A853", dash: "2 4" }]} /> : <Skeleton className="h-60" />}
        </Card>
        <Card><CardHeader title="New reviews" subtitle="Reviews received per day" />
          {data ? <LineChart ariaLabel="New reviews per day" data={data.reviews.series} series={[{ key: "count", label: "New reviews", color: "#2F6FE4" }]} /> : <Skeleton className="h-60" />}
        </Card>
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-3">
        <Card><CardHeader title="Rating mix" subtitle="All synced reviews" />
          {data && <BarList color="bg-g-yellow" rows={[5, 4, 3, 2, 1].map((n) => ({ label: `${n} star${n > 1 ? "s" : ""}`, value: data.reviews.rating_distribution[String(n)] ?? 0 }))} />}
        </Card>
        <Card className="lg:col-span-2"><CardHeader title="Locations" subtitle="Performance by branch" action={<Link href="/cards/analytics" className="text-sm font-semibold text-brand-700 hover:underline">Card analytics →</Link>} />
          {data && (data.locations.length ? (
            <div className="-mx-2 overflow-x-auto"><table className="w-full min-w-[480px] text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-ink-500"><tr><th className="px-2 py-2">Location</th><th className="px-2 py-2">Scans</th><th className="px-2 py-2">Visits</th><th className="px-2 py-2">Clicks</th><th className="px-2 py-2">New reviews</th><th className="px-2 py-2">Avg ★</th></tr></thead>
              <tbody>{data.locations.map((l) => <tr key={l.location} className="border-t border-ink-100"><td className="px-2 py-2.5 font-semibold">{l.location}</td><td className="px-2 tabular-nums">{l.scans}</td><td className="px-2 tabular-nums">{l.landing_views}</td><td className="px-2 tabular-nums">{l.google_clicks}</td><td className="px-2 tabular-nums">{l.new_reviews}</td><td className="px-2 tabular-nums">{l.avg_rating ?? "–"}</td></tr>)}</tbody>
            </table></div>) : <p className="text-sm text-ink-500">No locations yet.</p>)}
        </Card>
      </div>

      {data && data.sync.length > 0 && (
        <Card className="mt-5"><CardHeader title="Google sync status" subtitle="Reviews sync automatically every 30 minutes" />
          <ul className="divide-y divide-ink-100">{data.sync.map((s, i) => (
            <li key={i} className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-sm">
              <span className="font-semibold">{s.title ?? s.location}</span>
              <span className="flex items-center gap-2 text-ink-500"><Clock className="h-4 w-4" aria-hidden />{timeAgo(s.last_synced_at)}
                <Badge tone={s.status === "ok" ? "green" : s.status === "rate_limited" ? "amber" : s.status ? "red" : "gray"}>{s.status ?? "pending"}</Badge></span>
              {s.error && <span className="w-full text-xs text-red-700">{s.error}</span>}
            </li>))}</ul>
        </Card>
      )}
      {data && <p className="mt-4 text-xs text-ink-400">Showing {fmtDate(data.range.from)} – {fmtDate(data.range.to)} ({data.range.timezone}). Bot traffic and rapid refreshes are excluded.</p>}
    </>
  );
}
