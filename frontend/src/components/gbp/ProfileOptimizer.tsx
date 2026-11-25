"use client";
import clsx from "clsx";
import { AlertCircle, ArrowRight, Check, CircleHelp, PenLine } from "lucide-react";
import Link from "next/link";
import { fixHref } from "@/lib/operator";
import { Ring } from "@/components/charts/Bars";
import { CountUp } from "@/components/charts/CountUp";
import { Accordion } from "@/components/ui/Accordion";
import { Skeleton } from "@/components/ui/Card";
import { Panel } from "@/components/ui/kit";
import { fmtNum, timeAgo } from "@/lib/format";
import { useFetch } from "@/lib/use-api";

interface Check_ { key: string; title: string; state: "ok" | "improve" | "missing" | "unknown"; detail: string; action: string | null; href: string | null; current?: string; reason?: string; evidence?: Record<string, unknown> }
interface Opt {
  score: number | null; checks: Check_[]; fetched_at: string | null; error: string | null;
  current: { title: string | null; description: string | null };
  suggestion: { status: string; draft: { description?: string } | null } | null;
  keywords: { keyword: string; value: number | null; below: number | null }[]; keywords_months: [string, string] | null;
  history: { id: string; title: string; status: string; result: string; description: string | null; at: string; failure_reason: string | null }[];
  rules: string;
}

const ICON = { ok: Check, improve: AlertCircle, missing: AlertCircle, unknown: CircleHelp } as const;
const TONE = { ok: "bg-pos-tint text-pos", improve: "bg-warn-tint text-warn", missing: "bg-neg-tint text-neg", unknown: "bg-surface-2 text-muted" } as const;

/**
 * AI Profile Optimizer (read-only overview): checks from what Google last returned, before/after for a pending AI description, the search
 * terms Google reported, and what happened to past suggestions. Approving and publishing stays in the description card below, where the
 * owner edits the exact text that goes to Google.
 */
export function ProfileOptimizer({ gid }: { gid: string }) {
  const { data: o, error, loading } = useFetch<Opt>(`/agent/profile/${gid}/optimize`);
  if (loading && !o) return <Skeleton className="h-64" />;
  if (error || !o) return null;
  const todo = o.checks.filter((c) => c.state === "missing" || c.state === "improve");
  const after = o.suggestion?.draft?.description;
  return (
    <div className="space-y-6">
      <Panel title="Profile optimizer" meta={o.fetched_at ? `as Google reported ${timeAgo(o.fetched_at)}` : "Google hasn't been checked yet"}>
        <div className="flex flex-wrap items-center gap-5">
          {o.score !== null && <Ring value={o.score} size={92} stroke={9} label={`Profile score ${o.score} out of 100`}><b className="num text-[24px] font-semibold"><CountUp value={o.score} /></b></Ring>}
          <div className="min-w-0 flex-1 basis-60">
            <p className="text-lg font-semibold">{todo.length === 0 ? "Your profile looks complete" : `${todo.length} ${todo.length === 1 ? "thing" : "things"} to improve`}</p>
            <p className="mt-1 text-[13px] text-muted">{o.rules}</p>
          </div>
        </div>
        <ul className="mt-5 grid gap-2.5 md:grid-cols-2">
          {o.checks.map((c) => {
            const Icon = ICON[c.state];
            return (
              <li key={c.key} className="flex gap-3 rounded-tile bg-surface-2 p-3.5 transition-[transform,box-shadow] duration-300 ease-out hover:-translate-y-0.5 hover:shadow-card motion-reduce:transform-none">
                <span aria-hidden className={clsx("grid h-8 w-8 shrink-0 place-items-center rounded-full", TONE[c.state])}><Icon className="h-4 w-4" strokeWidth={2.25} /></span>
                <div className="min-w-0 flex-1">
                  <p className="font-semibold">{c.title}<span className="sr-only"> ({c.state})</span></p>
                  <p className="text-[13px] text-muted">{c.detail}</p>
                  {c.reason && (
<Accordion className="mt-1" summary="Why this matters"><div className="text-[13px]"><p className="text-muted">{c.reason}</p>
                      {c.current && <p className="mt-1"><span className="font-semibold">Now: </span><span className="text-muted">{c.current}</span></p>}
                      {c.evidence && Object.entries(c.evidence).filter(([, v]) => v !== null && v !== undefined && !(Array.isArray(v) && v.length === 0)).length > 0 && (
                        <p className="mt-1 text-muted"><span className="font-semibold text-ink">What we read: </span>{Object.entries(c.evidence).filter(([k, v]) => k !== "read_from_google_at" && v !== null && v !== undefined && !(Array.isArray(v) && v.length === 0)).map(([k, v]) => `${k.replaceAll("_", " ")}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`).join("; ")}</p>)}
                    </div></Accordion>)}
                  {c.action && (() => { const href = fixHref(c.key, c.state, c.href, gid); return href ? <Link href={href} className="mt-1 inline-flex min-h-9 items-center gap-1 text-[13px] font-semibold text-accent-ink hover:underline">{c.action}<ArrowRight className="h-3.5 w-3.5" aria-hidden /></Link> : null; })()}
                </div>
              </li>
            );
          })}
        </ul>
      </Panel>

      {after && (
        <Panel title="Before and after" meta="the AI's suggestion, waiting for your approval below">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="rounded-tile bg-surface-2 p-4"><p className="text-xs font-medium text-muted">Now on Google</p>
              <p className="mt-2 whitespace-pre-wrap text-sm">{o.current.description?.trim() || <span className="text-muted">No description</span>}</p>
              <p className="mt-2 text-xs text-muted">{(o.current.description ?? "").length} characters</p></div>
            <div className="rounded-tile bg-accent-tint p-4 ring-1 ring-inset ring-accent-edge"><p className="flex items-center gap-1.5 text-xs font-medium text-accent-ink"><PenLine className="h-3.5 w-3.5" aria-hidden />Suggested</p>
              <p className="mt-2 whitespace-pre-wrap text-sm">{after}</p><p className="mt-2 text-xs text-muted">{after.length} / 750 characters</p></div>
          </div>
        </Panel>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="How people find you" meta={o.keywords_months ? `${o.keywords_months[0]} to ${o.keywords_months[1]} · from Google` : "from Google"}>
          {o.keywords.length === 0 ? <p className="text-sm text-muted">Google hasn&rsquo;t reported search terms yet. They appear after the next daily check if Google has any.</p> : (
            <ul className="flex flex-wrap gap-1.5">{o.keywords.map((k) => <li key={k.keyword} className="rounded-full bg-surface-2 px-3 py-1.5 text-[13px] font-medium">{k.keyword} <span className="text-muted">{k.value !== null ? fmtNum(k.value) : `< ${k.below}`}</span></li>)}</ul>
          )}
          <p className="mt-3 text-xs text-muted">The AI uses these words in your description only where they genuinely describe you, and never adds them to your business name.</p>
        </Panel>
        <Panel title="Change history" meta="AI suggestions">
          {o.history.length === 0 ? <p className="text-sm text-muted">No suggestions applied or rejected yet.</p> : (
            <ul className="divide-y divide-line">{o.history.map((h) => (
              <li key={h.id} className="py-2.5 first:pt-0">
                <p className="flex flex-wrap items-center justify-between gap-2"><span className="font-medium">{h.title}</span>
                  <span className={clsx("rounded-full px-2.5 py-0.5 text-xs font-medium", h.status === "published" || h.status === "done" ? "bg-pos-tint text-pos" : h.status === "failed" ? "bg-neg-tint text-neg" : "bg-surface-2 text-muted")}>{h.result}</span></p>
                <p className="text-xs text-muted">{timeAgo(h.at)}{h.failure_reason ? ` · ${h.failure_reason}` : ""}</p>
              </li>))}</ul>
          )}
        </Panel>
      </div>
    </div>
  );
}
