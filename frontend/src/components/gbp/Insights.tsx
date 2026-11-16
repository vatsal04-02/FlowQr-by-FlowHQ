"use client";
import clsx from "clsx";
import { Search } from "lucide-react";
import { useMemo, useState } from "react";
import { Skeleton } from "@/components/ui/Card";
import { Panel, Segmented } from "@/components/ui/kit";
import { fmtNum } from "@/lib/format";
import { useFetch } from "@/lib/use-api";
import { Gate } from "./tools";

interface Kw { keyword: string; value: number | null; below: number | null }

/**
 * Search terms people used before seeing the profile (Google Performance API, monthly). Google gives exact counts only above a privacy
 * threshold; below it, only "fewer than N", which is shown exactly that way and never turned into a number or a bar.
 */
export function KeywordsPanel({ gid }: { gid: string }) {
  const [months, setMonths] = useState("3");
  const { data, error, loading } = useFetch<{ from_month: string; to_month: string; keywords: Kw[]; note: string }>(`/gbp/${gid}/keywords`, { months });
  const top = Math.max(1, ...(data?.keywords ?? []).map((k) => k.value ?? 0));
  const exact = (data?.keywords ?? []).filter((k) => k.value !== null);
  const small = (data?.keywords ?? []).filter((k) => k.value === null);
  return (
    <Panel title="What people searched" meta={data ? `${data.from_month} to ${data.to_month} · from Google` : undefined}
      action={<Segmented label="Months" value={months} onChange={setMonths} options={[["1", "1 month"], ["3", "3 months"], ["6", "6 months"]] as const} />}>
      {error ? <Gate error={error} /> : loading && !data ? <Skeleton className="h-48" /> : !data || data.keywords.length === 0 ? (
        <p className="rounded-tile bg-surface-2 p-5 text-sm text-muted">Google hasn&rsquo;t reported search terms for these months. New or low-traffic profiles often have none.</p>
      ) : (
        <>
          <ul className="space-y-2.5">
            {exact.slice(0, 12).map((k) => (
              <li key={k.keyword} className="grid grid-cols-[minmax(0,1.3fr)_minmax(0,1.5fr)_3.5rem] items-center gap-3 text-sm">
                <span className="flex min-w-0 items-center gap-2"><Search className="h-3.5 w-3.5 shrink-0 text-muted" aria-hidden /><span className="truncate font-medium" title={k.keyword}>{k.keyword}</span></span>
                <span className="block h-2.5 overflow-hidden rounded-full bg-surface-2"><span className="grow-x block h-full rounded-full bg-ink-solid" style={{ width: `${((k.value ?? 0) / top) * 100}%` }} /></span>
                <span className="num text-right font-semibold">{fmtNum(k.value)}</span>
              </li>
            ))}
          </ul>
          {small.length > 0 && (
            <div className="mt-5">
              <p className="text-xs font-medium text-muted">Smaller searches (Google only says &ldquo;fewer than&rdquo;)</p>
              <ul className="mt-2 flex flex-wrap gap-1.5">{small.slice(0, 20).map((k) => <li key={k.keyword} className="rounded-full bg-surface-2 px-3 py-1 text-[13px]">{k.keyword} <span className="text-muted">&lt; {k.below}</span></li>)}</ul>
            </div>
          )}
          <p className="mt-4 text-xs text-muted">{data.note}</p>
        </>
      )}
    </Panel>
  );
}

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const IMPRESSIONS = ["BUSINESS_IMPRESSIONS_DESKTOP_MAPS", "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH", "BUSINESS_IMPRESSIONS_MOBILE_MAPS", "BUSINESS_IMPRESSIONS_MOBILE_SEARCH"];
const ACTIONS = ["CALL_CLICKS", "WEBSITE_CLICKS", "BUSINESS_DIRECTION_REQUESTS", "BUSINESS_BOOKINGS", "MESSAGING_CLICKS"];

/** Monthly totals for the last 12 months straight from Google's daily series, with month-on-month change. The current month is partial. */
export function MonthlyTrend({ gid }: { gid: string }) {
  const end = useMemo(() => { const d = new Date(); d.setDate(d.getDate() - 3); return d; }, []);
  const start = useMemo(() => new Date(end.getFullYear() - 1, end.getMonth() + 1, 1), [end]);
  const [metric, setMetric] = useState<"views" | "actions">("views");
  const { data, error, loading } = useFetch<{ series: Record<string, { date: string; value: number }[]> }>(`/gbp/${gid}/performance`, { from: iso(start), to: iso(end) });
  const [fetchedAt] = useState(() => new Date());
  const months = useMemo(() => {
    if (!data) return [];
    const keys = metric === "views" ? IMPRESSIONS : ACTIONS;
    const by = new Map<string, number>();
    for (const k of keys) for (const p of data.series[k] ?? []) by.set(p.date.slice(0, 7), (by.get(p.date.slice(0, 7)) ?? 0) + p.value);
    const out: { m: string; v: number }[] = [];
    for (let d = new Date(start); d <= end; d = new Date(d.getFullYear(), d.getMonth() + 1, 1)) {
      const k = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
      out.push({ m: k, v: by.get(k) ?? 0 });
    }
    return out;
  }, [data, metric, start, end]);
  const max = Math.max(1, ...months.map((x) => x.v));
  const last = months.at(-2), prev = months.at(-3);
  const change = last && prev && prev.v > 0 ? Math.round(((last.v - prev.v) / prev.v) * 100) : null;
  return (
    <Panel title="Monthly trend" meta={`last 12 months · fetched from Google at ${fetchedAt.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}`}
      action={<Segmented label="Metric" value={metric} onChange={setMetric} options={[["views", "Profile views"], ["actions", "Customer actions"]] as const} />}>
      {error ? <Gate error={error} /> : loading && !data ? <Skeleton className="h-56" /> : (
        <>
          {change !== null && last && <p className="mb-3 text-sm"><b className="num text-lg font-semibold">{fmtNum(last.v)}</b> in {new Date(last.m + "-01").toLocaleDateString("en-IN", { month: "long" })}
            <span className={clsx("ml-2 rounded-full px-2 py-0.5 text-xs font-semibold", change >= 0 ? "bg-pos-tint text-pos" : "bg-neg-tint text-neg")}>{change >= 0 ? "↗" : "↘"} {Math.abs(change)}% vs the month before</span></p>}
          {months.every((x) => x.v === 0) && <p className="mb-3 rounded-tile bg-surface-2 p-4 text-sm text-muted">Google hasn&rsquo;t reported {metric === "views" ? "profile views" : "customer actions"} for these months yet. New or low-traffic profiles often have none.</p>}
          <div className="flex h-48 items-end gap-1.5 sm:gap-2" role="img" aria-label={`${metric === "views" ? "Profile views" : "Customer actions"} per month`}>
            {months.map((x, i) => (
              <div key={x.m} className="flex min-w-0 flex-1 flex-col items-center gap-1.5" title={`${x.m}: ${fmtNum(x.v)}`}>
                <div className={clsx("grow-y w-full rounded-t-[8px] rounded-b-[4px]", i === months.length - 1 ? "hatch bg-accent/30" : "bg-ink-solid")} style={{ height: `${Math.max(2, (x.v / max) * 100)}%`, ["--d" as string]: `${i * 30}ms` }} />
                <span className="text-[10px] text-muted sm:text-xs">{new Date(x.m + "-01").toLocaleDateString("en-IN", { month: "short" })}</span>
              </div>
            ))}
          </div>
          <table className="sr-only"><caption>Monthly totals</caption><tbody>{months.map((x) => <tr key={x.m}><td>{x.m}</td><td>{x.v}</td></tr>)}</tbody></table>
          <p className="mt-3 text-xs text-muted">The striped bar is the current month, still in progress. {metric === "views" ? "Views = Search + Maps impressions on desktop and mobile; Google counts one person once per day." : "Actions = calls, website clicks, direction requests, bookings and message clicks."}</p>
        </>
      )}
    </Panel>
  );
}

const DEFINITIONS: [string, string][] = [
  ["Profile views", "Times your profile was shown in Google Search or Maps, on mobile and desktop. One person counts once per day."],
  ["Calls", "Taps on the call button on your profile."],
  ["Website clicks", "Clicks on your website link."],
  ["Direction requests", "Requests for directions to your location."],
  ["Bookings", "Bookings made through Reserve with Google (only if you use it)."],
  ["Message clicks", "Taps on the messaging button (for example WhatsApp)."],
  ["Not shown", "Conversations and food orders: Google has deprecated these metrics. Menu clicks: only meaningful for food businesses."],
];

export function MetricGlossary() {
  return (
    <Panel title="What these numbers mean" meta="Google's definitions">
      <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">{DEFINITIONS.map(([k, v]) => <div key={k}><dt className="text-sm font-semibold">{k}</dt><dd className="text-[13px] text-muted">{v}</dd></div>)}</dl>
      <p className="mt-4 text-xs text-muted">Google reports with a delay of a few days, so the latest days are left out. These are Google&rsquo;s numbers, not FlowQR card scans.</p>
    </Panel>
  );
}
