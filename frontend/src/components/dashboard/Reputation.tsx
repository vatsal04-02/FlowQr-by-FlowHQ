"use client";
import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { Skeleton, Stars } from "@/components/ui/Card";
import { Status } from "@/components/ui/kit";
import { fmtNum, fmtRating, timeAgo } from "@/lib/format";
import type { Overview, Review } from "@/lib/types";
import { Hint } from "./Hint";
import { CardToReview } from "./HowItWorks";

const REPLY: Record<Review["reply_state"], ["ok" | "warn" | "bad" | "info", string]> = {
  none: ["warn", "Needs a reply"], draft: ["info", "Reply drafted"], approved: ["info", "Reply approved"], publishing: ["info", "Sending to Google"], published: ["ok", "Replied"], failed: ["bad", "Reply didn't send"],
};

export function Reputation({ o, recent, recentError, googleConnected, loading }: {
  o: Overview | null; recent: Review[] | null; recentError: string | null; googleConnected: boolean; loading: boolean;
}) {
  const r = o?.reviews;
  const total = r?.total_synced ?? 0;
  const answered = r ? total - r.awaiting_reply : 0;
  const dist = r?.rating_distribution ?? {};
  const peak = Math.max(1, ...Object.values(dist));
  return (
    <section aria-labelledby="rep-h" className="min-w-0 rounded-2xl border border-ink-100 bg-white p-4 sm:p-6">
      <div className="mb-4 flex items-center gap-1.5"><h2 id="rep-h" className="text-lg font-bold text-navy">Your online reputation</h2>
        <Hint label="Your online reputation" text="What customers say about you on Google: your star rating, how many reviews you have, and how many you've answered." /></div>

      {loading || !o ? <Skeleton className="h-56" /> : total === 0 ? (
        <div>
          <p className="text-[15px] font-semibold text-navy">{googleConnected ? "No Google reviews have come in yet." : "Your reviews will appear here."}</p>
          <p className="mt-1 max-w-xl text-sm text-ink-700">{googleConnected ? "When customers review you on Google, your rating and every review show up here." : "Connect Google and FlowQR shows your rating, your reviews and which ones still need an answer."}</p>
          {!googleConnected && <Link href="/gbp/locations" className="mt-3 inline-flex min-h-11 items-center gap-1.5 rounded-lg bg-fq px-4 text-sm font-semibold text-pure-ink transition-colors hover:bg-fq-hover">Connect Google<ArrowRight className="h-4 w-4" aria-hidden /></Link>}
          <div className="mt-6 border-t border-ink-100 pt-5"><CardToReview /></div>
        </div>
      ) : (
        <>
          <div className="grid gap-6 sm:grid-cols-[auto_minmax(0,1fr)] sm:items-center sm:gap-10">
            <div>
              <p className="num text-[56px] font-bold leading-none tracking-tight text-navy">{fmtRating(r!.average_rating_all_time)}</p>
              <div className="mt-2">{r!.average_rating_all_time !== null && <Stars rating={Math.round(r!.average_rating_all_time)} size={18} />}</div>
              <p className="mt-1.5 text-sm text-ink-500">from {fmtNum(total)} Google {total === 1 ? "review" : "reviews"}</p>
            </div>
            <ul className="min-w-0 space-y-1.5" aria-label="How many reviews gave each rating">
              {[5, 4, 3, 2, 1].map((s) => {
                const c = dist[String(s)] ?? 0;
                return (
                  <li key={s} className="grid grid-cols-[3.5rem_minmax(0,1fr)_2rem] items-center gap-2 text-[13px]">
                    <span className="text-ink-700">{s} {s === 1 ? "star" : "stars"}</span>
                    <span aria-hidden className="h-2.5 overflow-hidden rounded-full bg-flow-50"><span className="block h-full rounded-full bg-fq transition-[width] duration-500" style={{ width: `${(c / peak) * 100}%` }} /></span>
                    <span className="num text-right font-medium text-navy">{c}</span>
                  </li>);
              })}
            </ul>
          </div>

          <div className="mt-6 rounded-xl bg-flow-50 p-4">
            <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
              <p className="flex items-center gap-1.5 text-sm font-semibold text-navy">Reviews answered<Hint label="Reviews answered" text="How many of your Google reviews have a reply from you. Answering every review, good or bad, shows customers you care." /></p>
              <p className="num text-sm text-ink-700"><b className="text-navy">{answered}</b> of {total}</p>
            </div>
            <div role="progressbar" aria-label="Reviews answered" aria-valuenow={answered} aria-valuemin={0} aria-valuemax={total} className="mt-2 h-2.5 overflow-hidden rounded-full bg-white">
              <div className="h-full rounded-full bg-green-600 transition-[width] duration-500" style={{ width: `${(answered / total) * 100}%` }} />
            </div>
            <p className="mt-2 text-[13px] text-ink-700">{r!.awaiting_reply > 0 ? <>{r!.awaiting_reply} still {r!.awaiting_reply === 1 ? "needs" : "need"} a reply. <Link href="/gbp/reviews?state=none" className="font-semibold text-flow-700 underline">Reply now</Link></> : "Every review has a reply. Well done."}</p>
          </div>

          <div className="mt-6">
            <div className="mb-2 flex items-center justify-between"><h3 className="text-sm font-semibold text-navy">What customers said recently</h3><Link href="/gbp/reviews" className="inline-flex min-h-11 items-center text-[13px] font-semibold text-flow-700 hover:underline sm:min-h-8">All reviews</Link></div>
            {recentError ? <p className="text-sm text-ink-500">We couldn&rsquo;t load the latest reviews just now.</p> : !recent ? <Skeleton className="h-28" /> : recent.length === 0 ? <p className="text-sm text-ink-500">No recent reviews to show.</p> : (
              <ul className="divide-y divide-ink-100">
                {recent.slice(0, 3).map((v) => {
                  const [tone, label] = REPLY[v.reply_state];
                  return (
                    <li key={v.id}><Link href={`/gbp/reviews/${v.id}`} className="block rounded-lg py-3 transition-colors hover:bg-flow-50 sm:-mx-2 sm:px-2">
                      <div className="flex flex-wrap items-center justify-between gap-2"><Stars rating={v.rating} size={14} /><Status tone={tone}>{label}</Status></div>
                      <p className="mt-1 line-clamp-2 text-sm text-navy">{v.text ?? <span className="text-ink-400">Rating only, no comment</span>}</p>
                      <p className="mt-0.5 text-[13px] text-ink-500">{[v.location_name, timeAgo(v.review_created_at)].filter(Boolean).join(" · ")}</p>
                    </Link></li>);
                })}
              </ul>
            )}
          </div>
        </>
      )}
    </section>
  );
}
