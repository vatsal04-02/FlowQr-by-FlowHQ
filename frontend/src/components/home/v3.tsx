"use client";
import clsx from "clsx";
import { Eye, MapPin, MousePointerClick, Phone } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { AreaChart } from "@/components/charts/AreaChart";
import { CountUp } from "@/components/charts/CountUp";
import { Donut, Legend, type Slice } from "@/components/charts/Donut";
import { SourceTag } from "@/components/seo/parts";
import { Skeleton, Stars } from "@/components/ui/Card";
import { canDrawArea, dailyStack, ratingMix } from "@/lib/charts";
import { timeAgo } from "@/lib/format";
import type { GoogleMetrics } from "@/lib/seo";
import type { Overview, Review } from "@/lib/types";
import { Card, Delta, Title } from "./v2";

// ------------------------------------------------------------------------------------------------ latest reviews: the four newest, as the inbox sees them
export function LatestReviews({ items, total, loading }: { items: Review[] | null; total: number; loading: boolean }) {
  return (
    <Card label="Latest reviews">
      <Title right={<Link href="/gbp/reviews" className="inline-flex min-h-11 items-center text-[13px] font-semibold text-accent-ink hover:underline md:min-h-8">Inbox</Link>}>Latest reviews</Title>
      {loading || !items ? <Skeleton className="mt-3 h-[180px]" /> : items.length === 0 ? (
        <p className="mt-3 text-[14px] text-muted">No reviews have been synced yet. New ones appear here.</p>
      ) : (
        <ul className="mt-1 divide-y divide-line">
          {items.map((r) => {
            const replied = !!r.google_reply_text || r.reply_state === "published";
            return (
              <li key={r.id}>
                <Link href={`/gbp/reviews/${r.id}`} className="group grid grid-cols-[36px_minmax(0,1fr)_auto] items-center gap-3 py-2.5">
                  <span aria-hidden className="grid h-9 w-9 place-items-center rounded-full bg-surface-2 text-[13px] font-semibold text-ink-700">{(r.reviewer_name ?? "G").trim().slice(0, 1).toUpperCase()}</span>
                  <span className="min-w-0">
                    <span data-words="skip" className="block truncate text-[14px] font-semibold group-hover:text-accent-ink">{r.reviewer_name ?? "Google user"}</span>
                    <span data-words="skip" className="block truncate text-[13px] text-muted">{r.text || "Rating only, no written review"}</span>
                  </span>
                  <span className="flex flex-col items-end gap-0.5"><Stars rating={r.rating} size={12} /><span className={clsx("text-[12px]", replied ? "text-muted" : "font-semibold text-warn")}>{replied ? timeAgo(r.review_created_at) : "Needs reply"}</span></span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
      {items && total > items.length && <p className="mt-1 text-[12px] text-muted">{total} reviews synced in all</p>}
    </Card>
  );
}

// ------------------------------------------------------------------------------------------------ rating mix: how all synced reviews split by stars
const STAR_COLOR: Record<number, string> = { 5: "rgb(var(--c-pos))", 4: "rgb(var(--c-tone-teal))", 3: "rgb(var(--c-caution))", 2: "rgb(var(--c-tone-rose))", 1: "rgb(var(--c-neg))" };
export function RatingMix({ o, loading }: { o: Overview | null; loading: boolean }) {
  const r = o?.reviews;
  const slices: Slice[] = ratingMix(r?.rating_distribution).map((x) => ({ key: String(x.star), label: `${x.star} ${x.star === 1 ? "star" : "stars"}`, value: x.count, color: STAR_COLOR[x.star] }));
  const total = slices.reduce((a, s) => a + s.value, 0);
  return (
    <Card label="Rating mix" tone="amber">
      <Title right={total ? <span className="rounded-full bg-surface-2 px-2.5 py-0.5 text-[12px] font-medium text-ink-700">{total} reviews</span> : null}>Rating mix</Title>
      {loading || !r ? <Skeleton className="mt-3 h-[130px]" /> : total === 0 ? <p className="mt-3 text-[14px] text-muted">Shown once reviews have been synced.</p> : (
        <div className="mt-3 flex flex-wrap items-center gap-5">
          <Donut slices={slices} size={116} stroke={16} label={`Rating mix of ${total} reviews`}
            centre={r.average_rating_all_time === null ? "–" : <CountUp value={r.average_rating_all_time} decimals={1} />} sub="average" />
          <Legend slices={slices} />
        </div>
      )}
    </Card>
  );
}

// ------------------------------------------------------------------------------------------------ customer actions on Google: stored daily figures, never generated
const ACTIONS: { key: "calls" | "directions" | "website"; label: string; metric: string; color: string; icon: ReactNode }[] = [
  { key: "calls", label: "Calls", metric: "CALL_CLICKS", color: "rgb(var(--c-tone-teal))", icon: <Phone className="h-[15px] w-[15px]" aria-hidden /> },
  { key: "directions", label: "Directions", metric: "BUSINESS_DIRECTION_REQUESTS", color: "rgb(var(--c-tone-blue))", icon: <MapPin className="h-[15px] w-[15px]" aria-hidden /> },
  { key: "website", label: "Website clicks", metric: "WEBSITE_CLICKS", color: "rgb(var(--c-tone-amber))", icon: <MousePointerClick className="h-[15px] w-[15px]" aria-hidden /> },
];

export function GoogleActions({ m, loading, error }: { m: GoogleMetrics | null; loading: boolean; error: string | null }) {
  if (loading && !m) return <Card label="Customer actions"><Title>Customer actions</Title><Skeleton className="mt-3 h-[220px]" /></Card>;
  const ok = !!m && m.availability.state === "ok" && !!m.current;
  if (!ok || !m) {
    return (
      <Card label="Customer actions">
        <Title right={<SourceTag source="google" />}>Customer actions</Title>
        <p className="mt-2 text-[14px] text-muted">{error ? "Couldn't load these numbers." : "Google hasn't shared these numbers with FlowQR yet."} <Link href="/gbp/locations" className="font-semibold text-accent-ink hover:underline">Google connection</Link></p>
      </Card>
    );
  }
  const cur = m.current!, prev = m.previous;
  const views = (s: typeof cur | null) => (s && (s.search_views !== null || s.maps_views !== null) ? (s.search_views ?? 0) + (s.maps_views ?? 0) : null);
  const days = dailyStack(m.series, ACTIONS.map((a) => [a.metric]));
  const slices: Slice[] = ACTIONS.filter((a) => cur[a.key] !== null).map((a) => ({ key: a.key, label: a.label, value: cur[a.key] as number, color: a.color }));
  const sum = slices.reduce((a, s) => a + s.value, 0);
  const v = views(cur);
  return (
    <Card label="Customer actions" tone="blue">
      <Title right={<SourceTag source="google" />}>Customer actions</Title>
      <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
        {[...ACTIONS.map((a) => ({ label: a.label, value: cur[a.key], before: prev ? prev[a.key] : null })), { label: "Profile views", value: v, before: views(prev) }].map((x) => (
          <div key={x.label}><p className="text-[13px] text-muted">{x.label}</p>
            <p className="mt-0.5 flex items-baseline gap-2"><span className="num text-[22px] font-semibold leading-7 tracking-[-.02em]">{x.value === null ? "–" : <CountUp value={x.value} />}</span><Delta cur={x.value} prev={x.before} /></p></div>
        ))}
      </div>
      <div className="mt-4 grid gap-5 md:grid-cols-[minmax(0,1fr)_200px]">
        <div className="min-w-0">
          {canDrawArea(days)
            ? <AreaChart days={days} names={ACTIONS.map((a) => a.label)} colors={ACTIONS.map((a) => a.color)} ariaLabel="Calls, directions and website clicks per day, as reported by Google" />
            : <p className="rounded-[12px] bg-surface-2 p-3 text-[13px] text-muted">The daily chart appears once Google has shared three days in a row ({m.days_with_data} so far). The totals above are what Google has shared.</p>}
        </div>
        {sum > 0 && (
          <div className="flex flex-col items-center gap-3 md:items-stretch">
            <div className="flex justify-center"><Donut slices={slices} size={132} stroke={18} label="Share of calls, directions and website clicks" centre={<CountUp value={sum} />} sub="actions" /></div>
            <Legend slices={slices} />
          </div>
        )}
      </div>
      <p className="mt-3 flex items-start gap-1.5 text-[12px] text-muted"><Eye className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />Reported by Google a few days late. Days Google has not reported are left out, not counted as zero.</p>
    </Card>
  );
}
