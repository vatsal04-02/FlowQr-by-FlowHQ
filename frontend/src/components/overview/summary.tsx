"use client";
import clsx from "clsx";
import { ArrowRight, Star } from "lucide-react";
import Link from "next/link";
import { useMemo, type ReactNode } from "react";
import { LineChart } from "@/components/charts/LineChart";
import { Sparkline } from "@/components/charts/Sparkline";
import { Position, SourceTag, Unavailable, when } from "@/components/seo/parts";
import { Skeleton } from "@/components/ui/Card";
import { fmtNum, fmtRating } from "@/lib/format";
import type { Competitors, GoogleMetrics, GoogleMetricSummary, ProfileHealth, SeoOverview } from "@/lib/seo";
import type { Overview } from "@/lib/types";
import { useFetch } from "@/lib/use-api";
import { DeltaChip, Tile, TileHead } from "./widgets";

const More = ({ href, children }: { href: string; children: ReactNode }) => (
  <Link href={href} className="inline-flex min-h-9 items-center gap-1 text-[13px] font-semibold text-accent-ink hover:underline">{children}<ArrowRight className="h-3.5 w-3.5" aria-hidden /></Link>
);

// ------------------------------------------------------------------------------------------------ Google profile activity
const CELLS: [keyof GoogleMetricSummary, string, string][] = [
  ["search_views", "Search views", "Times your profile was shown in Google Search."],
  ["maps_views", "Maps views", "Times your profile was shown in Google Maps."],
  ["website", "Website clicks", "Taps on your website link."],
  ["calls", "Calls", "Taps on your phone number."],
  ["directions", "Directions", "Requests for directions to you."],
];

/** One band for everything Google reports about the profile. A metric Google did not return is "Not shared", never 0; if Google has shared nothing at all, one explanation replaces five empty tiles. */
export function GoogleBand({ range, loc, days }: { range: { from: string; to: string }; loc: string; days: number }) {
  const q = useFetch<GoogleMetrics>("/analytics/google-metrics", { from: range.from, to: range.to, location_id: loc });
  const d = q.data;
  return (
    <Tile i={3} dense labelledBy="ov-google" className="lg:col-span-2">
      <TileHead id="ov-google" title="Google profile activity" sub={d?.availability.state === "ok" ? `Reported by Google through ${when(d.range.to)}, compared with the ${d.range_days ?? days} days before` : "What customers do after finding you on Google"} right={<SourceTag source="google" />} />
      {q.loading && !d ? <Skeleton className="mt-4 h-24" /> : q.error ? <Unavailable className="mt-4" title="We couldn't load Google's numbers just now">{q.error}</Unavailable>
        : !d || d.availability.state !== "ok" || !d.current ? <Unavailable className="mt-4" title="Google isn't sharing these numbers yet" href="/gbp/locations" cta="Check the Google connection">{d?.availability.reason ?? "Connect Google to see them."} Nothing is estimated, and no zeros are shown in their place.</Unavailable>
        : (
          <>
            <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-4 sm:grid-cols-3 xl:grid-cols-5">
              {CELLS.map(([k, label, tip]) => {
                const v = d.current![k], pv = d.previous ? d.previous[k] : null;
                return (
                  <div key={k} className="min-w-0" title={tip}>
                    <dt className="text-[13px] font-medium text-muted">{label}</dt>
                    <dd className="num mt-1 text-[26px] font-semibold leading-8 tracking-[-.02em]">{v === null ? <span className="text-base font-medium text-muted">Not shared</span> : fmtNum(v)}</dd>
                    <div className="mt-1 min-h-6">{v !== null && pv !== null && <DeltaChip cur={v} prev={pv} kind="pct" days={d.range_days ?? days} />}</div>
                  </div>
                );
              })}
            </dl>
            <p className="mt-3 text-xs text-muted">{d.note} {d.days_with_data} of {d.range_days ?? days} days have data.{d.previous ? "" : " No earlier days are stored yet, so no comparison is shown."}</p>
          </>
        )}
    </Tile>
  );
}

// ------------------------------------------------------------------------------------------------ local visibility
export function VisibilityCard({ loc }: { loc: string }) {
  const q = useFetch<SeoOverview>("/seo/overview", { location_id: loc });
  const d = q.data, s = d?.summary;
  const spark = useMemo(() => (d?.trend ?? []).map((t) => Math.round((100 * t.top10) / Math.max(1, t.measured))), [d]);
  const moved = (d?.keywords ?? []).filter((k) => k.change);
  const up = moved.filter((k) => (k.change ?? 0) > 0).length;
  return (
    <Tile i={4} dense labelledBy="ov-vis">
      <TileHead id="ov-vis" title="Local visibility" sub="Where you appear for the searches you track" right={<SourceTag source="places" />} />
      {q.loading && !d ? <Skeleton className="mt-4 h-24" /> : !d || d.state === "no_location" ? <Unavailable className="mt-4" title="Connect a Google location" href="/gbp/locations" cta="Connect Google">Local visibility follows a specific Business Profile.</Unavailable>
        : d.state === "no_keywords" || !s || s.measured === 0 ? <Unavailable className="mt-4" title={d.state === "no_keywords" ? "No search terms tracked yet" : "Nothing measured yet"} href="/seo/rank" cta={d.state === "no_keywords" ? "Add a search term" : "Open rank tracking"}>{d.provider_configured ? "Rankings appear after the first check." : "Local ranking isn't set up on this server yet."}</Unavailable>
        : (
          <>
            <div className="mt-4 flex items-end justify-between gap-3">
              <p className="num text-[34px] font-semibold leading-none tracking-[-.02em]">{s.top10}<span className="text-lg font-medium text-muted"> of {s.measured}</span></p>
              <div className="text-accent">{spark.length >= 2 && <Sparkline id="sp-vis" values={spark} width={84} height={30} />}</div>
            </div>
            <p className="mt-1 text-[13px] text-muted">tracked terms show you in the top 10 · <b className="num text-ink">{s.top3}</b> in the top 3{moved.length ? ` · ${up} up, ${moved.length - up} down since last check` : ""}</p>
            <p className="mt-3 text-xs text-muted">Last checked {when(s.last_checked_at)}. Measured around your location with Google Places; Maps can differ by person.</p>
            <div className="mt-2"><More href="/seo">SEO overview</More></div>
          </>
        )}
    </Tile>
  );
}

// ------------------------------------------------------------------------------------------------ profile health
export function ProfileCard({ loc }: { loc: string }) {
  const q = useFetch<ProfileHealth>("/seo/profile-health", { location_id: loc });
  const d = q.data;
  const issues = (d?.locations ?? []).flatMap((l) => l.checks.filter((c) => c.status !== "ok").map((c) => ({ ...c, where: l.title }))).sort((a, b) => (a.status === "missing" ? 0 : 1) - (b.status === "missing" ? 0 : 1)).slice(0, 4);
  const h = d?.health;
  const noProfile = !!d && d.state === "ok" && d.locations.every((l) => l.state === "unavailable");
  return (
    <Tile i={5} dense labelledBy="ov-profile">
      <TileHead id="ov-profile" title="Profile health" sub="What to fix on your Google profile" right={<SourceTag source="flowqr" />} />
      {q.loading && !d ? <Skeleton className="mt-4 h-24" /> : !d || d.state === "no_location" || noProfile ? <Unavailable className="mt-4" title="Google hasn't shared your profile yet" href="/gbp/locations" cta="Check the Google connection">Profile checks use the profile Google returns. Until then nothing is scored.</Unavailable>
        : (
          <>
            <div className="mt-4 flex items-baseline gap-2">
              <p className="num text-[34px] font-semibold leading-none tracking-[-.02em]">{h?.score ?? "–"}</p>
              <p className="text-[13px] text-muted">{h?.score !== null && h?.score !== undefined ? "out of 100" : "not enough real data for a score"}</p>
            </div>
            {issues.length === 0 ? <p className="mt-3 text-sm text-muted">No open issues in the checks FlowQR can see.</p> : (
              <ul className="mt-3 space-y-1.5">
                {issues.map((c, i) => (
                  <li key={i} className="flex items-start gap-2 text-[13px]"><span aria-hidden className={clsx("mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full", c.status === "missing" ? "bg-neg" : "bg-warn")} />
                    <span className="min-w-0"><b className="font-semibold">{c.label}.</b> <span className="text-muted">{c.detail}</span> {c.link && <Link href={c.link} className="font-semibold text-accent-ink hover:underline">Fix</Link>}</span></li>
                ))}
              </ul>
            )}
            <div className="mt-2"><More href="/seo/profile">All profile checks</More></div>
          </>
        )}
    </Tile>
  );
}

// ------------------------------------------------------------------------------------------------ competitors
export function CompetitorCard({ loc }: { loc: string }) {
  const q = useFetch<Competitors>("/seo/competitors", { location_id: loc });
  const d = q.data;
  const top = (d?.competitors ?? []).slice(0, 3);
  return (
    <Tile i={6} dense labelledBy="ov-comp">
      <TileHead id="ov-comp" title="Competitors" sub="Seen next to you in Google" right={<SourceTag source="places" />} />
      {q.loading && !d ? <Skeleton className="mt-4 h-24" /> : !d || d.state !== "ok" ? <Unavailable className="mt-4" title="No competitor observations yet" href="/seo/competitors" cta="Open competitor analysis">They come from the checks you run for your tracked search terms. Nothing is shown until a check has run.</Unavailable>
        : (
          <>
            {d.you && <p className="mt-4 flex items-center justify-between gap-3 rounded-xl bg-accent-tint px-3 py-2 text-sm"><span className="font-semibold">You</span><span className="num flex items-center gap-1 font-semibold">{d.you.rating === null ? "–" : fmtRating(d.you.rating)}<Star className="h-3.5 w-3.5 fill-accent text-accent" aria-hidden /><span className="ml-1 font-normal text-muted">{d.you.reviews === null ? "–" : fmtNum(d.you.reviews)} reviews</span></span></p>}
            <ul className="mt-2 divide-y divide-ink-100">
              {top.map((c) => (
                <li key={c.place_id ?? c.name} className="flex items-center justify-between gap-3 py-2 text-sm"><span className="min-w-0 truncate font-medium">{c.name}</span>
                  <span className="num flex shrink-0 items-center gap-1 text-[13px]">{c.rating === null ? "–" : fmtRating(c.rating)}<Star className="h-3 w-3 fill-accent text-accent" aria-hidden /><span className="text-muted">{c.reviews === null ? "–" : fmtNum(c.reviews)}</span></span></li>
              ))}
            </ul>
            <p className="mt-2 text-xs text-muted">As observed, last on {when(top[0]?.observed_at ?? d.you?.observed_at)}.</p>
            <div className="mt-1"><More href="/seo/competitors">Competitor analysis</More></div>
          </>
        )}
    </Tile>
  );
}

// ------------------------------------------------------------------------------------------------ rating trend
export function RatingTrend({ o, loading, days }: { o: Overview | null; loading: boolean; days: number }) {
  const has = !!o && o.reviews.series.some((p) => Number(p.avg_rating) > 0);
  return (
    <Tile i={7} dense labelledBy="ov-rating-trend">
      <TileHead id="ov-rating-trend" title="Rating trend" sub={`Average rating of reviews received, last ${days} days`} right={<SourceTag source="google" />} />
      <div className="mt-3">
        {loading || !o ? <Skeleton className="h-44" /> : !has ? <Unavailable title="No rated reviews in this period">Days without a review have no point on the line, so a quiet week is never drawn as a drop.</Unavailable>
          : <LineChart ariaLabel={`Average rating per day for the last ${days} days`} data={o.reviews.series} series={[{ key: "avg_rating", label: "Average rating", color: "rgb(var(--c-accent))" }]} yMax={5} gaps height={190} />}
      </div>
    </Tile>
  );
}
