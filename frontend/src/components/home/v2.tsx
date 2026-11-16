"use client";
import clsx from "clsx";
import { ArrowDownRight, ArrowUpRight, ChevronRight, Info, Minus, QrCode, Star } from "lucide-react";
import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";
import { Bars, Meter, Ring, type BarDatum } from "@/components/charts/Bars";
import { Skeleton } from "@/components/ui/Card";
import type { Todo } from "@/lib/dashboard";
import { fmtNum } from "@/lib/format";
import type { Overview } from "@/lib/types";

export interface GrowthPart { key: string; label: string; weight: number; available: boolean; value: number | null; detail: string | null; href: string; count?: number; goal?: number; goal_set?: boolean; days_left?: number; to_go?: number; rate?: number; hours?: number | null; number?: number; percent?: number; top10?: number; measured?: number }
export interface GrowthScore { score: number | null; partial: boolean; covered_weight: number; parts: GrowthPart[]; weakest: string | null; note: string }
export interface FunnelStep { key: string; label: string; count: number }

export const Card = ({ children, className, label }: { children: ReactNode; className?: string; label?: string }) => <section aria-label={label} className={clsx("rounded-[16px] bg-surface p-4 shadow-card lg:p-5", className)}>{children}</section>;
export const Title = ({ children, right }: { children: ReactNode; right?: ReactNode }) => <div className="flex items-center justify-between gap-3"><h2 className="text-[15px] font-semibold">{children}</h2>{right}</div>;

function Delta({ cur, prev }: { cur: number | null | undefined; prev: number | null | undefined }) {
  if (cur == null || prev == null || prev === 0) return null;
  const p = Math.round(((cur - prev) / prev) * 100);
  const Icon = p > 0 ? ArrowUpRight : p < 0 ? ArrowDownRight : Minus;
  return <span className={clsx("inline-flex items-center gap-0.5 text-[13px] font-medium", p > 0 ? "text-pos" : p < 0 ? "text-neg" : "text-muted")}><Icon className="h-3.5 w-3.5" aria-hidden />{Math.abs(p)}%<span className="sr-only"> {p >= 0 ? "more" : "fewer"} than before</span></span>;
}

const PERIODS = [[7, "7d"], [30, "30d"], [90, "90d"]] as const;

// ------------------------------------------------------------------------------------------------ score
export function ScoreCard({ g, loading, days, onDays }: { g: GrowthScore | null; loading: boolean; days: number; onDays: (d: 7 | 30 | 90) => void }) {
  const weak = g?.parts.find((p) => p.key === g.weakest);
  return (
    <Card label="Growth score">
      <Title right={
        <div role="radiogroup" aria-label="Period" className="flex rounded-[10px] bg-surface-2 p-0.5">
          {PERIODS.map(([d, l]) => <button key={d} role="radio" aria-checked={days === d} onClick={() => onDays(d)} className={clsx("min-w-11 rounded-[8px] px-2 text-[13px] font-medium md:!min-h-8", days === d ? "bg-surface text-ink shadow-card" : "text-muted")}>{l}</button>)}
        </div>}>Growth score</Title>
      {loading || !g ? <Skeleton className="mt-3 h-[150px]" /> : (
        <div className="mt-3 grid grid-cols-[auto_minmax(0,1fr)] items-center gap-4 md:gap-6">
          <div className="flex flex-col items-center gap-1">
            <Ring value={g.score} size={96} label={g.score === null ? "No score yet" : `Growth score ${g.score} out of 100`}>
              <span><b className="num block text-[32px] font-semibold leading-none tracking-[-.02em]">{g.score ?? "–"}</b>{g.partial && g.score !== null && <span className="text-[11px] text-muted">partial</span>}</span>
            </Ring>
            {weak && <p className="max-w-[110px] text-center text-[12px] leading-4 text-muted">{weak.label} is lowest</p>}
          </div>
          <ul className="min-w-0 space-y-1.5">
            {g.parts.map((p) => (
              <li key={p.key}>
                <Link href={p.href} className="group grid grid-cols-[3.9rem_minmax(0,1fr)_auto] items-center gap-2 rounded-[8px] py-0.5 text-[13px] hover:bg-surface-2 md:grid-cols-[4.5rem_minmax(0,1fr)_7rem]" aria-label={`${p.label}: ${p.available ? p.detail : "no data yet"}`}>
                  <span className={clsx(p.key === g.weakest ? "font-semibold" : "text-ink-700")}>{p.label}</span>
                  <Meter value={p.available ? p.value : null} />
                  <span className="num truncate text-right text-[12px] text-muted md:text-[13px]">{!p.available ? "–" : p.key === "rating" ? p.number?.toFixed(1) : p.key === "reviews" ? `${p.count}/${p.goal}` : p.key === "replies" ? `${Math.round((p.rate ?? 0) * 100)}%` : p.key === "profile" ? `${p.percent}%` : `${p.top10}/${p.measured}`}</span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}

// ------------------------------------------------------------------------------------------------ four numbers, each with its picture
function Tile({ label, value, visual, foot, href }: { label: string; value: ReactNode; visual: ReactNode; foot?: ReactNode; href: string }) {
  return (
    <Link href={href} className="flex min-w-0 flex-col rounded-[16px] bg-surface p-3.5 shadow-card transition-transform hover:-translate-y-0.5 lg:p-4">
      <span className="text-[13px] text-muted">{label}</span>
      <span className="mt-0.5 flex items-baseline gap-2"><span className="num text-[24px] font-semibold leading-8 tracking-[-.02em]">{value}</span>{foot}</span>
      <span className="mt-auto pt-2">{visual}</span>
    </Link>
  );
}

export function Numbers({ o, prev, weekly, loading }: { o: Overview | null; prev: Overview | null; weekly: number[]; loading: boolean }) {
  if (loading || !o) return <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{[0, 1, 2, 3].map((k) => <Skeleton key={k} className="h-[108px] !rounded-[16px]" />)}</div>;
  const r = o.reviews;
  const dist = r.rating_distribution ?? {};
  const peak = Math.max(1, ...Object.values(dist));
  const replied = r.total_synced ? (r.total_synced - r.awaiting_reply) / r.total_synced : null;
  const hrs = r.avg_response_hours;
  const wk = Math.max(1, ...weekly);
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Tile label="Google rating" href="/reputation/insights" value={r.average_rating_all_time === null ? "–" : <span className="inline-flex items-center gap-1">{r.average_rating_all_time.toFixed(1)}<Star className="h-4 w-4 fill-star text-star" aria-hidden /></span>}
        visual={<span aria-hidden className="flex h-6 items-end gap-[3px]">{[1, 2, 3, 4, 5].map((n) => <span key={n} className={clsx("flex-1 rounded-t-[2px]", n >= 4 ? "bg-pos" : n === 3 ? "bg-caution" : "bg-neg")} style={{ height: `${Math.max(6, ((dist[String(n)] ?? 0) / peak) * 100)}%`, opacity: (dist[String(n)] ?? 0) ? 1 : 0.15 }} />)}</span>} />
      <Tile label="New reviews" href="/growth" value={fmtNum(r.new_in_range)} foot={<Delta cur={r.new_in_range} prev={prev?.reviews.new_in_range} />}
        visual={<span aria-hidden className="flex h-6 items-end gap-[3px]">{weekly.map((v, i) => <span key={i} className="flex-1 rounded-t-[2px] bg-chart" style={{ height: `${Math.max(6, (v / wk) * 100)}%`, opacity: v ? 1 : 0.15 }} />)}</span>} />
      <Tile label="Replied" href="/gbp/reviews?state=none" value={replied === null ? "–" : `${Math.round(replied * 100)}%`} visual={<Meter value={replied} />} />
      <Tile label="Reply time" href="/gbp/reviews" value={hrs === null ? "–" : hrs < 1 ? "<1 h" : hrs < 48 ? `${Math.round(hrs)} h` : `${Math.round(hrs / 24)} d`}
        visual={<span aria-hidden className="relative block h-2 rounded-full bg-surface-3">{hrs !== null && <span className={clsx("absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface", hrs <= 24 ? "bg-pos" : hrs <= 72 ? "bg-caution" : "bg-neg")} style={{ left: `${Math.min(100, (Math.log10(Math.max(1, hrs)) / Math.log10(168)) * 100)}%` }} />}<span className="absolute -bottom-3.5 left-0 text-[10px] text-muted">1h</span><span className="absolute -bottom-3.5 right-0 text-[10px] text-muted">1wk</span></span>} />
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
  return (
    <Card label="New reviews by week">
      <Title>{days <= 7 ? "New reviews by day" : "New reviews by week"}</Title>
      <div className="mt-4">{loading || !o ? <Skeleton className="h-[200px]" /> : <Bars data={data} goal={perBar ? Math.round(perBar * 10) / 10 : null} goalLabel="Goal" label={`New Google reviews per ${days <= 7 ? "day" : "week"}, this period and the one before`} />}</div>
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
export function DoThisWeek({ todos, hasCard, loading }: { todos: Todo[]; hasCard: boolean; loading: boolean }) {
  const list = [...todos, ...MOVES.filter((m) => !(m.id === "m-card" && hasCard))].filter((t, i, a) => a.findIndex((x) => x.href === t.href) === i).slice(0, 3);
  return (
    <Card label="Do this week">
      <Title>Do this week</Title>
      {loading ? <Skeleton className="mt-3 h-[150px]" /> : (
        <ol className="mt-2 divide-y divide-line">
          {list.map((t, i) => (
            <li key={t.id} className="flex items-center gap-3 py-2.5">
              <span aria-hidden className={clsx("num grid h-7 w-7 shrink-0 place-items-center rounded-full text-[13px] font-semibold", i === 0 ? "bg-accent-ink text-on-accent" : "bg-surface-2 text-ink-700")}>{i + 1}</span>
              <span className="min-w-0 flex-1 text-[14px] font-medium leading-5">{t.title}{t.tone === "bad" && <span className="sr-only"> (urgent)</span>}</span>
              <Link href={t.href} className={clsx("inline-flex min-h-11 shrink-0 items-center rounded-[10px] px-3 text-[13px] font-semibold md:min-h-9", i === 0 ? "bg-ink-solid text-ink-on" : "ring-1 ring-line hover:bg-surface-2")}>{t.cta}</Link>
            </li>
          ))}
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
