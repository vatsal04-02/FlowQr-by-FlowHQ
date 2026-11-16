"use client";
import clsx from "clsx";
import { AlertTriangle, ArrowDownRight, ArrowRight, ArrowUpRight, Clock, Lightbulb, MessageSquare, Minus, QrCode, Star } from "lucide-react";
import Link from "next/link";
import { useMemo, type ReactNode } from "react";
import { LineChart, type Series } from "@/components/charts/LineChart";
import { Skeleton, Stars } from "@/components/ui/Card";
import { Segmented } from "@/components/ui/kit";
import { DAY_OPTIONS, delta, type Days, type Todo } from "@/lib/dashboard";
import { fmtNum, fmtRating, timeAgo } from "@/lib/format";
import type { GoogleMetrics } from "@/lib/seo";
import type { Insights, Overview, Review } from "@/lib/types";

/** A small card on Home: 16px radius, one label, one number. Never more than four of these in a row. */
function Card({ children, className, label }: { children: ReactNode; className?: string; label?: string }) {
  return <section aria-label={label} className={clsx("panel min-w-0 p-4", className)}>{children}</section>;
}
const H = ({ id, children, right }: { id: string; children: ReactNode; right?: ReactNode }) => (
  <div className="flex items-center justify-between gap-3"><h2 id={id} className="text-[15px] font-semibold leading-5">{children}</h2>{right}</div>
);
/** A short comparison for a number: "+50% vs before". A drop is plain, not alarming (a quiet week is not a failure); no earlier period means no comparison is shown. */
const Short = ({ cur, prev }: { cur: number | null | undefined; prev: number | null | undefined }) => {
  if (cur === null || cur === undefined || prev === null || prev === undefined) return <span>No earlier period yet</span>;
  if (prev === 0) return <span>{cur > 0 ? "New this period" : "No change"}</span>;
  const pct = Math.round(((cur - prev) / prev) * 100);
  const Icon = pct > 0 ? ArrowUpRight : pct < 0 ? ArrowDownRight : Minus;
  return <span className={clsx("inline-flex items-center gap-1", pct > 0 && "font-medium text-pos")}><Icon className="h-3.5 w-3.5 shrink-0" aria-hidden />{pct === 0 ? "Same as before" : `${pct > 0 ? "+" : "-"}${Math.abs(pct)}% vs before`}</span>;
};

// ------------------------------------------------------------------------------------------------ 1. business overview
export function HomeHeader({ business, where, days, onDays }: { business: string; where: string; days: Days; onDays: (d: Days) => void }) {
  return (
    <header className="mb-4 flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
      <div className="min-w-0">
        <p className="text-[13px] font-medium text-muted">Your business at a glance</p>
        <h1 className="truncate text-[22px] font-semibold leading-7 tracking-[-.015em] sm:text-[26px] sm:leading-8">{business}</h1>
        <p className="text-[14px] text-muted">{where}</p>
      </div>
      <Segmented label="Show the last" value={String(days)} options={DAY_OPTIONS.map(([d, l]) => [String(d), l] as const)} onChange={(v) => onDays(Number(v) as Days)} />
    </header>
  );
}

function Metric({ label, value, sub, href, hint }: { label: string; value: ReactNode; sub: ReactNode; href?: string; hint?: string }) {
  const body = (
    <>
      <p className="text-[13px] font-medium text-muted" title={hint}>{label}</p>
      <p className="num mt-1 text-[28px] font-semibold leading-8 tracking-[-.02em]">{value}</p>
      <div className="mt-1 min-h-5 text-[13px] leading-5 text-muted">{sub}</div>
    </>
  );
  return href ? <Link href={href} className="panel block min-w-0 p-4 transition-colors hover:bg-surface-2/60">{body}</Link> : <div className="panel min-w-0 p-4">{body}</div>;
}

/** At most four numbers. The fourth appears only when Google has really shared it; otherwise one plain sentence says so (no zero, no estimate). */
export function Metrics({ o, prev, gm, days, loading, prevLoading }: { o: Overview | null; prev: Overview | null; gm: GoogleMetrics | null; days: number; loading: boolean; prevLoading?: boolean }) {
  if (loading || !o) return <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{[0, 1, 2, 3].map((k) => <Skeleton key={k} className="h-[116px] !rounded-[16px]" />)}</div>;
  const r = o.reviews;
  const answered = r.total_synced ? Math.round(((r.total_synced - r.awaiting_reply) / r.total_synced) * 100) : null;
  const gOk = gm?.availability.state === "ok" && gm.current && (gm.current.search_views !== null || gm.current.maps_views !== null);
  const views = gOk ? (gm!.current!.search_views ?? 0) + (gm!.current!.maps_views ?? 0) : null;
  const prevViews = gOk && gm!.previous && (gm!.previous.search_views !== null || gm!.previous.maps_views !== null) ? (gm!.previous.search_views ?? 0) + (gm!.previous.maps_views ?? 0) : null;
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Metric label="Google rating" href="/gbp/reviews" hint="The average of all your Google reviews."
        value={r.average_rating_all_time === null ? "–" : <span className="inline-flex items-center gap-1">{fmtRating(r.average_rating_all_time)}<Star className="h-5 w-5 fill-accent text-accent" aria-hidden /></span>}
        sub={r.total_synced ? `from ${fmtNum(r.total_synced)} ${r.total_synced === 1 ? "review" : "reviews"}` : "No reviews yet"} />
      <Metric label="New reviews" href="/analytics/reviews" hint="Reviews customers left during this period."
        value={fmtNum(r.new_in_range)} sub={prevLoading ? "" : <Short cur={r.new_in_range} prev={prev?.reviews.new_in_range} />} />
      <Metric label="Reviews answered" href="/gbp/reviews?state=none" hint="Reviews that have a reply from you."
        value={answered === null ? "–" : `${answered}%`} sub={r.awaiting_reply > 0 ? `${fmtNum(r.awaiting_reply)} still ${r.awaiting_reply === 1 ? "needs" : "need"} a reply` : r.total_synced ? "Every review is answered" : "Nothing to answer yet"} />
      {gOk
        ? <Metric label="Times people saw your profile" href="/analytics/performance" hint="How often your business showed up in Google Search and Maps." value={fmtNum(views as number)}
            sub={<Short cur={views} prev={prevViews} />} />
        : <div className="panel min-w-0 p-4"><p className="text-[13px] font-medium text-muted">Google profile activity</p><p className="mt-2 text-[13px] leading-5 text-muted">Google hasn&rsquo;t shared these numbers with FlowQR yet.</p></div>}
    </div>
  );
}

// ------------------------------------------------------------------------------------------------ 2. review growth
const PAIR: Series[] = [{ key: "cur", label: "This period", color: "rgb(var(--c-accent))" }, { key: "prev", label: "Before", color: "rgb(var(--c-ink-300))", dash: "4 4" }];

export function ReviewGrowth({ o, prev, days, loading }: { o: Overview | null; prev: Overview | null; days: number; loading: boolean }) {
  const data = useMemo(() => o?.reviews.series.map((p, i) => ({ date: p.date, cur: Number(p.count) || 0, prev: Number(prev?.reviews.series[i]?.count) || 0 })) ?? [], [o, prev]);
  const d = o && prev ? delta(o.reviews.new_in_range, prev.reviews.new_in_range) : null;
  const insight = !o ? "" : o.reviews.new_in_range === 0 ? "No new reviews in this period. A QR card at the counter is the easiest way to get them."
    : !prev || prev.reviews.new_in_range === 0 ? "There are no earlier reviews to compare with yet."
    : d && d.diff > 0 ? `${d.diff} more ${d.diff === 1 ? "review" : "reviews"} than the ${days} days before. Keep asking happy customers.`
    : d && d.diff < 0 ? `${Math.abs(d.diff)} fewer ${Math.abs(d.diff) === 1 ? "review" : "reviews"} than the ${days} days before. A card at the counter helps.` : `The same number as the ${days} days before.`;
  return (
    <Card label="Review growth" className="lg:col-span-2">
      <H id="home-growth" right={<Link href="/analytics/reviews" className="inline-flex min-h-11 items-center gap-1 text-[13px] font-semibold text-accent-ink hover:underline sm:min-h-9">Details<ArrowRight className="h-3.5 w-3.5" aria-hidden /></Link>}>New reviews over time</H>
      {loading || !o ? <Skeleton className="mt-3 h-52" /> : (
        <>
          <p className="mt-1 text-[14px] leading-5 text-ink-700">{insight}</p>
          <div className="mt-3"><LineChart ariaLabel={`New Google reviews per day for the last ${days} days, compared with the ${days} days before`} data={data} series={PAIR} height={200} /></div>
        </>
      )}
    </Card>
  );
}

// ------------------------------------------------------------------------------------------------ 3. things to take care of
const TONE = { bad: { icon: AlertTriangle, cls: "bg-neg-tint text-neg", word: "Important" }, warn: { icon: Clock, cls: "bg-warn-tint text-warn", word: "Soon" }, info: { icon: Lightbulb, cls: "bg-accent-tint text-accent-ink", word: "Idea" } } as const;

/** Three items at most, most urgent first: a short title, one line of why, one clear action. */
export function ThingsToDo({ todos, loading }: { todos: Todo[]; loading: boolean }) {
  const top = [...todos].sort((a, b) => (a.tone === b.tone ? 0 : a.tone === "bad" ? -1 : b.tone === "bad" ? 1 : a.tone === "warn" ? -1 : 1)).slice(0, 3);
  return (
    <Card label="Things to take care of">
      <H id="home-todo" right={todos.length > 3 ? <Link href="/ai/tasks" className="text-[13px] font-semibold text-accent-ink hover:underline">All {todos.length}</Link> : undefined}>Things to take care of</H>
      {loading ? <Skeleton className="mt-3 h-40" /> : top.length === 0 ? <p className="mt-3 text-[14px] text-muted">Nothing needs you right now. Nice work.</p> : (
        <ul className="mt-2 divide-y divide-ink-100">
          {top.map((t) => {
            const T = TONE[t.tone];
            return (
              <li key={t.id} className="flex items-start gap-3 py-3 first:pt-2 last:pb-0">
                <span aria-hidden className={clsx("mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-[9px]", T.cls)}><T.icon className="h-4 w-4" /></span>
                <div className="min-w-0 flex-1">
                  <p className="text-[14px] font-semibold leading-5">{t.title}<span className="sr-only"> ({T.word})</span></p>
                  <p className="mt-0.5 line-clamp-2 text-[13px] leading-[18px] text-muted">{t.detail}</p>
                  <Link href={t.href} className="mt-1.5 inline-flex min-h-11 items-center rounded-full bg-ink-solid px-4 text-[13px] font-semibold text-ink-on hover:opacity-90 sm:min-h-9">{t.cta}</Link>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

// ------------------------------------------------------------------------------------------------ 4. customer activity
export function CustomerActivity({ o, loading }: { o: Overview | null; loading: boolean }) {
  const e = o?.engagement;
  const rows: [string, number, string][] = e ? [["Scanned your QR or NFC card", e.scans, "bg-accent/45"], ["Opened your review page", e.landing_views, "bg-accent/70"], ["Tapped Continue to Google", e.google_clicks, "bg-accent"]] : [];
  const top = Math.max(1, ...rows.map((r) => r[1]));
  return (
    <Card label="Customer activity">
      <H id="home-activity" right={<Link href="/analytics/funnel" className="text-[13px] font-semibold text-accent-ink hover:underline">Details</Link>}>From QR scan to Google</H>
      {loading || !o ? <Skeleton className="mt-3 h-36" /> : o.cards.length === 0 ? (
        <div className="mt-3 rounded-xl bg-surface-2 p-4">
          <p className="flex items-center gap-2 text-[14px] font-semibold"><QrCode className="h-4 w-4" aria-hidden />No QR card yet</p>
          <p className="mt-1 text-[13px] text-muted">A card on your counter lets customers leave a Google review in a few taps.</p>
          <Link href="/gbp/cards" className="mt-3 inline-flex min-h-11 items-center rounded-full bg-ink-solid px-4 text-[13px] font-semibold text-ink-on sm:min-h-9">Set up a QR card</Link>
        </div>
      ) : (
        <>
          <ol className="mt-3 space-y-3">
            {rows.map(([label, v, bar]) => (
              <li key={label}>
                <div className="flex items-baseline justify-between gap-3 text-[13px]"><span className="text-ink-700">{label}</span><span className="num text-[15px] font-semibold">{fmtNum(v)}</span></div>
                <span aria-hidden className="mt-1 block h-2 overflow-hidden rounded-full bg-surface-3"><span className={clsx("block h-full rounded-full", bar)} style={{ width: `${Math.max(v ? 3 : 0, (v / top) * 100)}%` }} /></span>
              </li>
            ))}
          </ol>
          <p className="mt-3 text-xs leading-4 text-muted">Tapping Continue to Google is not a finished review. Reviews are counted separately.</p>
        </>
      )}
    </Card>
  );
}

// ------------------------------------------------------------------------------------------------ 5. customer feedback
export function CustomerFeedback({ o, ins, recent, loading }: { o: Overview | null; ins: Insights | null; recent: Review[] | null; loading: boolean }) {
  const dist = o?.reviews.rating_distribution ?? {};
  const peak = Math.max(1, ...Object.values(dist));
  const topics = [...(ins?.topics ?? [])].sort((a, b) => b.mentions - a.mentions).slice(0, 5);
  const total = o?.reviews.total_synced ?? 0;
  return (
    <Card label="Customer feedback" className="lg:col-span-2">
      <H id="home-feedback" right={<Link href="/reputation/insights" className="inline-flex min-h-11 items-center gap-1 text-[13px] font-semibold text-accent-ink hover:underline sm:min-h-9">What customers are saying<ArrowRight className="h-3.5 w-3.5" aria-hidden /></Link>}>What customers say</H>
      {loading || !o ? <Skeleton className="mt-3 h-48" /> : total === 0 ? <p className="mt-3 text-[14px] text-muted">Reviews will show here once customers start leaving them.</p> : (
        <div className="mt-3 grid gap-5 md:grid-cols-2">
          <div className="min-w-0">
            <ul className="space-y-1.5" aria-label="How many reviews gave each rating">
              {[5, 4, 3, 2, 1].map((n) => {
                const c = dist[String(n)] ?? 0;
                return (
                  <li key={n} className="grid grid-cols-[2rem_minmax(0,1fr)_2rem] items-center gap-2 text-[13px]">
                    <span className="num text-ink-700">{n} ★</span>
                    <span aria-hidden className="h-2 overflow-hidden rounded-full bg-surface-3"><span className="block h-full rounded-full bg-accent" style={{ width: `${(c / peak) * 100}%` }} /></span>
                    <span className="num text-right font-medium">{c}</span>
                  </li>
                );
              })}
            </ul>
            {topics.length > 0 && (
              <div className="mt-4">
                <p className="mb-1.5 text-[13px] font-medium text-muted">Often mentioned</p>
                <ul className="flex flex-wrap gap-1.5">
                  {topics.map((t) => { const good = t.positive >= t.negative; return (
                    <li key={t.topic} className={clsx("inline-flex min-h-8 items-center gap-1.5 rounded-full px-3 text-[13px] font-medium", good ? "bg-pos-tint text-pos" : "bg-neg-tint text-neg")}>{t.label}<span className="num text-xs opacity-80">{t.mentions}<span className="sr-only"> mentions, mostly {good ? "positive" : "negative"}</span></span></li>
                  ); })}
                </ul>
              </div>
            )}
          </div>
          <div className="min-w-0">
            <p className="mb-1 text-[13px] font-medium text-muted">Latest reviews</p>
            {!recent ? <Skeleton className="h-32" /> : recent.length === 0 ? <p className="text-[14px] text-muted">No reviews to show.</p> : (
              <ul className="divide-y divide-ink-100">
                {recent.slice(0, 3).map((v) => (
                  <li key={v.id}>
                    <Link href={`/gbp/reviews/${v.id}`} className="block py-2.5 first:pt-1.5">
                      <div className="flex items-center justify-between gap-2"><Stars rating={v.rating} size={13} /><span className="text-xs text-muted">{timeAgo(v.review_created_at)}</span></div>
                      <p className="mt-1 line-clamp-2 text-[14px] leading-5">{v.text ?? <span className="text-muted">Rating only, no comment</span>}</p>
                      <p className="mt-0.5 text-xs text-muted">{v.reviewer_name ?? "Google user"}{v.reply_state === "none" ? " · Needs a reply" : ""}</p>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
            <Link href="/gbp/reviews" className="mt-1 inline-flex min-h-11 items-center gap-1 text-[13px] font-semibold text-accent-ink hover:underline sm:min-h-9"><MessageSquare className="h-3.5 w-3.5" aria-hidden />See all reviews</Link>
          </div>
        </div>
      )}
    </Card>
  );
}
