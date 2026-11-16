"use client";
import { GbpFrame } from "@/components/gbp/GbpFrame";
import { GeoGrid } from "@/components/gbp/GeoGrid";
import { LocalRank } from "@/components/gbp/LocalRank";
import { SourceTag } from "@/components/seo/parts";
import { Card, Dashes, RankLadder, SeeAll, Title, WhoIsAhead } from "@/components/seo/visuals";
import { Alert, Skeleton } from "@/components/ui/Card";
import { fmtNum } from "@/lib/format";
import { useLocationScope } from "@/lib/location-scope";
import type { Competitors, SeoOverview } from "@/lib/seo";
import { useFetch } from "@/lib/use-api";

/**
 * GBP › Rankings: where you show up for each word (Places, measured), the words people searched (Google, impressions: not a position), and who is ahead.
 * Adding words and running checks stays in the existing manager below; the map grid stays off until its cost is approved.
 */
export default function RankingsPage() {
  const { locationId } = useLocationScope();
  const loc = locationId ?? "";
  const ov = useFetch<SeoOverview>("/seo/overview", { location_id: loc });
  const comp = useFetch<Competitors>("/seo/competitors", { location_id: loc });
  const d = ov.data, t = d?.google_terms;
  const topTerm = Math.max(1, ...(t?.terms ?? []).map((x) => x.value ?? 0));
  return (
    <>
      <h1 className="mb-4 text-[22px] font-semibold leading-7 sm:text-[26px]">Rankings</h1>
      {ov.error && <Alert tone="error">{ov.error}</Alert>}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-12 lg:gap-4">
        <Card label="Your words" className="lg:col-span-7">
          <Title right={<SourceTag source="places" />}>Your words</Title>
          <div className="mt-4">{ov.loading && !d ? <Skeleton className="h-40" /> : d && d.keywords.length ? <RankLadder words={d.keywords} /> : <p className="text-[14px] text-muted">No words yet. Add one below.</p>}</div>
        </Card>
        <Card label="What people search" className="lg:col-span-5">
          <Title right={<SourceTag source="google" />}>What people search</Title>
          {!t ? <><Dashes bars={6} className="mt-4 !h-6" /><p className="mt-3 text-[13px] text-muted">Waiting for Google.</p></> : (
            <>
              <ol className="mt-3 space-y-2.5">
                {t.terms.slice(0, 5).map((x) => (
                  <li key={x.keyword}>
                    <div className="flex items-baseline justify-between gap-3 text-[14px]"><span data-words="skip" className="min-w-0 truncate">{x.keyword}</span><b className="num shrink-0 font-semibold">{x.value === null ? "<15" : fmtNum(x.value)}</b></div>
                    <span aria-hidden className="mt-1 block h-1.5 overflow-hidden rounded-full bg-surface-3"><span className="fq-bar-x block h-full rounded-full bg-chart" style={{ width: `${x.value === null ? 3 : Math.max(3, (x.value / topTerm) * 100)}%` }} /></span>
                  </li>
                ))}
              </ol>
              <div className="mt-2"><SeeAll href="/seo/searches" /></div>
            </>
          )}
        </Card>
        <Card label="Who is ahead of you" className="lg:col-span-12">
          <Title right={<SourceTag source="places" />}>Who is ahead</Title>
          <div className="mt-3">{comp.loading && !comp.data ? <Skeleton className="h-32" /> : comp.data?.state === "ok" ? <><WhoIsAhead d={comp.data} limit={5} /><div className="mt-1"><SeeAll href="/seo/competitors">All competitors</SeeAll></div></> : <p className="text-[14px] text-muted">Shown after your first word check.</p>}</div>
        </Card>
      </div>
      <div className="mt-4"><GbpFrame>{(gid) => <div className="space-y-4"><LocalRank key={gid} gid={gid} /><GeoGrid key={`map-${gid}`} gid={gid} /></div>}</GbpFrame></div>
    </>
  );
}
