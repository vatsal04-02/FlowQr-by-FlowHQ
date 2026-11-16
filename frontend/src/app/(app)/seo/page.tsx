"use client";
import { ArrowRight, Search } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";
import { LineChart } from "@/components/charts/LineChart";
import { Move, Position, SourceTag, Unavailable, when } from "@/components/seo/parts";
import { Alert, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { Panel } from "@/components/ui/kit";
import { fmtNum } from "@/lib/format";
import { useLocationScope } from "@/lib/location-scope";
import type { SeoOverview } from "@/lib/seo";
import { useFetch } from "@/lib/use-api";

function Kpi({ label, value, sub, tone }: { label: string; value: string; sub: string; tone?: "pos" | "warn" }) {
  return (
    <div className="min-w-0 rounded-[14px] bg-surface-2 p-3.5">
      <p className="text-[13px] font-medium text-muted">{label}</p>
      <p className={`num mt-1 text-[28px] font-semibold leading-8 tracking-[-.02em] ${tone === "pos" ? "text-pos" : ""}`}>{value}</p>
      <p className="mt-0.5 text-xs text-muted">{sub}</p>
    </div>
  );
}

/** Local SEO › Overview: how visible the business is in Google local search. Positions are Places measurements, search terms are Google's, and the two are never mixed. */
export default function SeoOverviewPage() {
  const { locationId } = useLocationScope();
  const q = useFetch<SeoOverview>("/seo/overview", { location_id: locationId ?? "" });
  const d = q.data;
  const s = d?.summary;
  const trend = useMemo(() => (d?.trend ?? []).map((t) => ({ date: t.date, top10: Math.round((100 * t.top10) / Math.max(1, t.measured)), top3: Math.round((100 * t.top3) / Math.max(1, t.measured)) })), [d]);
  const moved = (d?.keywords ?? []).filter((k) => k.change !== null && k.change !== 0);
  const up = moved.filter((k) => (k.change ?? 0) > 0).length, down = moved.length - up;
  const best = [...(d?.keywords ?? [])].filter((k) => k.rank !== null).sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99)).slice(0, 5);
  const weak = (d?.keywords ?? []).filter((k) => k.status === "ok" && (k.rank === null || k.rank > 10)).slice(0, 5);

  return (
    <>
      <PageHeader title="SEO Overview" subtitle="How visible you are in Google local search. Every number says where it comes from: measured with Google Places, reported by Google, or calculated by FlowQR." />
      {q.error && <Alert tone="error" title="We couldn't load your local SEO numbers">{q.error}</Alert>}
      {q.loading && !d && <Skeleton className="h-64" />}
      {d && d.state === "no_location" && (
        <EmptyState icon={<Search className="h-5 w-5" />} title="Connect a Google location first" action={<Link href="/gbp/locations" className="font-semibold text-accent-ink hover:underline">Connect Google</Link>}>
          Local SEO follows a specific Google Business Profile. Once a location is connected you can track the searches your customers use.
        </EmptyState>
      )}
      {d && d.state !== "no_location" && (
        <div className="space-y-4">
          {!d.tracking_allowed && <Alert tone="info" title="Keyword tracking isn't part of your plan">Your plan doesn&rsquo;t include local ranking. Google&rsquo;s own search terms below are still shown when Google shares them.</Alert>}
          {d.tracking_allowed && !d.provider_configured && <Alert tone="info" title="Local ranking isn't set up on this server yet">Positions are measured with Google&rsquo;s Places API, which needs a key configured by FlowHQ. Nothing is estimated in the meantime.</Alert>}

          {d.state === "no_keywords" ? (
            d.tracking_allowed && (
              <EmptyState icon={<Search className="h-5 w-5" />} title="No search terms tracked yet" action={<Link href="/seo/rank" className="font-semibold text-accent-ink hover:underline">Add your first search term</Link>}>
                Track what customers type, for example &ldquo;dentist near me&rdquo;. FlowQR then measures where you appear and keeps the history.
              </EmptyState>
            )
          ) : s && (
            <>
              <section aria-label="Local visibility summary" className="panel !rounded-[16px] p-4">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2"><h2 className="text-[15px] font-semibold">Local visibility</h2><span className="flex items-center gap-2 text-[13px] text-muted"><SourceTag source="places" />last checked {when(s.last_checked_at)}</span></div>
                <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                  <Kpi label="In the top 3" value={s.measured ? `${s.top3} of ${s.measured}` : "–"} sub="tracked search terms" tone={s.top3 ? "pos" : undefined} />
                  <Kpi label="In the top 10" value={s.measured ? `${s.top10} of ${s.measured}` : "–"} sub="tracked search terms" />
                  <Kpi label="Not in the first 20" value={s.measured ? String(s.not_found) : "–"} sub={s.failed ? `${s.failed} could not be measured` : "a real result, not an error"} />
                  <Kpi label="Moved since last check" value={moved.length ? `${up} up · ${down} down` : "–"} sub={moved.length ? "search terms that changed place" : "needs two checks to compare"} />
                </div>
                <p className="mt-3 text-xs text-muted">{s.note}</p>
              </section>

              <div className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
                <Panel dense title="Visibility trend" meta="share of tracked terms where you show" action={<SourceTag source="places" />}>
                  {trend.length >= 2
                    ? <LineChart ariaLabel="Share of tracked search terms where you appear in the top 3 and top 10, by day measured" data={trend} yMax={100} height={210}
                        series={[{ key: "top10", label: "In top 10 (%)", color: "rgb(var(--c-accent))" }, { key: "top3", label: "In top 3 (%)", color: "rgb(var(--c-ink-solid))", dash: "5 4" }]} />
                    : <Unavailable title="The trend needs checks on at least two different days">Each point is a day FlowQR measured your positions. {trend.length === 1 ? "There is one so far." : "There are none yet."} Nothing is drawn in between.</Unavailable>}
                </Panel>
                <Panel dense title="Needs attention" meta="from your own measurements">
                  {d.attention.length === 0 ? <p className="text-sm text-muted">Nothing to flag right now.</p> : (
                    <ul className="divide-y divide-ink-100">
                      {d.attention.map((a, i) => (
                        <li key={i} className="py-2 first:pt-0 last:pb-0"><p className="flex items-center gap-2 text-sm font-medium">{a.keyword}<SourceTag source={a.source} /></p><p className="text-[13px] text-muted">{a.detail}</p></li>
                      ))}
                    </ul>
                  )}
                </Panel>
              </div>

              <Panel dense title="Tracked search terms" meta={`${s.tracked} tracked`} action={<Link href="/seo/rank" className="inline-flex items-center gap-1 text-[13px] font-semibold text-accent-ink hover:underline">Manage and check<ArrowRight className="h-3.5 w-3.5" aria-hidden /></Link>} flush>
                <div className="overflow-x-auto">
                  <table className="dt min-w-[560px]">
                    <thead><tr><th>Search term</th><th>Location</th><th>Position</th><th>Change</th><th className="!text-right">Last checked</th></tr></thead>
                    <tbody>{d.keywords.map((k) => (
                      <tr key={k.id}><td className="font-medium">{k.keyword}</td><td className="text-muted">{k.location ?? "–"}</td><td><Position rank={k.rank} status={k.status} /></td><td><Move change={k.change} /></td><td className="!text-right text-muted">{when(k.checked_at)}</td></tr>
                    ))}</tbody>
                  </table>
                </div>
              </Panel>

              <div className="grid gap-4 md:grid-cols-2">
                <Panel dense title="Top-performing terms" meta="best positions" action={<SourceTag source="places" />}>
                  {best.length === 0 ? <p className="text-sm text-muted">No term has a measured position yet.</p> : <ul className="space-y-2">{best.map((k) => <li key={k.id} className="flex items-center justify-between gap-3 text-sm"><span className="truncate font-medium">{k.keyword}</span><Position rank={k.rank} status={k.status} /></li>)}</ul>}
                </Panel>
                <Panel dense title="Terms to work on" meta="outside the top 10" action={<SourceTag source="places" />}>
                  {weak.length === 0 ? <p className="text-sm text-muted">Every measured term shows you in the top 10.</p> : <ul className="space-y-2">{weak.map((k) => <li key={k.id} className="flex items-center justify-between gap-3 text-sm"><span className="truncate font-medium">{k.keyword}</span><Position rank={k.rank} status={k.status} /></li>)}</ul>}
                </Panel>
              </div>
            </>
          )}

          <Panel dense title="What people searched before finding your profile" meta="monthly, from Google" action={<SourceTag source="google" />}>
            {d.google_terms ? (
              <>
                <ul className="divide-y divide-ink-100">
                  {d.google_terms.terms.map((t) => (
                    <li key={t.keyword} className="flex items-center justify-between gap-3 py-2 text-sm first:pt-0">
                      <span className="min-w-0 truncate font-medium">{t.keyword}{t.tracked && <span className="ml-2 text-xs font-normal text-muted">tracked</span>}</span>
                      <span className="num shrink-0 font-semibold">{t.value === null ? "Too few to report" : fmtNum(t.value)}</span>
                    </li>
                  ))}
                </ul>
                <p className="mt-3 text-xs text-muted">{d.google_terms.note} Months covered: {d.google_terms.months.join(", ") || "–"}. Updated {when(d.google_terms.fetched_at)}.</p>
              </>
            ) : <Unavailable title="Google hasn't shared search terms yet">When Google Business Profile access is live for your account, the terms people used before seeing your profile appear here. They are impressions, not rankings, and nothing is shown until Google provides them.</Unavailable>}
          </Panel>
        </div>
      )}
    </>
  );
}
