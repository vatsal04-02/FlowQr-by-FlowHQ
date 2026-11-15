"use client";
import clsx from "clsx";
import { Check, Clock, X } from "lucide-react";
import Link from "next/link";
import { Skeleton } from "@/components/ui/Card";
import type { TimelineItem, TimelineState } from "@/lib/dashboard";
import { timeAgo } from "@/lib/format";
import { Hint } from "./Hint";

const LOOK: Record<TimelineState, { Icon: typeof Check; ring: string; label: string; text: string }> = {
  done: { Icon: Check, ring: "bg-green-100 text-green-800", label: "Done", text: "text-green-800" },
  pending: { Icon: Clock, ring: "bg-amber-100 text-amber-900", label: "Waiting", text: "text-amber-900" },
  failed: { Icon: X, ring: "bg-red-100 text-red-800", label: "Didn't work", text: "text-red-800" },
};

/** A readable list of what really happened, newest first. Each line says in words, and with an icon, whether it is done, waiting or failed. */
export function Timeline({ items, loading, error }: { items: TimelineItem[]; loading: boolean; error: string | null }) {
  return (
    <section aria-labelledby="act-h" className="min-w-0 rounded-2xl border border-ink-100 bg-white p-4 sm:p-6">
      <div className="mb-1 flex items-center gap-1.5"><h2 id="act-h" className="text-lg font-bold text-navy">Recent activity</h2>
        <Hint label="Recent activity" text="The latest things that happened: reviews that arrived, what your AI assistant prepared or finished, and cards that were scanned." align="end" /></div>
      <ul className="mb-4 flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-ink-500" aria-label="What the icons mean">
        {(["done", "pending", "failed"] as const).map((s) => { const L = LOOK[s]; return <li key={s} className="flex items-center gap-1.5"><span aria-hidden className={clsx("grid h-4 w-4 place-items-center rounded-full", L.ring)}><L.Icon className="h-2.5 w-2.5" strokeWidth={3} /></span>{L.label}</li>; })}
      </ul>
      {loading ? <Skeleton className="h-64" /> : error ? <p className="text-sm text-ink-500">We couldn&rsquo;t load your recent activity just now.</p> : items.length === 0 ? (
        <p className="rounded-xl bg-flow-50 p-4 text-sm text-ink-700">Nothing has happened yet. New reviews, drafts your AI assistant prepares and card scans will show up here as they happen.</p>
      ) : (
        <ol className="relative">
          {items.map((it, i) => {
            const L = LOOK[it.state];
            const body = (
              <>
                <p className="text-sm font-semibold leading-snug text-navy">{it.title}</p>
                {it.detail && <p className="mt-0.5 line-clamp-2 text-[13px] leading-snug text-ink-700">{it.detail}</p>}
                <p className="mt-1 text-[13px] text-ink-500">{it.tag && <span className={clsx("font-semibold", L.text)}>{it.tag}</span>}{it.tag && it.at ? " · " : ""}{it.at ? timeAgo(it.at) : it.tag ? "" : ""}</p>
              </>
            );
            return (
              <li key={it.id} className="relative flex gap-3 pb-4 last:pb-0">
                {i < items.length - 1 && <span aria-hidden className="absolute left-[13px] top-7 h-[calc(100%-1.75rem)] w-0.5 bg-ink-100" />}
                <span aria-hidden className={clsx("relative z-[1] mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full", L.ring)}><L.Icon className="h-3.5 w-3.5" strokeWidth={3} /></span>
                <div className="min-w-0 flex-1">{it.href ? <Link href={it.href} className="block rounded-md transition-colors hover:bg-flow-50 sm:-mx-1.5 sm:px-1.5">{body}</Link> : body}<span className="sr-only">{L.label}</span></div>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
