"use client";
import { ConnectGoogleEmptyState } from "@/components/settings/parts";
import { Card, Dashes, RankLadder, SeeAll, Title } from "@/components/seo/visuals";
import { SourceTag } from "@/components/seo/parts";
import { GoogleProfileCard } from "@/components/gbp/GoogleProfileCard";
import { OptimizationCenter } from "@/components/seo/OptimizationCenter";
import { Alert, Skeleton } from "@/components/ui/Card";
import { LinkButton } from "@/components/ui/Button";
import { fmtNum } from "@/lib/format";
import { useLocationScope } from "@/lib/location-scope";
import type { GoogleMetrics, SeoOverview } from "@/lib/seo";
import { useFetch } from "@/lib/use-api";

const isoDay = (d: Date) => d.toISOString().slice(0, 10);
const SLOTS: [string, string, string[]][] = [["calls", "Calls", ["CALL_CLICKS"]], ["directions", "Directions", ["BUSINESS_DIRECTION_REQUESTS"]], ["website", "Website", ["WEBSITE_CLICKS"]],
  ["views", "Views", ["BUSINESS_IMPRESSIONS_DESKTOP_SEARCH", "BUSINESS_IMPRESSIONS_MOBILE_SEARCH", "BUSINESS_IMPRESSIONS_DESKTOP_MAPS", "BUSINESS_IMPRESSIONS_MOBILE_MAPS"]]];

/** GBP › Overview: how Google shows you, what needs fixing, then your words on Maps and what Google reports. Who is ahead and the profile checklist live on their own pages. */
export default function SeoOverviewPage() {
  const { locationId } = useLocationScope();
  const loc = locationId ?? "";
  const to = new Date(), from = new Date(); from.setDate(to.getDate() - 29);
  const ov = useFetch<SeoOverview>("/seo/overview", { location_id: loc });
  const gm = useFetch<GoogleMetrics>("/analytics/google-metrics", { from: isoDay(from), to: isoDay(to), location_id: loc });
  const d = ov.data, g = gm.data;
  const gOk = g?.availability.state === "ok" && !!g.current;

  return (
    <>
      <h1 className="mb-4 hidden text-[22px] font-semibold leading-7 sm:text-[26px] md:block">How you show up on Google</h1>
      <div className="mb-4 md:hidden"><h1 className="fq-page-title">Google</h1><p className="fq-page-sub mt-1.5">How you show up on Google</p></div>
      {ov.error && <Alert tone="error">{ov.error}</Alert>}
      <div className="mb-3 lg:mb-4"><GoogleProfileCard /></div>
      <div className="mb-4 lg:mb-5"><OptimizationCenter /></div>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-12 lg:gap-4">
        <Card label="Your words on Google Maps" className="lg:col-span-6">
          <Title right={<SourceTag source="places" />}>Your words on Maps</Title>
          <div className="mt-4">
            {ov.loading && !d ? <Skeleton className="h-40" /> : !d || d.state === "no_location" ? <ConnectGoogleEmptyState compact what="Tracking words needs a connected Google location." />
              : d.keywords.length === 0 ? <Empty text="Add the words customers search for." href="/seo/rankings" cta="Add a word" />
              : <><RankLadder words={d.keywords} limit={4} />{d.keywords.length > 4 && <div className="mt-2"><SeeAll href="/seo/rankings" /></div>}</>}
          </div>
        </Card>

        <Card label="From Google" className="lg:col-span-6">
          <Title right={<SourceTag source="google" />}>From Google</Title>
          <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-4 max-md:mt-2 max-md:gap-0">
            {SLOTS.map(([k, label, metrics]) => {
              const series = metrics.flatMap((m) => g?.series[m] ?? []);
              const byDay = new Map<string, number>(); series.forEach((p) => byDay.set(p.date, (byDay.get(p.date) ?? 0) + p.value));
              const vals = [...byDay.entries()].sort().map(([, v]) => v);
              const total = vals.reduce((a, b) => a + b, 0), top = Math.max(1, ...vals);
              return (
                <div key={k} className="min-w-0 max-md:border-b max-md:border-set-line max-md:py-3.5 max-md:odd:border-r max-md:odd:pr-4 max-md:even:pl-4 max-md:[&:nth-last-child(-n+2)]:border-b-0">
                  <dt className="text-[13px] text-muted max-md:text-xs max-md:font-bold max-md:text-set-soft">{label}</dt>
                  <dd className="num text-[20px] font-semibold leading-7 max-md:text-2xl max-md:font-extrabold max-md:leading-tight">{gOk && vals.length ? fmtNum(total) : "–"}</dd>
                  {gOk && vals.length ? <span aria-hidden className="mt-1 flex h-10 items-end gap-[2px]">{vals.map((v, i) => <span key={i} className="flex-1 rounded-t-[1px] bg-chart" style={{ height: `${Math.max(3, (v / top) * 100)}%` }} />)}</span> : <Dashes className="mt-1" />}
                </div>
              );
            })}
          </dl>
          {!gOk && !gm.loading && <div className="mt-4 flex flex-wrap items-center justify-between gap-2"><p className="text-[13px] text-muted">Waiting for Google.</p><LinkButton href="/gbp/locations" variant="secondary" size="sm">Check connection</LinkButton></div>}
          {gOk && <div className="mt-3"><SeeAll href="/seo/performance">Last 30 days</SeeAll></div>}
        </Card>

      </div>
    </>
  );
}

function Empty({ text, href, cta }: { text: string; href: string; cta: string }) {
  return <div className="flex flex-wrap items-center justify-between gap-3"><p className="text-[14px] text-muted">{text}</p><LinkButton href={href} variant="secondary" size="sm">{cta}</LinkButton></div>;
}
