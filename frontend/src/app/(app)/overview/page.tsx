"use client";
import { useMemo, useState } from "react";
import { CustomerActivity, CustomerFeedback, HomeHeader, Metrics, ReviewGrowth, ThingsToDo } from "@/components/home/sections";
import { AiReply, CardToReview } from "@/components/dashboard/HowItWorks";
import { GettingStarted } from "@/components/overview/GettingStarted";
import { Alert } from "@/components/ui/Card";
import type { Activity, TasksResponse } from "@/lib/agent";
import { useAuth } from "@/lib/auth";
import { buildTodos, previousRange, type Days } from "@/lib/dashboard";
import { fmtNum } from "@/lib/format";
import { useLocationScope } from "@/lib/location-scope";
import type { GoogleMetrics } from "@/lib/seo";
import type { GoogleConnection, Insights, Location, Overview, Review } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

const isoDay = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
function rangeFor(days: Days) {
  const to = new Date(), from = new Date();
  from.setDate(to.getDate() - (days - 1));
  return { from: isoDay(from), to: isoDay(to) };
}

/**
 * Home: "how is my business doing?" in five short blocks, in the order an owner cares about: the few numbers that matter, review growth, what to do next, what customers do with
 * the card, and what they say. Detail lives elsewhere (Results, Reviews, Visibility). Every number comes from the existing APIs and anything without data says so; loading this page
 * never calls Google (Google's figures are the ones FlowQR's daily job stored).
 */
export default function Home() {
  const { me, tenant } = useAuth();
  const [days, setDays] = useState<Days>(30);
  const { locationId } = useLocationScope();
  const loc = locationId ?? "";
  const range = useMemo(() => rangeFor(days), [days]);
  const before = useMemo(() => previousRange(range.from, days), [range.from, days]);

  const ov = useFetch<Overview>("/analytics/overview", { from: range.from, to: range.to, location_id: loc });
  const prevOv = useFetch<Overview>("/analytics/overview", { from: before.from, to: before.to, location_id: loc });
  const ins = useFetch<Insights>("/analytics/insights", { from: range.from, to: range.to, location_id: loc });
  const gm = useFetch<GoogleMetrics>("/analytics/google-metrics", { from: range.from, to: range.to, location_id: loc });
  const locs = useFetch<Location[]>("/locations");
  const google = useFetch<{ configured: boolean; connections: GoogleConnection[] }>("/google/status");
  const waiting = useFetch<{ total: number; items: Review[] }>("/reviews", { reply_state: "none", location_id: loc, limit: 20 });
  const failed = useFetch<{ total: number; items: Review[] }>("/reviews", { reply_state: "failed", location_id: loc, limit: 5 });
  const recent = useFetch<{ total: number; items: Review[] }>("/reviews", { location_id: loc, limit: 5 });
  const plan = useFetch<TasksResponse>("/agent/tasks", { scope: "today" });
  const activity = useFetch<Activity>("/agent/activity");

  const o = ov.data, p = prevOv.data;
  const connections = google.data?.connections ?? [];
  const todos = useMemo(() => buildTodos({
    overview: o, tasks: plan.data?.tasks ?? [], pendingApprovals: activity.data?.pending_approvals ?? 0, failedReplies: failed.data?.total ?? 0,
    sensitiveWaiting: waiting.data?.items.filter((r) => r.sensitive_reasons.length).length ?? 0, locations: locs.data ?? [], connections, googleConfigured: google.data?.configured,
  }), [o, plan.data, activity.data, failed.data, waiting.data, locs.data, connections, google.data?.configured]);

  const isNew = !!o && o.cards.length === 0 && o.reviews.total_synced === 0 && o.engagement.scans === 0;
  const loading = ov.loading && !o;
  const nLocs = locs.data?.filter((l) => l.is_active).length ?? 0;
  const here = loc ? locs.data?.find((l) => l.id === loc)?.name : null;
  const where = here ?? (nLocs ? `${nLocs} ${nLocs === 1 ? "location" : "locations"}` : "No location yet");
  const awaiting = o?.reviews.awaiting_reply ?? 0;

  return (
    <>
      <HomeHeader business={tenant?.name ?? (me?.user.full_name ? `${me.user.full_name.split(" ")[0]}` : "Your business")} where={`${where}${o ? ` · ${awaiting ? `${fmtNum(awaiting)} ${awaiting === 1 ? "review needs" : "reviews need"} a reply` : "every review answered"}` : ""}`} days={days} onDays={setDays} />

      {ov.error && <div className="mb-4"><Alert tone="error" title="We couldn't load your numbers" action={<button type="button" onClick={() => { void ov.reload(); void prevOv.reload(); }} className="inline-flex min-h-11 items-center rounded-full bg-surface px-4 text-sm font-semibold text-ink">Try again</button>}>{ov.error}</Alert></div>}

      {o && <GettingStarted />}

      {o && isNew ? (
        <section aria-label="How FlowQR works" className="panel grid gap-8 p-4 sm:p-6"><CardToReview /><div className="border-t border-line pt-6"><AiReply /></div></section>
      ) : (
        <div className="space-y-4">
          <Metrics o={o} prev={p} gm={gm.data} days={days} loading={loading} />
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <ReviewGrowth o={o} prev={p} days={days} loading={loading || (prevOv.loading && !p)} />
            <ThingsToDo todos={todos} loading={!o && !ov.error && !plan.data} />
            <CustomerActivity o={o} loading={loading} />
            <CustomerFeedback o={o} ins={ins.data} recent={recent.data?.items ?? null} loading={loading} />
          </div>
        </div>
      )}
    </>
  );
}
