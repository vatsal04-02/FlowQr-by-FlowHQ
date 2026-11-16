"use client";
import clsx from "clsx";
import { ArrowDownRight, ArrowRight, ArrowUpRight, Minus } from "lucide-react";
import Link from "next/link";
import { useMemo, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from "react";
import { LineChart, type Series } from "@/components/charts/LineChart";
import { Skeleton } from "@/components/ui/Card";
import { delta, deltaText, type Days } from "@/lib/dashboard";
import { fmtNum } from "@/lib/format";
import type { Overview } from "@/lib/types";
import { useGoogleActivity } from "@/lib/use-google-activity";
import { Hint } from "./Hint";

type TabKey = "reviews" | "google" | "actions" | "cards";
const TABS: [TabKey, string, string][] = [
  ["reviews", "Reviews", "How many new Google reviews you received each day."],
  ["google", "Google profile use", "Every call, website click, direction request, booking or message from your Google profile each day, as reported by Google."],
  ["actions", "Calls and website clicks", "Customers who phoned you or opened your website straight from your Google profile."],
  ["cards", "Card scans and taps", "Customers who scanned your QR code or tapped your NFC card each day."],
];
const ORANGE = "rgb(var(--c-accent))", NAVY = "rgb(var(--c-ink-solid))", GREY = "rgb(var(--c-ink-300))";
// This period = a solid orange line over a soft orange glow; the period before = a thin dashed grey line (so the two differ by style, not only colour).
const PAIR: Series[] = [{ key: "cur", label: "This period", color: ORANGE }, { key: "prev", label: "Previous period", color: GREY, dash: "4 4" }];

function Headline({ total, d, days, unit, sub }: { total: number; d: ReturnType<typeof delta>; days: number; unit: [string, string]; sub?: ReactNode }) {
  const t = deltaText(d, days, unit);
  const Icon = t.dir === "up" ? ArrowUpRight : t.dir === "down" ? ArrowDownRight : Minus;
  return (
    <div className="mb-3 flex flex-wrap items-end gap-x-4 gap-y-1">
      <p className="num text-[38px] font-semibold leading-none tracking-[-.03em] text-ink">{fmtNum(total)}</p>
      <p className={clsx("flex items-center gap-1 rounded-full px-2.5 py-1 text-[13px]", t.dir === "up" ? "bg-pos-tint font-medium text-pos" : "bg-surface-2 text-muted")}><Icon className="h-4 w-4 shrink-0" strokeWidth={2.25} aria-hidden />{t.text}</p>
      {sub && <p className="w-full text-[13px] text-ink-500">{sub}</p>}
    </div>
  );
}

function Blocked({ title, children, href, cta }: { title: string; children: ReactNode; href: string; cta: string }) {
  return (
    <div className="grid place-items-center rounded-tile bg-surface-2 px-5 py-10 text-center">
      <div className="max-w-sm"><p className="text-base font-semibold">{title}</p><p className="mt-1 text-sm text-muted">{children}</p>
        <Link href={href} className="mt-4 inline-flex min-h-11 items-center gap-1.5 rounded-full bg-ink-solid px-5 text-sm font-semibold text-ink-on transition-transform hover:-translate-y-px">{cta}<ArrowRight className="h-4 w-4" aria-hidden /></Link></div>
    </div>
  );
}

/** The one range control lives in the page header; this card follows it. */
export function Growth({ o, prev, range, loc, days, loading, error, googleConnected, className, style }: {
  o: Overview | null; prev: Overview | null; range: { from: string; to: string }; loc: string; days: Days; loading: boolean; error: string | null; googleConnected: boolean;
  className?: string; style?: CSSProperties;
}) {
  const [tab, setTab] = useState<TabKey>("reviews");
  // Live from Google, and only once one of the two Google tabs is open.
  const google = useGoogleActivity(range, days, loc, tab === "google" || tab === "actions");
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKey = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const next = (i + step + TABS.length) % TABS.length;
    setTab(TABS[next][0]); refs.current[next]?.focus();
  };

  const reviews = useMemo(() => o?.reviews.series.map((p, i) => ({ date: p.date, cur: Number(p.count) || 0, prev: Number(prev?.reviews.series[i]?.count) || 0 })) ?? [], [o, prev]);
  const scans = useMemo(() => o?.engagement.series.map((p, i) => ({ date: p.date, cur: Number(p.scan) || 0, prev: Number(prev?.engagement.series[i]?.scan) || 0 })) ?? [], [o, prev]);
  const g = google.state === "ready" ? google : null;
  const gSeries = g?.series.map((p) => ({ date: p.date, cur: p.interactions, prev: p.prev_interactions })) ?? [];
  const aSeries = g?.series.map((p) => ({ date: p.date, calls: p.calls, website: p.website })) ?? [];
  const hint = TABS.find((t) => t[0] === tab)![2];

  let body: ReactNode;
  if (error) body = <p className="rounded-tile bg-neg-tint p-4 text-sm">We couldn&rsquo;t load your numbers just now. {error}</p>;
  else if (tab === "reviews" || tab === "cards") {
    if (loading || !o) body = <Skeleton className="h-64" />;
    else if (tab === "reviews" && o.reviews.total_synced === 0 && !googleConnected)
      body = <Blocked title="Reviews appear once Google is connected" href="/gbp/locations" cta="Connect Google">FlowQR reads your Google reviews so you can answer them in one place and see how they change over time.</Blocked>;
    else if (tab === "cards" && o.cards.length === 0)
      body = <Blocked title="No card on a counter yet" href="/gbp/cards" cta="See your cards">Each time a customer scans or taps your card, it&rsquo;s counted here.</Blocked>;
    else {
      const isR = tab === "reviews";
      const total = isR ? o.reviews.new_in_range : o.engagement.scans;
      const d = isR ? delta(o.reviews.new_in_range, prev?.reviews.new_in_range) : delta(o.engagement.scans, prev?.engagement.scans);
      const ch = o.engagement.by_channel;
      body = (
        <>
          <Headline total={total} d={d} days={days} unit={isR ? ["review", "reviews"] : ["scan or tap", "scans and taps"]}
            sub={isR ? undefined : ch ? `QR scans ${fmtNum(ch.qr.scans)} · NFC taps ${fmtNum(ch.nfc.scans)}${ch.untracked.scans ? ` · ${fmtNum(ch.untracked.scans)} from before FlowQR recorded which door they used` : ""}` : undefined} />
          <LineChart ariaLabel={isR ? `New Google reviews per day for the last ${days} days, compared with the previous ${days} days` : `Card scans and taps per day for the last ${days} days, compared with the previous ${days} days`}
            data={isR ? reviews : scans} series={PAIR} height={240} />
          {!isR && <p className="mt-2 text-[13px] text-ink-500">{fmtNum(o.engagement.landing_views)} opened your review page and {fmtNum(o.engagement.google_clicks)} tapped Continue to Google. Tapping isn&rsquo;t proof that a review was posted, so reviews are counted separately.</p>}
        </>
      );
    }
  } else {
    if (google.state === "loading" || google.state === "idle") body = <Skeleton className="h-64" />;
    else if (google.state === "disconnected") body = <Blocked title={google.reason === "no-locations" ? "Choose which Google locations to follow" : "Connect Google to see this"} href="/gbp/locations" cta={google.reason === "no-locations" ? "Choose locations" : "Connect Google"}>Google tells FlowQR how customers find and use your profile. This chart fills in once it&rsquo;s connected.</Blocked>;
    else if (google.state === "error") body = <Blocked title="Google didn't share these numbers just now" href="/analytics/performance" cta="See details">{google.message}</Blocked>;
    else if (tab === "google") body = (
      <>
        <Headline total={google.current.interactions} d={delta(google.current.interactions, google.previous.interactions)} days={google.reportedDays || days} unit={["action", "actions"]}
          sub={`Your profile was shown ${fmtNum(google.current.views)} times in Google Search and Maps.`} />
        <LineChart ariaLabel={`Customer actions on your Google profile per day for the last ${days} days, compared with the previous ${days} days`} data={gSeries} series={PAIR} height={240} />
        <p className="mt-2 text-[13px] text-ink-500">{google.reportedThrough ? `Google has shared numbers up to ${new Date(google.reportedThrough + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short" })}. It reports a few days late, so the most recent days are left out rather than shown as zero.` : "Google hasn't reported this period yet."}{google.partialErrors > 0 ? ` ${google.partialErrors} location didn't answer and is left out.` : ""}</p>
      </>
    );
    else body = (
      <>
        <Headline total={google.current.calls + google.current.website} d={delta(google.current.calls + google.current.website, google.previous.calls + google.previous.website)} days={google.reportedDays || days} unit={["visit or call", "calls and website visits"]}
          sub={`${fmtNum(google.current.calls)} calls · ${fmtNum(google.current.website)} website clicks · ${fmtNum(google.current.directions)} direction requests`} />
        <LineChart ariaLabel={`Calls and website clicks from your Google profile per day for the last ${days} days`} data={aSeries}
          series={[{ key: "calls", label: "Calls", color: ORANGE }, { key: "website", label: "Website clicks", color: NAVY, dash: "6 4" }]} height={240} />
        <p className="mt-2 text-[13px] text-ink-500">Reported by Google, a few days late. Days it hasn&rsquo;t reported yet are left out.</p>
      </>
    );
  }

  return (
    <section aria-labelledby="growth-h" style={style} className={clsx("panel min-w-0 p-5 sm:p-6", className)}>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-1.5"><h2 id="growth-h" className="text-lg font-semibold leading-6">Your business growth</h2><Hint label="Your business growth" text="Each chart compares this period (orange) with the same number of days before it (grey dashed), so you can see if things are moving up." /></div>
      </div>
      <div role="tablist" aria-label="What to show" className="mb-4 inline-flex max-w-full gap-1 overflow-x-auto rounded-full bg-surface-2 p-1 no-scrollbar">
        {TABS.map(([k, label], i) => (
          <button key={k} ref={(el) => { refs.current[i] = el; }} role="tab" id={`growth-tab-${k}`} aria-selected={tab === k} aria-controls="growth-panel" tabIndex={tab === k ? 0 : -1}
            onClick={() => setTab(k)} onKeyDown={(e) => onKey(e, i)}
            className={clsx("min-h-11 shrink-0 whitespace-nowrap rounded-full px-4 text-sm font-medium transition-colors sm:min-h-9", tab === k ? "bg-surface text-ink shadow-pill" : "text-muted hover:text-ink")}>{label}</button>
        ))}
      </div>
      <p className="mb-3 text-sm text-muted">{hint}</p>
      <div id="growth-panel" role="tabpanel" aria-labelledby={`growth-tab-${tab}`} key={tab} className="fq-enter">{body}</div>
    </section>
  );
}
