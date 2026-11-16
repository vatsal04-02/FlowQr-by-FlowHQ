"use client";
import { ImagePlus, Lock, Megaphone, Pencil, Plus, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { LineChart } from "@/components/charts/LineChart";
import { DateRange, presetRange } from "@/components/DateRange";
import { Button, LinkButton } from "@/components/ui/Button";
import { Alert, Badge, Card, CardHeader, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { Panel } from "@/components/ui/kit";
import { ErrorSummary, Input, Select, Textarea } from "@/components/ui/Form";
import { useToast } from "@/components/ui/Toast";
import { api, ApiError, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useForm } from "@/lib/form";
import type { GoogleConnection, GoogleLocation } from "@/lib/types";
import { useFetch } from "@/lib/use-api";
import { Gallery } from "./Gallery";
import { ProfileEditor } from "./ProfileEditor";

const DAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"];

/** Why a profile tool isn't available: plan limit, server not configured for Google yet, or a real failure. */
export function Gate({ error }: { error: string }) {
  const upgrade = /plan|subscription/i.test(error);
  const pending = /awaiting configuration|not configured|configuration pending/i.test(error);
  if (/hasn.t approved FlowQR|awaiting .*approval/i.test(error)) return <Alert tone="warning" title="Awaiting Google approval">Google hasn&rsquo;t granted FlowQR Business Profile API access yet, so this tool is unavailable and nothing was changed. Your QR/NFC cards, review links and AI writing assistant keep working.</Alert>;
  if (/not enabled on FlowQR/i.test(error)) return <Alert tone="warning" title="A Google API is switched off for FlowQR">{error} Contact FlowQR support; this is fixed on FlowQR&rsquo;s side.</Alert>;
  if (/10 profile edits per minute/i.test(error)) return <Alert tone="warning" title="Slow down a little">{error}</Alert>;
  if (pending) return <Alert tone="warning" title="Configuration pending">Google Business Profile tools need Google API access, which isn&rsquo;t configured on this server yet. Your QR/NFC cards, review links and AI writing assistant work without it.</Alert>;
  return <Alert tone={upgrade ? "info" : "error"} title={upgrade ? "Not included in your plan" : "Couldn't load from Google"} action={upgrade ? <LinkButton href="/settings/billing" size="sm" variant="secondary">View plans</LinkButton> : undefined}>{error}</Alert>;
}


interface Info { title: string | null; description: string | null; phone: string | null; website: string | null; primary_category: { id: string; name: string } | null; additional_categories: { id: string; name: string }[]; hours: { day: string; open: string; close: string }[] }

export function InfoTab({ gid, part }: { gid: string; part?: "all" | "info" | "hours" }) { return <ProfileEditor gid={gid} part={part} />; }

interface Media { name: string; category: string | null; url: string | null; thumbnail: string | null }

export function MediaTab({ gid, canAdd = true }: { gid: string; canAdd?: boolean }) { return <Gallery gid={gid} canAdd={canAdd} />; }

const METRIC_LABELS: Record<string, string> = { CALL_CLICKS: "Calls", WEBSITE_CLICKS: "Website clicks", BUSINESS_DIRECTION_REQUESTS: "Direction requests", BUSINESS_CONVERSATIONS: "Messages", BUSINESS_BOOKINGS: "Bookings" };

export function PerfTab({ gid }: { gid: string }) {
  const [range, setRange] = useState(presetRange("30"));
  const { data, error, loading } = useFetch<{ totals: Record<string, number>; series: Record<string, { date: string; value: number }[]>; note: string }>(`/gbp/${gid}/performance`, { from: range.from, to: range.to });
  if (error) return <Gate error={error} />;
  const impressions = data ? Object.entries(data.totals).filter(([k]) => k.startsWith("BUSINESS_IMPRESSIONS")).reduce((a, [, v]) => a + v, 0) : 0;
  const days = data ? [...new Set(Object.values(data.series).flatMap((s) => s.map((p) => p.date)))].sort() : [];
  const chart = days.map((d) => ({ date: d, calls: data!.series.CALL_CLICKS?.find((p) => p.date === d)?.value ?? 0, website: data!.series.WEBSITE_CLICKS?.find((p) => p.date === d)?.value ?? 0, directions: data!.series.BUSINESS_DIRECTION_REQUESTS?.find((p) => p.date === d)?.value ?? 0 }));
  return (
    <>
      <div className="mb-4"><DateRange value={range} onChange={setRange} /></div>
      {loading && !data ? <Skeleton className="h-60" /> : data && (<>
        <dl className="panel grid grid-cols-2 divide-ink-100 overflow-hidden sm:grid-cols-4 sm:divide-x">
          {[["Profile views", impressions, "Search + Maps impressions"], ...Object.entries(METRIC_LABELS).filter(([k]) => k in data.totals).slice(0, 3).map(([k, l]) => [l, data.totals[k] ?? 0, ""] as [string, number, string])].map(([k, v, h]) => (
            <div key={k as string} className="border-b border-ink-100 px-4 py-3 sm:border-b-0"><dt className="text-xs font-medium text-ink-500">{k as string}</dt><dd className="num mt-1 text-2xl font-bold leading-none tracking-tight">{(v as number).toLocaleString("en-IN")}</dd>{h && <p className="mt-1.5 text-xs text-ink-500">{h as string}</p>}</div>))}
        </dl>
        <Panel className="mt-4" title="Actions on your Google profile">
          <LineChart ariaLabel="Calls, website clicks and direction requests per day" data={chart} series={[{ key: "calls", label: "Calls", color: "rgb(var(--c-pos))" }, { key: "website", label: "Website clicks", color: "rgb(var(--c-accent))", dash: "6 4" }, { key: "directions", label: "Directions", color: "rgb(var(--c-ink-solid))", dash: "2 4" }]} /></Panel>
        <p className="mt-3 text-xs text-ink-500">{data.note}</p></>)}
    </>
  );
}
