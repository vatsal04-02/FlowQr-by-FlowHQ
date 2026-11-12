"use client";
import { Download } from "lucide-react";
import { useMemo, useState } from "react";
import { DateRange, presetRange } from "@/components/DateRange";
import { GbpFrame } from "@/components/gbp/GbpFrame";
import { Gate, PerfTab } from "@/components/gbp/tools";
import { Button } from "@/components/ui/Button";
import { Alert, PageHeader, Skeleton } from "@/components/ui/Card";
import { Panel } from "@/components/ui/kit";
import { api, errorMessage } from "@/lib/api";
import { useGbp } from "@/lib/use-gbp";
import { useEffect } from "react";

const METRICS: [string, string][] = [["CALL_CLICKS", "Calls"], ["WEBSITE_CLICKS", "Website clicks"], ["BUSINESS_DIRECTION_REQUESTS", "Directions"], ["BUSINESS_BOOKINGS", "Bookings"], ["MESSAGING_CLICKS", "Messages"]];
interface Row { id: string; title: string; totals: Record<string, number> | null; error: string | null }

/** Same Google numbers for every connected location side by side, with the time they were fetched and a CSV export. */
function Compare() {
  const g = useGbp();
  const [range, setRange] = useState(presetRange("30"));
  const [rows, setRows] = useState<Row[]>([]);
  const [fetchedAt, setFetchedAt] = useState<Date | null>(null);
  const [busy, setBusy] = useState(false);
  const ids = useMemo(() => g.selected.map((l) => [l.id, l.title ?? "Location"] as const), [g.selected]);
  useEffect(() => {
    if (ids.length < 2) return;
    let live = true;
    setBusy(true);
    void Promise.all(ids.slice(0, 10).map(async ([id, title]): Promise<Row> => {
      try { const r = await api<{ totals: Record<string, number> }>(`/gbp/${id}/performance`, { params: { from: range.from, to: range.to } }); return { id, title, totals: r.totals, error: null }; }
      catch (e) { return { id, title, totals: null, error: errorMessage(e) }; }
    })).then((r) => { if (live) { setRows(r); setFetchedAt(new Date()); setBusy(false); } });
    return () => { live = false; };
  }, [ids, range.from, range.to]);
  if (ids.length < 2) return null;
  const impressions = (t: Record<string, number>) => Object.entries(t).filter(([k]) => k.startsWith("BUSINESS_IMPRESSIONS")).reduce((a, [, v]) => a + v, 0);
  function exportCsv() {
    const head = ["location", "profile_views", ...METRICS.map(([, l]) => l.toLowerCase().replace(/ /g, "_"))];
    const body = rows.map((r) => [r.title, r.totals ? impressions(r.totals) : "", ...METRICS.map(([k]) => (r.totals ? r.totals[k] ?? 0 : ""))]);
    const csv = [head, ...body].map((l) => l.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(",")).join("\n");
    const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob(["\ufeff" + csv], { type: "text/csv" })); a.download = `flowqr-google-performance-${range.from}-${range.to}.csv`; a.click();
  }
  return (
    <Panel title="Compare locations" meta={fetchedAt ? `fetched from Google at ${fetchedAt.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}` : undefined}
      action={<div className="flex items-center gap-2"><DateRange value={range} onChange={setRange} /><Button size="sm" variant="secondary" icon={<Download className="h-4 w-4" />} disabled={!rows.length} onClick={exportCsv}>CSV</Button></div>} flush>
      {busy && rows.length === 0 ? <Skeleton className="m-4 h-24" /> : (
        <div className="overflow-x-auto"><table className="dt min-w-[560px]"><thead><tr><th>Location</th><th className="!text-right">Profile views</th>{METRICS.map(([, l]) => <th key={l} className="!text-right">{l}</th>)}</tr></thead>
          <tbody>{rows.map((r) => <tr key={r.id}><td className="font-medium">{r.title}</td>{r.totals ? <><td className="n">{impressions(r.totals).toLocaleString("en-IN")}</td>{METRICS.map(([k]) => <td key={k} className="n">{(r.totals![k] ?? 0).toLocaleString("en-IN")}</td>)}</> : <td colSpan={METRICS.length + 1} className="text-red-700">{r.error}</td>}</tr>)}</tbody></table></div>)}
    </Panel>
  );
}

export default function PerformancePage() {
  return (
    <>
      <PageHeader eyebrow="Google Business" title="Performance" subtitle="What Google reports about your profile: views and customer actions. Google's data runs a few days behind and is not the same as FlowQR card scans. Nothing here is estimated." />
      <GbpFrame>{(gid) => <div className="space-y-5"><PerfTab key={gid} gid={gid} /><Compare /></div>}</GbpFrame>
    </>
  );
}
