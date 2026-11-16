"use client";
import clsx from "clsx";
import {
  AlertTriangle, ArrowDownRight, ArrowRight, ArrowUpRight, Check, Clock, Lightbulb, Link2, ListFilter, MessageSquare, Minus,
  MousePointerClick, ScanLine, Search, Sparkles, Star,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { Sparkline } from "@/components/charts/Sparkline";
import { LinkButton } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Card";
import { useToast } from "@/components/ui/Toast";
import { api } from "@/lib/api";
import type { GoogleStored, Todo } from "@/lib/dashboard";
import { fmtDate, fmtHours, fmtNum, fmtRating } from "@/lib/format";
import type { Insights, Location, Overview, Review } from "@/lib/types";

// ------------------------------------------------------------------------------------------ small pieces

const reduced = () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Counts up to the value over 900 ms (DESIGN.md §8). Screen readers get the final value only; reduced motion shows it at once. */
export function CountUp({ value, format = fmtNum }: { value: number; format?: (n: number) => string }) {
  const [v, setV] = useState(() => (reduced() ? value : 0));
  const from = useRef(reduced() ? value : 0);
  useEffect(() => {
    if (reduced()) { setV(value); from.current = value; return; }
    const start = from.current, t0 = performance.now();
    let raf = 0;
    const tick = (t: number) => {
      const p = Math.min(1, (t - t0) / 900), e = 1 - Math.pow(1 - p, 3);
      setV(start + (value - start) * e);
      if (p < 1) raf = requestAnimationFrame(tick); else from.current = value;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value]);
  return <><span aria-hidden>{format(v)}</span><span className="sr-only">{format(value)}</span></>;
}

/** Card shell for the overview grid: reveal blur-to-sharp with a stagger, optional hover lift (only when the whole card is a target). */
export function Tile({ children, className, i = 0, lift, label, labelledBy, dense }: { children: ReactNode; className?: string; i?: number; lift?: boolean; label?: string; labelledBy?: string; dense?: boolean }) {
  return (
    <section aria-label={label} aria-labelledby={labelledBy} style={{ "--d": `${i * 60}ms` } as CSSProperties}
      className={clsx("panel rv min-w-0", dense ? "!rounded-[16px] p-4" : "p-5 sm:p-6", lift && "lift", className)}>{children}</section>
  );
}

export function TileHead({ id, title, sub, right }: { id: string; title: string; sub?: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0"><h2 id={id} className="text-lg font-semibold leading-6">{title}</h2>{sub && <p className="mt-0.5 text-sm text-muted">{sub}</p>}</div>
      {right}
    </div>
  );
}

type Kind = "pct" | "abs" | "pts";
/** The change against the previous period, as a pill with an arrow and words for screen readers. `null` when there is nothing to compare. */
function change(cur: number | null | undefined, prev: number | null | undefined, kind: Kind) {
  if (cur === null || cur === undefined || prev === null || prev === undefined) return null;
  const diff = cur - prev;
  if (kind === "pct") {
    if (prev <= 0) return cur > 0 ? { dir: "up" as const, text: "new" } : null;
    const p = Math.round((diff / prev) * 100);
    return { dir: p > 0 ? "up" as const : p < 0 ? "down" as const : "flat" as const, text: `${Math.abs(p)}%` };
  }
  if (kind === "pts") { const p = Math.round(diff * 100); return { dir: p > 0 ? "up" as const : p < 0 ? "down" as const : "flat" as const, text: `${Math.abs(p)} pts` }; }
  const r = Math.round(diff * 10) / 10;
  return { dir: r > 0 ? "up" as const : r < 0 ? "down" as const : "flat" as const, text: Math.abs(r).toFixed(1) };
}

export function DeltaChip({ cur, prev, kind, days, onHero }: { cur: number | null | undefined; prev: number | null | undefined; kind: Kind; days: number; onHero?: boolean }) {
  const c = change(cur, prev, kind);
  if (!c) return <span className={clsx("text-xs", onHero ? "scrim" : "text-muted")}>Nothing earlier to compare</span>;
  const Icon = c.dir === "up" ? ArrowUpRight : c.dir === "down" ? ArrowDownRight : Minus;
  const words = `${c.dir === "up" ? "Up" : c.dir === "down" ? "Down" : "No change,"} ${c.dir === "flat" ? "" : c.text} compared with the previous ${days} days`;
  return (
    <span title={words} className={clsx("inline-flex h-6 shrink-0 items-center gap-1 rounded-full px-2 text-xs font-semibold",
      onHero ? "bg-[rgba(19,16,20,.32)] text-pure-white" : c.dir === "up" ? "bg-pos-tint text-pos" : c.dir === "down" ? "bg-neg-tint text-neg" : "bg-surface-2 text-muted")}>
      <Icon className="h-3 w-3" strokeWidth={2.5} aria-hidden /><span aria-hidden>{c.text}</span><span className="sr-only">{words}</span>
    </span>
  );
}

const StarFill = ({ className }: { className?: string }) => <Star className={clsx("fill-accent text-accent", className)} aria-hidden />;

// ------------------------------------------------------------------------------------------ 1. average rating + locations

export function RatingCard({ o, prev, locs, days, loading, googleConnected }: {
  o: Overview | null; prev: Overview | null; locs: Location[]; days: number; loading: boolean; googleConnected: boolean;
}) {
  const toast = useToast();
  const link = locs.find((l) => l.is_active && l.review_url)?.review_url ?? null;
  const share = async () => {
    if (!link) return;
    try { await navigator.clipboard.writeText(link); toast("Review link copied"); } catch { toast("Couldn't copy. Open Locations to copy it.", "error"); }
  };
  const avg = o?.reviews.average_rating_all_time ?? null;
  const awaiting = o?.reviews.awaiting_reply ?? 0;
  const syncBy = new Map((o?.sync ?? []).map((s) => [s.location, s]));
  const rows = o?.locations ?? [];
  return (
    <Tile i={0} labelledBy="ov-rating">
      <div className="flex items-start justify-between gap-3">
        <h2 id="ov-rating" className="text-sm font-medium text-muted">Average Google rating</h2>
        <span className="text-xs text-muted">All time</span>
      </div>
      {loading || !o ? <Skeleton className="mt-3 h-24" /> : (
        <>
          <div className="mt-2 grid grid-cols-[auto_minmax(0,1fr)] items-center gap-5">
            <p className="num flex items-center gap-2 text-[44px] font-semibold leading-[48px] tracking-[-.03em]">
              {avg === null ? "–" : <CountUp value={avg} format={(n) => fmtRating(n)} />}{avg !== null && <StarFill className="h-8 w-8" />}
            </p>
            {avg !== null && (
              <ul className="min-w-0 space-y-1" aria-label="How many reviews gave each rating">
                {[5, 4, 3, 2, 1].map((n) => {
                  const c = o.reviews.rating_distribution?.[String(n)] ?? 0, peak = Math.max(1, ...Object.values(o.reviews.rating_distribution ?? {}));
                  return (
                    <li key={n} className="grid grid-cols-[1.1rem_minmax(0,1fr)_1.6rem] items-center gap-1.5 text-[11px] text-muted">
                      <span className="num text-right font-medium">{n}★</span>
                      <span aria-hidden className="h-1.5 overflow-hidden rounded-full bg-surface-2"><span className="grow-x block h-full rounded-full bg-gradient-to-r from-accent-hi to-accent" style={{ width: `${(c / peak) * 100}%`, "--d": `${(5 - n) * 60}ms` } as CSSProperties} /></span>
                      <span className="num text-right font-medium text-ink">{c}</span>
                    </li>);
                })}
              </ul>
            )}
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {o.reviews.new_in_range > 0 && <DeltaChip cur={o.reviews.average_rating_in_range} prev={prev?.reviews.new_in_range ? prev.reviews.average_rating_in_range : null} kind="abs" days={days} />}
            <span className="text-xs text-muted">
              {avg === null ? (googleConnected ? "No Google reviews synced yet" : "Connect Google to see your rating")
                : `${o.reviews.new_in_range > 0 ? `New reviews averaged ${fmtRating(o.reviews.average_rating_in_range)} · ` : ""}${fmtNum(o.reviews.total_synced)} Google reviews`}
            </span>
          </div>
        </>
      )}
      <div className="mt-5 grid grid-cols-2 gap-3">
        <LinkButton href="/gbp/reviews?state=none" icon={<MessageSquare className="h-4 w-4" aria-hidden />}>{awaiting > 0 ? `Reply · ${fmtNum(awaiting)}` : "Reviews"}</LinkButton>
        {link ? <button type="button" onClick={() => void share()} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-full bg-surface-2 px-4 text-sm font-semibold transition-colors hover:bg-surface-3"><Link2 className="h-4 w-4" aria-hidden />Share link</button>
          : <LinkButton href="/gbp/locations" variant="secondary" icon={<Link2 className="h-4 w-4" aria-hidden />}>Add link</LinkButton>}
      </div>
      <div className="well mt-5 p-4">
        <p className="text-xs text-muted"><b className="font-semibold text-ink">Locations</b><span className="mx-2" aria-hidden>|</span>{rows.length} {rows.length === 1 ? "location" : "locations"}</p>
        {loading || !o ? <Skeleton className="mt-3 h-20" /> : rows.length === 0 ? <p className="mt-2 text-sm text-muted">No locations yet. <Link href="/gbp/locations" className="font-semibold text-accent-ink hover:underline">Add one</Link></p> : (
          <ul className="mt-3 grid grid-cols-2 gap-2.5 min-[420px]:grid-cols-3">
            {rows.slice(0, 3).map((l) => {
              const s = syncBy.get(l.location);
              const st = !s ? ["Not connected", "text-muted"] : s.status && s.status !== "ok" && s.status !== "running" ? ["Reconnect", "text-neg"] : ["Active", "text-pos"];
              return (
                <li key={l.location} className="min-w-0 rounded-inner bg-surface p-3">
                  <p className="truncate font-semibold" title={l.location}>{l.location}</p>
                  <p className="mt-1.5 flex items-center gap-1 text-lg font-semibold leading-6">{l.avg_rating === null ? "–" : fmtRating(l.avg_rating)}{l.avg_rating !== null && <StarFill className="h-3.5 w-3.5" />}</p>
                  <p className="truncate text-xs text-muted">{fmtNum(l.new_reviews)} new</p>
                  <p className={clsx("mt-1.5 flex items-center gap-1.5 text-xs font-medium", st[1])}><span aria-hidden className="h-1.5 w-1.5 rounded-full bg-current" />{st[0]}</p>
                </li>
              );
            })}
          </ul>
        )}
        {rows.length > 3 && <Link href="/analytics/reports" className="mt-3 inline-flex min-h-9 items-center gap-1 text-[13px] font-semibold text-accent-ink hover:underline">Compare all {rows.length} locations<ArrowRight className="h-3.5 w-3.5" aria-hidden /></Link>}
      </div>
    </Tile>
  );
}

// ------------------------------------------------------------------------------------------ 2. the four key numbers

/** A circular gauge. The number beside or inside it says the same thing, so the ring is decorative unless it is given a label. `marker` (0-100) puts a dot where a steady pace would be. */
function Ring({ pct, size = 120, stroke = 10, label, children, marker }: { pct: number; size?: number; stroke?: number; label?: string; children?: ReactNode; marker?: number }) {
  const r = (size - stroke) / 2, c = 2 * Math.PI * r, p = Math.max(0, Math.min(100, pct)), gid = `ring-${size}-${stroke}`;
  const ang = marker !== undefined ? (Math.max(0, Math.min(100, marker)) / 100) * 2 * Math.PI : null;
  return (
    <span className="relative inline-grid shrink-0 place-items-center text-ink" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role={label ? "img" : undefined} aria-label={label} aria-hidden={label ? undefined : true} className="-rotate-90 overflow-visible">
        <defs><linearGradient id={gid} x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stopColor="rgb(var(--c-accent-hi))" /><stop offset="100%" stopColor="rgb(var(--c-accent-lo))" /></linearGradient></defs>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="currentColor" strokeOpacity=".1" strokeWidth={stroke} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={`url(#${gid})`} strokeWidth={stroke} strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - p / 100)} style={{ transition: "stroke-dashoffset .9s cubic-bezier(.2,.7,.2,1)" }} />
        {ang !== null && <circle cx={size / 2 + r * Math.cos(ang)} cy={size / 2 + r * Math.sin(ang)} r={stroke / 2 + 1} fill="rgb(var(--c-surface))" stroke="rgb(var(--c-ink-solid))" strokeWidth="2" />}
      </svg>
      {children && <span className="absolute inset-0 grid place-items-center text-center">{children}</span>}
    </span>
  );
}

function StatTile({ hero, label, icon, href, value, foot, i, spark }: { hero?: boolean; label: string; icon: ReactNode; href: string; value: ReactNode; foot: ReactNode; i: number; spark?: ReactNode }) {
  return (
    <div style={{ "--d": `${80 + i * 50}ms` } as CSSProperties}
      className={clsx("rv lift relative flex min-h-[168px] min-w-0 flex-col justify-between overflow-hidden rounded-tile p-4 sm:min-h-[176px] sm:p-[18px]", hero ? "hero-grad" : "bg-surface-2 ring-1 ring-ink-100")}>
      <div className="flex items-center justify-between gap-2">
        <span className={clsx("min-w-0 font-medium leading-tight", hero && "scrim !h-auto !rounded-xl !px-2.5 !py-0.5 !text-[13px] !font-semibold")}>{label}</span>
        <Link href={href} aria-label={`Open ${label}`} className={clsx("grid h-11 w-11 shrink-0 place-items-center rounded-full transition-colors sm:h-9 sm:w-9", hero ? "bg-white/20 text-pure-white hover:bg-white/30" : "bg-accent-tint text-accent-ink hover:bg-accent-edge/60")}>{icon}</Link>
      </div>
      <div className="my-3 flex items-end justify-between gap-2">
        <div className={clsx("num font-semibold tracking-[-.02em]", hero ? "text-[40px] leading-[44px] sm:text-[44px] sm:leading-[46px]" : "text-[30px] leading-9 sm:text-[34px] sm:leading-[38px]")}>{value}</div>
        {spark && <div className={clsx("hidden shrink-0 pb-1 min-[380px]:block", hero ? "text-white/90" : "text-accent")}>{spark}</div>}
      </div>
      <div className="flex flex-wrap items-center gap-2">{foot}</div>
    </div>
  );
}

export function KeyTiles({ o, prev, google, days, loading }: { o: Overview | null; prev: Overview | null; google: GoogleStored; days: number; loading: boolean }) {
  const ic = "h-[17px] w-[17px]";
  if (loading || !o) return <Tile i={1} label="Key numbers"><div className="grid grid-cols-2 gap-3 sm:gap-4">{[0, 1, 2, 3].map((k) => <Skeleton key={k} className="h-[168px] !rounded-tile" />)}</div></Tile>;
  const r = o.reviews, e = o.engagement;
  return (
    <Tile i={1} label="Key numbers" className="!p-4 sm:!p-5">
      <div className="grid h-full grid-cols-2 gap-3 sm:gap-4">
        <StatTile hero i={0} label="New reviews" href="/gbp/reviews" icon={<Star className={ic} strokeWidth={1.75} aria-hidden />} value={<CountUp value={r.new_in_range} />} spark={<Sparkline id="sp-rev" values={r.series.map((p) => Number(p.count) || 0)} />}
          foot={<><DeltaChip onHero cur={r.new_in_range} prev={prev?.reviews.new_in_range} kind="pct" days={days} /><span className="scrim">Last {days} days</span></>} />
        <StatTile i={1} label="Reply rate" href="/gbp/reviews?state=none" icon={<MessageSquare className={ic} strokeWidth={1.75} aria-hidden />}
          value={r.reply_rate_in_range === null ? "–" : <CountUp value={Math.round(r.reply_rate_in_range * 100)} format={(n) => `${Math.round(n)}%`} />}
          spark={r.reply_rate_in_range === null ? undefined : <Ring pct={r.reply_rate_in_range * 100} size={46} stroke={6} label={`${Math.round(r.reply_rate_in_range * 100)}% of new reviews answered`} />}
          foot={r.reply_rate_in_range === null ? <span className="text-xs text-muted">No new reviews to answer</span>
            : <><DeltaChip cur={r.reply_rate_in_range} prev={prev?.reviews.reply_rate_in_range} kind="pts" days={days} />{r.avg_response_hours !== null && <span className="text-xs text-muted">Avg {fmtHours(Math.round(r.avg_response_hours))}</span>}</>} />
        <StatTile i={2} label="Waiting for a reply" href="/gbp/reviews?state=none" icon={<MessageSquare className={ic} strokeWidth={1.75} aria-hidden />}
          value={<CountUp value={r.awaiting_reply} />}
          foot={r.awaiting_reply === 0 ? <span className="text-xs text-muted">Every review is answered</span> : <span className="text-xs text-muted">Replies need your approval</span>} />
        <StatTile i={3} label="Card scans" href="/gbp/cards" icon={<ScanLine className={ic} strokeWidth={1.75} aria-hidden />}
          value={o.cards.length === 0 ? "–" : <CountUp value={e.scans} />} spark={o.cards.length === 0 ? undefined : <Sparkline id="sp-scan" values={e.series.map((p) => Number(p.scan) || 0)} />}
          foot={o.cards.length === 0 ? <Link href="/gbp/cards" className="text-xs font-semibold text-accent-ink hover:underline">No card yet</Link>
            : <><DeltaChip cur={e.scans} prev={prev?.engagement.scans} kind="pct" days={days} /><span className="text-xs text-muted">QR + NFC</span></>} />
      </div>
    </Tile>
  );
}

// ------------------------------------------------------------------------------------------ 3. review trend (stacked bars)

type Bucket = { label: string; from: string; total: number; low: number; avg: number | null };
/** Days for 7, weeks otherwise. Average rating is weighted by review count. */
function buckets(series: Overview["reviews"]["series"], days: number): Bucket[] {
  const size = days <= 7 ? 1 : 7;
  const out: Bucket[] = [];
  for (let i = 0; i < series.length; i += size) {
    const chunk = series.slice(i, i + size);
    const total = chunk.reduce((a, p) => a + (Number(p.count) || 0), 0);
    const low = chunk.reduce((a, p) => a + (Number(p.low_count) || 0), 0);
    const sum = chunk.reduce((a, p) => a + (Number(p.avg_rating) || 0) * (Number(p.count) || 0), 0);
    const d = new Date(chunk[0].date + "T00:00:00");
    out.push({ from: chunk[0].date, label: d.toLocaleDateString("en-IN", size === 1 ? { weekday: "short" } : { day: "2-digit", month: "short" }), total, low, avg: total ? sum / total : null });
  }
  return out;
}
const niceMax = (v: number) => { if (v <= 4) return 4; const step = v <= 20 ? 5 : v <= 40 ? 10 : Math.pow(10, Math.floor(Math.log10(v))) / 2; return Math.ceil(v / step / 4) * step * 4; };

export function ReviewTrend({ o, days, loading, googleConnected }: { o: Overview | null; days: number; loading: boolean; googleConnected: boolean }) {
  const [hover, setHover] = useState<number | null>(null);
  const data = useMemo(() => (o ? buckets(o.reviews.series, days) : []), [o, days]);
  const split = !!o && o.reviews.series.some((p) => p.low_count !== undefined);
  const W = 340, H = 236, L = 30, B = 26, T = 10;
  const max = niceMax(Math.max(1, ...data.map((d) => d.total)));
  const pitch = (W - L - 4) / Math.max(1, data.length), bw = Math.min(26, pitch * 0.62);
  const y = (v: number) => T + (H - B - T) * (1 - v / max);
  const every = data.length > 8 ? 2 : 1;
  const empty = !!o && data.every((d) => d.total === 0);
  const sum = data.reduce((a, d) => a + d.total, 0);
  const best = data.reduce<Bucket | null>((b, d) => (d.total > (b?.total ?? 0) ? d : b), null);
  const wavg = sum ? data.reduce((a, d) => a + (d.avg ?? 0) * d.total, 0) / sum : null;
  return (
    <Tile i={2} labelledBy="ov-trend" className="flex flex-col">
      <TileHead id="ov-trend" title="Review trend" sub={`New Google reviews per ${days <= 7 ? "day" : "week"}${split ? ", split by rating" : ""}`} />
      <div className="well mt-4 flex flex-1 flex-col px-4 pb-2.5 pt-3.5">
        <div className="mb-1.5 flex items-center justify-between gap-2 text-[13px] font-semibold">
          <span>New reviews</span>
          {split && <span className="flex gap-3 text-xs font-medium"><span className="flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-[3px] bg-gradient-to-b from-accent-hi to-accent-lo" />4–5★</span><span className="flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-[3px]" style={{ backgroundImage: "repeating-linear-gradient(135deg, rgb(var(--c-ink-solid)) 0 2px, rgb(var(--c-ink-300)) 2px 4px)" }} />1–3★</span></span>}
        </div>
        {loading || !o ? <Skeleton className="h-52 flex-1" /> : (o.reviews.total_synced === 0 && !googleConnected) ? (
          <div className="grid flex-1 place-items-center py-8 text-center"><div><p className="font-semibold">Reviews appear once Google is connected</p><Link href="/gbp/locations" className="mt-2 inline-flex min-h-11 items-center gap-1 text-sm font-semibold text-accent-ink hover:underline">Connect Google<ArrowRight className="h-4 w-4" aria-hidden /></Link></div></div>
        ) : (
          <div className="relative flex flex-1 items-center">
            <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full overflow-visible" role="img" aria-label={`New reviews per ${days <= 7 ? "day" : "week"} for the last ${days} days`}>
              <defs>
                <pattern id="ov-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" fill="rgb(var(--c-ink-solid))" /><rect width="2" height="6" fill="rgb(var(--c-ink-300))" /></pattern>
                <linearGradient id="ov-bar" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="rgb(var(--c-accent-hi))" /><stop offset="100%" stopColor="rgb(var(--c-accent-lo))" /></linearGradient>
              </defs>
              {[0, .25, .5, .75, 1].map((t) => (
                <g key={t}>
                  <line x1={L} x2={W} y1={y(max * t)} y2={y(max * t)} stroke="rgb(var(--c-ink-200))" strokeOpacity={t === 0 ? 1 : .7} strokeDasharray={t === 0 ? undefined : "2 4"} />
                  <text x={L - 8} y={y(max * t) + 4} textAnchor="end" fontSize="11" fill="rgb(var(--c-ink-500))">{Math.round(max * t)}</text>
                </g>
              ))}
              {data.map((d, i) => {
                const x = L + i * pitch + (pitch - bw) / 2;
                const hi = split ? d.total - d.low : d.total;
                const hiH = (H - B - T) * hi / max, loH = (H - B - T) * d.low / max;
                return (
                  <g key={d.from} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} opacity={hover === null || hover === i ? 1 : 0.55} style={{ transition: "opacity .15s" }}>
                    <rect x={x - 4} y={T} width={bw + 8} height={H - B - T} rx="8" fill={hover === i ? "rgb(var(--c-ink) / .06)" : "transparent"} />
                    {hi > 0 && <rect className="grow-y" style={{ "--d": `${i * 40}ms` } as CSSProperties} x={x} y={y(hi)} width={bw} height={hiH} rx={Math.min(9, bw / 2.6)} fill="url(#ov-bar)" />}
                    {split && d.low > 0 && <rect className="grow-y" style={{ "--d": `${i * 40 + 120}ms` } as CSSProperties} x={x} y={y(hi) - loH - (hi > 0 ? 3 : 0)} width={bw} height={loH} rx={Math.min(9, bw / 2.6)} fill="url(#ov-hatch)" />}
                    {d.total === 0 && <rect x={x} y={H - B - 3} width={bw} height={3} rx={1.5} fill="rgb(var(--c-ink-200))" />}
                    {i % every === 0 && <text x={x + bw / 2} y={H - 7} textAnchor="middle" fontSize="11" fill="rgb(var(--c-ink-500))">{d.label}</text>}
                  </g>
                );
              })}
            </svg>
            {hover !== null && data[hover] && (
              <div className="pointer-events-none absolute z-10 -translate-x-1/2 whitespace-nowrap rounded-xl bg-surface px-3 py-2 text-xs shadow-lift ring-1 ring-ink-100"
                style={{ left: `${Math.min(80, Math.max(20, ((L + hover * pitch + pitch / 2) / W) * 100))}%`, top: `${Math.max(0, (y(data[hover].total) / H) * 100 - 30)}%` }}>
                <span className="text-ink-500">{days <= 7 ? fmtDate(data[hover].from) : `Week of ${fmtDate(data[hover].from)}`}</span><br />
                <b className="text-[13px] tabular-nums">{fmtNum(data[hover].total)}</b> {data[hover].total === 1 ? "review" : "reviews"}{split && data[hover].low ? <span className="text-ink-500"> · {data[hover].low} at 1–3★</span> : null}{data[hover].avg ? <span className="text-ink-500"> · avg {fmtRating(data[hover].avg)}</span> : null}
              </div>
            )}
            {empty && <p className="pointer-events-none absolute inset-0 grid place-items-center text-sm text-muted">No new reviews in this period</p>}
          </div>
        )}
        {o && !loading && !empty && (
          <dl className="mt-2 grid grid-cols-3 gap-2 border-t border-ink-100 pt-3 text-center">
            <div><dt className="text-[11px] text-muted">In this period</dt><dd className="num text-[15px] font-semibold">{fmtNum(sum)}</dd></div>
            <div><dt className="text-[11px] text-muted">Busiest {days <= 7 ? "day" : "week"}</dt><dd className="num text-[15px] font-semibold">{best ? `${best.label} · ${best.total}` : "–"}</dd></div>
            <div><dt className="text-[11px] text-muted">Average rating</dt><dd className="num text-[15px] font-semibold">{wavg ? fmtRating(wavg) : "–"}</dd></div>
          </dl>
        )}
        {o && !loading && (
          <table className="sr-only"><caption>New reviews per period</caption><thead><tr><th>From</th><th>Reviews</th>{split && <th>1–3 stars</th>}<th>Average rating</th></tr></thead>
            <tbody>{data.map((d) => <tr key={d.from}><td>{fmtDate(d.from)}</td><td>{d.total}</td>{split && <td>{d.low}</td>}<td>{d.avg ? fmtRating(d.avg) : "–"}</td></tr>)}</tbody></table>
        )}
      </div>
    </Tile>
  );
}

// ------------------------------------------------------------------------------------------ 5. recent activity

const REPLY: Record<Review["reply_state"], [string, string]> = {
  none: ["Needs reply", "text-neg"], draft: ["Draft ready", "text-accent-ink"], approved: ["Approved", "text-accent-ink"], publishing: ["Sending to Google", "text-accent-ink"], published: ["Replied", "text-pos"], failed: ["Didn't send", "text-neg"],
};
function replyStatus(r: Review): [string, string] {
  if (r.reply_state === "none" && r.google_reply_text) return ["Replied on Google", "text-pos"];
  if (r.sensitive_reasons.length && (r.reply_state === "none" || r.reply_state === "draft")) return ["Flagged · needs you", "text-warn"];
  return REPLY[r.reply_state];
}
const when = (iso: string) => new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });

export function RecentActivity({ items, loading, error, i }: { items: Review[] | null; loading: boolean; error: string | null; i: number }) {
  const router = useRouter();
  const [q, setQ] = useState("");
  const icon = (r: Review) => r.sensitive_reasons.length
    ? <span aria-hidden className="grid h-8 w-8 shrink-0 place-items-center rounded-[10px] bg-warn-tint text-warn"><AlertTriangle className="h-4 w-4" /></span>
    : <span aria-hidden className="grid h-8 w-8 shrink-0 place-items-center rounded-[10px] bg-accent-tint text-accent-ink"><Star className="h-4 w-4" /></span>;
  return (
    <Tile i={i} labelledBy="ov-activity" className="lg:col-span-2">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="ov-activity" className="text-lg font-semibold leading-6">Recent activity</h2>
        <div className="flex w-full items-center gap-2 sm:w-auto">
          <form role="search" className="flex-1 sm:flex-none" onSubmit={(e) => { e.preventDefault(); router.push(q.trim() ? `/gbp/reviews?q=${encodeURIComponent(q.trim())}` : "/gbp/reviews"); }}>
            <label className="flex h-11 items-center gap-2 rounded-full bg-surface-2 px-4 text-muted focus-within:ring-2 focus-within:ring-accent sm:w-[230px]">
              <Search className="h-4 w-4 shrink-0" aria-hidden /><span className="sr-only">Search reviews</span>
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search reviews" className="focus-inner w-full bg-transparent text-sm text-ink outline-none placeholder:text-muted" />
            </label>
          </form>
          <Link href="/gbp/reviews" className="inline-flex h-11 items-center gap-2 rounded-full px-4 text-sm font-medium text-muted transition-colors hover:bg-surface-2 hover:text-ink">Filter<ListFilter className="h-4 w-4" aria-hidden /></Link>
        </div>
      </div>
      {loading && !items ? <Skeleton className="mt-5 h-64" /> : error && !items ? <p className="mt-5 rounded-tile bg-neg-tint p-4 text-sm">We couldn&rsquo;t load recent reviews. {error}</p>
        : !items || items.length === 0 ? <p className="mt-5 rounded-tile bg-surface-2 p-5 text-sm text-muted">No reviews yet. New Google reviews and your replies show up here.</p> : (
        <>
          <table className="dt mt-5 hidden sm:table">
            <thead><tr><th>Reviewer</th><th>Rating</th><th>Status</th><th className="hidden xl:table-cell">Date</th></tr></thead>
            <tbody>
              {items.map((r) => {
                const [label, cls] = replyStatus(r);
                return (
                  <tr key={r.id} className="cursor-pointer" onClick={() => router.push(`/gbp/reviews/${r.id}`)}>
                    <td className="max-w-0 w-[44%]"><Link href={`/gbp/reviews/${r.id}`} onClick={(e) => e.stopPropagation()} className="flex min-w-0 items-center gap-2.5">{icon(r)}<span className="truncate">{r.reviewer_name ?? "A Google user"}{r.location_name ? ` · ${r.location_name}` : ""}</span></Link></td>
                    <td className="whitespace-nowrap font-semibold text-accent-ink">{r.rating.toFixed(1)} ★</td>
                    <td className="whitespace-nowrap"><span className={clsx("inline-flex items-center gap-1.5 text-[13px] font-medium", cls)}><span aria-hidden className="h-1.5 w-1.5 rounded-full bg-current" />{label}</span></td>
                    <td className="hidden whitespace-nowrap xl:table-cell">{when(r.review_created_at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <ul className="mt-4 divide-y divide-line sm:hidden">
            {items.map((r) => {
              const [label, cls] = replyStatus(r);
              return (
                <li key={r.id}><Link href={`/gbp/reviews/${r.id}`} className="flex items-center gap-3 py-3">
                  {icon(r)}
                  <span className="min-w-0 flex-1"><span className="block truncate font-medium">{r.reviewer_name ?? "A Google user"}</span>
                    <span className={clsx("block text-xs font-medium", cls)}>{label}<span className="font-normal text-muted"> · {when(r.review_created_at)}</span></span></span>
                  <span className="shrink-0 font-semibold text-accent-ink">{r.rating.toFixed(1)} ★</span>
                </Link></li>
              );
            })}
          </ul>
        </>
      )}
    </Tile>
  );
}

// ------------------------------------------------------------------------------------------ 6. customer funnel (cards)

export function Funnel({ o, loading, i }: { o: Overview | null; loading: boolean; i: number }) {
  const e = o?.engagement;
  const rows: [string, number][] = e ? [["Card scans and taps", e.scans], ["Review page visits", e.landing_views], ["Clicks to Google", e.google_clicks]] : [];
  const top = Math.max(1, ...rows.map((r) => r[1]));
  return (
    <Tile i={i} labelledBy="ov-funnel" lift>
      <TileHead id="ov-funnel" title="Customer funnel" sub="From your QR/NFC cards" />
      {loading || !o ? <Skeleton className="mt-5 h-48" /> : o.cards.length === 0 ? (
        <div className="mt-5 rounded-tile bg-surface-2 p-5"><p className="font-semibold">No card on a counter yet</p><p className="mt-1 text-sm text-muted">Every scan or tap of your card is counted here.</p>
          <Link href="/gbp/cards" className="mt-2 inline-flex min-h-11 items-center gap-1 text-sm font-semibold text-accent-ink hover:underline">See your cards<ArrowRight className="h-4 w-4" aria-hidden /></Link></div>
      ) : (
        <>
          <ol className="mt-5 space-y-1">
            {rows.map(([label, v], n) => {
              const prevV = n > 0 ? rows[n - 1][1] : null;
              const conv = prevV ? Math.round((v / prevV) * 100) : null;
              return (
                <li key={label}>
                  {conv !== null && <p className="my-1.5 flex items-center gap-1.5 pl-1 text-[11px] font-medium text-muted"><ArrowDownRight className="h-3 w-3" aria-hidden /><span><b className="num text-ink">{conv}%</b> of the step above</span></p>}
                  <div className="flex items-baseline justify-between gap-3"><span className="text-[13px] font-medium text-ink-700">{label}</span><span className="num text-[17px] font-semibold">{fmtNum(v)}</span></div>
                  <span className="mt-1 block h-3.5 overflow-hidden rounded-full bg-surface-2"><span className="grow-x block h-full rounded-full" style={{ width: `${Math.max(v ? 4 : 0, (v / top) * 100)}%`, "--d": `${n * 90}ms`, background: `linear-gradient(90deg, rgb(var(--c-accent-hi) / ${[.55, .78, 1][n] ?? 1}), rgb(var(--c-accent) / ${[.7, .9, 1][n] ?? 1}))` } as CSSProperties} /></span>
                </li>);
            })}
          </ol>
          <div className="mt-5 border-t border-dashed border-ink-200 pt-4">
            <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted">Counted separately</p>
            <div className="flex items-baseline justify-between gap-3"><span className="text-[13px] font-medium text-ink-700">New Google reviews (synced)</span><span className="num text-[17px] font-semibold">{fmtNum(o.reviews.new_in_range)}</span></div>
            <span className="mt-1 block h-3.5 overflow-hidden rounded-full bg-surface-2"><span className="grow-x block h-full rounded-full bg-ink-solid" style={{ width: `${Math.max(o.reviews.new_in_range ? 3 : 0, (o.reviews.new_in_range / top) * 100)}%`, "--d": "300ms" } as CSSProperties} /></span>
          </div>
          <p className="mt-4 rounded-inner bg-surface-2 px-3.5 py-3 text-[13px] text-muted">Clicks are not reviews. We can&rsquo;t tell which scan led to a review, so reviews are counted separately.</p>
        </>
      )}
    </Tile>
  );
}

// ------------------------------------------------------------------------------------------ 8. what customers mention

export function Mentions({ ins, loading, error, i }: { ins: Insights | null; loading: boolean; error: string | null; i: number }) {
  const topics = [...(ins?.topics ?? [])].sort((a, b) => b.mentions - a.mentions).slice(0, 6);
  const s = ins?.sentiment, total = s ? s.positive + s.neutral + s.negative : 0;
  const pct = (n: number) => (total ? (n / total) * 100 : 0);
  return (
    <Tile i={i} labelledBy="ov-mentions">
      <TileHead id="ov-mentions" title="What customers mention" sub="Topics in written reviews this period" />
      {loading && !ins ? <Skeleton className="mt-5 h-40" /> : error && !ins ? <p className="mt-5 text-sm text-muted">We couldn&rsquo;t read the topics just now.</p>
        : !ins || ins.reviews_with_text === 0 ? <p className="mt-5 rounded-tile bg-surface-2 p-5 text-sm text-muted">No written reviews in this period yet. Topics appear once customers write a few words.</p> : (
        <>
          <ul className="mt-4 flex flex-wrap gap-2" aria-label="Topics">
            {topics.map((t) => {
              const good = t.positive >= t.negative;
              return (
                <li key={t.topic} className={clsx("inline-flex h-9 items-center gap-2 rounded-full px-3.5 text-sm font-medium", good ? "bg-pos-tint" : "bg-neg-tint")}>
                  <i aria-hidden className={clsx("h-2 w-2 rounded-full", good ? "bg-pos" : "bg-neg")} />{t.label}
                  <b className={clsx("num rounded-full bg-surface px-2 text-xs font-semibold leading-5", good ? "text-pos" : "text-neg")}>{t.mentions}<span className="sr-only"> mentions, mostly {good ? "positive" : "negative"}</span></b>
                </li>);
            })}
          </ul>
          {s && total > 0 && (
            <div className="mt-6">
              <p className="flex items-baseline justify-between text-xs text-muted"><span className="font-medium">Overall sentiment</span><span><b className="num text-[17px] font-semibold text-ink">{Math.round(pct(s.positive))}%</b> positive</span></p>
              <div className="mt-2 flex h-3.5 gap-[3px]" role="img" aria-label={`${Math.round(pct(s.positive))}% positive, ${Math.round(pct(s.neutral))}% neutral, ${Math.round(pct(s.negative))}% negative`}>
                {s.positive > 0 && <i className="grow-x block rounded-full bg-pos" style={{ width: `${pct(s.positive)}%` }} />}
                {s.neutral > 0 && <i className="grow-x block rounded-full bg-ink-300" style={{ width: `${pct(s.neutral)}%`, "--d": "80ms" } as CSSProperties} />}
                {s.negative > 0 && <i className="grow-x block rounded-full bg-neg" style={{ width: `${pct(s.negative)}%`, "--d": "160ms" } as CSSProperties} />}
              </div>
              <ul className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
                <li className="flex items-center gap-1.5"><i aria-hidden className="h-2 w-2 rounded-full bg-pos" />Positive <b className="num text-ink">{Math.round(pct(s.positive))}%</b></li>
                <li className="flex items-center gap-1.5"><i aria-hidden className="h-2 w-2 rounded-full bg-ink-300" />Neutral <b className="num text-ink">{Math.round(pct(s.neutral))}%</b></li>
                <li className="flex items-center gap-1.5"><i aria-hidden className="h-2 w-2 rounded-full bg-neg" />Negative <b className="num text-ink">{Math.round(pct(s.negative))}%</b></li>
              </ul>
            </div>
          )}
        </>
      )}
      <LinkButton href="/reputation/insights" variant="secondary" size="sm" className="mt-5" icon={<Sparkles className="h-4 w-4" aria-hidden />}>See all insights</LinkButton>
    </Tile>
  );
}

// ------------------------------------------------------------------------------------------ 9. needs your attention

const TODO_ICON = { bad: AlertTriangle, warn: Clock, info: Lightbulb } as const;

export function Attention({ todos, loading, noPlanYet, tasksError, i }: { todos: Todo[]; loading: boolean; noPlanYet: boolean; tasksError: string | null; i: number }) {
  const n = todos.length;
  const line = n > 0 ? `Your AI assistant has ${n} ${n === 1 ? "thing" : "things"} to help with today.` : noPlanYet ? "Your AI assistant hasn't made today's plan yet." : "You're all caught up.";
  return (
    <Tile i={i} labelledBy="ov-attention" className="lg:col-span-2">
      <TileHead id="ov-attention" title="Needs your attention" sub={<>{line} Nothing is posted to Google until you approve it.</>}
        right={n > 0 ? <span className="rounded-full bg-accent-tint px-2.5 py-0.5 text-xs font-medium text-accent-ink">{n} {n === 1 ? "item" : "items"}</span> : undefined} />
      {tasksError && <p className="mt-2 text-sm text-neg">We couldn&rsquo;t load today&rsquo;s plan just now. {tasksError}</p>}
      {loading ? <div className="mt-5 grid gap-3.5 md:grid-cols-3">{[0, 1, 2].map((k) => <Skeleton key={k} className="h-44 !rounded-tile" />)}</div> : n === 0 ? (
        <div className="mt-5 flex flex-wrap items-center gap-4 rounded-tile bg-surface-2 p-5">
          <span aria-hidden className="grid h-10 w-10 place-items-center rounded-full bg-pos-tint text-pos"><Check className="h-5 w-5" strokeWidth={2.5} /></span>
          <p className="min-w-0 flex-1 basis-60 text-sm text-muted">{noPlanYet ? "Open AI to let your assistant look at your reviews and profile." : "Every review has an answer and nothing is waiting for you. Your assistant checks again tomorrow morning."}</p>
          <LinkButton href="/ai/today" variant="secondary" size="sm">Open AI</LinkButton>
        </div>
      ) : (
        <>
          <ul className="mt-5 grid gap-3.5 md:grid-cols-3">
            {todos.slice(0, 3).map((t, k) => {
              const Icon = TODO_ICON[t.tone];
              return (
                <li key={t.id} className={clsx("flex min-h-[188px] flex-col rounded-tile p-[18px]", k === 0 ? "bg-accent-tint ring-1 ring-inset ring-accent-edge" : "bg-surface-2")}>
                  <span aria-hidden className={clsx("mb-3 grid h-10 w-10 place-items-center rounded-inner bg-surface", t.tone === "bad" ? "text-neg" : t.tone === "warn" ? "text-warn" : "text-ink")}><Icon className="h-[18px] w-[18px]" strokeWidth={1.75} /></span>
                  <p className="font-semibold leading-snug">{t.title}</p>
                  <p className="mt-1 flex-1 text-[13px] leading-snug text-muted">{t.detail}</p>
                  <div className="mt-3 flex items-center justify-between gap-2">
                    <span className="text-xs text-muted">{t.tone === "bad" ? "Needs a look" : t.tone === "warn" ? "Waiting for you" : "Suggested"}</span>
                    <LinkButton href={t.href} size="sm" variant={k === 0 ? "brand" : "primary"}>{t.cta}</LinkButton>
                  </div>
                </li>
              );
            })}
          </ul>
          {n > 3 && <Link href="/ai/today" className="mt-3 inline-flex min-h-11 items-center gap-1 text-sm font-semibold text-accent-ink hover:underline">and {n - 3} more in AI<ArrowRight className="h-3.5 w-3.5" aria-hidden /></Link>}
        </>
      )}
    </Tile>
  );
}

// ------------------------------------------------------------------------------------------ 4. monthly review goal

const monthStart = (d: Date) => new Date(d.getFullYear(), d.getMonth(), 1);
const isoD = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/**
 * Monthly review goal (PRD §9): new Google reviews this calendar month against the business's goal. With no goal set it suggests last
 * month's count + 10% (shown as a suggestion, never saved silently). The pace line is plain arithmetic on this month so far.
 */
export function GoalCard({ i, goal, canEdit, onSave }: { i: number; goal: number | null | undefined; canEdit: boolean; onSave: (g: number | null) => Promise<void> }) {
  const now = new Date();
  const first = monthStart(now);
  const lastFirst = new Date(first.getFullYear(), first.getMonth() - 1, 1), lastEnd = new Date(first.getTime() - 86400000);
  const cur = useFetchOverview(isoD(first), isoD(now));
  const prev = useFetchOverview(isoD(lastFirst), isoD(lastEnd));
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState("");
  const [busy, setBusy] = useState(false);
  const suggested = prev ? Math.max(5, Math.ceil(prev.reviews.new_in_range * 1.1)) : null;
  const target = goal ?? suggested;
  const count = cur?.reviews.new_in_range ?? 0;
  const day = now.getDate(), daysInMonth = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
  const pace = count / day;
  const left = target ? Math.max(0, target - count) : 0;
  const eta = pace > 0 && left > 0 ? new Date(now.getTime() + Math.ceil(left / pace) * 86400000) : null;
  const pct = target ? Math.min(100, (count / target) * 100) : 0;
  const locs = [...(cur?.locations ?? [])].sort((a, b) => b.new_reviews - a.new_reviews).slice(0, 4);

  async function save(v: number | null) {
    setBusy(true);
    try { await onSave(v); setEditing(false); } finally { setBusy(false); }
  }
  return (
    <Tile i={i} labelledBy="ov-goal">
      <TileHead id="ov-goal" title="Monthly review goal" right={goal ? undefined : <span className="rounded-full bg-accent-tint px-2.5 py-0.5 text-xs font-medium text-accent-ink">{suggested ? "Suggested" : "Not set"}</span>} />
      {!cur ? <Skeleton className="mt-5 h-40" /> : (
        <>
          <div className="mt-5 flex items-center gap-5" role="progressbar" aria-label="Reviews this month" aria-valuenow={count} aria-valuemin={0} aria-valuemax={target ?? undefined}>
            <Ring pct={pct} size={128} stroke={12} marker={target ? (day / daysInMonth) * 100 : undefined}>
              <span><b className="num block text-[28px] font-semibold leading-none tracking-[-.02em]">{fmtNum(count)}</b><span className="mt-1 block text-[11px] text-muted">of {target ? fmtNum(target) : "–"}</span></span>
            </Ring>
            <div className="min-w-0 space-y-2 text-[13px]">
              <p><b className="num text-[22px] font-semibold tracking-[-.02em]">{target ? `${Math.round(pct)}%` : "–"}</b><span className="ml-1.5 text-muted">of this month&rsquo;s goal</span></p>
              {target && <p className="flex items-start gap-2 text-muted"><i aria-hidden className="mt-1 inline-block h-2.5 w-2.5 shrink-0 rounded-full border-2 border-ink-solid bg-surface" /><span>Steady pace by today: <b className="num text-ink">{fmtNum(Math.round((target * day) / daysInMonth))}</b></span></p>}
              <p className="text-muted">{daysInMonth - day} {daysInMonth - day === 1 ? "day" : "days"} left this month</p>
            </div>
          </div>
          <p className="mt-5 rounded-inner bg-surface-2 px-3.5 py-3 text-[13px] text-muted">
            {!target ? "Set a goal to see your pace." : left === 0 ? <>Goal reached with {daysInMonth - day} {daysInMonth - day === 1 ? "day" : "days"} to spare.</>
              : count === 0 ? <>No new reviews yet this month. {fmtNum(left)} to go.</>
              : <>{fmtNum(left)} more to hit your goal. At this month&rsquo;s pace you&rsquo;ll reach it around <b className="text-ink">{eta && eta.getMonth() === now.getMonth() ? eta.toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : "next month"}</b>.</>}
            {!goal && suggested && <> Suggested from last month ({fmtNum(prev!.reviews.new_in_range)}) + 10%.</>}
          </p>
          {locs.length > 1 && target && (
            <div className="mt-5 space-y-3"><p className="text-xs font-medium text-muted">By location</p>
              {locs.map((l) => (
                <div key={l.location} className="grid grid-cols-[minmax(0,6rem)_1fr_2.5rem] items-center gap-3 text-sm">
                  <span className="truncate font-medium" title={l.location}>{l.location}</span>
                  <span className="block h-2 overflow-hidden rounded-full bg-surface-2"><span className="grow-x block h-full rounded-full bg-gradient-to-r from-accent-hi to-accent" style={{ width: `${Math.min(100, (l.new_reviews / target) * 100)}%` }} /></span>
                  <b className="num text-right font-semibold">{fmtNum(l.new_reviews)}</b>
                </div>))}
            </div>
          )}
          {canEdit && (editing ? (
            <form className="mt-5 flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); const n = parseInt(val, 10); if (n > 0) void save(n); }}>
              <label className="sr-only" htmlFor="goal-input">Reviews per month</label>
              <input id="goal-input" type="number" min={1} max={100000} inputMode="numeric" value={val} onChange={(e) => setVal(e.target.value)} autoFocus
                className="h-11 w-28 rounded-full bg-surface-2 px-4 text-sm font-semibold" />
              <button type="submit" disabled={busy || !(parseInt(val, 10) > 0)} className="inline-flex h-11 items-center rounded-full bg-ink-solid px-5 text-sm font-semibold text-ink-on disabled:opacity-50">Save</button>
              <button type="button" onClick={() => setEditing(false)} className="h-11 rounded-full px-3 text-sm font-medium text-muted hover:text-ink">Cancel</button>
              {goal && <button type="button" onClick={() => void save(null)} className="h-11 rounded-full px-3 text-sm font-medium text-muted hover:text-neg">Clear goal</button>}
            </form>
          ) : (
            <button type="button" onClick={() => { setVal(String(target ?? 10)); setEditing(true); }} className="mt-5 inline-flex min-h-11 items-center rounded-full bg-surface-2 px-4 text-sm font-semibold hover:bg-surface-3 sm:min-h-9">
              {goal ? "Edit goal" : suggested ? `Use ${fmtNum(suggested)} as my goal` : "Set a goal"}
            </button>
          ))}
        </>
      )}
    </Tile>
  );
}

function useFetchOverview(from: string, to: string): Overview | null {
  const [o, setO] = useState<Overview | null>(null);
  useEffect(() => {
    let live = true;
    void api<Overview>("/analytics/overview", { params: { from, to } }).then((r) => { if (live) setO(r); }).catch(() => undefined);
    return () => { live = false; };
  }, [from, to]);
  return o;
}
