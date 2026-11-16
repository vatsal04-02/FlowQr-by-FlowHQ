"use client";
import { useEffect, useMemo, useState } from "react";
import { api, errorMessage } from "./api";
import { previousRange } from "./dashboard";
import { useGbp } from "./use-gbp";

/** What Google itself reports about the profile, summed over the owner's connected locations. */
export interface GoogleTotals { interactions: number; views: number; calls: number; website: number; directions: number }
export interface GooglePoint { date: string; interactions: number; calls: number; website: number; prev_interactions: number }
export type GoogleActivity =
  | { state: "idle" } // not asked for yet: nothing has been requested from Google
  | { state: "loading" }
  | { state: "disconnected"; reason: "not-connected" | "no-locations" }
  | { state: "error"; message: string }
  | { state: "ready"; current: GoogleTotals; previous: GoogleTotals; series: GooglePoint[]; fetchedAt: Date; partialErrors: number;
      /** Google reports a few days late: only days up to this date are counted, in both periods, so a comparison is like for like. */
      reportedDays: number; reportedThrough: string | null };

type Resp = { series: Record<string, { date: string; value: number }[]> };
const zero = (): GoogleTotals => ({ interactions: 0, views: 0, calls: 0, website: 0, directions: 0 });
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/**
 * Live Google numbers for the two Google charts. Only runs while `enabled`. One call per location covers both the chosen period and the one before it (Google's data is daily), so every comparison is real
 * data and costs no extra requests. "Interactions" is every customer action Google reports (calls, website clicks, directions,
 * bookings, messages); "views" is how often the profile was shown in Search and Maps.
 */
export function useGoogleActivity(range: { from: string; to: string }, days: number, locationId: string, enabled: boolean): GoogleActivity {
  const g = useGbp();
  const [result, setResult] = useState<GoogleActivity>({ state: "idle" });
  const ids = useMemo(() => g.selected.filter((l) => !locationId || l.location_id === locationId).slice(0, 10).map((l) => l.id), [g.selected, locationId]);
  const key = ids.join(",");

  useEffect(() => {
    // These are live calls to Google, so they only happen once the owner opens a Google chart, never just because the dashboard loaded.
    if (!enabled) { setResult({ state: "idle" }); return; }
    if (g.loading || g.locsLoading) { setResult({ state: "loading" }); return; }
    if (!g.conn) { setResult({ state: "disconnected", reason: "not-connected" }); return; }
    if (ids.length === 0) { setResult({ state: "disconnected", reason: "no-locations" }); return; }
    let live = true;
    setResult({ state: "loading" });
    const prev = previousRange(range.from, days);
    void Promise.allSettled(ids.map((id) => api<Resp>(`/gbp/${id}/performance`, { params: { from: prev.from, to: range.to } }))).then((rs) => {
      if (!live) return;
      const ok = rs.filter((r): r is PromiseFulfilledResult<Resp> => r.status === "fulfilled").map((r) => r.value);
      if (ok.length === 0) {
        const first = rs.find((r): r is PromiseRejectedResult => r.status === "rejected");
        setResult({ state: "error", message: first ? errorMessage(first.reason) : "Google didn't answer." });
        return;
      }
      // per-day sums across locations
      const perDay = new Map<string, { interactions: number; views: number; calls: number; website: number; directions: number }>();
      for (const resp of ok) for (const [metric, pts] of Object.entries(resp.series)) for (const p of pts) {
        const d = perDay.get(p.date) ?? { interactions: 0, views: 0, calls: 0, website: 0, directions: 0 };
        if (metric.startsWith("BUSINESS_IMPRESSIONS")) d.views += p.value; else d.interactions += p.value;
        if (metric === "CALL_CLICKS") d.calls += p.value;
        if (metric === "WEBSITE_CLICKS") d.website += p.value;
        if (metric === "BUSINESS_DIRECTION_REQUESTS") d.directions += p.value;
        perDay.set(p.date, d);
      }
      const reported = [...perDay.keys()].sort().pop() ?? null;
      const current = zero(), previous = zero(), series: GooglePoint[] = [];
      const start = new Date(range.from + "T00:00:00");
      for (let i = 0; i < days; i++) {
        const day = new Date(start); day.setDate(start.getDate() + i);
        if (reported === null || iso(day) > reported) continue; // not reported by Google yet: leave out, never show as zero
        const before = new Date(day); before.setDate(day.getDate() - days);
        const c = perDay.get(iso(day)), b = perDay.get(iso(before));
        if (c) for (const k of Object.keys(current) as (keyof GoogleTotals)[]) current[k] += c[k];
        if (b) for (const k of Object.keys(previous) as (keyof GoogleTotals)[]) previous[k] += b[k];
        series.push({ date: iso(day), interactions: c?.interactions ?? 0, calls: c?.calls ?? 0, website: c?.website ?? 0, prev_interactions: b?.interactions ?? 0 });
      }
      setResult({ state: "ready", current, previous, series, fetchedAt: new Date(), partialErrors: rs.length - ok.length, reportedDays: series.length, reportedThrough: reported });
    });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, g.loading, g.locsLoading, !!g.conn, key, range.from, range.to, days]);

  return result;
}
