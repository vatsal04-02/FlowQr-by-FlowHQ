"use client";
import Link from "next/link";
import { useState } from "react";
import { BarList } from "@/components/charts/BarList";
import { LineChart } from "@/components/charts/LineChart";
import { DateRange, presetRange } from "@/components/DateRange";
import { Funnel, StatusBadge, useCampaignParam, useCampaigns } from "@/components/review-growth/shared";
import { Alert, PageHeader, Skeleton, Stat } from "@/components/ui/Card";
import { FilterSelect } from "@/components/ui/Form";
import { CellBar, Panel } from "@/components/ui/kit";
import { fmtNum, fmtPct } from "@/lib/format";
import type { RGAnalytics } from "@/lib/review-growth";
import type { Overview } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

export default function ReviewGrowthAnalytics() {
  const preset = useCampaignParam();
  const [range, setRange] = useState(presetRange("30"));
  const [picked, setPicked] = useState<string | null>(null);
  const campaign = picked ?? preset;
  const list = useCampaigns(true);
  const { data: a, error } = useFetch<RGAnalytics>("/review-growth/analytics", { from: range.from, to: range.to, campaign_id: campaign });
  const ov = useFetch<Overview>("/analytics/overview", { from: range.from, to: range.to });
  const t = a?.totals;
  const maxScans = Math.max(1, ...(a?.campaigns ?? []).map((c) => c.scans));

  return (
    <>
      <PageHeader title="Review campaign results" subtitle="How many people scanned, opened the page and tapped to Google, for each campaign."
        actions={<>
          <FilterSelect label="Campaign" value={campaign} onChange={(e) => setPicked(e.target.value)}><option value="">All campaigns</option>{list.data?.map((c) => <option key={c.id} value={c.id}>{c.name}{c.status === "archived" ? " (archived)" : ""}</option>)}</FilterSelect>
          <DateRange value={range} onChange={setRange} />
        </>} />
      {error && <Alert tone="error">{error}</Alert>}
      {!a && !error && <Skeleton className="h-80" />}
      {a && t && (
        <div className="space-y-4">
          <section aria-labelledby="journey-h" className="rounded-2xl bg-brand-50 p-4 sm:p-6">
            <h2 id="journey-h" className="text-lg font-bold text-navy">What customers do after they scan</h2>
            <p className="mt-0.5 text-sm text-ink-700">Each step, and how many of those who opened your page reached it.</p>
            <ol className="mt-4 space-y-2.5">
              {([["Opened your review page", t.scans, `${fmtNum(t.unique_visitors)} different visitors`], ["Started a review", t.feedback_submitted, "Picked stars or topics"], ["Confirmed their review", t.drafts_approved, "Read it and chose to continue"], ["Continued to Google", t.google_redirects, "A tap, not a posted review"]] as const).map(([label, n, note], i) => {
                const share = t.scans ? Math.min(1, n / t.scans) : 0;
                return (
                  <li key={label} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1 sm:grid-cols-[13rem_minmax(0,1fr)_auto]">
                    <div className="min-w-0"><p className="text-sm font-semibold text-navy">{label}</p><p className="text-[13px] text-ink-500">{note}</p></div>
                    <p className="num text-right text-xl font-bold text-navy sm:order-3">{fmtNum(n)}<span className="ml-2 text-sm font-medium text-ink-500">{i === 0 ? "" : t.scans ? fmtPct(n / t.scans) : "–"}</span></p>
                    <div aria-hidden className="col-span-2 h-4 overflow-hidden rounded-full bg-white sm:col-span-1"><div className="h-full rounded-full bg-fq transition-[width] duration-700" style={{ width: `${Math.max(share * 100, n ? 2 : 0)}%`, opacity: 1 - i * 0.12 }} /></div>
                  </li>);
              })}
            </ol>
            <p className="mt-3 text-[13px] text-ink-700">Continuing to Google doesn&rsquo;t mean a review was posted. Customers post on Google themselves, and real new reviews are counted under Google Business → Reviews.</p>
          </section>

          {!campaign && ov.data?.engagement.by_channel && (() => {
            const ch = ov.data!.engagement.by_channel!;
            const rows: [string, typeof ch.qr][] = [["QR code scans", ch.qr], ["NFC card taps", ch.nfc]];
            const max = Math.max(1, ...rows.map(([, r]) => r.scans));
            return (
              <section aria-labelledby="chan-h" className="rounded-2xl border border-ink-100 bg-white p-4 sm:p-6">
                <h2 id="chan-h" className="text-lg font-bold text-navy">QR scans vs NFC taps</h2>
                <div className="mt-3 grid gap-4 sm:grid-cols-2">
                  {rows.map(([label, r]) => (
                    <div key={label} className="rounded-xl bg-ink-50 p-4">
                      <p className="text-sm font-semibold text-navy">{label}</p><p className="num mt-1 text-3xl font-bold text-navy">{fmtNum(r.scans)}</p>
                      <div aria-hidden className="mt-2 h-2.5 overflow-hidden rounded-full bg-white"><div className="h-full rounded-full bg-fq" style={{ width: `${(r.scans / max) * 100}%` }} /></div>
                      <p className="mt-2 text-[13px] text-ink-700">{fmtNum(r.landing_views)} opened the page · {fmtNum(r.google_clicks)} continued to Google</p>
                    </div>))}
                </div>
                {ch.untracked.scans > 0 && <p className="mt-3 text-[13px] text-ink-500">{fmtNum(ch.untracked.scans)} more came from before FlowQR recorded which one they used.</p>}
              </section>);
          })()}

          <div className="grid gap-4 lg:grid-cols-[1fr_1.35fr]">
            <div className="space-y-4">
              <Panel title="How customers write" meta="two paths, one funnel">
                <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
                  {([["Asked for AI help", t.ai_requested], ["AI drafts generated", t.drafts_generated], ["Rewrites (Regenerate)", t.regenerations], ["Asked for more detail", t.needs_more],
                    ["Drafts that failed checks", t.generation_failures], ["Chose to write it themselves", t.manual_selected]] as const).map(([k, v]) => (
                    <div key={k}><dt className="text-[13px] text-ink-500">{k}</dt><dd className="num mt-0.5 text-xl font-bold leading-none">{fmtNum(v)}</dd></div>))}
                </dl>
              </Panel>
            </div>
            <div className="space-y-4">
            <Panel title="Activity over time">
              <LineChart ariaLabel="Page opens, reviews started, confirmed and Google clicks per day" data={a.series} height={250}
                series={[{ key: "scans", label: "Opened", color: "rgb(var(--c-accent))" }, { key: "feedback_submitted", label: "Started", color: "rgb(var(--c-ink-solid))", dash: "6 4" }, { key: "drafts_approved", label: "Confirmed", color: "rgb(var(--c-accent))", dash: "3 3" }, { key: "google_redirects", label: "To Google", color: "rgb(var(--c-pos))", dash: "2 4" }]} />
            </Panel>
            <Panel title="Topics customers choose" meta={`${fmtNum(t.suggestion_sessions)} sessions picked at least one`}>
              {a.suggestions.length === 0 ? <p className="text-sm text-ink-500">No topic has been picked yet. Counts appear once customers use the suggestions on your review page.</p>
                : <BarList rows={a.suggestions.slice(0, 8).map((s) => ({ label: s.label, value: s.count }))} />}
              <p className="mt-3 text-xs text-ink-500">Topics are what customers chose to comment on, not what they said about them.</p>
            </Panel>
            </div>
          </div>

          <Panel title="Ratings given on your review page" meta="chosen by customers here, not on Google">
            {a.ratings.rated === 0 ? <p className="text-sm text-ink-500">No star ratings yet in this period.</p> : (
              <div className="grid gap-5 md:grid-cols-[1fr_auto] md:items-center">
                <BarList color="bg-brand-600" rows={([5, 4, 3, 2, 1] as const).map((n) => ({ label: `${n} ${n === 1 ? "star" : "stars"}`, value: a.ratings.distribution[String(n) as "1"], sub: a.ratings.rated ? fmtPct(a.ratings.distribution[String(n) as "1"] / a.ratings.rated) : "" }))} />
                <dl className="grid grid-cols-3 gap-x-6 text-sm md:grid-cols-1 md:gap-y-3">
                  <div><dt className="text-[13px] text-ink-500">Average</dt><dd className="num text-xl font-bold leading-tight">{a.ratings.average?.toFixed(1) ?? "–"} <span className="text-sm font-normal text-ink-500">/ 5</span></dd></div>
                  <div><dt className="text-[13px] text-ink-500">Rated</dt><dd className="num text-xl font-bold leading-tight">{fmtNum(a.ratings.rated)}</dd></div>
                  <div><dt className="text-[13px] text-ink-500">Wrote without stars</dt><dd className="num text-xl font-bold leading-tight">{fmtNum(a.ratings.unrated)}</dd></div>
                </dl>
              </div>)}
            <p className="mt-3 text-xs text-ink-500">{a.ratings.source} Your Google rating is set by customers on Google and appears under Reviews. Stars here never hide, change or route anyone&rsquo;s path to Google.</p>
          </Panel>

          <details className="rounded-2xl border border-ink-100 bg-white"><summary className="flex min-h-11 cursor-pointer items-center px-4 text-sm font-semibold text-navy">More detail: AI drafts, cost and quality</summary><div className="border-t border-ink-100">
          <Panel title="AI cost and quality" meta="drafts in this period">
            {a.ai.requests === 0 ? <p className="text-sm text-ink-500">No AI drafts were requested in this period.</p> : (
              <dl className="grid grid-cols-2 gap-x-6 gap-y-4 text-sm md:grid-cols-4">
                {([
                  ["Drafts accepted", `${fmtNum(a.ai.accepted)} of ${fmtNum(a.ai.requests)}`],
                  ["Cost per accepted draft", a.ai.cost_per_accepted_draft_usd === null ? "–" : `$${a.ai.cost_per_accepted_draft_usd.toFixed(5)}`],
                  ["Model calls per request", a.ai.avg_calls_per_request === null ? "–" : a.ai.avg_calls_per_request.toFixed(2)],
                  ["Retries", fmtNum(a.ai.retries)],
                  ["Rule-check rejections", a.ai.rules_rejection_rate === null ? "–" : fmtPct(a.ai.rules_rejection_rate)],
                  ["Fact-check rejections", a.ai.factcheck_rejection_rate === null ? "–" : fmtPct(a.ai.factcheck_rejection_rate)],
                  ["Tokens in / out", `${fmtNum(a.ai.tokens_in)} / ${fmtNum(a.ai.tokens_out)}`],
                  ["Median latency", a.ai.latency_ms_median === null ? "–" : `${(a.ai.latency_ms_median / 1000).toFixed(1)}s`],
                ] as const).map(([k, v]) => <div key={k}><dt className="text-[13px] text-ink-500">{k}</dt><dd className="num mt-0.5 text-lg font-bold leading-tight">{v}</dd></div>)}
              </dl>)}
            <p className="mt-3 text-xs text-ink-500">Cost is the provider-reported charge. Rejected drafts are never shown to customers.</p>
          </Panel></div></details>

          <Panel title="Campaigns compared" meta="ranked by scans" flush>
            {a.campaigns.length === 0 ? <p className="p-4 text-sm text-ink-500">No campaigns yet. <Link href="/gbp/campaigns?new=1" className="font-medium text-brand-700 hover:underline">Create one</Link></p> : (
              <div className="overflow-x-auto"><table className="dt min-w-[820px]">
                <thead><tr><th>Campaign</th><th>Status</th><th className="w-[20%]">Scans</th><th className="!text-right">Started</th><th className="!text-right">AI drafts</th><th className="!text-right">Manual</th><th className="!text-right">Rewrites</th><th className="!text-right">Approved</th><th className="!text-right">To Google</th><th className="!text-right">Scan → Google</th></tr></thead>
                <tbody>{a.campaigns.map((c) => (
                  <tr key={c.id}>
                    <td><Link href={`/gbp/campaigns/${c.id}`} className="font-medium text-brand-700 hover:underline">{c.name}</Link></td>
                    <td><StatusBadge status={c.status as "active" | "paused" | "archived"} /></td>
                    <td><div className="flex items-center gap-2"><span className="num w-9 text-right font-semibold">{fmtNum(c.scans)}</span><CellBar value={c.scans} max={maxScans} /></div></td>
                    <td className="n">{fmtNum(c.feedback_submitted)}</td><td className="n">{fmtNum(c.drafts_generated)}</td><td className="n">{fmtNum(c.manual_selected)}</td><td className="n">{fmtNum(c.regenerations)}</td>
                    <td className="n">{fmtNum(c.drafts_approved)}</td><td className="n">{fmtNum(c.google_redirects)}</td><td className="n text-ink-500">{fmtPct(c.conversion)}</td>
                  </tr>))}</tbody>
              </table></div>)}
          </Panel>

          <details className="panel p-4 text-sm">
            <summary className="cursor-pointer text-[13px] font-semibold">How we count</summary>
            <dl className="mt-3 grid gap-3 sm:grid-cols-2">
              {Object.entries(a.definitions).map(([k, v]) => <div key={k}><dt className="font-medium">{k.replace(/_/g, " ")}</dt><dd className="mt-0.5 text-[13px] text-ink-500">{v}</dd></div>)}
              <div><dt className="font-medium">Published reviews</dt><dd className="mt-0.5 text-[13px] text-ink-500">Not measured here. Customers post on Google themselves, and a tap on Continue to Google isn&rsquo;t proof. Connected locations show real new reviews under Reviews.</dd></div>
            </dl>
          </details>
        </div>
      )}
    </>
  );
}
