"use client";
import { GbpFrame } from "@/components/gbp/GbpFrame";
import { GeoGrid } from "@/components/gbp/GeoGrid";
import { LocalRank } from "@/components/gbp/LocalRank";
import { SourceTag } from "@/components/seo/parts";
import { Card, Dashes, RankLadder, SeeAll, Title, WhoIsAhead } from "@/components/seo/visuals";
import { Alert, Skeleton } from "@/components/ui/Card";
import { CountUp } from "@/components/charts/CountUp";
import { shares } from "@/lib/charts";
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
  // Share of the five shown terms. A term Google reports only as "fewer than 15" has no number, so it is left out of the shares rather than guessed.
  const shown = (t?.terms ?? []).slice(0, 5);
  const counted = shown.filter((x) => x.value !== null) as (typeof shown[number] & { value: number })[];
  const pct = shares(counted.map((x) => x.value));
  const total = counted.reduce((a, x) => a + x.value, 0);
  const COLORS = ["rgb(var(--c-tone-blue))", "rgb(var(--c-tone-teal))", "rgb(var(--c-tone-amber))", "rgb(var(--c-tone-rose))", "rgb(var(--c-tone-sky))"];
  const colorOf = (k: string) => COLORS[Math.max(0, shown.findIndex((x) => x.keyword === k)) % COLORS.length];
  return (
    <>
      <h1 className="mb-4 text-[22px] font-semibold leading-7 sm:text-[26px]">Rankings</h1>
      {ov.error && <Alert tone="error">{ov.error}</Alert>}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-12 lg:gap-4">
        <Card label="Your words" tone="teal" className="lg:col-span-7">
          <Title right={<SourceTag source="places" />}>Your words</Title>
          <div className="mt-4">{ov.loading && !d ? <Skeleton className="h-40" /> : d && d.keywords.length ? <RankLadder words={d.keywords} /> : <div className="rounded-[14px] border-[1.5px] border-dashed border-line p-5 text-center"><p className="text-[15px] font-semibold">No words yet</p><p className="mt-1 text-[13.5px] text-muted">Add the searches you want to be found for in “Manage words” below.{t && t.terms.length > 0 ? " People already use words like:" : ""}</p>{t && t.terms.length > 0 && <ul className="mt-3 flex flex-wrap justify-center gap-1.5">{t.terms.slice(0, 3).map((x) => <li key={x.keyword} data-words="skip" className="rounded-full bg-surface-2 px-3 py-1 text-[13px] font-medium">{x.keyword}</li>)}</ul>}</div>}</div>
        </Card>
        <Card label="What people search" tone="blue" className="lg:col-span-5">
          <Title right={<SourceTag source="google" />}>What people search</Title>
          {!t ? <><Dashes bars={6} className="mt-4 !h-6" /><p className="mt-3 text-[13px] text-muted">Waiting for Google.</p></> : (
            <>
              {total > 0 && (
                <>
                  <div aria-hidden className="mt-3 flex h-3.5 gap-[3px]">{counted.map((x, i) => <i key={x.keyword} className="fq-bar-x block rounded-full" style={{ flex: x.value, background: colorOf(x.keyword), animationDelay: `${i * 90}ms` }} title={`${x.keyword}: ${fmtNum(x.value)}`} />)}</div>
                  <p className="mt-2 text-[13px] text-muted">Share of these {counted.length} searches · <CountUp value={total} /> in all</p>
                </>
              )}
              <ol className="mt-3 space-y-2.5">
                {shown.map((x) => (
                  <li key={x.keyword}>
                    <div className="flex items-baseline justify-between gap-3 text-[14px]"><span data-words="skip" className="flex min-w-0 items-center gap-2"><i aria-hidden className="h-2.5 w-2.5 shrink-0 rounded-[3px]" style={{ background: colorOf(x.keyword) }} /><span className="truncate">{x.keyword}</span></span>
                      <b className="num shrink-0 font-semibold">{x.value === null ? "<15" : fmtNum(x.value)}{x.value !== null && <em className="ml-1 text-[13px] font-medium not-italic text-muted">{pct[counted.findIndex((c) => c.keyword === x.keyword)]}%</em>}</b></div>
                    <span aria-hidden className="mt-1 block h-1.5 overflow-hidden rounded-full bg-surface-3"><span className="fq-bar-x block h-full rounded-full" style={{ background: colorOf(x.keyword), width: `${x.value === null ? 3 : Math.max(3, (x.value / topTerm) * 100)}%` }} /></span>
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
