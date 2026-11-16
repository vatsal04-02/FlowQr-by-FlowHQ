"use client";
import { GettingStarted } from "@/components/overview/GettingStarted";
import { useMemo, useState, type CSSProperties } from "react";
import { HealthCard } from "@/components/agent/HealthCard";
import { Growth } from "@/components/dashboard/Growth";
import { AiReply, CardToReview } from "@/components/dashboard/HowItWorks";
import { CompetitorCard, GoogleBand, ProfileCard, RatingTrend, VisibilityCard } from "@/components/overview/summary";
import { Attention, Funnel, GoalCard, KeyTiles, Mentions, RatingCard, RecentActivity, ReviewTrend, Tile } from "@/components/overview/widgets";
import { Alert, PageHeader } from "@/components/ui/Card";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { Segmented } from "@/components/ui/kit";
import type { Activity, ReportSummary, TasksResponse } from "@/lib/agent";
import { useAuth } from "@/lib/auth";
import { useLocationScope } from "@/lib/location-scope";
import { buildTodos, DAY_OPTIONS, googleStored, greeting, previousRange, type Days } from "@/lib/dashboard";
import { fmtNum, timeAgo } from "@/lib/format";
import type { Card, GoogleConnection, Insights, Location, Overview, Review } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

const isoDay = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
function rangeFor(days: Days) {
  const to = new Date(), from = new Date();
  from.setDate(to.getDate() - (days - 1));
  return { from: isoDay(from), to: isoDay(to) };
}

/**
 * Workspace › Overview: the central business summary. Reputation first (rating, reviews, replies, growth), then what Google reports, local visibility, profile health,
 * competitors and what to do next. Date range and location filters apply to the whole page (the location comes from the app-wide picker).
 * (Originally PRD §6.1: "how is my Google profile doing?" on one screen.) Every number comes from the
 * existing APIs; a period is compared with the one before it by fetching that period for real, and anything without data says so
 * instead of showing a zero or a guess. Loading this page never calls Google: Google's numbers are the ones FlowQR's daily job stored.
 */
export default function Dashboard() {
  const { me, tenant, isAdmin, refresh } = useAuth();
  const toast = useToast();
  const [days, setDays] = useState<Days>(30);
  // the one location filter for the whole app (top of the page); "" = all locations
  const { locationId } = useLocationScope();
  const loc = locationId ?? "";
  const range = useMemo(() => rangeFor(days), [days]);
  const before = useMemo(() => previousRange(range.from, days), [range.from, days]);

  const ov = useFetch<Overview>("/analytics/overview", { from: range.from, to: range.to, location_id: loc });
  const prevOv = useFetch<Overview>("/analytics/overview", { from: before.from, to: before.to, location_id: loc });
  const ins = useFetch<Insights>("/analytics/insights", { from: range.from, to: range.to, location_id: loc });
  const locs = useFetch<Location[]>("/locations");
  const cards = useFetch<Card[]>("/cards");
  const google = useFetch<{ configured: boolean; connections: GoogleConnection[] }>("/google/status");
  const waiting = useFetch<{ total: number; items: Review[] }>("/reviews", { reply_state: "none", location_id: loc, limit: 20 });
  const failed = useFetch<{ total: number; items: Review[] }>("/reviews", { reply_state: "failed", location_id: loc, limit: 5 });
  const recent = useFetch<{ total: number; items: Review[] }>("/reviews", { location_id: loc, limit: 5 });
  const plan = useFetch<TasksResponse>("/agent/tasks", { scope: "today" });
  const activity = useFetch<Activity>("/agent/activity");
  const summary = useFetch<ReportSummary>("/reports/summary", { location_id: loc || undefined });

  const o = ov.data, p = prevOv.data;
  const connections = google.data?.connections ?? [];
  const googleConnected = connections.some((c) => c.status === "active");
  const googleNow = useMemo(() => googleStored(summary.data, summary.error, googleConnected, google.loading && !google.data), [summary.data, summary.error, googleConnected, google.loading, google.data]);

  const todos = useMemo(() => buildTodos({
    overview: o, tasks: plan.data?.tasks ?? [], pendingApprovals: activity.data?.pending_approvals ?? 0, failedReplies: failed.data?.total ?? 0,
    sensitiveWaiting: waiting.data?.items.filter((r) => r.sensitive_reasons.length).length ?? 0, locations: locs.data ?? [], connections, googleConfigured: google.data?.configured,
  }), [o, plan.data, activity.data, failed.data, waiting.data, locs.data, connections, google.data?.configured]);

  const isNew = !!o && o.cards.length === 0 && o.reviews.total_synced === 0 && o.engagement.scans === 0;
  const lastSync = (o?.sync ?? []).map((s) => s.last_synced_at).filter(Boolean).sort().pop();
  const syncBad = o?.sync.some((s) => s.status && s.status !== "ok" && s.status !== "running");
  const first = me?.user.full_name?.trim().split(/\s+/)[0];
  const nLocs = locs.data?.filter((l) => l.is_active).length ?? 0;
  const here = loc ? locs.data?.find((l) => l.id === loc)?.name : null;
  const awaiting = o?.reviews.awaiting_reply ?? 0;
  const loading = ov.loading && !o;
  const noPlanYet = !!plan.data && plan.data.tasks.length === 0 && !activity.data?.last_plan_date;

  const where = here ?? (nLocs ? `${nLocs} ${nLocs === 1 ? "location" : "locations"}` : tenant?.name);
  const replies = o ? (awaiting ? `${fmtNum(awaiting)} ${awaiting === 1 ? "review needs" : "reviews need"} a reply` : "Every review answered") : null;
  const subtitle = (
    <span className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5">
      <span>{[where, replies].filter(Boolean).join(" · ")}</span>
      {google.data && (googleConnected
        ? <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${syncBad ? "bg-neg-tint text-neg" : "bg-pos-tint text-pos"}`}>{syncBad ? "Google sync needs a look" : `Google updated ${timeAgo(lastSync)}`}</span>
        : <span className="rounded-full bg-surface px-2.5 py-0.5 text-xs font-medium text-muted shadow-pill">Google not connected</span>)}
    </span>
  );

  return (
    <>
      <PageHeader title={`${greeting()}${first ? `, ${first}` : ""}`} subtitle={subtitle}
        actions={<>
          <Segmented tone="solid" label="Show the last" value={String(days)} options={DAY_OPTIONS.map(([d, l]) => [String(d), l] as const)} onChange={(v) => setDays(Number(v) as Days)} />
        </>} />

      {ov.error && <div className="mb-5"><Alert tone="error" title="We couldn't load your numbers" action={<button type="button" onClick={() => { void ov.reload(); void prevOv.reload(); }} className="inline-flex min-h-11 items-center rounded-full bg-white px-4 text-sm font-semibold text-ink hover:bg-ink-50">Try again</button>}>{ov.error}</Alert></div>}

      {o && <GettingStarted />}  {/* one checklist, computed by the server from what exists; it hides itself when the essentials are done */}

      {o && isNew ? (
        <FirstRun />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:gap-5 lg:grid-flow-row-dense lg:grid-cols-2 xl:grid-cols-3">
          {/* 1. reputation: rating, total reviews, new reviews, pending replies, review growth */}
          <RatingCard o={o} prev={p} locs={locs.data ?? []} days={days} loading={loading} googleConnected={googleConnected} />
          <KeyTiles o={o} prev={p} google={googleNow} days={days} loading={loading} />
          <ReviewTrend o={o} days={days} loading={loading} googleConnected={googleConnected} />
          {/* 2. what Google reports about the profile (explicit unavailable state until Google shares it) and local search visibility */}
          <GoogleBand range={range} loc={loc} days={days} />
          <VisibilityCard loc={loc} />
          {/* 3. trends over time */}
          <Growth className="rv lg:col-span-2" style={{ "--d": "360ms" } as CSSProperties} o={o} prev={p} range={range} loc={loc} days={days}
            loading={loading || (prevOv.loading && !p)} error={ov.error} googleConnected={googleConnected} />
          <ProfileCard loc={loc} />
          <RatingTrend o={o} loading={loading} days={days} />
          <CompetitorCard loc={loc} />
          <GoalCard i={8} goal={tenant?.review_goal} canEdit={isAdmin} onSave={async (g) => {
            try { await api("/tenant", { method: "PATCH", body: { review_goal: g } }); await refresh(); toast(g ? "Goal saved." : "Goal cleared."); }
            catch (e) { toast(errorMessage(e), "error"); }
          }} />
          {/* 4. what to do next */}
          <Attention i={9} todos={todos} loading={!o && !ov.error && !plan.data} noPlanYet={noPlanYet} tasksError={plan.error} />
          <RecentActivity i={10} items={recent.data?.items ?? null} loading={recent.loading} error={recent.error} />
          <Mentions i={11} ins={ins.data} loading={ins.loading} error={ins.error} />
          <Funnel i={12} o={o} loading={loading} />
          <Tile i={13} label="How your business is doing" className="lg:col-span-2 xl:col-span-3"><HealthCard compact variant="strip" /></Tile>
        </div>
      )}
    </>
  );
}

/** First-run experience: the checklist above is the real one (from the server); this adds two labelled pictures of how FlowQR works. */
function FirstRun() {
  return (
    <section aria-label="How FlowQR works" className="panel rv grid gap-8 p-5 sm:p-6"><CardToReview /><div className="border-t border-line pt-6"><AiReply /></div></section>
  );
}
