"use client";
import clsx from "clsx";
import { ArrowDownRight, ArrowRight, ArrowUpRight, ChevronRight, Clock, Flag, Info, MessageSquarePlus, Minus, QrCode, Reply, Sparkles, Star } from "lucide-react";
import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";
import { Bars, Meter, Ring, type BarDatum } from "@/components/charts/Bars";
import { CountUp } from "@/components/charts/CountUp";
import { buttonClass } from "@/components/ui/Button";
import { Segmented } from "@/components/ui/Segmented";
import { Skeleton } from "@/components/ui/Card";
import type { Todo } from "@/lib/dashboard";
import { liftOf, newReviewsVerdict, ratingVerdict, repliedVerdict, replyTimeVerdict, reviewInsight, scoreVerdict, type ScorePart, type Verdict } from "@/lib/charts";
import { fmtNum } from "@/lib/format";
import type { Overview } from "@/lib/types";

export interface GrowthPart { key: string; label: string; weight: number; available: boolean; value: number | null; detail: string | null; href: string; count?: number; goal?: number; goal_set?: boolean; days_left?: number; to_go?: number; rate?: number; hours?: number | null; number?: number; percent?: number; top10?: number; measured?: number }
export interface GrowthScore { score: number | null; partial: boolean; covered_weight: number; parts: GrowthPart[]; weakest: string | null; note: string }
export interface FunnelStep { key: string; label: string; count: number }

export type ToneName = "teal" | "amber" | "rose" | "sky" | "blue" | "accent" | "ok";
/** A Home card: frosted glass over the page's glow. With a `tone` it takes that metric family's hue (corner glow, tinted edge) and, with `tilt`, leans toward the pointer. `hero` adds the travelling edge light (one per page). */
export const Card = ({ children, className, label, tone, tilt, hero }: { children: ReactNode; className?: string; label?: string; tone?: ToneName; tilt?: boolean; hero?: boolean }) =>
  <section aria-label={label} data-tilt={tilt ? "" : undefined} className={clsx("relative rounded-[20px] p-4 lg:p-4", tone ? `tn t-${tone}` : "glass", tilt && "tilt", hero && "beam", className)}>{children}</section>;
export const Title = ({ children, right }: { children: ReactNode; right?: ReactNode }) => <div className="flex items-center justify-between gap-3"><h2 className="text-[15px] font-semibold">{children}</h2>{right}</div>;

export function Delta({ cur, prev }: { cur: number | null | undefined; prev: number | null | undefined }) {
  if (cur == null || prev == null || prev === 0) return null;
  const p = Math.round(((cur - prev) / prev) * 100);
  const Icon = p > 0 ? ArrowUpRight : p < 0 ? ArrowDownRight : Minus;
  return <span className={clsx("inline-flex items-center gap-0.5 text-[13px] font-medium", p > 0 ? "text-pos" : p < 0 ? "text-neg" : "text-muted")}><Icon className="h-3.5 w-3.5" aria-hidden />{Math.abs(p)}%<span className="sr-only"> {p >= 0 ? "more" : "fewer"} than before</span></span>;
}

const PERIODS = [[7, "7d"], [30, "30d"], [90, "90d"]] as const;

// ------------------------------------------------------------------------------------------------ score: the hero of the page
const partValue = (p: GrowthPart) => !p.available ? "–" : p.key === "rating" ? (p.number?.toFixed(1) ?? "–") : p.key === "reviews" ? `${p.count}/${p.goal}` : p.key === "replies" ? `${Math.round((p.rate ?? 0) * 100)}%` : p.key === "profile" ? `${p.percent}%` : `${p.top10}/${p.measured}`;
/** What would put a part that has no data yet into the score. A real next step, never a made-up target. */
const UNLOCK: Record<string, string> = { rank: "Track a search word to add Rank to your score", profile: "Complete your Google profile to add Profile to your score", rating: "Your first review adds Rating to your score", reviews: "Set a monthly review goal to add Reviews to your score", replies: "Your first reply adds Replies to your score" };
const parts = (g: GrowthScore): ScorePart[] => g.parts.map((p) => ({ key: p.key, weight: p.weight, available: p.available, value: p.value }));

export function ScoreCard({ g, loading, days, onDays }: { g: GrowthScore | null; loading: boolean; days: number; onDays: (d: 7 | 30 | 90) => void }) {
  const weak = g?.parts.find((p) => p.key === g.weakest);
  const v = g ? scoreVerdict(g.score, parts(g)) : null;
  const missing = g?.parts.find((p) => !p.available);
  const names = v && g ? v.fixes.map((k) => g.parts.find((p) => p.key === k)?.label).filter(Boolean).join(", ") : "";
  const milestone = missing ? { text: UNLOCK[missing.key] ?? `Add ${missing.label} to your score`, href: missing.href } : g && g.score !== null && g.score < 90 ? { text: `Reach 90 (you are at ${g.score})`, href: weak?.href ?? "/overview" } : null;
  return (
    <Card label="Growth score" hero className="!p-5 lg:!p-5">
      <span aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden rounded-[inherit]"><span className="absolute -left-14 -top-20 h-64 w-64 rounded-full bg-[radial-gradient(closest-side,rgb(var(--c-tone-blue)/.16),transparent)]" /></span>
      <div className="relative flex items-center justify-between gap-3">
        <h2 className="text-[15px] font-semibold">Growth score</h2>
        <Segmented options={PERIODS} value={days as 7 | 30 | 90} onChange={onDays} label="Period" />
      </div>
      {loading || !g ? <Skeleton className="relative mt-4 h-[170px]" /> : (
        <div className="relative mt-4 grid items-center gap-5 md:grid-cols-[minmax(0,230px)_minmax(0,1fr)] md:gap-8">
          <div className="flex flex-col items-center gap-3 text-center">
            <Ring value={g.score} size={132} stroke={12} label={g.score === null ? "No score yet" : `Growth score ${g.score} out of 100`}>
              <span><b className="num block text-[44px] font-semibold leading-none tracking-[-.03em]">{g.score === null ? "–" : <CountUp value={g.score} />}</b>{g.partial && g.score !== null && <span className="text-[11px] text-muted">partial</span>}</span>
            </Ring>
            {v && (
              <p className="max-w-[230px] text-[13.5px] leading-snug">
                <b className={clsx("font-semibold", v.tone === "good" ? "text-pos" : v.tone === "fair" ? "text-warn" : "text-neg")}>{v.word}</b>
                {v.fixes.length === 0 ? " — nothing to fix right now" : v.reach ? ` — ${v.fixes.length} ${v.fixes.length === 1 ? "fix" : "fixes"} could take you to ${v.reach}` : ` — ${v.fixes.length} ${v.fixes.length === 1 ? "part needs" : "parts need"} work`}
                {names && <span className="mt-0.5 block text-[12px] text-muted">{names}</span>}
              </p>
            )}
            {weak && <Link href={weak.href} className="btn-glass inline-flex min-h-11 items-center gap-1.5 rounded-full px-3.5 text-[13px] font-semibold md:min-h-9"><Sparkles className="h-3.5 w-3.5" aria-hidden />Improve {weak.label.toLowerCase()}</Link>}
          </div>
          <div className="min-w-0">
            <ul className="grid justify-center gap-1 [grid-template-columns:repeat(auto-fit,minmax(58px,96px))] md:gap-3 md:[grid-template-columns:repeat(auto-fit,minmax(64px,116px))]">
              {g.parts.filter((p) => p.available).map((p) => (
                <li key={p.key} className="min-w-0">
                  <Link href={p.href} aria-label={`${p.label}: ${p.detail}`} className="group flex flex-col items-center gap-1.5 rounded-[16px] px-0.5 py-2.5 transition-[background-color,transform] duration-200 ease-spring hover:-translate-y-0.5 hover:bg-surface-2/70">
                    <Ring value={p.value === null ? null : p.value * 100} size={58} stroke={8} label=""><span className="num text-[13px] font-semibold">{partValue(p)}</span></Ring>
                    <span className={clsx("w-full truncate text-center text-[12.5px] leading-none", p.key === g.weakest ? "font-semibold text-ink" : "text-ink-700")}>{p.label}</span>
                  </Link>
                </li>
              ))}
            </ul>
            {milestone && (
              <Link href={milestone.href} className="mt-3 flex items-center gap-2 rounded-[14px] bg-surface-2/70 px-3 py-2.5 text-[13px] ring-1 ring-line transition-colors hover:bg-surface-2">
                <Flag className="h-4 w-4 shrink-0 text-ink-600" aria-hidden /><span className="min-w-0"><b className="font-semibold">Next milestone</b><span className="text-muted"> · {milestone.text}</span></span>
              </Link>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}

// ------------------------------------------------------------------------------------------------ four numbers, each with its picture, its context and a verdict
const CHIP: Record<"good" | "attention", string> = { good: "bg-pos-tint text-pos", attention: "bg-warn-tint text-warn" };
function Chip({ v }: { v: Verdict }) {
  if (!v) return null;
  const word = v === "good" ? "Good" : "Needs attention";
  return (
    <>
      <span className={clsx("hidden shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold leading-4 sm:inline lg:hidden min-[1280px]:inline", CHIP[v])}>{word}</span>
      <span role="img" aria-label={word} title={word} className={clsx("h-2.5 w-2.5 shrink-0 rounded-full sm:hidden lg:inline-block min-[1280px]:hidden", v === "good" ? "bg-pos" : "bg-warn")} />
    </>
  );
}
function Tile({ label, icon, tone, value, visual, foot, href, verdict, ctx }: { label: string; icon: ReactNode; tone: ToneName; value: ReactNode; visual: ReactNode; foot?: ReactNode; href: string; verdict?: Verdict; ctx?: ReactNode }) {
  return (
    <Link href={href} data-tilt className={clsx("tn tilt t-" + tone, "relative flex min-w-0 flex-col rounded-[20px] p-3.5 lg:p-3.5")}>
      <span className="flex items-center justify-between gap-2">
        <span className="flex min-w-0 items-center gap-2 text-[13px] text-muted"><i aria-hidden className="kic !h-[26px] !w-[26px] !rounded-[8px]">{icon}</i><span className="truncate">{label}</span></span>
        <Chip v={verdict ?? null} />
      </span>
      <span className="mt-2 flex items-baseline gap-2"><span className="num text-[28px] font-semibold leading-9 tracking-[-.025em]">{value}</span>{foot}</span>
      {ctx && <span className="mt-0.5 block truncate text-[12px] leading-4 text-muted">{ctx}</span>}
      <span className="mt-auto pt-2">{visual}</span>
    </Link>
  );
}

const hoursText = (h: number) => (h < 1 ? "<1 h" : h < 48 ? `${Math.round(h)} h` : `${Math.round(h / 24)} d`);

export function Numbers({ o, prev, weekly, loading, days }: { o: Overview | null; prev: Overview | null; weekly: number[]; loading: boolean; days: number }) {
  if (loading || !o) return <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{[0, 1, 2, 3].map((k) => <Skeleton key={k} className="h-[136px] !rounded-[20px]" />)}</div>;
  const r = o.reviews;
  const dist = r.rating_distribution ?? {};
  const peak = Math.max(1, ...Object.values(dist));
  const replied = r.total_synced ? (r.total_synced - r.awaiting_reply) / r.total_synced : null;
  const hrs = r.avg_response_hours;
  const wk = Math.max(1, ...weekly);
  const icn = "h-[15px] w-[15px]";
  const p = prev?.reviews;
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Tile label="Google rating" tone="amber" icon={<Star className={icn} aria-hidden />} href="/reputation/insights" verdict={ratingVerdict(r.average_rating_all_time)}
        ctx={r.average_rating_in_range != null ? `All reviews · ${r.average_rating_in_range.toFixed(1)} in the last ${days} days` : "All reviews"}
        value={r.average_rating_all_time === null ? "–" : <span className="inline-flex items-center gap-1"><CountUp value={r.average_rating_all_time} decimals={1} /><Star className="h-4 w-4 fill-star text-star" aria-hidden /></span>}
        visual={<span aria-hidden className="flex h-6 items-end gap-[3px]">{[1, 2, 3, 4, 5].map((n) => <span key={n} className={clsx("flex-1 rounded-t-[2px]", n >= 4 ? "bg-pos" : n === 3 ? "bg-caution" : "bg-neg")} style={{ height: `${Math.max(6, ((dist[String(n)] ?? 0) / peak) * 100)}%`, opacity: (dist[String(n)] ?? 0) ? 1 : 0.15 }} />)}</span>} />
      <Tile label="New reviews" tone="blue" icon={<MessageSquarePlus className={icn} aria-hidden />} href="/growth" value={<CountUp value={r.new_in_range} />} foot={<Delta cur={r.new_in_range} prev={p?.new_in_range} />}
        verdict={newReviewsVerdict(r.new_in_range, p?.new_in_range)} ctx={p ? `vs ${p.new_in_range} in the ${days} days before` : `Last ${days} days`}
        visual={<span aria-hidden className="flex h-6 items-end gap-[3px]">{weekly.map((v, i) => <span key={i} className="fq-bar flex-1 rounded-t-[2px] bg-chart" style={{ height: `${Math.max(6, (v / wk) * 100)}%`, opacity: v ? 1 : 0.15, animationDelay: `${i * 40}ms` }} />)}</span>} />
      <Tile label="Replied" tone="ok" icon={<Reply className={icn} aria-hidden />} href="/gbp/reviews?state=none" value={replied === null ? "–" : <><CountUp value={Math.round(replied * 100)} />%</>}
        verdict={repliedVerdict(replied)} ctx={r.reply_rate_in_range != null ? `All reviews · ${Math.round(r.reply_rate_in_range * 100)}% in the last ${days} days` : "All reviews"}
        visual={<Meter value={replied} />} />
      <Tile label="Reply time" tone="teal" icon={<Clock className={icn} aria-hidden />} href="/gbp/reviews" verdict={replyTimeVerdict(hrs)}
        ctx={hrs === null ? undefined : p?.avg_response_hours != null ? `Average · ${hoursText(p.avg_response_hours)} in the ${days} days before` : `Average, last ${days} days`}
        value={hrs === null ? "–" : hrs < 1 ? "<1 h" : hrs < 48 ? <><CountUp value={Math.round(hrs)} /> h</> : <><CountUp value={Math.round(hrs / 24)} /> d</>}
        visual={<span aria-hidden className="relative block h-2 rounded-full bg-surface-3">{hrs !== null && <span className={clsx("absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface", hrs <= 24 ? "bg-pos" : hrs <= 72 ? "bg-caution" : "bg-neg")} style={{ left: `${Math.min(100, (Math.log10(Math.max(1, hrs)) / Math.log10(168)) * 100)}%` }} />}</span>} />
    </div>
  );
}

// ------------------------------------------------------------------------------------------------ review growth, by week
export function WeeklyReviews({ o, prev, days, goal, loading }: { o: Overview | null; prev: Overview | null; days: number; goal: number | null; loading: boolean }) {
  const data = useMemo<BarDatum[]>(() => {
    if (!o) return [];
    const size = days <= 7 ? 1 : 7;
    const out: BarDatum[] = [];
    const s = o.reviews.series, p = prev?.reviews.series ?? [];
    for (let i = 0; i < s.length; i += size) {
      const cur = s.slice(i, i + size).reduce((a, x) => a + (Number(x.count) || 0), 0);
      const before = p.length ? p.slice(i, i + size).reduce((a, x) => a + (Number(x.count) || 0), 0) : null;
      const d = new Date(s[i].date + "T00:00:00");
      out.push({ key: s[i].date, cur, prev: before, label: d.toLocaleDateString("en-IN", size === 1 ? { weekday: "short" } : { day: "numeric", month: "short" }), tip: size === 1 ? d.toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "short" }) : `Week of ${d.toLocaleDateString("en-IN", { day: "numeric", month: "short" })}` });
    }
    return out;
  }, [o, prev, days]);
  const perBar = goal ? (days <= 7 ? goal / 30 : (goal * 7) / 30) : null;
  const insight = o ? reviewInsight(o.reviews.new_in_range, prev ? prev.reviews.new_in_range : null, days) : null;
  return (
    <Card label="New reviews by week">
      <Title>{days <= 7 ? "New reviews by day" : "New reviews by week"}</Title>
      {insight && <p className="mt-1 text-[13.5px] font-medium text-ink-700">{insight}</p>}
      <div className="mt-3">{loading || !o ? <Skeleton className="h-[160px]" /> : <Bars data={data} height={150} prevAsLine goal={perBar ? Math.round(perBar * 10) / 10 : null} goalLabel="Goal" label={`New Google reviews per ${days <= 7 ? "day" : "week"}, this period and the one before`} />}</div>
    </Card>
  );
}

// ------------------------------------------------------------------------------------------------ do this week: never empty
const MOVES: Todo[] = [
  { id: "m-link", tone: "info", title: "Send your review link", detail: "", href: "/growth", cta: "Send link" },
  { id: "m-card", tone: "info", title: "Put a card at the counter", detail: "", href: "/gbp/cards", cta: "Set up card" },
  { id: "m-photos", tone: "info", title: "Add recent photos", detail: "", href: "/gbp/photos", cta: "Add photos" },
  { id: "m-words", tone: "info", title: "Track a search word", detail: "", href: "/seo/rankings", cta: "Add a word" },
];
/** Which part of the Growth score a to-do works on, from where it leads. Only where the link is unambiguous; everything else carries no score tag. */
const PART_OF = (href: string): string | null => (href.startsWith("/gbp/reviews") ? "replies" : href.startsWith("/seo/rankings") ? "rank" : href.startsWith("/gbp/info") || href.startsWith("/gbp/photos") || href.startsWith("/seo/profile") ? "profile" : href.startsWith("/growth") ? "reviews" : null);

export function DoThisWeek({ todos, hasCard, loading, g }: { todos: Todo[]; hasCard: boolean; loading: boolean; g?: GrowthScore | null }) {
  const list = [...todos, ...MOVES.filter((m) => !(m.id === "m-card" && hasCard))].filter((t, i, a) => a.findIndex((x) => x.href === t.href) === i).slice(0, 3);
  const ps = g ? parts(g) : null;
  return (
    <Card label="Do this week" className="h-full">
      <Title>Do this week</Title>
      {loading ? <Skeleton className="mt-3 h-[150px]" /> : (
        <ol className="mt-3 space-y-2">
          {list.map((t, i) => {
            const key = PART_OF(t.href), lift = key && ps && g ? liftOf(g.score, ps, key) : 0;
            const label = key ? g?.parts.find((p) => p.key === key)?.label : null;
            return (
              <li key={t.id} className={clsx("flex items-center gap-3 rounded-[16px] p-2.5 pl-3 transition-colors", i === 0 ? "bg-surface-2 ring-1 ring-line" : "bg-surface-2/60 hover:bg-surface-2")}>
                <span aria-hidden className={clsx("num grid h-6 w-6 shrink-0 place-items-center rounded-full text-[12px] font-semibold", i === 0 ? "bg-ink-solid text-ink-on" : "bg-surface text-ink-700 shadow-pill")}>{i + 1}</span>
                <span className="min-w-0 flex-1">
                  <span className="line-clamp-2 block text-[14px] font-medium leading-5">{t.title}{t.tone === "bad" && <span className="sr-only"> (urgent)</span>}</span>
                  <span className="mt-1 flex flex-wrap items-center gap-1.5">
                    {lift > 0 && <span className="rounded-full bg-pos-tint px-2 py-0.5 text-[11px] font-semibold leading-4 text-pos" title={`${label} at full marks would add up to ${lift} to the score`}>{label} · up to +{lift}</span>}
                    <span className={clsx("rounded-full px-2 py-0.5 text-[11px] font-medium leading-4", t.state === "In progress" ? "bg-chart/15 text-chart" : "bg-surface text-muted ring-1 ring-line")}>{t.state ?? "To do"}</span>
                  </span>
                </span>
                {i === 0
                  ? <Link href={t.href} className={buttonClass("brand", "sm", "shrink-0")}>{t.cta}</Link>
                  : <Link href={t.href} aria-label={t.cta} title={t.cta} className="btn-glass group grid h-11 w-11 shrink-0 place-items-center rounded-full transition-transform duration-200 ease-spring hover:translate-x-0.5 md:h-9 md:w-9"><ArrowRight className="h-4 w-4" aria-hidden /></Link>}
              </li>
            );
          })}
        </ol>
      )}
    </Card>
  );
}

// ------------------------------------------------------------------------------------------------ cards to Google: four steps
const STEPS: [string, string][] = [["scans", "Scans"], ["feedback_submitted", "Feedback"], ["drafts_approved", "Approved"], ["google_redirects", "To Google"]];
export function FunnelStrip({ steps, hasCard, loading }: { steps: FunnelStep[] | null; hasCard: boolean; loading: boolean }) {
  const [info, setInfo] = useState(false);
  const vals = STEPS.map(([k, l]) => [l, steps?.find((s) => s.key === k)?.count ?? 0] as const);
  const top = Math.max(1, ...vals.map((v) => v[1]));
  const empty = !hasCard && vals.every((v) => !v[1]);
  return (
    <Card label="Cards to Google">
      <Title right={<button type="button" aria-label="What counts as a review" aria-expanded={info} onClick={() => setInfo((v) => !v)} className="grid h-11 w-11 place-items-center rounded-full text-muted hover:bg-surface-2 md:h-8 md:w-8"><Info className="h-4 w-4" aria-hidden /></button>}>Cards to Google</Title>
      {info && <p className="mt-1 text-[13px] text-muted">A tap on To Google is not a review. Reviews are counted from Google.</p>}
      {loading ? <Skeleton className="mt-3 h-[110px]" /> : (
        <>
          <ol className="mt-3 grid grid-cols-4 gap-2" aria-label="From card scan to Google">
            {vals.map(([l, v], i) => (
              <li key={l} className="min-w-0">
                <span className="num block text-[20px] font-semibold leading-7">{empty ? "–" : fmtNum(v)}</span>
                <span aria-hidden className="mt-1 flex h-12 items-end rounded-[6px] bg-surface-2"><span className={clsx("fq-bar w-full rounded-[6px]", empty ? "h-[2px] bg-ink-300" : "bg-chart")} style={empty ? undefined : { height: `${Math.max(4, (v / top) * 100)}%`, opacity: 1 - i * 0.15 }} /></span>
                <span className="mt-1 block truncate text-[12px] text-muted">{l}</span>
              </li>
            ))}
          </ol>
          {empty && <Link href="/gbp/cards" className="mt-3 inline-flex min-h-11 items-center gap-1.5 rounded-[10px] px-3 text-[13px] font-semibold ring-1 ring-line hover:bg-surface-2 md:min-h-9"><QrCode className="h-4 w-4" aria-hidden />Set up a QR card<ChevronRight className="h-3.5 w-3.5" aria-hidden /></Link>}
        </>
      )}
    </Card>
  );
}
