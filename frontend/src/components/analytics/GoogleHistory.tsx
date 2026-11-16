"use client";
import clsx from "clsx";
import { ArrowDownRight, ArrowUpRight, Download, Minus } from "lucide-react";
import type { ReactNode } from "react";
import { Bars } from "@/components/charts/Bars";
import type { Range } from "@/components/DateRange";
import { SourceTag } from "@/components/seo/parts";
import { Card, Dashes, Title } from "@/components/seo/visuals";
import { Button, LinkButton } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Card";
import { DataTable } from "@/components/ui/DataTable";
import { fmtNum } from "@/lib/format";
import { useLocationScope } from "@/lib/location-scope";
import type { GoogleMetrics, GoogleMetricSummary } from "@/lib/seo";
import { useFetch } from "@/lib/use-api";

const CARDS: [keyof GoogleMetricSummary, string, string[]][] = [
  ["calls", "Calls", ["CALL_CLICKS"]], ["directions", "Directions", ["BUSINESS_DIRECTION_REQUESTS"]], ["website", "Website clicks", ["WEBSITE_CLICKS"]],
  ["search_views", "Profile views", ["BUSINESS_IMPRESSIONS_DESKTOP_SEARCH", "BUSINESS_IMPRESSIONS_MOBILE_SEARCH", "BUSINESS_IMPRESSIONS_DESKTOP_MAPS", "BUSINESS_IMPRESSIONS_MOBILE_MAPS"]],
];

function Change({ cur, prev }: { cur: number | null; prev: number | null }) {
  if (cur === null || prev === null || prev === 0) return null;
  const p = Math.round(((cur - prev) / prev) * 100);
  const Icon = p > 0 ? ArrowUpRight : p < 0 ? ArrowDownRight : Minus;
  return <span className={clsx("inline-flex items-center gap-0.5 text-[13px] font-medium", p > 0 ? "text-pos" : p < 0 ? "text-neg" : "text-muted")}><Icon className="h-3.5 w-3.5" aria-hidden />{Math.abs(p)}%</span>;
}

/**
 * GBP › Performance, from the daily figures FlowQR stored from Google (gbp_metric_daily): four cards, each its number, the change against the period before and a bar per
 * day (counts are bars). Until Google has shared anything, the page is one card of dashes with one button. `extra` (the live detail) only appears once data exists.
 */
export function GoogleHistory({ range, extra }: { range: Range; extra?: ReactNode }) {
  const { locationId } = useLocationScope();
  const q = useFetch<GoogleMetrics>("/analytics/google-metrics", { from: range.from, to: range.to, location_id: locationId ?? "" });
  const d = q.data;
  const ok = !!d && d.availability.state === "ok" && !!d.current;
  if (q.loading && !d) return <Skeleton className="h-64" />;
  if (!ok) return (
    <Card label="Google performance">
      <Title right={<SourceTag source="google" />}>From Google</Title>
      <div className="mt-4 grid grid-cols-2 gap-4 md:grid-cols-4">{CARDS.map(([k, l]) => <div key={k}><p className="text-[13px] text-muted">{l}</p><p className="text-[20px] font-semibold">–</p><Dashes className="mt-1" /></div>)}</div>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3"><p className="text-[14px] text-muted">{q.error ? "Couldn't load." : "Waiting for Google. History starts the first day Google shares."}</p><LinkButton href="/gbp/locations" variant="secondary" size="sm">Check connection</LinkButton></div>
    </Card>
  );
  const sum = (metrics: string[]) => {
    const m = new Map<string, number>();
    for (const k of metrics) for (const p of d!.series[k] ?? []) m.set(p.date, (m.get(p.date) ?? 0) + p.value);
    return [...m.entries()].sort().map(([date, v]) => ({ key: date, cur: v, label: new Date(date + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short" }) }));
  };
  const views = (s: GoogleMetricSummary | null) => (s && (s.search_views !== null || s.maps_views !== null) ? (s.search_views ?? 0) + (s.maps_views ?? 0) : null);
  const val = (s: GoogleMetricSummary | null, k: keyof GoogleMetricSummary) => (k === "search_views" ? views(s) : s ? s[k] : null);

  function exportCsv() {
    const head = ["location", ...CARDS.map(([, l]) => l.toLowerCase().replace(/ /g, "_"))];
    const lines = [["all locations", ...CARDS.map(([k]) => val(d!.current, k) ?? "")], ...d!.by_location.map((l) => [l.title ?? "Location", ...CARDS.map(([k]) => val(l.totals, k) ?? "")])];
    const csv = [head, ...lines].map((l) => l.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(",")).join("\n");
    const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv" })); a.download = `flowqr-google-${d!.range.from}-${d!.range.to}.csv`; a.click();
  }
  return (
    <div className="space-y-3 lg:space-y-4">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:gap-4">
        {CARDS.map(([k, label, metrics]) => {
          const cur = val(d!.current, k), prev = d!.previous ? val(d!.previous, k) : null;
          return (
            <Card key={k} label={label}>
              <Title>{label}</Title>
              <p className="mt-1 flex items-baseline gap-2"><span className="num text-[28px] font-semibold leading-9 tracking-[-.02em]">{cur === null ? "–" : fmtNum(cur)}</span><Change cur={cur} prev={prev} /></p>
              <div className="mt-3"><Bars data={sum(metrics)} height={110} label={`${label} per day`} unit={label.toLowerCase()} /></div>
            </Card>
          );
        })}
      </div>
      {d!.by_location.length > 1 && (
        <Card label="By location">
          <Title right={<Button size="sm" variant="secondary" icon={<Download className="h-4 w-4" />} onClick={exportCsv}>CSV</Button>}>By location</Title>
          <div className="mt-3"><DataTable label="Google activity by location" rows={d!.by_location} rowKey={(l) => l.id} cols={[
            { key: "n", header: "Location", cell: (l) => <span className="font-medium">{l.title ?? "Location"}</span> },
            ...CARDS.map(([k, label]) => ({ key: k, header: label, align: "right" as const, cell: (l: GoogleMetrics["by_location"][number]) => <span className="num">{val(l.totals, k) === null ? "–" : fmtNum(val(l.totals, k) as number)}</span> })),
          ]} /></div>
        </Card>
      )}
      {d!.by_location.length <= 1 && <div className="flex justify-end"><Button size="sm" variant="secondary" icon={<Download className="h-4 w-4" />} onClick={exportCsv}>Download CSV</Button></div>}
      {extra}
    </div>
  );
}
