"use client";
import Link from "next/link";
import { Ring } from "@/components/charts/Bars";
import { Card, Dashes, RankLadder, SeeAll, Title, WhoIsAhead } from "@/components/seo/visuals";
import { SourceTag } from "@/components/seo/parts";
import { Alert, Skeleton } from "@/components/ui/Card";
import { LinkButton } from "@/components/ui/Button";
import { fmtNum } from "@/lib/format";
import { useLocationScope } from "@/lib/location-scope";
import type { Competitors, GoogleMetrics, ProfileHealth, SeoOverview } from "@/lib/seo";
import { useFetch } from "@/lib/use-api";

const isoDay = (d: Date) => d.toISOString().slice(0, 10);
const SLOTS: [string, string, string[]][] = [["calls", "Calls", ["CALL_CLICKS"]], ["directions", "Directions", ["BUSINESS_DIRECTION_REQUESTS"]], ["website", "Website", ["WEBSITE_CLICKS"]],
  ["views", "Views", ["BUSINESS_IMPRESSIONS_DESKTOP_SEARCH", "BUSINESS_IMPRESSIONS_MOBILE_SEARCH", "BUSINESS_IMPRESSIONS_DESKTOP_MAPS", "BUSINESS_IMPRESSIONS_MOBILE_MAPS"]]];

/** GBP › Overview: the rank ladder first, then what Google reports (or one honest empty card), who is ahead, and what to fix on the profile. */
export default function SeoOverviewPage() {
  const { locationId } = useLocationScope();
  const loc = locationId ?? "";
  const to = new Date(), from = new Date(); from.setDate(to.getDate() - 29);
  const ov = useFetch<SeoOverview>("/seo/overview", { location_id: loc });
  const gm = useFetch<GoogleMetrics>("/analytics/google-metrics", { from: isoDay(from), to: isoDay(to), location_id: loc });
  const comp = useFetch<Competitors>("/seo/competitors", { location_id: loc });
  const prof = useFetch<ProfileHealth>("/seo/profile-health", { location_id: loc });
  const d = ov.data, g = gm.data;
  const gOk = g?.availability.state === "ok" && !!g.current;
  const pl = prof.data?.locations.find((l) => l.state === "ok");
  const missing = (pl?.checks ?? []).filter((c) => c.status !== "ok").slice(0, 3);

  return (
    <>
      <h1 className="mb-4 text-[22px] font-semibold leading-7 sm:text-[26px]">How you show up on Google</h1>
      {ov.error && <Alert tone="error">{ov.error}</Alert>}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-12 lg:gap-4">
        <Card label="Your words on Google Maps" className="lg:col-span-7">
          <Title right={<SourceTag source="places" />}>Your words on Maps</Title>
          <div className="mt-4">
            {ov.loading && !d ? <Skeleton className="h-40" /> : !d || d.state === "no_location" ? <Empty text="Connect a Google location to track words." href="/gbp/locations" cta="Connect Google" />
              : d.keywords.length === 0 ? <Empty text="Add the words customers search for." href="/seo/rankings" cta="Add a word" />
              : <><RankLadder words={d.keywords} limit={4} />{d.keywords.length > 4 && <div className="mt-2"><SeeAll href="/seo/rankings" /></div>}</>}
          </div>
        </Card>

        <Card label="From Google" className="lg:col-span-5">
          <Title right={<SourceTag source="google" />}>From Google</Title>
          <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-4">
            {SLOTS.map(([k, label, metrics]) => {
              const series = metrics.flatMap((m) => g?.series[m] ?? []);
              const byDay = new Map<string, number>(); series.forEach((p) => byDay.set(p.date, (byDay.get(p.date) ?? 0) + p.value));
              const vals = [...byDay.entries()].sort().map(([, v]) => v);
              const total = vals.reduce((a, b) => a + b, 0), top = Math.max(1, ...vals);
              return (
                <div key={k} className="min-w-0">
                  <dt className="text-[13px] text-muted">{label}</dt>
                  <dd className="num text-[20px] font-semibold leading-7">{gOk && vals.length ? fmtNum(total) : "–"}</dd>
                  {gOk && vals.length ? <span aria-hidden className="mt-1 flex h-10 items-end gap-[2px]">{vals.map((v, i) => <span key={i} className="flex-1 rounded-t-[1px] bg-chart" style={{ height: `${Math.max(3, (v / top) * 100)}%` }} />)}</span> : <Dashes className="mt-1" />}
                </div>
              );
            })}
          </dl>
          {!gOk && !gm.loading && <div className="mt-4 flex flex-wrap items-center justify-between gap-2"><p className="text-[13px] text-muted">Waiting for Google.</p><LinkButton href="/gbp/locations" variant="secondary" size="sm">Check connection</LinkButton></div>}
          {gOk && <div className="mt-3"><SeeAll href="/seo/performance">Last 30 days</SeeAll></div>}
        </Card>

        <Card label="Who is ahead of you" className="lg:col-span-7">
          <Title right={<SourceTag source="places" />}>Who is ahead</Title>
          <div className="mt-3">{comp.loading && !comp.data ? <Skeleton className="h-32" /> : comp.data?.state === "ok" ? <><WhoIsAhead d={comp.data} limit={3} /><div className="mt-1"><SeeAll href="/seo/competitors" /></div></> : <Empty text="Run a word check to see who is next to you." href="/seo/rankings" cta="Check words" />}</div>
        </Card>

        <Card label="Profile strength" className="lg:col-span-5">
          <Title>Profile strength</Title>
          {prof.loading && !prof.data ? <Skeleton className="mt-3 h-32" /> : !pl ? <div className="mt-3 flex items-center gap-4"><Ring value={null} size={72} stroke={8} label="Profile not shared yet"><span className="text-[13px] text-muted">–</span></Ring><p className="text-[13px] text-muted">Waiting for Google.</p></div> : (
            <div className="mt-3 flex items-start gap-4">
              <Ring value={pl.completeness} size={72} stroke={8} label={`Profile ${pl.completeness}% complete`}><b className="num text-[17px] font-semibold">{pl.completeness}%</b></Ring>
              <ul className="min-w-0 flex-1 divide-y divide-line">
                {missing.length === 0 ? <li className="py-2 text-[14px]">Complete</li> : missing.map((c) => (
                  <li key={c.key} className="flex items-center justify-between gap-2 py-1.5 text-[14px]"><span className="min-w-0 truncate">{c.label}</span>{c.link && <Link href={c.link} className="inline-flex min-h-11 shrink-0 items-center text-[13px] font-semibold underline underline-offset-2 md:min-h-8">Fix</Link>}</li>
                ))}
              </ul>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}

function Empty({ text, href, cta }: { text: string; href: string; cta: string }) {
  return <div className="flex flex-wrap items-center justify-between gap-3"><p className="text-[14px] text-muted">{text}</p><LinkButton href={href} variant="secondary" size="sm">{cta}</LinkButton></div>;
}
