"use client";
import { WebsiteBanner } from "@/components/website/WebsiteBanner";
import { ChevronDown } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { DoThisWeek, FunnelStrip, Numbers, ScoreCard, WeeklyReviews, type FunnelStep, type GrowthScore } from "@/components/home/v2";
import { GoogleActions, LatestReviews, RatingMix } from "@/components/home/v3";
import { MarketingBand } from "@/components/home/Marketing";
import { GettingStarted } from "@/components/overview/GettingStarted";
import { Alert } from "@/components/ui/Card";
import type { Activity, TasksResponse } from "@/lib/agent";
import { useAuth } from "@/lib/auth";
import { buildTodos, previousRange, type Days } from "@/lib/dashboard";
import { useLocationScope } from "@/lib/location-scope";
import type { GoogleMetrics } from "@/lib/seo";
import type { GoogleConnection, Location, Overview, Review } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

/** One block of the page, revealed blur-to-sharp in reading order (the delay is in ms). */
const Rv = ({ d, className, children }: { d: number; className?: string; children: ReactNode }) => <div className={`rv lg:[&>*]:h-full ${className ?? ""}`} style={{ ["--d" as string]: `${d}ms` }}>{children}</div>;
const isoDay = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
function rangeFor(days: Days) {
  const to = new Date(), from = new Date();
  from.setDate(to.getDate() - (days - 1));
  return { from: isoDay(from), to: isoDay(to) };
}

/** "Good morning, Geeta": the greeting follows the hour on this device, and uses only the first name. It starts as a plain "Hello" so the server and the browser agree on the first paint. */
function useGreeting(fullName: string | null | undefined) {
  const [g, setG] = useState({ hello: "Hello", date: "" });
  useEffect(() => {
    const now = new Date(), h = now.getHours();
    setG({ hello: h < 5 ? "Hello" : h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : h < 22 ? "Good evening" : "Hello", date: now.toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" }) });
  }, []);
  const first = (fullName ?? "").trim().split(/\s+/)[0] ?? "";
  const name = first ? first[0].toUpperCase() + first.slice(1) : "";
  return { title: name ? `${g.hello}, ${name}` : g.hello, date: g.date };
}

/** The secondary charts are folded away by default (Home answers two questions first); the choice is remembered on this device. */
const MORE_KEY = "flowqr:home-more";

/**
 * Home answers "am I getting better, and what do I do this week?" and nothing else up front: the Growth score and its parts, the three moves for the week, four numbers, the newest
 * reviews and the weekly trend. Setup shows only while there is setup left. What customers do on Google, how ratings split, the steps from card to Google and Google marketing sit
 * behind one "More insight" fold. Every figure is drawn from numbers the API returned (docs/DESIGN.md §4).
 */
export default function Home() {
  const { tenant, me } = useAuth();
  const greeting = useGreeting(me?.user.full_name);
  const [days, setDays] = useState<Days>(30);
  const [more, setMore] = useState(false);
  useEffect(() => { try { setMore(localStorage.getItem(MORE_KEY) === "1"); } catch { /* private mode */ } }, []);
  const toggleMore = () => setMore((m) => { try { localStorage.setItem(MORE_KEY, m ? "0" : "1"); } catch { /* private mode */ } return !m; });
  const { locationId } = useLocationScope();
  const loc = locationId ?? "";
  const range = useMemo(() => rangeFor(days), [days]);
  const before = useMemo(() => previousRange(range.from, days), [range.from, days]);

  const ov = useFetch<Overview>("/analytics/overview", { from: range.from, to: range.to, location_id: loc });
  const prevOv = useFetch<Overview>("/analytics/overview", { from: before.from, to: before.to, location_id: loc });
  const score = useFetch<GrowthScore>("/analytics/growth-score", { location_id: loc });
  const funnel = useFetch<{ funnel: FunnelStep[] }>("/review-growth/analytics", { from: range.from, to: range.to, location_id: loc });
  const locs = useFetch<Location[]>("/locations");
  const google = useFetch<{ configured: boolean; connections: GoogleConnection[] }>("/google/status");
  const waiting = useFetch<{ total: number; items: Review[] }>("/reviews", { reply_state: "none", location_id: loc, limit: 20 });
  const failed = useFetch<{ total: number; items: Review[] }>("/reviews", { reply_state: "failed", location_id: loc, limit: 5 });
  const latest = useFetch<{ total: number; items: Review[] }>("/reviews", { location_id: loc, limit: 4 });
  const gm = useFetch<GoogleMetrics>("/analytics/google-metrics", { from: range.from, to: range.to, location_id: loc });
  const plan = useFetch<TasksResponse>("/agent/tasks", { scope: "today" });
  const activity = useFetch<Activity>("/agent/activity");

  const o = ov.data, p = prevOv.data;
  const connections = google.data?.connections ?? [];
  const todos = useMemo(() => buildTodos({
    overview: o, tasks: plan.data?.tasks ?? [], pendingApprovals: activity.data?.pending_approvals ?? 0, failedReplies: failed.data?.total ?? 0,
    sensitiveWaiting: waiting.data?.items.filter((r) => r.sensitive_reasons.length).length ?? 0, locations: locs.data ?? [], connections, googleConfigured: google.data?.configured,
  }), [o, plan.data, activity.data, failed.data, waiting.data, locs.data, connections, google.data?.configured]);
  const weekly = useMemo(() => {
    const s = o?.reviews.series ?? [], out: number[] = [];
    for (let i = 0; i < s.length; i += 7) out.push(s.slice(i, i + 7).reduce((a, x) => a + (Number(x.count) || 0), 0));
    return out;
  }, [o]);
  const goal = score.data?.parts.find((x) => x.key === "reviews")?.goal ?? null;
  const hasCard = (o?.cards.length ?? 0) > 0;
  const loading = ov.loading && !o;

  return (
    <>
      <WebsiteBanner />
      <div className="mb-4 sm:mb-5">
        <h1 className="text-[30px] font-bold leading-[36px] tracking-[-.015em] text-ink sm:text-[32px] sm:leading-10 lg:text-[34px]"><span className="sr-only">Home. </span>{greeting.title}</h1>
        <p className="mt-1 min-h-[22px] text-[15px] leading-[22px] text-muted sm:text-base">{greeting.date}{greeting.date && tenant?.name ? " · " : ""}{tenant?.name}</p>
      </div>
      {ov.error && <div className="mb-4"><Alert tone="error" title="We couldn't load your numbers" action={<button type="button" onClick={() => { void ov.reload(); void prevOv.reload(); }} className="inline-flex min-h-11 items-center rounded-[10px] bg-surface px-4 text-sm font-semibold text-ink">Try again</button>}>{ov.error}</Alert></div>}
      {/* the order on a phone is the order of the questions: how am I doing, what do I do, the numbers, the newest reviews, the trend. From a laptop up, the score and the moves share a row. */}
      <div data-flat className="grid grid-cols-1 gap-3 lg:grid-cols-12 lg:items-stretch">
        <Rv d={0} className="lg:order-1 lg:col-span-8"><ScoreCard g={score.data} loading={score.loading && !score.data} days={days} onDays={setDays} /></Rv>
        <Rv d={70} className="lg:order-2 lg:col-span-4"><DoThisWeek todos={todos} hasCard={hasCard} loading={!o && !ov.error} g={score.data} /></Rv>
        {o && <div className="empty:hidden lg:order-3 lg:col-span-12 [&>section]:mb-0"><GettingStarted /></div>}
        <Rv d={120} className="lg:order-4 lg:col-span-12"><Numbers o={o} prev={p} weekly={weekly} loading={loading} days={days} /></Rv>
        <Rv d={160} className="lg:order-6 lg:col-span-5"><LatestReviews items={latest.data?.items.slice(0, 3) ?? null} total={latest.data?.total ?? 0} loading={latest.loading && !latest.data} /></Rv>
        {/* the trend, and from a laptop up the steps from card to Google under it (on a phone those steps are in "More insight") */}
        <div className="space-y-3 lg:order-5 lg:col-span-7">
          <Rv d={200}><WeeklyReviews o={o} prev={p} days={days} goal={goal} loading={loading || (prevOv.loading && !p)} /></Rv>
          <Rv d={240} className="hidden lg:block"><FunnelStrip steps={funnel.data?.funnel ?? null} hasCard={hasCard} loading={funnel.loading && !funnel.data} /></Rv>
        </div>
        <div className="lg:order-7 lg:col-span-12">
          <button type="button" aria-expanded={more} aria-controls="home-more" onClick={toggleMore}
            className="mx-auto flex min-h-11 items-center gap-1.5 rounded-full px-4 text-[14px] font-semibold text-ink-700 ring-1 ring-line transition-colors hover:bg-surface hover:text-ink">
            {more ? "Show less" : "More insight"}<ChevronDown className={`h-4 w-4 transition-transform duration-200 ${more ? "rotate-180" : ""}`} aria-hidden />
          </button>
          {more && (
            <div id="home-more" className="fq-enter mt-3 grid grid-cols-1 gap-3 lg:grid-cols-12">
              <div className="lg:col-span-12"><MarketingBand /></div>
              <div className="lg:col-span-7"><GoogleActions m={gm.data} loading={gm.loading} error={gm.error} /></div>
              <div className="space-y-3 lg:col-span-5"><RatingMix o={o} loading={loading} /><div className="lg:hidden"><FunnelStrip steps={funnel.data?.funnel ?? null} hasCard={hasCard} loading={funnel.loading && !funnel.data} /></div></div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
