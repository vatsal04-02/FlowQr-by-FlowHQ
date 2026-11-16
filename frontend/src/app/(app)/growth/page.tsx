"use client";
import { Download, Image as ImageIcon } from "lucide-react";
import { useMemo, useState } from "react";
import { Ring } from "@/components/charts/Bars";
import { SendLink } from "@/components/growth/SendLink";
import { DoThisWeek, type GrowthScore } from "@/components/home/v2";
import { Card, SeeAll, Title } from "@/components/seo/visuals";
import { Button, LinkButton } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Card";
import { useToast } from "@/components/ui/Toast";
import { api, apiFile, errorMessage } from "@/lib/api";
import { Sheet } from "@/components/ui/Sheet";
import { useAuth } from "@/lib/auth";
import { fmtNum } from "@/lib/format";
import { useLocationScope } from "@/lib/location-scope";
import type { Overview } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

interface Campaign { id: string; name: string; status: string; url: string; location_name: string | null }
interface Funnel { funnel: { key: string; label: string; count: number }[] }
const STEPS: [string, string][] = [["scans", "Scans"], ["feedback_submitted", "Feedback"], ["drafts_approved", "Approved"], ["google_redirects", "To Google"]];
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

function saveBlob(blob: Blob, name: string) { const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000); }

/** A shareable picture of the real rating (from the overview), drawn on a canvas. Shared through the phone's share sheet when it accepts files, otherwise downloaded. */
async function ratingImage(business: string, rating: number, reviews: number): Promise<Blob> {
  const c = document.createElement("canvas"); c.width = 1080; c.height = 1080;
  const g = c.getContext("2d")!;
  g.fillStyle = "#FFFFFF"; g.fillRect(0, 0, 1080, 1080);
  g.fillStyle = "#16130F"; g.textAlign = "center";
  g.font = "600 220px Inter, system-ui, sans-serif"; g.fillText(rating.toFixed(1), 540, 520);
  g.fillStyle = "#D9A314"; g.font = "120px system-ui, sans-serif"; g.fillText("★★★★★".slice(0, Math.round(rating)), 540, 680);
  g.fillStyle = "#6B645B"; g.font = "500 48px Inter, system-ui, sans-serif"; g.fillText(`from ${reviews.toLocaleString("en-IN")} Google reviews`, 540, 790);
  g.fillStyle = "#16130F"; g.font = "600 56px Inter, system-ui, sans-serif"; g.fillText(business.slice(0, 32), 540, 240);
  return new Promise((r) => c.toBlob((b) => r(b!), "image/png"));
}

/** Growth › Goals: this month against the goal (ring), the link to send right now, the four steps from card to Google, the week's moves and the wins to share. */
export default function GoalsPage() {
  const { tenant, isAdmin, refresh } = useAuth();
  const [goalOpen, setGoalOpen] = useState(false);
  const [goalVal, setGoalVal] = useState("");
  const toast = useToast();
  const { locationId } = useLocationScope();
  const loc = locationId ?? "";
  const now = new Date();
  const first = iso(new Date(now.getFullYear(), now.getMonth(), 1)), today = iso(now);
  const score = useFetch<GrowthScore>("/analytics/growth-score", { location_id: loc });
  const funnel = useFetch<Funnel>("/review-growth/analytics", { from: first, to: today, location_id: loc });
  const camps = useFetch<Campaign[]>("/review-growth/campaigns");
  const ov = useFetch<Overview>("/analytics/overview", { from: first, to: today, location_id: loc });
  const [busy, setBusy] = useState<string | null>(null);
  const rv = score.data?.parts.find((p) => p.key === "reviews");
  const live = (camps.data ?? []).filter((c) => c.status === "active");
  const pick = useMemo(() => live.find((c) => !loc || c.location_name) ?? live[0], [live, loc]);
  const vals = STEPS.map(([k, l]) => [l, funnel.data?.funnel.find((s) => s.key === k)?.count ?? 0] as const);
  const top = Math.max(1, ...vals.map((v) => v[1]));
  const r = ov.data?.reviews;

  async function shareRating() {
    if (!r || r.average_rating_all_time === null) return;
    setBusy("img");
    try {
      const blob = await ratingImage(tenant?.name ?? "Our business", r.average_rating_all_time, r.total_synced);
      const file = new File([blob], "google-rating.png", { type: "image/png" });
      const nav = navigator as Navigator & { canShare?: (d: ShareData) => boolean; share?: (d: ShareData) => Promise<void> };
      if (nav.canShare?.({ files: [file] }) && nav.share) { try { await nav.share({ files: [file], title: tenant?.name ?? "" }); } catch { /* closed */ } }
      else saveBlob(blob, "google-rating.png");
    } finally { setBusy(null); }
  }
  async function saveGoal(v: number | null) {
    try { await api("/tenant", { method: "PATCH", body: { review_goal: v } }); await refresh(); await score.reload(); setGoalOpen(false); toast(v ? "Goal saved." : "Goal cleared."); }
    catch (e) { toast(errorMessage(e), "error"); }
  }
  async function monthPdf() {
    setBusy("pdf");
    try { const { blob } = await apiFile(`/reports/summary.pdf?${new URLSearchParams({ from: first, to: today, ...(loc ? { location_id: loc } : {}) })}`); saveBlob(blob, `flowqr-report-${first.slice(0, 7)}.pdf`); }
    catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(null); }
  }

  return (
    <>
      <h1 className="mb-4 text-[22px] font-semibold leading-7 sm:text-[26px]">Goals</h1>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-12 lg:gap-4">
        <Card label="This month" className="lg:col-span-7">
          <Title>This month</Title>
          {score.loading && !rv ? <Skeleton className="mt-3 h-36" /> : (
            <div className="mt-3 flex flex-wrap items-center gap-5">
              <Ring value={rv && rv.goal ? Math.min(100, ((rv.count ?? 0) / rv.goal) * 100) : null} size={120} stroke={11} label={`${rv?.count ?? 0} of ${rv?.goal ?? "–"} reviews this month`}>
                <span><b className="num block text-[30px] font-semibold leading-none">{rv?.count ?? "–"}</b><span className="num text-[12px] text-muted">of {rv?.goal ?? "–"}</span></span>
              </Ring>
              <div className="min-w-0 flex-1 space-y-1 text-[14px]">
                <p><b className="num text-[20px] font-semibold">{rv?.to_go ?? "–"}</b> <span className="text-muted">to go</span></p>
                <p><b className="num text-[20px] font-semibold">{rv?.days_left ?? "–"}</b> <span className="text-muted">days left</span></p>
                {isAdmin && <button type="button" onClick={() => { setGoalVal(String(rv?.goal ?? 10)); setGoalOpen(true); }} className="!min-h-0 text-[13px] text-muted underline underline-offset-2">{rv?.goal_set ? "Edit goal" : "Set goal"}</button>}
              </div>
              <div className="w-full sm:w-auto">{pick ? <SendLink url={pick.url} name={tenant?.name ?? pick.name} label="Send review link" variant="brand" size="md" className="w-full sm:w-auto" /> : <LinkButton href="/gbp/campaigns" variant="brand" className="w-full sm:w-auto">Create a campaign</LinkButton>}</div>
            </div>
          )}
        </Card>

        <Card label="From card to Google" className="lg:col-span-5">
          <Title right={<SeeAll href="/growth/funnel">By card</SeeAll>}>Card to Google<span className="sr-only">. A tap on To Google is not a review.</span></Title>
          {funnel.loading && !funnel.data ? <Skeleton className="mt-3 h-36" /> : (
            <ol className="mt-3 space-y-2.5">
              {vals.map(([l, v], i) => (
                <li key={l} className="grid grid-cols-[5.5rem_minmax(0,1fr)_2.5rem] items-center gap-2 text-[14px]">
                  <span className="text-ink-700">{l}</span>
                  <span aria-hidden className="h-3 overflow-hidden rounded-full bg-surface-3"><span className="fq-bar-x block h-full rounded-full bg-ink-solid" style={{ width: `${v ? Math.max(3, (v / top) * 100) : 0}%`, opacity: 1 - i * 0.15 }} /></span>
                  <b className="num text-right font-semibold">{fmtNum(v)}</b>
                </li>
              ))}
            </ol>
          )}
        </Card>


        <Card label="Share your wins" className="lg:col-span-5">
          <Title>Share your wins</Title>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <Button variant="secondary" loading={busy === "img"} disabled={!r || r.average_rating_all_time === null} onClick={() => void shareRating()} icon={<ImageIcon className="h-4 w-4" aria-hidden />}>Rating image</Button>
            <Button variant="secondary" loading={busy === "pdf"} onClick={() => void monthPdf()} icon={<Download className="h-4 w-4" aria-hidden />}>Month PDF</Button>
          </div>
        </Card>
        <div className="lg:col-span-7"><DoThisWeek todos={[]} hasCard={(ov.data?.cards.length ?? 0) > 0} loading={false} /></div>
      </div>
      <Sheet open={goalOpen} onClose={() => setGoalOpen(false)} title="Monthly review goal"
        footer={<>{rv?.goal_set && <Button variant="ghost" onClick={() => void saveGoal(null)}>Clear goal</Button>}<Button onClick={() => { const n = parseInt(goalVal, 10); if (n > 0) void saveGoal(n); }} disabled={!(parseInt(goalVal, 10) > 0)}>Save goal</Button></>}>
        <label htmlFor="goal" className="text-[13px] text-muted">New Google reviews per month</label>
        <input id="goal" type="number" min={1} max={100000} inputMode="numeric" value={goalVal} onChange={(e) => setGoalVal(e.target.value)} className="mt-1 min-h-11 w-full rounded-[12px] bg-surface-2 px-3 text-[16px] font-semibold" />
      </Sheet>
    </>
  );
}
