"use client";
import { ArrowRight, Check } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { ColumnChart } from "@/components/charts/ColumnChart";
import { LineChart } from "@/components/charts/LineChart";
import { FlowCard } from "@/components/CardArt";
import { DateRange, presetRange } from "@/components/DateRange";
import { LinkButton } from "@/components/ui/Button";
import { Alert, PageHeader, Skeleton, Stars } from "@/components/ui/Card";
import { FilterSelect } from "@/components/ui/Form";
import { CellBar, Meter, Panel, Segmented, Status } from "@/components/ui/kit";
import { HealthCard } from "@/components/agent/HealthCard";
import type { TasksResponse } from "@/lib/agent";
import { useAuth } from "@/lib/auth";
import { fmtDate, fmtHours, fmtNum, fmtPct, fmtRating, timeAgo } from "@/lib/format";
import type { Card, GoogleConnection, Location, Overview, Review } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

type Tone = "bad" | "warn" | "info";
interface Item { tone: Tone; title: string; detail: string; href: string; cta: string }
const REVIEW_STATE: Record<Review["reply_state"], ["ok" | "warn" | "bad" | "info" | "idle", string]> = {
  none: ["warn", "Needs reply"], draft: ["info", "Draft ready"], approved: ["info", "Approved"], published: ["ok", "Replied"], failed: ["bad", "Publish failed"],
};

function AgentSummary() {
  const plan = useFetch<TasksResponse>("/agent/tasks", { scope: "today" });
  const open = (plan.data?.tasks ?? []).filter((t) => !["published", "done", "dismissed"].includes(t.status));
  const waiting = open.filter((t) => t.status === "awaiting_approval").length;
  const done = (plan.data?.tasks ?? []).filter((t) => ["published", "done"].includes(t.status)).length;
  return (
    <div className="mb-5 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <HealthCard compact />
      <Panel title="Today's plan" action={<Link className="text-[13px] font-medium text-brand-700 hover:underline" href="/agent">Open</Link>}>
        {plan.error ? <p className="text-sm text-red-700">{plan.error}</p> : !plan.data ? <Skeleton className="h-16" /> : (
          <>
            <p className="text-sm text-ink-700"><b className="num text-lg">{open.length}</b> to do · <b className="num text-lg">{waiting}</b> waiting for your approval · <b className="num text-lg">{done}</b> finished today</p>
            <ul className="mt-2 space-y-1 text-sm">{open.slice(0, 3).map((t) => <li key={t.id} className="truncate text-ink-700">• {t.title}</li>)}</ul>
            {open.length === 0 && <p className="mt-1 text-sm text-ink-500">Nothing needs doing right now, or the agent has not run yet.</p>}
          </>)}
      </Panel>
    </div>
  );
}

export default function Dashboard() {
  const { tenant } = useAuth();
  const [range, setRange] = useState(presetRange("30"));
  const [loc, setLoc] = useState("");
  const [view, setView] = useState<"cards" | "reviews">("cards");
  const p = { from: range.from, to: range.to, location_id: loc };
  const ov = useFetch<Overview>("/analytics/overview", p);
  const locs = useFetch<Location[]>("/locations");
  const cards = useFetch<Card[]>("/cards");
  const google = useFetch<{ configured: boolean; connections: GoogleConnection[] }>("/google/status");
  const waiting = useFetch<{ total: number; items: Review[] }>("/reviews", { reply_state: "none", location_id: loc, limit: 20 });
  const failed = useFetch<{ total: number; items: Review[] }>("/reviews", { reply_state: "failed", location_id: loc, limit: 5 });
  const recent = useFetch<{ total: number; items: Review[] }>("/reviews", { location_id: loc, limit: 6 });
  const o = ov.data;

  const items = useMemo<Item[]>(() => {
    if (!o) return [];
    const out: Item[] = [];
    if (failed.data?.total) out.push({ tone: "bad", title: `${failed.data.total} ${failed.data.total === 1 ? "reply" : "replies"} failed to publish`, detail: "Google did not accept them. Open each one to retry or edit.", href: "/reviews?state=failed", cta: "Review failures" });
    const sensitive = waiting.data?.items.filter((r) => r.sensitive_reasons.length) ?? [];
    if (sensitive.length) out.push({ tone: "bad", title: `${sensitive.length} ${sensitive.length === 1 ? "review needs" : "reviews need"} your personal attention`, detail: "These mention refunds, safety or other sensitive topics. AI drafts need your explicit sign-off.", href: "/reviews?state=none", cta: "Open reviews" });
    if (o.reviews.awaiting_reply > 0) out.push({ tone: "warn", title: `${o.reviews.awaiting_reply} ${o.reviews.awaiting_reply === 1 ? "review is" : "reviews are"} waiting for a reply`, detail: o.reviews.drafts_pending_approval ? `${o.reviews.drafts_pending_approval} already have a draft to approve.` : "Draft a reply with AI, edit it, then approve and publish.", href: "/reviews?state=none", cta: "Reply" });
    const badSync = o.sync.filter((s) => s.status && s.status !== "ok" && s.status !== "running");
    for (const s of badSync) out.push({ tone: "bad", title: `Sync problem at ${s.title ?? s.location}`, detail: s.error ?? `Last status: ${s.status}.`, href: "/google", cta: "Check connection" });
    const gc = google.data?.connections.find((c) => c.status === "revoked" || c.status === "error");
    if (gc) out.push({ tone: "bad", title: "Google connection needs reconnecting", detail: gc.last_error ?? "Access was revoked or expired.", href: "/google", cta: "Reconnect" });
    const noLink = (locs.data ?? []).filter((l) => l.is_active && !l.review_url);
    if (noLink.length) out.push({ tone: "warn", title: `${noLink.map((l) => l.name).join(", ")} ${noLink.length === 1 ? "has" : "have"} no Google review link`, detail: "Customers who scan a card here can't continue to Google until you add one.", href: "/locations", cta: "Add link" });
    if (!google.data?.connections.some((c) => c.status === "active") && o.reviews.total_synced === 0) out.push({ tone: "info", title: "Review sync is off", detail: google.data?.configured === false ? "Google sign-in isn't configured on this server yet. Cards and the writing assistant still work in manual-link mode." : "Connect Google Business Profile to sync reviews and publish approved replies.", href: "/google", cta: "Google connection" });
    const quiet = o.engagement.scans > 0 ? o.cards.filter((c) => (c.status === "active" || c.status === "assigned") && c.scans === 0) : [];
    if (quiet.length) out.push({ tone: "info", title: `${quiet.length} ${quiet.length === 1 ? "card has" : "cards have"} no scans in this period`, detail: quiet.map((c) => c.card_code).join(", ") + ". Check placement or that the card is on display.", href: "/cards", cta: "View cards" });
    const rank = { bad: 0, warn: 1, info: 2 };
    return out.sort((a, b) => rank[a.tone] - rank[b.tone]);
  }, [o, failed.data, waiting.data, google.data, locs.data]);

  const isNew = !!o && o.cards.length === 0 && o.reviews.total_synced === 0 && o.engagement.scans === 0;
  const syncedHere = new Set((o?.sync ?? []).filter((s) => s.status === "ok").map((s) => s.location));
  const lastSync = (o?.sync ?? []).map((s) => s.last_synced_at).filter(Boolean).sort().pop();
  const syncChip = !google.data ? null : google.data.connections.some((c) => c.status === "active")
    ? <Status tone={o?.sync.some((s) => s.status && s.status !== "ok" && s.status !== "running") ? "bad" : "ok"}>Google sync · {timeAgo(lastSync)}</Status>
    : <Status tone="idle">Manual-link mode</Status>;
  const maxScans = Math.max(1, ...(o?.locations ?? []).map((l) => l.scans));

  return (
    <>
      <PageHeader eyebrow="Overview" title={tenant?.name ?? "Overview"}
        subtitle={o && !isNew ? `${fmtNum(o.engagement.scans)} card scans and ${fmtNum(o.reviews.new_in_range)} new reviews in this period.` : undefined}
        actions={<>
          {syncChip}
          <FilterSelect label="Location" value={loc} onChange={(e) => setLoc(e.target.value)}>
            <option value="">All locations</option>{locs.data?.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </FilterSelect>
          <DateRange value={range} onChange={setRange} />
        </>} />

      <AgentSummary />

      {ov.error && <div className="mb-4"><Alert tone="error" title="Couldn't load analytics">{ov.error}</Alert></div>}
      {!o && !ov.error && <div className="grid gap-4 lg:grid-cols-[1.6fr_1fr]"><Skeleton className="h-64" /><Skeleton className="h-64" /></div>}

      {o && isNew && <Setup locs={locs.data ?? []} cards={cards.data ?? []} googleActive={!!google.data?.connections.some((c) => c.status === "active")} googleConfigured={!!google.data?.configured} />}

      {o && !isNew && (
        <div className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-[1.55fr_1fr]">
            {/* Priority: the one thing that needs a person first, then the rest. */}
            <Panel title="Needs attention" meta={items.length ? `${items.length} open` : undefined} flush>
              {items.length === 0 ? (
                <div className="flex items-center gap-3 p-4 text-sm"><span className="grid h-7 w-7 place-items-center rounded-full bg-green-50 text-ok"><Check className="h-4 w-4" aria-hidden /></span>
                  <p><span className="font-semibold">All clear.</span> <span className="text-ink-500">Every review has a reply, every location has a review link and sync is healthy.</span></p></div>
              ) : (
                <ul className="divide-y divide-ink-100">
                  {items.slice(0, 5).map((it, i) => (
                    <li key={it.title} className={i === 0 ? "bg-ink-50/60 p-4" : "px-4 py-3"}>
                      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                        <span aria-hidden className={`h-2 w-2 shrink-0 rounded-full ${it.tone === "bad" ? "bg-red-600" : it.tone === "warn" ? "bg-amber-500" : "bg-brand-600"}`} />
                        <div className="min-w-0 flex-1">
                          <p className={i === 0 ? "text-[15px] font-semibold" : "text-sm font-medium"}>{it.title}</p>
                          <p className="mt-0.5 text-[13px] text-ink-500">{it.detail}</p>
                        </div>
                        {i === 0 ? <LinkButton href={it.href} size="sm">{it.cta}<ArrowRight className="h-3.5 w-3.5" aria-hidden /></LinkButton>
                          : <Link href={it.href} className="inline-flex min-h-11 items-center gap-1 text-[13px] font-medium text-brand-700 hover:underline sm:min-h-8">{it.cta}<ArrowRight className="h-3 w-3" aria-hidden /></Link>}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>

            {/* Reputation: rating, volume and reply coverage composed as one panel. */}
            <Panel title="Reputation" meta="all synced reviews" flush>
              {o.reviews.total_synced === 0 ? (
                <p className="p-4 text-sm text-ink-500">No synced reviews yet. Ratings and reply coverage appear here once Google reviews sync. Card activity below works without it.</p>
              ) : (
                <>
                  <div className="flex items-end justify-between gap-4 p-4 pb-3">
                    <div>
                      <p className="num text-[44px] font-bold leading-none tracking-tight">{fmtRating(o.reviews.average_rating_all_time)}</p>
                      <div className="mt-2 flex items-center gap-2">{o.reviews.average_rating_all_time && <Stars rating={Math.round(o.reviews.average_rating_all_time)} size={15} />}<span className="text-xs text-ink-500">{fmtNum(o.reviews.total_synced)} reviews</span></div>
                    </div>
                    <ul className="w-[46%] space-y-1" aria-label="Rating distribution">
                      {[5, 4, 3, 2, 1].map((n) => (
                        <li key={n} className="grid grid-cols-[14px_1fr_26px] items-center gap-1.5 text-xs text-ink-500"><span className="num">{n}</span>
                          <CellBar value={o.reviews.rating_distribution[String(n)] ?? 0} max={Math.max(1, ...Object.values(o.reviews.rating_distribution))} color="bg-star" /><span className="num text-right text-ink-700">{o.reviews.rating_distribution[String(n)] ?? 0}</span></li>
                      ))}
                    </ul>
                  </div>
                  <div className="border-t border-ink-100 p-4">
                    <div className="mb-1.5 flex items-baseline justify-between text-[13px]"><span className="font-medium">Reply coverage</span>
                      <span className="num text-ink-500">{o.reviews.total_synced - o.reviews.awaiting_reply} of {o.reviews.total_synced} replied</span></div>
                    <Meter label="Reply coverage" value={o.reviews.total_synced - o.reviews.awaiting_reply} max={o.reviews.total_synced} tone={o.reviews.awaiting_reply ? "warn" : "ok"} />
                    <dl className="mt-3 grid grid-cols-2 gap-x-2 gap-y-3 text-xs sm:grid-cols-4 lg:grid-cols-2 xl:grid-cols-4">
                      {[["New in period", fmtNum(o.reviews.new_in_range)],
                        ["Avg in period", fmtRating(o.reviews.average_rating_in_range)], ["Reply rate", fmtPct(o.reviews.reply_rate_in_range)], ["Avg response", fmtHours(o.reviews.avg_response_hours)]].map(([k, v]) => (
                        <div key={k}><dt className="text-ink-500">{k}</dt><dd className="num mt-0.5 text-sm font-semibold">{v}</dd></div>))}
                    </dl>
                  </div>
                </>
              )}
            </Panel>
          </div>

          <div className="grid gap-4 lg:grid-cols-[1.55fr_1fr]">
            <Panel title="Activity" meta={`${fmtDate(o.range.from, { day: "numeric", month: "short" })} – ${fmtDate(o.range.to, { day: "numeric", month: "short" })}`}
              action={<Segmented label="Activity view" value={view} onChange={setView} options={[["cards", "Cards"], ["reviews", "Reviews"]] as const} />}>
              {view === "cards" ? (
                <>
                  <LineChart ariaLabel="Card scans, landing page visits and clicks to Google over time" data={o.engagement.series} height={190} series={[
                    { key: "scan", label: "Scans", color: "#1B46B8" }, { key: "landing_view", label: "Visits", color: "#57554F", dash: "6 4" }, { key: "google_click", label: "Clicks to Google", color: "#0A7D6B", dash: "2 4" }]} />
                  <ol className="mt-3 grid grid-cols-3 divide-x divide-ink-100 rounded-lg border border-ink-100 text-center" aria-label="Customer funnel">
                    {[["Scans", o.engagement.scans, null], ["Visits", o.engagement.landing_views, o.engagement.scans ? o.engagement.landing_views / o.engagement.scans : null], ["Clicks to Google", o.engagement.google_clicks, o.engagement.click_through_rate]].map(([k, v, r]) => (
                      <li key={k as string} className="px-2 py-2"><p className="num text-lg font-bold leading-tight">{fmtNum(v as number)}</p><p className="text-xs text-ink-500">{k as string}{r !== null && <span className="num"> · {fmtPct(r as number)}</span>}</p></li>))}
                  </ol>
                  <p className="mt-2 text-xs text-ink-500">A click to Google doesn&rsquo;t prove a review was posted. Reviews that actually landed are shown under Reviews.</p>
                </>
              ) : o.reviews.total_synced === 0 ? (
                <p className="py-10 text-center text-sm text-ink-500">Review activity appears here once Google reviews sync.</p>
              ) : (
                <>
                  <ColumnChart data={o.reviews.series} valueKey="count" label="new reviews" ariaLabel="New reviews per day" height={210} />
                  <p className="mt-2 text-xs text-ink-500">New reviews per day, from synced Google locations only.</p>
                </>
              )}
            </Panel>

            <Panel title="Locations" meta="branch comparison" action={<Link href="/locations" className="text-[13px] font-medium text-brand-700 hover:underline">Manage</Link>} flush>
              {o.locations.length === 0 ? <p className="p-4 text-sm text-ink-500">No locations yet.</p> : (
                <div className="overflow-x-auto"><table className="dt min-w-[380px]">
                  <thead><tr><th>Location</th><th className="!text-right">Scans</th><th className="!text-right">Reviews</th><th className="!text-right">Avg ★</th></tr></thead>
                  <tbody>{o.locations.map((l) => {
                    const meta = locs.data?.find((x) => x.name === l.location);
                    const link = syncedHere.has(l.location) ? <Status tone="ok">Synced</Status> : meta?.review_url ? <Status tone="idle">Manual link</Status> : <Status tone="warn">No link</Status>;
                    return (
                      <tr key={l.location}><td><p className="font-medium">{l.location}</p>{link}</td>
                        <td className="n"><span className="font-medium">{fmtNum(l.scans)}</span><CellBar value={l.scans} max={maxScans} /></td>
                        <td className="n">{l.new_reviews}</td><td className="n">{l.avg_rating ?? "–"}</td></tr>);
                  })}</tbody>
                </table></div>
              )}
            </Panel>
          </div>

          <div className="grid gap-4 lg:grid-cols-[1.55fr_1fr]">
            <Panel title="Latest reviews" meta="newest first" action={<Link href="/reviews" className="text-[13px] font-medium text-brand-700 hover:underline">All reviews</Link>} flush>
              {!recent.data ? <Skeleton className="m-4 h-28" /> : recent.data.items.length === 0 ? (
                <p className="p-4 text-sm text-ink-500">No reviews yet. They appear after Google sync; in manual-link mode customers post directly on Google.</p>
              ) : (
                <ul className="divide-y divide-ink-100">{recent.data.items.map((r) => {
                  const [tone, label] = REVIEW_STATE[r.reply_state];
                  return (
                    <li key={r.id}><Link href={`/reviews/${r.id}`} className="grid grid-cols-[auto_1fr_auto] items-start gap-x-3 gap-y-1 px-4 py-3 transition-colors hover:bg-ink-50/60">
                      <Stars rating={r.rating} size={13} />
                      <p className="line-clamp-1 text-sm">{r.text ?? <span className="text-ink-400">Rating only</span>}</p>
                      <Status tone={tone}>{label}</Status>
                      <span /><p className="text-xs text-ink-500">{r.location_name} · {timeAgo(r.review_created_at)}</p><span />
                    </Link></li>);
                })}</ul>
              )}
            </Panel>

            <Panel title="Cards" meta="last scan" action={<Link href="/cards" className="text-[13px] font-medium text-brand-700 hover:underline">All cards</Link>} flush>
              {!cards.data ? <Skeleton className="m-4 h-28" /> : (
                <ul className="divide-y divide-ink-100">{[...cards.data].sort((a, b) => (b.last_scan_at ?? "").localeCompare(a.last_scan_at ?? "")).slice(0, 5).map((c) => (
                  <li key={c.id}><Link href={`/cards/${c.id}`} className="flex items-center justify-between gap-3 px-4 py-2.5 transition-colors hover:bg-ink-50/60">
                    <div className="min-w-0"><p className="card-code text-[13px] font-medium">{c.card_code}</p><p className="truncate text-xs text-ink-500">{c.label ?? "No label"} · {c.location_name ?? "No location"}</p></div>
                    <div className="shrink-0 text-right"><p className="text-xs text-ink-500">{c.last_scan_at ? timeAgo(c.last_scan_at) : "never scanned"}</p>
                      {c.status !== "active" && c.status !== "assigned" && <Status tone="idle">{c.status}</Status>}</div>
                  </Link></li>))}</ul>
              )}
            </Panel>
          </div>
        </div>
      )}
    </>
  );
}

/** First-run experience: a real checklist computed from the business's data, plus a preview of the card to come. */
function Setup({ locs, cards, googleActive, googleConfigured }: { locs: Location[]; cards: Card[]; googleActive: boolean; googleConfigured: boolean }) {
  const steps: { done: boolean; title: string; body: string; href?: string; cta?: string }[] = [
    { done: true, title: "Create your business", body: "Your account and first location exist." },
    { done: locs.length > 0 && locs.some((l) => l.review_url), title: "Add your Google review link", body: "Paste the link customers should land on. You can change it any time without reprinting cards.", href: "/locations", cta: "Add link" },
    { done: cards.length > 0, title: "Get your FlowQR cards", body: "Cards are assigned to your locations by the FlowQR team after you order them.", href: "/payments", cta: "Order cards" },
    { done: cards.some((c) => (c.stats.scan ?? 0) > 0), title: "Tap or scan one yourself", body: "Open the card with your phone to see exactly what customers see.", href: "/cards", cta: "View cards" },
    { done: googleActive, title: "Connect Google (optional)", body: googleConfigured ? "Sync reviews and approve AI-drafted replies from one inbox." : "Reviews sync once Google API access is configured for this server. Manual-link mode works without it.", href: "/google", cta: "Google connection" },
  ];
  const next = steps.findIndex((s) => !s.done);
  return (
    <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
      <Panel title="Get set up" meta={`${steps.filter((s) => s.done).length} of ${steps.length} done`} flush>
        <ol className="divide-y divide-ink-100">
          {steps.map((s, i) => (
            <li key={s.title} className={`flex items-start gap-3 px-4 py-3.5 ${i === next ? "bg-ink-50/60" : ""}`}>
              <span aria-hidden className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full text-[11px] font-bold ${s.done ? "bg-ok text-white" : i === next ? "bg-brand-600 text-white" : "bg-ink-100 text-ink-500"}`}>{s.done ? <Check className="h-3 w-3" strokeWidth={3} /> : i + 1}</span>
              <div className="min-w-0 flex-1"><p className={`text-sm ${s.done ? "text-ink-500 line-through decoration-ink-300" : "font-semibold"}`}>{s.title}<span className="sr-only">{s.done ? " (done)" : ""}</span></p>{!s.done && <p className="mt-0.5 text-[13px] text-ink-500">{s.body}</p>}</div>
              {!s.done && s.href && (i === next ? <LinkButton href={s.href} size="sm">{s.cta}</LinkButton> : <Link href={s.href} className="inline-flex min-h-11 items-center text-[13px] font-medium text-brand-700 hover:underline sm:min-h-8">{s.cta}</Link>)}
            </li>
          ))}
        </ol>
      </Panel>
      <Panel title="Your card" meta="preview">
        <div className="mx-auto w-full max-w-[220px]"><FlowCard code="FQR-0000" state="unassigned" /></div>
        <p className="mt-3 text-[13px] text-ink-500">Once assigned, each card has its own permanent QR/NFC link and printed ID. Scans, visits and clicks start appearing on this page.</p>
      </Panel>
    </div>
  );
}
