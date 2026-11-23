"use client";
import { ConnectGoogleEmptyState } from "@/components/settings/parts";
import { Crosshair, Pin, PinOff, Star } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Sparkline } from "@/components/charts/Sparkline";
import { Move, SourceTag, when } from "@/components/seo/parts";
import { DataTable } from "@/components/ui/DataTable";
import { Alert, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Panel } from "@/components/ui/kit";
import { fmtNum } from "@/lib/format";
import { useLocationScope } from "@/lib/location-scope";
import type { Competitor, Competitors } from "@/lib/seo";
import { useFetch } from "@/lib/use-api";

const rating = (r: number | null) => (r === null ? "–" : r.toFixed(1));

/**
 * Local SEO › Competitor Analysis. Stage 1: the businesses seen in your stored results. Stage 2: follow up to five of them and keep what Google showed for each on every date. Competitors are the other businesses that appeared next to you in the stored Google Places results for your tracked terms. Ratings and
 * review counts are what Google returned on the dates shown. Nothing is requested from Google to draw this page, and nothing between two observations is estimated.
 */
export default function CompetitorsPage() {
  const { locationId } = useLocationScope();
  const q = useFetch<Competitors>("/seo/competitors", { location_id: locationId ?? "" });
  const d = q.data;
  const { isAdmin } = useAuth();
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  async function pin(place: string | null, locs: string[] | undefined) {
    if (!place || !locs?.length) return;
    setBusy(place);
    try { await api("/seo/competitors/pinned", { method: "POST", body: { google_location_id: locs[0], place_id: place } }); toast("Following this business. Its past observations are now kept."); await q.reload(); }
    catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(null); }
  }
  async function unpin(id: string) {
    setBusy(id);
    try { await api(`/seo/competitors/pinned/${id}`, { method: "DELETE" }); toast("No longer following."); await q.reload(); }
    catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(null); }
  }
  return (
    <>
      <PageHeader title="Nearby competitors" subtitle="Other businesses that show up next to yours on Google for the words you track, with their rating and reviews on each date." />
      {q.error && <Alert tone="error" title="We couldn't load competitor observations">{q.error}</Alert>}
      {q.loading && !d && <Skeleton className="h-64" />}
      {d?.state === "no_location" && <ConnectGoogleEmptyState what="Competitors are found through the searches you track for a location." />}
      {d?.state === "no_keywords" && <EmptyState icon={<Crosshair className="h-5 w-5" />} title="Track a search term first" action={<Link href="/seo/rankings" className="font-semibold text-accent-ink hover:underline">Add a search term</Link>}>Competitors are the businesses that appear for the terms you track.</EmptyState>}
      {d?.state === "no_observations" && <EmptyState icon={<Crosshair className="h-5 w-5" />} title="No checks have run yet" action={<Link href="/seo/rankings" className="font-semibold text-accent-ink hover:underline">Run a check</Link>}>After a check, the businesses Google shows next to you appear here with the date they were seen.</EmptyState>}
      {d?.state === "ok" && (
        <div className="space-y-4">
          <Alert tone="info" title="What this is">{d.note}</Alert>
          {d.you && (
            <section aria-label="Your business" className="panel !rounded-[16px] p-4">
              <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-[15px] font-semibold">You, as last observed</h2><span className="flex items-center gap-2 text-[13px] text-muted"><SourceTag source="places" />{when(d.you.observed_at)}</span></div>
              <p className="mt-2 flex flex-wrap items-baseline gap-x-6 gap-y-1"><span className="num inline-flex items-center gap-1 text-[28px] font-semibold leading-8">{rating(d.you.rating)}<Star className="h-5 w-5 fill-accent text-accent" aria-hidden /></span>
                <span className="text-sm text-muted"><b className="num text-ink">{d.you.reviews === null ? "–" : fmtNum(d.you.reviews)}</b> Google reviews</span>
                {d.you.change && <span className="text-sm text-muted">{d.you.change.reviews_change >= 0 ? "+" : ""}{d.you.change.reviews_change} since {when(d.you.change.from)}</span>}</p>
            </section>
          )}
          {(d.opportunities ?? []).length > 0 && (
            <Panel dense title="Opportunities" meta="from the observations below" action={<SourceTag source="flowqr" />}>
              <ul className="space-y-2 text-sm">{d.opportunities!.map((o, i) => <li key={i}>{o.detail}</li>)}</ul>
            </Panel>
          )}
          <Panel dense title="Businesses seen next to you" meta={`${d.competitors.length} in the last ${d.window_days} days`} action={<SourceTag source="places" />}>
            {d.competitors.length === 0 ? <p className="text-sm text-muted">No other business appeared in the stored results.</p> : (
              <DataTable label="Businesses seen next to you" rows={d.competitors} rowKey={(c) => c.place_id ?? c.name ?? "x"} cols={[
                { key: "n", header: "Business", cell: (c) => <span className="font-semibold">{c.name ?? "Unnamed place"}</span> },
                { key: "r", header: "Rating", cell: (c) => <span className="num">{rating(c.rating)}</span> },
                { key: "v", header: "Reviews", cell: (c) => <span className="num">{c.reviews === null ? "–" : fmtNum(c.reviews)}</span> },
                { key: "g", header: "New reviews", cell: (c) => c.change ? <span className="inline-flex flex-col items-end sm:items-start"><Move change={c.change.reviews_change} unit="reviews" /><span className="text-xs font-normal text-muted">{when(c.change.from)} to {when(c.change.to)}</span></span> : <span className="text-[13px] font-normal text-muted">Seen once</span> },
                { key: "w", header: "Where they appear", tableOnly: true, cell: (c) => <span className="text-[13px]">{c.keywords.slice(0, 2).map((k) => <span key={k.keyword} className="block"><b className="font-semibold">#{k.best_position}</b> for {k.keyword}<span className="text-muted"> · above you in {k.ahead_of_you} of {k.your_checks}</span></span>)}</span> },
                { key: "s", header: "Last seen", align: "right", cell: (c) => <span className="text-muted">{when(c.observed_at)}</span> },
                ...(isAdmin ? [{ key: "f", header: "Follow", align: "right" as const, cell: (c: Competitor) => c.pinned ? <span className="text-xs font-medium text-muted">Following</span>
                  : <button type="button" disabled={busy === c.place_id || (d.pinned?.length ?? 0) >= (d.pin_limit ?? 5)} onClick={() => void pin(c.place_id, c.google_location_ids)} className="inline-flex min-h-11 items-center gap-1 rounded-full bg-surface-3 px-3 text-[13px] font-semibold hover:bg-ink-200/60 disabled:opacity-50 sm:min-h-9"><Pin className="h-3.5 w-3.5" aria-hidden />Follow</button> }] : []),
              ]} />
            )}
          </Panel>
          <Panel dense title="Competitors you follow" meta={`${d.pinned?.length ?? 0} of ${d.pin_limit ?? 5}`} action={<SourceTag source="places" />}>
            {(d.pinned ?? []).length === 0 ? <p className="text-sm text-muted">{isAdmin ? "Use Follow in the table to keep a competitor's rating, review count and position over time. Following costs nothing: it uses the results your own checks already receive, and the past observations FlowQR already holds are kept from the day you follow." : "An owner or admin can follow competitors from the table above."}</p> : (
              <ul className="divide-y divide-ink-100">
                {d.pinned!.map((c) => (
                  <li key={c.id} className="grid gap-3 py-3 first:pt-0 last:pb-0 sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:items-center">
                    <div className="min-w-0">
                      <p className="truncate font-semibold">{c.name}</p>
                      <p className="mt-0.5 text-[13px] text-muted">{c.rating === null ? "–" : c.rating.toFixed(1)}&nbsp;&#9733; · {c.reviews === null ? "–" : fmtNum(c.reviews)} reviews as last seen {when(c.observed_at)}</p>
                      <p className="mt-0.5 text-[13px] text-muted">Appeared in <b className="num text-ink">{c.visibility.appeared_in}</b> of {c.visibility.of_checks} checks · top 10 in {c.visibility.in_top10} · above you in {c.visibility.ahead_of_you}</p>
                      <p className="mt-0.5 text-xs text-muted">{c.change ? <>Reviews {c.change.reviews_change >= 0 ? "+" : ""}{c.change.reviews_change}{c.change.rating_change ? `, rating ${c.change.rating_change > 0 ? "+" : ""}${c.change.rating_change}` : ""} between {when(c.change.from)} and {when(c.change.to)}</> : `${c.observations} observation${c.observations === 1 ? "" : "s"} so far: a change needs two on different days.`}</p>
                    </div>
                    <div className="text-accent" aria-hidden>{c.series.filter((p) => p.reviews !== null).length >= 2 && <Sparkline id={`sp-${c.id}`} values={c.series.filter((p) => p.reviews !== null).map((p) => p.reviews as number)} width={96} height={30} fit />}</div>
                    {isAdmin && <button type="button" disabled={busy === c.id} onClick={() => void unpin(c.id)} className="inline-flex min-h-9 items-center gap-1 justify-self-start rounded-full bg-surface-2 px-3 text-[13px] font-semibold hover:bg-surface-3 disabled:opacity-50 sm:justify-self-end"><PinOff className="h-3.5 w-3.5" aria-hidden />Unfollow</button>}
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      )}
    </>
  );
}
