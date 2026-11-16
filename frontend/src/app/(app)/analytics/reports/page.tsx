"use client";
import { Download, FileText } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";
import { DateRange, presetRange } from "@/components/DateRange";
import { Button } from "@/components/ui/Button";
import { Alert, PageHeader, Skeleton, Stars } from "@/components/ui/Card";
import { Panel } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import type { ReportSummary } from "@/lib/agent";
import { apiFile, errorMessage, saveBlob } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtHours, fmtNum, fmtPct, fmtRating, timeAgo } from "@/lib/format";
import { useLocationScope } from "@/lib/location-scope";
import { useFetch } from "@/lib/use-api";

/** One number in a grey well: label, value, optional note. */
function Metric({ label, value, note }: { label: string; value: ReactNode; note?: ReactNode }) {
  return (
    <div className="min-w-0 rounded-tile bg-surface-2 p-4">
      <dt className="text-sm font-medium text-muted">{label}</dt>
      <dd className="num mt-2 text-[28px] font-semibold leading-none tracking-[-.02em]">{value}</dd>
      {note && <p className="mt-2 text-xs text-muted">{note}</p>}
    </div>
  );
}

const TASK_LABEL: Record<string, string> = { suggested: "Suggested", drafted: "Drafted", awaiting_approval: "Waiting for approval", approved: "Approved", scheduled: "Scheduled", published: "Published", failed: "Failed", snoozed: "Snoozed", dismissed: "Dismissed", done: "Done", draft: "Draft", publishing: "Publishing", canceled: "Cancelled" };
const statusLine = (m: Record<string, number>) => Object.entries(m).map(([k, v]) => `${TASK_LABEL[k] ?? k.replace(/_/g, " ")} ${v}`).join(" · ");

/**
 * Overview › Reports: one summary for the chosen dates and location, with the same filters applied to the PDF and every CSV.
 * Real numbers only. Google's own numbers come in Google's fixed 28-day window and are labelled as such.
 */
export default function ReportsPage() {
  const { role } = useAuth();
  const toast = useToast();
  const { locationId } = useLocationScope();
  const [range, setRange] = useState(presetRange("30"));
  const q = { from: range.from, to: range.to, location_id: locationId };
  const { data: r, error, loading, reload } = useFetch<ReportSummary>("/reports/summary", q);
  const [busy, setBusy] = useState<string | null>(null);
  const staff = role === "staff";
  const suffix = `${range.from}_${range.to}`;

  async function download(path: string, name: string) {
    setBusy(name);
    const params = new URLSearchParams({ from: range.from, to: range.to, ...(locationId ? { location_id: locationId } : {}) });
    try { const { blob } = await apiFile(`${path}?${params}`); saveBlob(blob, name); toast("Downloaded."); }
    catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(null); }
  }

  const dist = r?.reputation.distribution ?? {};
  const maxDist = Math.max(1, ...Object.values(dist));
  const exports: [string, string][] = [["reviews", "Reviews"], ["posts", "Posts"], ...(staff ? [] : [["tasks", "Agent tasks"], ["ai", "AI activity"]] as [string, string][])];

  return (
    <>
      <PageHeader title="Reports" subtitle="Real numbers only. Anything Google or a setup hasn't provided is marked as missing, never estimated." actions={<DateRange value={range} onChange={setRange} />} />
      {error && <Alert tone="error" title="We couldn't build the report" action={<Button size="sm" variant="inverse" onClick={() => void reload()}>Try again</Button>}>{error}</Alert>}
      {loading && !r ? <Skeleton className="h-72" /> : r && (
        <div className="space-y-6">
          <section className="panel flex flex-wrap items-center justify-between gap-4 p-5 sm:p-6" aria-label="Downloads">
            <div className="min-w-0">
              <h2 className="text-lg font-semibold">Download</h2>
              <p className="mt-0.5 text-sm text-muted">{r.range.from} to {r.range.to} · {r.location ?? "All locations"}. Downloads use exactly these filters.</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" icon={<FileText className="h-4 w-4" />} loading={busy === `flowqr-report-${suffix}.pdf`} disabled={busy !== null}
                onClick={() => void download("/reports/summary.pdf", `flowqr-report-${suffix}.pdf`)}>PDF report</Button>
              {exports.map(([k, l]) => (
                <Button key={k} size="sm" variant="secondary" icon={<Download className="h-4 w-4" />} loading={busy === `flowqr-${k}-${suffix}.csv`} disabled={busy !== null}
                  onClick={() => void download(`/reports/export/${k}.csv`, `flowqr-${k}-${suffix}.csv`)}>{l} (CSV)</Button>
              ))}
            </div>
          </section>

          <Panel title="Reputation" meta={`${r.range.from} to ${r.range.to}`}>
            <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
              <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <Metric label="New reviews" value={fmtNum(r.reputation.reviews)} />
                <Metric label="Average rating" value={r.reputation.average_rating === null ? "–" : <>{fmtRating(r.reputation.average_rating)}<span className="ml-1 text-base text-accent">★</span></>} note={r.reputation.average_rating === null ? "No reviews in these dates" : undefined} />
                <Metric label="Replied" value={fmtNum(r.reputation.replied)} note={r.reputation.reply_rate !== null ? `${fmtPct(r.reputation.reply_rate)} of new reviews` : undefined} />
                <Metric label="Avg time to reply" value={fmtHours(r.reputation.avg_response_hours)} note={r.reputation.avg_response_hours === null ? "Nothing to measure yet" : undefined} />
                <Metric label="Unanswered now" value={fmtNum(r.reputation.unanswered_now)} note={r.reputation.unanswered_now > 0 ? <Link className="font-semibold text-accent-ink hover:underline" href="/gbp/reviews?state=none">Reply now</Link> : "All time, not just these dates"} />
              </dl>
              <div className="rounded-tile bg-surface-2 p-4">
                <p className="text-sm font-medium text-muted">Rating mix</p>
                <ul className="mt-3 space-y-2.5">{[5, 4, 3, 2, 1].map((n) => { const v = dist[String(n)] ?? 0; return (
                  <li key={n} className="grid grid-cols-[76px_1fr_32px] items-center gap-3 text-sm">
                    <Stars rating={n} size={11} />
                    <span className="block h-2 overflow-hidden rounded-full bg-surface"><span className={`grow-x block h-full rounded-full ${n >= 4 ? "bg-ink-solid" : "bg-accent"}`} style={{ width: `${(v / maxDist) * 100}%` }} /></span>
                    <span className="num text-right font-semibold">{v}</span>
                  </li>); })}</ul>
              </div>
            </div>
          </Panel>

          <Panel title="Google performance" meta="Google's last 28 days, not the dates above">
            {r.google_performance.available ? (
              <div className="overflow-x-auto"><table className="dt min-w-[520px]">
                <thead><tr><th>Location</th><th className="!text-right">Last 28 days</th><th className="!text-right">Previous 28</th><th className="!text-right">Change</th><th>Fetched</th></tr></thead>
                <tbody>{r.google_performance.locations.map((l) => { const d = l.last_28_days - l.previous_28_days; return (
                  <tr key={l.location}><td className="max-w-[420px] truncate" title={l.location}>{l.location}</td><td className="n">{fmtNum(l.last_28_days)}</td><td className="n">{fmtNum(l.previous_28_days)}</td>
                    <td className="n"><span className={d > 0 ? "text-pos" : d < 0 ? "text-neg" : "text-muted"}>{d > 0 ? "↗ " : d < 0 ? "↘ " : ""}{d === 0 ? "No change" : fmtNum(Math.abs(d))}</span></td>
                    <td className="whitespace-nowrap text-muted">{timeAgo(l.fetched_at)}</td></tr>); })}</tbody>
              </table></div>
            ) : <p className="rounded-tile bg-surface-2 p-4 text-sm text-muted">{r.google_performance.note}</p>}
            {r.google_performance.available && <p className="mt-3 text-[13px] text-muted">{r.google_performance.note} Day-by-day detail: <Link className="font-semibold text-accent-ink hover:underline" href="/analytics/performance">Search &amp; Maps</Link>.</p>}
            {r.google_performance.errors.map((e) => <p key={e.location} className="mt-2 text-[13px] text-warn">{e.location}: {e.error}</p>)}
          </Panel>

          <Panel title="QR review campaigns" action={<Link className="text-sm font-semibold text-accent-ink hover:underline" href="/analytics/campaigns">Funnel detail</Link>}>
            {r.campaigns ? (
              <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
                <Metric label="QR scans" value={fmtNum(r.campaigns.scans)} />
                <Metric label="Unique devices" value={fmtNum(r.campaigns.unique_visitors)} />
                <Metric label="Started a review" value={fmtNum(r.campaigns.feedback_submitted)} />
                <Metric label="Confirmed a review" value={fmtNum(r.campaigns.drafts_approved)} />
                <Metric label="Continued to Google" value={fmtNum(r.campaigns.google_redirects)} />
              </dl>
            ) : <p className="text-sm text-muted">Campaign totals are not shown to location-restricted accounts.</p>}
            <p className="mt-3 text-[13px] text-muted">A tap on &ldquo;Continue to Google&rdquo; is not proof that a review was posted. More: <Link className="font-semibold text-accent-ink hover:underline" href="/analytics/reviews">reviews</Link> · <Link className="font-semibold text-accent-ink hover:underline" href="/analytics/funnel">card scans</Link>.</p>
          </Panel>

          {r.ai_activity && (
            <Panel title="AI activity" meta="whole business, these dates">
              <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <Metric label="Replies published" value={fmtNum(r.ai_activity.replies_published)} />
                <Metric label="AI uses" value={fmtNum(r.ai_activity.ai_uses.reduce((a, x) => a + x.count, 0))} />
                <Metric label="Agent tasks" value={fmtNum(Object.values(r.ai_activity.tasks_by_status).reduce((a, x) => a + x, 0))} note={statusLine(r.ai_activity.tasks_by_status) || "None"} />
                <Metric label="Google posts" value={fmtNum(Object.values(r.ai_activity.posts_by_status).reduce((a, x) => a + x, 0))} note={statusLine(r.ai_activity.posts_by_status) || "None"} />
              </dl>
            </Panel>
          )}
        </div>
      )}
    </>
  );
}
