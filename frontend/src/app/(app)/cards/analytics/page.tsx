"use client";
import { useState } from "react";
import { BarList } from "@/components/charts/BarList";
import { LineChart } from "@/components/charts/LineChart";
import { DateRange, presetRange } from "@/components/DateRange";
import { Alert, Badge, Card, CardHeader, PageHeader, Skeleton } from "@/components/ui/Card";
import { FilterSelect } from "@/components/ui/Form";
import { fmtPct } from "@/lib/format";
import type { Location, Overview } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

export default function CardAnalytics() {
  const [range, setRange] = useState(presetRange("30"));
  const [loc, setLoc] = useState("");
  const locs = useFetch<Location[]>("/locations");
  const { data, error, loading } = useFetch<Overview>("/analytics/overview", { from: range.from, to: range.to, location_id: loc });

  return (
    <>
      <PageHeader title="Card analytics" subtitle="How each card and location performs, step by step." actions={<>
        <FilterSelect label="Location" value={loc} onChange={(e) => setLoc(e.target.value)}><option value="">All locations</option>{locs.data?.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</FilterSelect>
        <DateRange value={range} onChange={setRange} /></>} />
      {error && <Alert tone="error">{error}</Alert>}
      <Card className="mb-5"><CardHeader title="What each number means" />
        <dl className="grid gap-3 text-sm sm:grid-cols-2">
          {data && Object.entries({ "QR/NFC scans": data.engagement.definitions.scans, "Landing page visits": data.engagement.definitions.landing_views, "Clicks to Google": data.engagement.definitions.google_clicks, "Submitted Google reviews": data.engagement.definitions.submitted_reviews }).map(([k, v]) => (
            <div key={k} className="rounded-xl bg-ink-50 p-3"><dt className="font-semibold">{k}</dt><dd className="mt-0.5 text-ink-500">{v}</dd></div>
          ))}
        </dl>
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card><CardHeader title="Funnel" subtitle={`Click-through: ${fmtPct(data?.engagement.click_through_rate)} of visits`} />
          {data ? <BarList rows={[{ label: "Scans", value: data.engagement.scans }, { label: "Visits", value: data.engagement.landing_views }, { label: "AI assists", value: data.engagement.ai_assists }, { label: "Google clicks", value: data.engagement.google_clicks }]} color="bg-flow-500" /> : <Skeleton className="h-32" />}
          {data && <p className="mt-4 rounded-xl bg-amber-50 p-3 text-sm text-amber-900">Submitted reviews can't be matched to a click. See actual new reviews: <b>{data.reviews.new_in_range}</b> in this period (connected Google locations only).</p>}
        </Card>
        <Card><CardHeader title="Activity over time" />
          {data ? <LineChart ariaLabel="Scans, visits and clicks over time" data={data.engagement.series} series={[{ key: "scan", label: "Scans", color: "#F26B1D" }, { key: "landing_view", label: "Visits", color: "#2F6FE4", dash: "6 4" }, { key: "google_click", label: "Clicks to Google", color: "#34A853", dash: "2 4" }]} /> : <Skeleton className="h-60" />}
        </Card>
      </div>

      <Card className="mt-5" pad={false}>
        <div className="p-5 sm:p-6"><CardHeader title="Card performance" subtitle="Ranked by scans" /></div>
        {loading && !data ? <Skeleton className="m-5 h-32" /> : data && data.cards.length === 0 ? <p className="px-6 pb-6 text-sm text-ink-500">No cards assigned yet.</p> : (
          <div className="overflow-x-auto"><table className="w-full min-w-[640px] text-left text-sm">
            <thead className="border-y border-ink-100 bg-ink-50 text-xs uppercase tracking-wide text-ink-500"><tr>{["Card", "Location", "Status", "Scans", "Visits", "AI uses", "Google clicks"].map((h) => <th key={h} className="px-4 py-2.5 font-semibold">{h}</th>)}</tr></thead>
            <tbody>{data?.cards.map((c) => (
              <tr key={c.card_code} className="border-b border-ink-100 last:border-0">
                <td className="px-4 py-3 font-semibold">{c.card_code}{c.label && <span className="block text-xs font-normal text-ink-500">{c.label}</span>}</td>
                <td className="px-4">{c.location ?? "–"}</td><td className="px-4"><Badge tone={c.status === "active" ? "green" : "gray"}>{c.status}</Badge></td>
                <td className="px-4 tabular-nums font-semibold">{c.scans}</td><td className="px-4 tabular-nums">{c.landing_views}</td><td className="px-4 tabular-nums">{c.ai_assists}</td><td className="px-4 tabular-nums">{c.google_clicks}</td>
              </tr>))}</tbody>
          </table></div>
        )}
      </Card>
    </>
  );
}
