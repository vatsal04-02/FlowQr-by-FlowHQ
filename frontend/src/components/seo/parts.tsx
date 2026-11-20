"use client";
import clsx from "clsx";
import { ArrowDownRight, ArrowRight, ArrowUpRight, Info, Minus } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import type { Source } from "@/lib/seo";

const SRC: Record<Source, { label: string; tip: string; cls: string }> = {
  google: { label: "Google", tip: "Reported by Google Business Profile.", cls: "bg-pos-tint text-pos" },
  places: { label: "Measured · Places", tip: "Measured with Google's Places API: the position among the first 20 results around your location. Google Maps itself can order results differently by device and person.", cls: "bg-surface-3 text-ink-700" },
  flowqr: { label: "Calculated", tip: "Calculated by FlowQR from the data shown, with the formula visible.", cls: "bg-surface-3 text-ink-700" },
};

/** Where a number comes from. Shown on every Local SEO and Performance card so Google data, Places measurements and our own calculations are never confused. */
export function SourceTag({ source, className }: { source: Source; className?: string }) {
  const s = SRC[source];
  return <span title={s.tip} className={clsx("inline-flex h-5 items-center whitespace-nowrap rounded-full px-2 text-[12px] font-semibold", s.cls, className)}>{s.label}</span>;
}

/** The explicit "unavailable" state: says what is missing and why, and never shows a zero in its place. */
export function Unavailable({ title, children, href, cta, className }: { title: string; children?: ReactNode; href?: string; cta?: string; className?: string }) {
  return (
    <div className={clsx("rounded-xl bg-surface-2 p-4", className)}>
      <p className="flex items-center gap-2 text-sm font-semibold"><Info className="h-4 w-4 shrink-0 text-muted" aria-hidden />{title}</p>
      {children && <p className="mt-1 text-[13px] leading-snug text-muted">{children}</p>}
      {href && <Link href={href} className="mt-2 inline-flex min-h-9 items-center gap-1 text-[13px] font-semibold text-accent-ink hover:underline">{cta}<ArrowRight className="h-3.5 w-3.5" aria-hidden /></Link>}
    </div>
  );
}

export function Position({ rank, status }: { rank: number | null; status: string | null }) {
  if (status === null) return <span className="text-muted">Not measured yet</span>;
  if (status === "error") return <span className="font-medium text-neg">Could not be measured</span>;
  if (rank === null) return <span className="text-muted">Not in first 20</span>;
  return <span className={clsx("num inline-flex h-6 min-w-[2rem] items-center justify-center rounded-full px-2 text-[13px] font-semibold", rank <= 3 ? "bg-pos-tint text-pos" : rank <= 10 ? "bg-accent-tint text-accent-ink" : "bg-surface-3 text-ink-700")}>#{rank}</span>;
}

/** Up / down / flat with words for screen readers. Positive = better. */
export function Move({ change, unit = "places" }: { change: number | null; unit?: string }) {
  if (change === null) return <span className="text-[13px] text-muted">–</span>;
  if (change === 0) return <span className="inline-flex items-center gap-1 text-[13px] text-muted"><Minus className="h-3.5 w-3.5" aria-hidden />No change</span>;
  const up = change > 0, Icon = up ? ArrowUpRight : ArrowDownRight;
  return <span className={clsx("inline-flex items-center gap-1 text-[13px] font-medium", up ? "text-pos" : "text-neg")}><Icon className="h-3.5 w-3.5" aria-hidden />{Math.abs(change)}<span className="sr-only"> {unit} {up ? "up" : "down"}</span></span>;
}

export const when = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "–");
