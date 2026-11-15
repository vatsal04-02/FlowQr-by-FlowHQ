"use client";
import clsx from "clsx";
import { ArrowDownRight, ArrowRight, ArrowUpRight, MapPin, MessageCircle, Minus, ScanLine, Star } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { HealthCard } from "@/components/agent/HealthCard";
import { Skeleton, Stars } from "@/components/ui/Card";
import { delta, deltaText, type GoogleStored } from "@/lib/dashboard";
import { fmtNum, fmtRating, timeAgo } from "@/lib/format";
import type { Overview } from "@/lib/types";
import { Hint } from "./Hint";

/** A comparison in words and an arrow. Only an increase is green; a decrease is plain, not alarming, because a quiet week isn't a failure. */
function Change({ d, days, unit, decimals }: { d: ReturnType<typeof delta>; days: number; unit?: [string, string]; decimals?: number }) {
  const t = deltaText(d, days, unit, decimals);
  const Icon = t.dir === "up" ? ArrowUpRight : t.dir === "down" ? ArrowDownRight : Minus;
  return (
    <p className={clsx("mt-2 flex items-start gap-1 text-[13px] leading-snug", t.dir === "up" ? "font-medium text-green-800" : "text-ink-500")}>
      <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0" strokeWidth={2.25} aria-hidden /><span>{t.text}</span>
    </p>
  );
}

function Cell({ icon, label, hint, align, children }: { icon: ReactNode; label: string; hint: string; align: "start" | "end"; children: ReactNode }) {
  return (
    <div className="min-w-0 rounded-xl bg-white p-4 transition-transform duration-200 hover:-translate-y-0.5 sm:p-5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2.5">
          <span aria-hidden className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-flow-100 text-flow-700">{icon}</span>
          <h3 className="text-[13px] font-semibold leading-tight text-navy sm:text-sm">{label}</h3>
        </div>
        <Hint label={label} text={hint} align={align} />
      </div>
      <div className="mt-3">{children}</div>
    </div>
  );
}

const Big = ({ children }: { children: ReactNode }) => <p className="num text-[34px] font-bold leading-none tracking-tight text-navy sm:text-[38px]">{children}</p>;
const Missing = ({ children, href, cta }: { children: ReactNode; href?: string; cta?: string }) => (
  <div><Big>–</Big><p className="mt-2 text-[13px] leading-snug text-ink-500">{children}</p>
    {href && <Link href={href} className="mt-1 inline-flex min-h-11 items-center gap-1 text-[13px] font-semibold text-flow-700 hover:underline sm:min-h-8">{cta}<ArrowRight className="h-3 w-3" aria-hidden /></Link>}</div>
);

export function Glance({ o, prev, google, days, googleConnected, loading }: {
  o: Overview | null; prev: Overview | null; google: GoogleStored; days: number; googleConnected: boolean; loading: boolean;
}) {
  const ch = o?.engagement.by_channel;
  const hasReviews = !!o && (o.reviews.total_synced > 0 || googleConnected);
  return (
    <section aria-labelledby="glance-h" className="rounded-2xl bg-flow-50 p-3 sm:p-5">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-3 px-1 sm:mb-4">
        <h2 id="glance-h" className="text-lg font-bold text-navy">Your business at a glance</h2>
        <p className="text-[13px] text-ink-500">Last {days} days, compared with the {days} days before</p>
      </div>

      <div className="grid grid-cols-1 gap-2.5 min-[480px]:grid-cols-2 lg:grid-cols-4 lg:gap-3">
        <Cell icon={<MessageCircle className="h-4 w-4" strokeWidth={2} />} label="New Google reviews" align="start"
          hint="Reviews customers left on your Google profile during this period.">
          {loading || !o ? <Skeleton className="h-16" /> : !hasReviews ? <Missing href="/gbp/locations" cta="Connect Google">Your reviews will show here once Google is connected.</Missing> : (
            <><Big>{fmtNum(o.reviews.new_in_range)}</Big><Change d={delta(o.reviews.new_in_range, prev?.reviews.new_in_range)} days={days} unit={["review", "reviews"]} /></>
          )}
        </Cell>

        <Cell icon={<Star className="h-4 w-4" strokeWidth={2} />} label="Average Google rating" align="end"
          hint="The average star rating across all your Google reviews, the same number as in Your online reputation below. Underneath, how this period's new reviews compare.">
          {loading || !o ? <Skeleton className="h-16" /> : !hasReviews || (o.reviews.average_rating_all_time === null) ? <Missing>Ratings appear after your first Google reviews come in.</Missing> : (() => {
            const inRange = o.reviews.new_in_range > 0 && o.reviews.average_rating_in_range !== null;
            const value = o.reviews.average_rating_all_time!;
            return (
              <><div className="flex items-end gap-2"><Big>{fmtRating(value)}</Big><span className="pb-0.5"><Stars rating={Math.round(value)} size={14} /></span></div>
                {inRange
                  ? <><p className="mt-2 text-[13px] text-ink-700">New reviews this period averaged <b className="num">{fmtRating(o.reviews.average_rating_in_range)}</b></p>
                      <Change d={delta(o.reviews.average_rating_in_range, prev?.reviews.average_rating_in_range ?? null)} days={days} decimals={1} /></>
                  : <p className="mt-2 text-[13px] text-ink-500">Overall, across {fmtNum(o.reviews.total_synced)} reviews. No new ones this period.</p>}</>
            );
          })()}
        </Cell>

        <Cell icon={<MapPin className="h-4 w-4" strokeWidth={2} />} label="People who used your Google profile" align="start"
          hint="Calls, website clicks, direction requests, bookings and messages from your Google profile, as reported by Google. FlowQR saves Google's last 28 days each day, so this one doesn't change with the 7/30/90 filter.">
          {google.state === "loading" ? <Skeleton className="h-16" />
            : google.state === "not-connected" ? <Missing href="/gbp/locations" cta="Connect Google">Connect Google to see how customers use your profile.</Missing>
            : google.state === "unavailable" ? <Missing href="/overview/performance" cta="See details">{google.note}</Missing>
            : <><Big>{fmtNum(google.current)}</Big><Change d={delta(google.current, google.previous)} days={28} />
                <p className="mt-1 text-[13px] text-ink-500">Google&rsquo;s last 28 days · updated {timeAgo(google.fetchedAt)}</p></>}
        </Cell>

        <Cell icon={<ScanLine className="h-4 w-4" strokeWidth={2} />} label="Customers who opened your card" align="end"
          hint="Times a customer scanned your QR code or tapped your NFC card. Automatic bots and quick repeat taps are left out.">
          {loading || !o ? <Skeleton className="h-16" /> : o.cards.length === 0 ? <Missing href="/gbp/cards" cta="See cards">You don&rsquo;t have a card yet. Scans show here once one is on your counter.</Missing> : (
            <><Big>{fmtNum(o.engagement.scans)}</Big><Change d={delta(o.engagement.scans, prev?.engagement.scans)} days={days} />
              {ch && o.engagement.scans > 0 && <p className="mt-1 text-[13px] text-ink-500">QR {fmtNum(ch.qr.scans)} · NFC {fmtNum(ch.nfc.scans)}{ch.untracked.scans > 0 ? ` · earlier ${fmtNum(ch.untracked.scans)}` : ""}</p>}</>
          )}
        </Cell>
      </div>

      <div className="mt-3 rounded-xl bg-white/70 p-4 sm:mt-4 sm:p-5"><HealthCard compact variant="strip" /></div>
    </section>
  );
}
