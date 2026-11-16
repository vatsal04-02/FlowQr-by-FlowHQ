"use client";
import { useMemo, useState } from "react";
import { DoThisWeek, FunnelStrip, Numbers, ScoreCard, WeeklyReviews, type FunnelStep, type GrowthScore } from "@/components/home/v2";
import { GettingStarted } from "@/components/overview/GettingStarted";
import { Alert } from "@/components/ui/Card";
import type { Activity, TasksResponse } from "@/lib/agent";
import { useAuth } from "@/lib/auth";
import { buildTodos, previousRange, type Days } from "@/lib/dashboard";
import { useLocationScope } from "@/lib/location-scope";
import type { GoogleConnection, Location, Overview, Review } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

const isoDay = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
function rangeFor(days: Days) {
  const to = new Date(), from = new Date();
  from.setDate(to.getDate() - (days - 1));
  return { from: isoDay(from), to: isoDay(to) };
}

/**
 * Home answers "am I getting better, and what do I do this week?" with pictures first: the Growth score ring and its five parts, four numbers each with its own small chart,
 * reviews by week against the goal, three moves for the week (never empty), and the four steps from card to Google. Detail lives in Reviews, SEO & Google and Growth.
 */
export default function Home() {
  const { tenant } = useAuth();
  const [days, setDays] = useState<Days>(30);
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
      <h1 className="sr-only">Home, {tenant?.name}</h1>
      {ov.error && <div className="mb-4"><Alert tone="error" title="We couldn't load your numbers" action={<button type="button" onClick={() => { void ov.reload(); void prevOv.reload(); }} className="inline-flex min-h-11 items-center rounded-[10px] bg-surface px-4 text-sm font-semibold text-ink">Try again</button>}>{ov.error}</Alert></div>}
      <div className="grid gap-3 lg:grid-cols-12 lg:gap-4">
        <div className="space-y-3 lg:col-span-8 lg:space-y-4">
          <ScoreCard g={score.data} loading={score.loading && !score.data} days={days} onDays={setDays} />
          <Numbers o={o} prev={p} weekly={weekly} loading={loading} />
          <div className="lg:hidden"><DoThisWeek todos={todos} hasCard={hasCard} loading={!o && !ov.error} /></div>
          <WeeklyReviews o={o} prev={p} days={days} goal={goal} loading={loading || (prevOv.loading && !p)} />
        </div>
        <div className="space-y-3 lg:col-span-4 lg:space-y-4">
          <div className="hidden lg:block"><DoThisWeek todos={todos} hasCard={hasCard} loading={!o && !ov.error} /></div>
          <FunnelStrip steps={funnel.data?.funnel ?? null} hasCard={hasCard} loading={funnel.loading && !funnel.data} />
          {o && <GettingStarted />}
        </div>
      </div>
    </>
  );
}
