"use client";
import clsx from "clsx";
import { ArrowDownRight, ArrowUpRight, Minus, Star } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { fmtNum } from "@/lib/format";
import type { Competitors, SeoKeyword } from "@/lib/seo";

export const Card = ({ children, className, label }: { children: ReactNode; className?: string; label?: string }) => <section aria-label={label} className={clsx("rounded-[16px] bg-surface p-4 shadow-card lg:p-5", className)}>{children}</section>;
export const Title = ({ children, right }: { children: ReactNode; right?: ReactNode }) => <div className="flex items-center justify-between gap-3"><h2 className="text-[15px] font-semibold">{children}</h2>{right}</div>;
export const SeeAll = ({ href, children = "See all" }: { href: string; children?: ReactNode }) => <Link href={href} className="inline-flex min-h-11 items-center text-[13px] font-medium text-ink-600 underline underline-offset-2 md:min-h-8">{children}</Link>;
const day = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : "");

/** One lane per tracked word: a dot on a 1-20 track, the rank printed beside it, the change since the last check. "Not in the first 20" sits past the end as a hollow dot. */
export function RankLadder({ words, limit }: { words: SeoKeyword[]; limit?: number }) {
  const list = limit ? words.slice(0, limit) : words;
  return (
    <ul className="space-y-4">
      {list.map((k) => {
        const measured = k.status === "ok";
        const pos = k.rank === null ? 100 : ((k.rank - 1) / 19) * 92;
        const Icon = (k.change ?? 0) > 0 ? ArrowUpRight : (k.change ?? 0) < 0 ? ArrowDownRight : Minus;
        return (
          <li key={k.id}>
            <div className="flex items-baseline justify-between gap-3">
              <span data-words="skip" className="min-w-0 truncate text-[14px] font-medium">{k.keyword}</span>
              <span className="num flex shrink-0 items-center gap-2 text-[14px]">
                {measured && k.change ? <span className={clsx("inline-flex items-center text-[13px] font-medium", k.change > 0 ? "text-pos" : "text-neg")}><Icon className="h-3.5 w-3.5" aria-hidden />{Math.abs(k.change)}</span> : null}
                <b className="text-[17px] font-semibold">{!measured ? "–" : k.rank === null ? "20+" : `#${k.rank}`}</b>
              </span>
            </div>
            <div className="relative mt-2 h-5" role="img" aria-label={!measured ? `${k.keyword}: not measured yet` : `${k.keyword}: position ${k.rank ?? "past 20"} out of the first 20`}>
              <span aria-hidden className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-ink-200" />
              {[0, 2 / 19, 9 / 19].map((t) => <span key={t} aria-hidden className="absolute top-1/2 h-2 w-px -translate-y-1/2 bg-ink-300" style={{ left: `${t * 92}%` }} />)}
              <span aria-hidden className="absolute top-1/2 h-2 w-px -translate-y-1/2 bg-ink-300" style={{ left: "92%" }} />
              {measured && <span aria-hidden className={clsx("absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2", k.rank === null ? "border-ink-400 bg-surface" : "border-surface bg-ink-solid")} style={{ left: `${pos}%` }} />}
            </div>
            <div aria-hidden className="mt-0.5 flex justify-between text-[11px] text-muted"><span>1</span><span>{measured ? day(k.checked_at) : "not checked"}</span><span>20</span></div>
          </li>
        );
      })}
    </ul>
  );
}

/** You and the businesses Google showed next to you, ranked by reviews, each row with a bar. The gap to the first is computed from the stored numbers. */
export function WhoIsAhead({ d, limit = 4 }: { d: Competitors; limit?: number }) {
  type Row = { name: string; rating: number | null; reviews: number | null; you?: boolean; change?: number | null };
  const rows: Row[] = d.competitors.map((c) => ({ name: c.name ?? "Unnamed place", rating: c.rating, reviews: c.reviews, change: c.change?.reviews_change ?? null }));
  if (d.you) rows.push({ name: "You", rating: d.you.rating, reviews: d.you.reviews, you: true, change: d.you.change?.reviews_change ?? null });
  rows.sort((a, b) => (b.reviews ?? -1) - (a.reviews ?? -1));
  const youAt = rows.findIndex((r) => r.you);
  const shown = rows.slice(0, limit);
  if (youAt >= limit) shown.push(rows[youAt]);
  const top = Math.max(1, ...rows.map((r) => r.reviews ?? 0));
  const gap = youAt > 0 && rows[0].reviews != null && rows[youAt].reviews != null ? rows[0].reviews - rows[youAt].reviews : null;
  return (
    <>
      <ol className="space-y-2">
        {shown.map((r) => (
          <li key={r.name + (r.you ? "-you" : "")} className={clsx("rounded-[10px] px-2 py-1.5", r.you && "bg-surface-2")}>
            <div className="flex items-baseline gap-2 text-[14px]">
              <span className="num w-5 shrink-0 text-[13px] text-muted">{rows.indexOf(r) + 1}</span>
              <span data-words={r.you ? undefined : "skip"} className={clsx("min-w-0 flex-1 truncate", r.you ? "font-semibold" : "font-medium")}>{r.name}</span>
              <span className="num inline-flex shrink-0 items-center gap-0.5 text-[13px]">{r.rating?.toFixed(1) ?? "–"}<Star className="h-3 w-3 fill-star text-star" aria-hidden /></span>
              <span className="num w-12 shrink-0 text-right text-[13px] font-medium">{r.reviews == null ? "–" : fmtNum(r.reviews)}</span>
            </div>
            <span aria-hidden className="ml-7 mt-1 block h-1.5 overflow-hidden rounded-full bg-surface-3"><span className={clsx("fq-bar-x block h-full rounded-full", r.you ? "bg-accent-ink" : "bg-ink-400")} style={{ width: `${((r.reviews ?? 0) / top) * 100}%` }} /></span>
          </li>
        ))}
      </ol>
      {gap !== null && gap > 0 && <p className="mt-3 text-[13px] text-muted">Gap to #1: <b className="num text-ink">{fmtNum(gap)}</b> reviews</p>}
    </>
  );
}

/** A slot that Google has not filled yet: dashes in the shape of the chart, never sample bars. */
export const Dashes = ({ bars = 14, className }: { bars?: number; className?: string }) => (
  <span aria-hidden className={clsx("flex h-10 items-end gap-[3px]", className)}>{Array.from({ length: bars }, (_, i) => <span key={i} className="h-[2px] flex-1 bg-ink-300" />)}</span>
);
