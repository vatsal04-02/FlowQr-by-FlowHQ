/**
 * Pure helpers behind the Home, Inbox and Insights charts (no imports, so `npm test` covers them).
 *
 * The one rule: a chart is drawn from numbers the API returned. Nothing here invents, spreads or fills in a value. A day Google has not reported is not a day with zero; it is a gap,
 * and a chart that would be mostly gaps is not drawn at all (the page shows the totals instead).
 */

export type Pt = { date: string; value: number };
export type Day = { date: string; values: number[] };

const DAY = 86_400_000;
const ms = (d: string) => Date.UTC(+d.slice(0, 4), +d.slice(5, 7) - 1, +d.slice(8, 10));
/** Whole days between two YYYY-MM-DD dates. */
export const dayGap = (a: string, b: string) => Math.round((ms(b) - ms(a)) / DAY);

/**
 * One stacked row per day, one value per group (a group is one or more Google metrics that are summed, e.g. the four profile-view metrics).
 * A day appears only when EVERY group has a stored value for it; a day missing from any group is left out rather than counted as zero for that group.
 */
export function dailyStack(series: Record<string, Pt[]>, groups: string[][]): Day[] {
  const perGroup = groups.map((g) => {
    const m = new Map<string, number>();
    for (const metric of g) for (const p of series[metric] ?? []) m.set(p.date, (m.get(p.date) ?? 0) + p.value);
    return m;
  });
  if (!perGroup.length) return [];
  const dates = [...perGroup[0].keys()].filter((d) => perGroup.every((m) => m.has(d))).sort();
  return dates.map((date) => ({ date, values: perGroup.map((m) => m.get(date) as number) }));
}

/** Split into runs of consecutive days, so a gap is drawn as a gap and never joined across. */
export function runs(days: Day[]): Day[][] {
  const out: Day[][] = [];
  for (const d of days) {
    const last = out[out.length - 1];
    if (last && dayGap(last[last.length - 1].date, d.date) === 1) last.push(d); else out.push([d]);
  }
  return out;
}

/** An area chart needs a line to draw: at least three real days in a row. Fewer, and the page shows totals instead. */
export const canDrawArea = (days: Day[]) => runs(days).some((r) => r.length >= 3);

/** Whole-number percentages that add up to exactly 100 (largest remainder). All zeros stay zeros. */
export function shares(values: number[]): number[] {
  const total = values.reduce((a, b) => a + b, 0);
  if (!total) return values.map(() => 0);
  const raw = values.map((v) => (v / total) * 100), base = raw.map(Math.floor);
  let rest = 100 - base.reduce((a, b) => a + b, 0);
  raw.map((x, i) => [x - base[i], i] as const).sort((a, b) => b[0] - a[0]).forEach(([, i]) => { if (rest-- > 0) base[i]++; });
  return base;
}

/** The API's rating distribution ({"1": n, ... "5": n}) as rows from 5 stars down. Missing keys are real zeros there (the API always sends all five). */
export function ratingMix(dist: Record<string, number> | null | undefined): { star: number; count: number }[] {
  return [5, 4, 3, 2, 1].map((star) => ({ star, count: Number(dist?.[String(star)] ?? 0) }));
}

/** Percentage change against the period before; null when there is nothing honest to compare (no earlier number, or it was zero). */
export function pctChange(cur: number | null | undefined, prev: number | null | undefined): number | null {
  if (cur == null || prev == null || prev === 0) return null;
  return Math.round(((cur - prev) / prev) * 100);
}

/** "Waiting", the order the owner reads a review's life in. Built only from timestamps the API returned; a step with no timestamp is not shown. */
export type Step = { key: string; label: string; at: string };
export function reviewTimeline(r: { review_created_at: string; google_reply_at?: string | null; latest_draft?: { created_at: string; approved_at: string | null; published_at: string | null; status: string; generated_by_ai?: boolean } | null }): Step[] {
  const out: Step[] = [{ key: "received", label: "Review received", at: r.review_created_at }];
  const d = r.latest_draft;
  if (d) {
    out.push({ key: "drafted", label: d.generated_by_ai ? "Reply drafted by FlowQR" : "Reply drafted", at: d.created_at });
    if (d.approved_at) out.push({ key: "approved", label: "Approved by a person", at: d.approved_at });
    if (d.published_at) out.push({ key: "published", label: "Sent to Google", at: d.published_at });
  }
  if (r.google_reply_at && !out.some((s) => s.key === "published")) out.push({ key: "replied", label: "Reply on Google", at: r.google_reply_at });
  return out.sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
}
