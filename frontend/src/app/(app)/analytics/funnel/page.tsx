"use client";
import Link from "next/link";
import { useState } from "react";
import { LineChart } from "@/components/charts/LineChart";
import { DateRange, presetRange } from "@/components/DateRange";
import { Alert, PageHeader, Skeleton } from "@/components/ui/Card";
import { FilterSelect } from "@/components/ui/Form";
import { CellBar, Panel, Status } from "@/components/ui/kit";
import { fmtNum, fmtPct } from "@/lib/format";
import type { Card as CardT, Location, Overview } from "@/lib/types";
import { useFetch } from "@/lib/use-api";
import { timeAgo } from "@/lib/format";

const rate = (a: number, b: number) => (b ? fmtPct(a / b) : "–");

export default function CardAnalytics() {
  const [range, setRange] = useState(presetRange("30"));
  const [loc, setLoc] = useState("");
  const locs = useFetch<Location[]>("/locations");
  const cards = useFetch<CardT[]>("/cards");
  const { data: o, error } = useFetch<Overview>("/analytics/overview", { from: range.from, to: range.to, location_id: loc });
  const lastScan = new Map((cards.data ?? []).map((c) => [c.card_code, c.last_scan_at]));
  const sorted = [...(o?.cards ?? [])].sort((a, b) => b.scans - a.scans);
  const maxScans = Math.max(1, ...sorted.map((c) => c.scans));
  const e = o?.engagement;
  const steps = e ? [["Scans", e.scans, 1], ["Landing page visits", e.landing_views, e.scans ? e.landing_views / e.scans : 0], ["Clicks to Google", e.google_clicks, e.scans ? e.google_clicks / e.scans : 0]] as const : [];

  return (
    <>
      <PageHeader title="QR & NFC results" subtitle="From QR scan to Google: how many scans became page visits and clicks to Google."
        actions={<>
          <FilterSelect label="Location" value={loc} onChange={(ev) => setLoc(ev.target.value)}><option value="">All locations</option>{locs.data?.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</FilterSelect>
          <DateRange value={range} onChange={setRange} />
        </>} />
      {error && <Alert tone="error">{error}</Alert>}
      {!o && !error && <Skeleton className="h-72" />}
      {o && e && (
        <div className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-[1fr_1.35fr]">
            <Panel title="Funnel" meta="from your cards">
              <ol className="space-y-3">
                {steps.map(([k, v, share]) => (
                  <li key={k}>
                    <div className="mb-1 flex items-baseline justify-between text-sm"><span className="font-medium">{k}</span><span className="num"><b className="font-semibold">{fmtNum(v)}</b>{k !== "Scans" && <span className="ml-2 text-xs text-ink-500">{fmtPct(share)} of scans</span>}</span></div>
                    <div className="h-6 overflow-hidden rounded bg-ink-100"><div className="h-full rounded bg-brand-600" style={{ width: `${Math.max(share * 100, v ? 1.5 : 0)}%` }} /></div>
                  </li>
                ))}
              </ol>
              <p className="mt-4 text-[13px] text-ink-500">Visit-to-click rate: <b className="num font-semibold text-ink">{fmtPct(e.click_through_rate)}</b>. AI writing help was used <b className="num font-semibold text-ink">{fmtNum(e.ai_assists)}</b> times.</p>
              <div className="mt-4 border-t border-ink-100 pt-3 text-[13px]">
                <p className="flex items-baseline justify-between"><span className="font-medium">Reviews that actually landed</span><b className="num text-base font-semibold">{fmtNum(o.reviews.new_in_range)}</b></p>
                <p className="mt-1 text-xs text-ink-500">Counted from synced Google reviews, not from clicks. A submitted review can&rsquo;t be matched to a card. Connected locations only.</p>
              </div>
            </Panel>
            <Panel title="Activity over time">
              <LineChart ariaLabel="Scans, visits and clicks over time" data={e.series} height={250} series={[{ key: "scan", label: "Scans", color: "rgb(var(--c-accent))" }, { key: "landing_view", label: "Visits", color: "rgb(var(--c-ink-solid))", dash: "6 4" }, { key: "google_click", label: "Clicks to Google", color: "rgb(var(--c-pos))", dash: "2 4" }]} />
            </Panel>
          </div>

          <Panel title="Cards compared" meta="ranked by scans" flush>
            {sorted.length === 0 ? <p className="p-4 text-sm text-ink-500">No cards assigned yet.</p> : (
              <div className="overflow-x-auto"><table className="dt min-w-[820px]">
                <thead><tr><th>Card</th><th>Location</th><th>Status</th><th className="w-[22%]">Scans</th><th className="!text-right">Visits</th><th className="!text-right">Visit rate</th><th className="!text-right">Clicks</th><th className="!text-right">Click rate</th><th>Last scan</th></tr></thead>
                <tbody>{sorted.map((c) => (
                  <tr key={c.card_code}>
                    <td><span className="card-code text-[13px] font-medium">{c.card_code}</span>{c.label && <p className="text-xs text-ink-500">{c.label}</p>}</td>
                    <td>{c.location ?? "–"}</td>
                    <td><Status tone={c.status === "active" ? "ok" : c.status === "assigned" ? "info" : "idle"}>{c.status}</Status></td>
                    <td><div className="flex items-center gap-2"><span className="num w-9 text-right font-semibold">{fmtNum(c.scans)}</span><CellBar value={c.scans} max={maxScans} /></div></td>
                    <td className="n">{fmtNum(c.landing_views)}</td><td className="n text-ink-500">{rate(c.landing_views, c.scans)}</td>
                    <td className="n">{fmtNum(c.google_clicks)}</td><td className="n text-ink-500">{rate(c.google_clicks, c.landing_views)}</td>
                    <td className="whitespace-nowrap text-ink-500">{lastScan.get(c.card_code) ? timeAgo(lastScan.get(c.card_code)) : "never"}</td>
                  </tr>))}</tbody>
              </table></div>
            )}
          </Panel>

          <Panel title="Locations compared" action={<Link href="/analytics/reviews" className="text-[13px] font-medium text-brand-700 hover:underline">Full analytics</Link>} flush>
            <div className="overflow-x-auto"><table className="dt min-w-[560px]">
              <thead><tr><th>Location</th><th className="!text-right">Scans</th><th className="!text-right">Visits</th><th className="!text-right">Clicks</th><th className="!text-right">New reviews</th><th className="!text-right">Avg ★</th></tr></thead>
              <tbody>{o.locations.map((l) => (
                <tr key={l.location}><td className="font-medium">{l.location}</td><td className="n font-medium">{fmtNum(l.scans)}</td><td className="n">{fmtNum(l.landing_views)}</td><td className="n">{fmtNum(l.google_clicks)}</td><td className="n">{l.new_reviews}</td><td className="n">{l.avg_rating ?? "–"}</td></tr>))}</tbody>
            </table></div>
          </Panel>

          <details className="panel p-4 text-sm">
            <summary className="cursor-pointer text-[13px] font-semibold">How we count</summary>
            <dl className="mt-3 grid gap-3 sm:grid-cols-2">
              {Object.entries({ "QR/NFC scans": e.definitions.scans, "Landing page visits": e.definitions.landing_views, "Clicks to Google": e.definitions.google_clicks, "Submitted Google reviews": e.definitions.submitted_reviews }).map(([k, v]) => (
                <div key={k}><dt className="font-medium">{k}</dt><dd className="mt-0.5 text-[13px] text-ink-500">{v}</dd></div>))}
            </dl>
          </details>
        </div>
      )}
    </>
  );
}
