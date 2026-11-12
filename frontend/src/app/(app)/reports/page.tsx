"use client";
import { Download, FileText } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { DateRange, presetRange } from "@/components/DateRange";
import { Button } from "@/components/ui/Button";
import { Alert, PageHeader, Skeleton } from "@/components/ui/Card";
import { Panel } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import type { ReportSummary } from "@/lib/agent";
import { apiFile, errorMessage, saveBlob } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtHours, fmtNum, fmtPct, fmtRating, timeAgo } from "@/lib/format";
import { useLocationScope } from "@/lib/location-scope";
import { useFetch } from "@/lib/use-api";

export default function ReportsPage() {
  const { role } = useAuth();
  const toast = useToast();
  const { locationId } = useLocationScope();
  const [range, setRange] = useState(presetRange("30"));
  const q = { from: range.from, to: range.to, location_id: locationId };
  const { data: r, error, loading } = useFetch<ReportSummary>("/reports/summary", q);
  const [busy, setBusy] = useState<string | null>(null);
  async function download(path: string, name: string) {
    setBusy(name);
    try { const { blob } = await apiFile(`${path}?from=${range.from}&to=${range.to}`); saveBlob(blob, name); } catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(null); }
  }
  const staff = role === "staff";
  return (
    <>
      <PageHeader eyebrow="Reports" title="Reports" subtitle="Real numbers only. Anything Google or a setup has not provided is marked as missing, never estimated." actions={<DateRange value={range} onChange={setRange} />} />
      {error && <Alert tone="error">{error}</Alert>}
      {loading && !r ? <Skeleton className="h-72" /> : r && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2" aria-label="Downloads">
            <Button size="sm" icon={<FileText className="h-4 w-4" />} loading={busy === "flowqr-report.pdf"} onClick={() => void download("/reports/summary.pdf", "flowqr-report.pdf")}>PDF report</Button>
            {[["reviews", "Reviews"], ["posts", "Posts"], ...(staff ? [] : [["tasks", "Agent tasks"], ["ai", "AI activity"]])].map(([k, l]) => <Button key={k} size="sm" variant="secondary" icon={<Download className="h-4 w-4" />} loading={busy === `flowqr-${k}.csv`} onClick={() => void download(`/reports/export/${k}.csv`, `flowqr-${k}.csv`)}>{l} (CSV)</Button>)}
          </div>
          <Panel title="Reputation" meta={`${r.range.from} to ${r.range.to}`}>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-5">
              {([["New reviews", fmtNum(r.reputation.reviews)], ["Average rating", fmtRating(r.reputation.average_rating)], ["Replied", `${r.reputation.replied}${r.reputation.reply_rate !== null ? ` (${fmtPct(r.reputation.reply_rate)})` : ""}`], ["Avg time to reply", fmtHours(r.reputation.avg_response_hours)], ["Unanswered now", fmtNum(r.reputation.unanswered_now)]] as const).map(([k, v]) => <div key={k}><dt className="text-[13px] text-ink-500">{k}</dt><dd className="num mt-1 text-2xl font-bold leading-none">{v}</dd></div>)}
            </dl>
            <p className="mt-3 text-xs text-ink-500">Ratings 1–5: {Object.entries(r.reputation.distribution).map(([k, v]) => `${k}★ ${v}`).join(" · ")}</p>
          </Panel>
          <Panel title="Google performance">
            {r.google_performance.available ? (
              <div className="overflow-x-auto"><table className="dt min-w-[480px]"><thead><tr><th>Location</th><th className="!text-right">Last 28 days</th><th className="!text-right">Previous 28</th><th>Fetched</th></tr></thead><tbody>{r.google_performance.locations.map((l) => <tr key={l.location}><td>{l.location}</td><td className="n">{fmtNum(l.last_28_days)}</td><td className="n">{fmtNum(l.previous_28_days)}</td><td className="text-ink-500">{timeAgo(l.fetched_at)}</td></tr>)}</tbody></table></div>
            ) : <p className="text-sm text-ink-700">{r.google_performance.note}</p>}
            {r.google_performance.available && <p className="mt-2 text-xs text-ink-500">{r.google_performance.note} More detail: <Link className="text-brand-700 underline" href="/performance">Performance</Link>.</p>}
            {r.google_performance.errors.map((e) => <p key={e.location} className="mt-2 text-[13px] text-amber-800">{e.location}: {e.error}</p>)}
          </Panel>
          <Panel title="QR review campaigns" action={<Link className="text-[13px] font-medium text-brand-700 hover:underline" href="/review-growth/analytics">Funnel analytics</Link>}>
            {r.campaigns ? <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">{([["QR scans", r.campaigns.scans], ["Unique devices", r.campaigns.unique_visitors], ["Started a review", r.campaigns.feedback_submitted], ["Confirmed a review", r.campaigns.drafts_approved], ["Continued to Google", r.campaigns.google_redirects]] as const).map(([k, v]) => <div key={k}><dt className="text-[13px] text-ink-500">{k}</dt><dd className="num mt-1 text-2xl font-bold leading-none">{fmtNum(v)}</dd></div>)}</dl>
              : <p className="text-sm text-ink-500">Campaign totals are not shown to location-restricted accounts.</p>}
            <p className="mt-3 text-xs text-ink-500">A tap on &ldquo;Continue to Google&rdquo; is not proof that a review was posted. More: <Link className="text-brand-700 underline" href="/analytics">review analytics</Link> · <Link className="text-brand-700 underline" href="/cards/analytics">card scans</Link>.</p>
          </Panel>
          {r.ai_activity && <Panel title="AI activity"><dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
            <div><dt className="text-[13px] text-ink-500">Replies published</dt><dd className="num mt-1 text-2xl font-bold">{r.ai_activity.replies_published}</dd></div>
            <div><dt className="text-[13px] text-ink-500">AI uses</dt><dd className="num mt-1 text-2xl font-bold">{r.ai_activity.ai_uses.reduce((a, x) => a + x.count, 0)}</dd></div>
            <div><dt className="text-[13px] text-ink-500">Agent tasks</dt><dd className="mt-1 text-sm">{Object.entries(r.ai_activity.tasks_by_status).map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`).join(" · ") || "none"}</dd></div>
            <div><dt className="text-[13px] text-ink-500">Posts</dt><dd className="mt-1 text-sm">{Object.entries(r.ai_activity.posts_by_status).map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`).join(" · ") || "none"}</dd></div></dl></Panel>}
        </div>)}
    </>
  );
}
