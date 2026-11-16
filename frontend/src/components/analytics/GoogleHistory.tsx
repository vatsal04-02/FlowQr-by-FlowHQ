"use client";
import { Download } from "lucide-react";
import { useMemo } from "react";
import { LineChart, type Series } from "@/components/charts/LineChart";
import type { Range } from "@/components/DateRange";
import { SourceTag, Unavailable, when } from "@/components/seo/parts";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Card";
import { Panel } from "@/components/ui/kit";
import { fmtNum } from "@/lib/format";
import { useLocationScope } from "@/lib/location-scope";
import type { GoogleMetrics, GoogleMetricSummary } from "@/lib/seo";
import { useFetch } from "@/lib/use-api";

const ROWS: [keyof GoogleMetricSummary, string][] = [
  ["search_views", "Search views"], ["maps_views", "Maps views"], ["website", "Website clicks"], ["calls", "Calls"], ["directions", "Direction requests"], ["bookings", "Bookings"], ["messages", "Messages"],
];
const SEARCH = ["BUSINESS_IMPRESSIONS_DESKTOP_SEARCH", "BUSINESS_IMPRESSIONS_MOBILE_SEARCH"], MAPS = ["BUSINESS_IMPRESSIONS_DESKTOP_MAPS", "BUSINESS_IMPRESSIONS_MOBILE_MAPS"];
const ORANGE = "rgb(var(--c-accent))", INK = "rgb(var(--c-ink-solid))";

function sumDaily(series: GoogleMetrics["series"], metrics: string[]) {
  const by = new Map<string, number>(), seen = new Set<string>();
  for (const m of metrics) for (const p of series[m] ?? []) { by.set(p.date, (by.get(p.date) ?? 0) + p.value); seen.add(p.date); }
  return by;
}

const pct = (cur: number | null, prev: number | null) => (cur === null || prev === null ? null : prev === 0 ? (cur > 0 ? null : 0) : Math.round(((cur - prev) / prev) * 100));

/**
 * Analytics › Performance › Search & Maps, from the daily history FlowQR stored (gbp_metric_daily). A comparison appears only when the earlier period has stored days; a metric Google
 * did not return is "Not shared", never 0. Until Google has actually shared data the whole block is one explicit unavailable state.
 */
export function GoogleHistory({ range }: { range: Range }) {
  const { locationId } = useLocationScope();
  const q = useFetch<GoogleMetrics>("/analytics/google-metrics", { from: range.from, to: range.to, location_id: locationId ?? "" });
  const d = q.data;
  const ok = !!d && d.availability.state === "ok" && !!d.current;

  const views = useMemo(() => {
    if (!d || !ok) return [];
    const s = sumDaily(d.series, SEARCH), m = sumDaily(d.series, MAPS);
    return [...new Set([...s.keys(), ...m.keys()])].sort().map((date) => ({ date, search: s.get(date) ?? 0, maps: m.get(date) ?? 0 }));
  }, [d, ok]);
  const actions = useMemo(() => {
    if (!d || !ok) return [];
    const c = sumDaily(d.series, ["CALL_CLICKS"]), w = sumDaily(d.series, ["WEBSITE_CLICKS"]), r = sumDaily(d.series, ["BUSINESS_DIRECTION_REQUESTS"]);
    return [...new Set([...c.keys(), ...w.keys(), ...r.keys()])].sort().map((date) => ({ date, calls: c.get(date) ?? 0, website: w.get(date) ?? 0, directions: r.get(date) ?? 0 }));
  }, [d, ok]);
  const viewSeries: Series[] = [{ key: "search", label: "Search views", color: ORANGE }, { key: "maps", label: "Maps views", color: INK, dash: "5 4" }];
  const actionSeries: Series[] = [{ key: "website", label: "Website clicks", color: ORANGE }, { key: "calls", label: "Calls", color: INK, dash: "5 4" }, { key: "directions", label: "Directions", color: "rgb(var(--c-ink-300))", dash: "2 4" }];

  function exportCsv() {
    if (!d) return;
    const head = ["location", ...ROWS.map(([, l]) => l.toLowerCase().replace(/ /g, "_"))];
    const lines = [["all locations", ...ROWS.map(([k]) => d.current?.[k] ?? "")], ...d.by_location.map((l) => [l.title ?? "Location", ...ROWS.map(([k]) => l.totals?.[k] ?? "")])];
    const csv = [head, ...lines].map((l) => l.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(",")).join("\n");
    const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv" })); a.download = `flowqr-google-activity-${d.range.from}-${d.range.to}.csv`; a.click();
  }

  return (
    <section aria-labelledby="gh-h" className="space-y-4">
      <Panel dense title={<span id="gh-h">Google activity</span>} meta={ok ? `${when(d!.range.from)} to ${when(d!.range.to)}` : undefined}
        action={<span className="flex items-center gap-2"><SourceTag source="google" />{ok && <Button size="sm" variant="secondary" icon={<Download className="h-4 w-4" />} onClick={exportCsv}>CSV</Button>}</span>}>
        {q.loading && !d ? <Skeleton className="h-40" /> : q.error ? <Unavailable title="We couldn't load Google's numbers just now">{q.error}</Unavailable>
          : !ok ? <Unavailable title="Google isn't sharing these numbers yet" href="/gbp/locations" cta="Check the Google connection">{d?.availability.reason} Nothing is estimated, and no zeros are shown in their place. FlowQR collects Google&rsquo;s figures once a day and keeps them, so history builds from the first day Google shares them.</Unavailable>
          : (
            <>
              <div className="overflow-x-auto">
                <table className="dt min-w-[520px]">
                  <thead><tr><th>Metric</th><th className="!text-right">This period</th><th className="!text-right">Previous period</th><th className="!text-right">Change</th></tr></thead>
                  <tbody>{ROWS.filter(([k]) => d!.current![k] !== null || d!.previous?.[k] != null).map(([k, label]) => {
                    const cur = d!.current![k], prev = d!.previous ? d!.previous[k] : null, ch = pct(cur, prev);
                    return <tr key={k}><td className="font-medium">{label}</td><td className="n">{cur === null ? "Not shared" : fmtNum(cur)}</td><td className="n text-muted">{prev === null ? "–" : fmtNum(prev)}</td>
                      <td className={`n ${ch === null ? "text-muted" : ch > 0 ? "text-pos" : ch < 0 ? "text-neg" : "text-muted"}`}>{ch === null ? "–" : `${ch > 0 ? "+" : ""}${ch}%`}</td></tr>;
                  })}</tbody>
                </table>
              </div>
              <p className="mt-3 text-xs text-muted">
                {d!.note} {d!.days_with_data} of {d!.range_days} days in this range have stored data
                {d!.previous_range ? `; the previous period (${when(d!.previous_range.from)} to ${when(d!.previous_range.to)}) has ${d!.previous_range.days_with_data}.` : "; no earlier days are stored yet, so no comparison is shown."}
                {d!.availability.last_fetched_at ? ` Last collected ${when(d!.availability.last_fetched_at)}.` : ""}
              </p>
            </>
          )}
      </Panel>

      {ok && (
        <div className="grid gap-4 xl:grid-cols-2">
          <Panel dense title="Search and Maps views" meta="per day" action={<SourceTag source="google" />}>
            {views.length >= 2 ? <LineChart ariaLabel="Profile views in Google Search and Maps per day" data={views} series={viewSeries} height={220} /> : <Unavailable title="Not enough days stored to draw a line">A line needs at least two days of Google data in this range.</Unavailable>}
          </Panel>
          <Panel dense title="Customer actions" meta="per day" action={<SourceTag source="google" />}>
            {actions.length >= 2 ? <LineChart ariaLabel="Website clicks, calls and direction requests per day" data={actions} series={actionSeries} height={220} /> : <Unavailable title="Not enough days stored to draw a line">A line needs at least two days of Google data in this range.</Unavailable>}
          </Panel>
        </div>
      )}

      {ok && d!.by_location.length > 1 && (
        <Panel dense title="By location" meta="same period" flush>
          <div className="overflow-x-auto">
            <table className="dt min-w-[640px]">
              <thead><tr><th>Location</th><th className="!text-right">Search views</th><th className="!text-right">Maps views</th><th className="!text-right">Website</th><th className="!text-right">Calls</th><th className="!text-right">Directions</th><th className="!text-right">Days stored</th></tr></thead>
              <tbody>{d!.by_location.map((l) => (
                <tr key={l.id}><td className="font-medium">{l.title ?? "Location"}</td>
                  {(["search_views", "maps_views", "website", "calls", "directions"] as const).map((k) => <td key={k} className="n">{l.totals ? (l.totals[k] === null ? "–" : fmtNum(l.totals[k] as number)) : "–"}</td>)}
                  <td className="n text-muted">{l.days_with_data}</td></tr>
              ))}</tbody>
            </table>
          </div>
        </Panel>
      )}
    </section>
  );
}
