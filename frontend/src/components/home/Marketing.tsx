"use client";
import { AlertTriangle, CalendarDays, CheckCircle2, ImagePlus, Sparkles, Store } from "lucide-react";
import Link from "next/link";
import type { PostItem } from "@/lib/agent";
import { fmtWhen, type Overview, type Readiness } from "@/lib/marketing";
import { useFetch } from "@/lib/use-api";
import { Panel } from "@/components/ui/kit";

/**
 * Home's marketing band: what is going out on Google, what is waiting for you, and what needs fixing. Every number comes from /marketing/overview and the post queue; nothing is sample data.
 * With no campaigns yet it is one calm invitation instead of a row of zeros.
 */
export function MarketingBand() {
  const ov = useFetch<Overview>("/marketing/overview");
  const posts = useFetch<{ posts: PostItem[]; timezone: string }>("/posts", { status: "scheduled", limit: 20 });
  const ready = useFetch<Readiness>("/marketing/readiness");
  if (ov.error || (ov.loading && !ov.data)) return null;
  const o = ov.data!;
  const tz = posts.data?.timezone ?? "Asia/Kolkata";
  const upcoming = (posts.data?.posts ?? []).filter((p) => p.scheduled_for).sort((a, b) => +new Date(a.scheduled_for!) - +new Date(b.scheduled_for!)).slice(0, 3);
  const broken = (ready.data?.checks ?? []).filter((c) => !c.ok && ["connection", "scope", "api"].includes(c.key));
  const attention: { key: string; text: string; href: string; tone: "bad" | "warn" }[] = [
    ...(o.failed > 0 ? [{ key: "failed", text: `${o.failed} post${o.failed === 1 ? "" : "s"} didn't publish`, href: "/gbp/posts", tone: "bad" as const }] : []),
    ...broken.map((c) => ({ key: c.key, text: c.detail, href: c.action ?? "/settings/connections/google", tone: "bad" as const })),
    ...(o.awaiting_review > 0 ? [{ key: "review", text: `${o.awaiting_review} post${o.awaiting_review === 1 ? "" : "s"} waiting for your approval`, href: "/gbp/studio", tone: "warn" as const }] : []),
  ];
  const fresh = o.campaigns === 0 && o.generated_posts === 0;
  const stats: [string, number, string][] = [["Campaigns", o.campaigns, ""], ["To approve", o.awaiting_review, o.awaiting_review ? "text-warn" : ""], ["Scheduled", o.scheduled, ""], ["Published", o.published, o.published ? "text-pos" : ""]];
  return (
    <Panel title="Google marketing" meta={<Link href="/gbp/studio" className="inline-flex min-h-11 items-center font-medium underline sm:min-h-0">Open Studio</Link>}>
      {fresh ? (
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="max-w-lg text-[14px] text-ink-700">Describe what you want to promote and FlowQR writes a week of Google posts for you to approve. Nothing goes live until you say so.</p>
          <Link href="/gbp/studio/new" className="inline-flex min-h-11 shrink-0 items-center justify-center gap-2 rounded-full bg-ink-solid px-5 text-sm font-semibold text-ink-on"><Sparkles aria-hidden className="h-4 w-4" />Create a campaign</Link>
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-3">
          <div className="min-w-0">
            <ul aria-label="Marketing numbers" className="grid grid-cols-2 gap-2">
              {stats.map(([l, v, t]) => <li key={l} className="rounded-xl bg-surface-2 px-3 py-2"><span className="block text-[12px] text-muted">{l}</span><span className={`num text-xl font-semibold ${t}`}>{v}</span></li>)}
            </ul>
            <div className="mt-3 flex flex-wrap gap-2">
              <Link href="/gbp/studio/new" className="inline-flex min-h-11 items-center gap-1.5 rounded-full bg-ink-solid px-4 text-[13px] font-semibold text-ink-on"><Sparkles aria-hidden className="h-4 w-4" />New campaign</Link>
              <Link href="/gbp/photos" className="inline-flex min-h-11 items-center gap-1.5 rounded-full bg-surface-2 px-4 text-[13px] font-medium"><ImagePlus aria-hidden className="h-4 w-4" />Photos</Link>
              <Link href="/gbp/studio?tab=calendar" className="inline-flex min-h-11 items-center gap-1.5 rounded-full bg-surface-2 px-4 text-[13px] font-medium"><CalendarDays aria-hidden className="h-4 w-4" />Calendar</Link>
              <Link href="/seo/profile" className="inline-flex min-h-11 items-center gap-1.5 rounded-full bg-surface-2 px-4 text-[13px] font-medium"><Store aria-hidden className="h-4 w-4" />Profile</Link>
            </div>
          </div>
          <div className="min-w-0">
            <p className="text-[13px] font-semibold text-ink-700">Up next on Google</p>
            {upcoming.length === 0 ? <p className="mt-1.5 text-[13px] text-muted">Nothing is scheduled. Approve a generated post to schedule it.</p> : (
              <ul className="mt-1.5 space-y-1.5">{upcoming.map((p) => <li key={p.id}><Link href="/gbp/posts" className="block rounded-xl bg-surface-2 px-3 py-2 hover:bg-surface-3"><span className="block text-[12px] text-muted">{fmtWhen(p.scheduled_for, tz)}</span><span data-words="skip" className="line-clamp-2 text-[13px]">{p.summary}</span></Link></li>)}</ul>)}
          </div>
          <div className="min-w-0">
            <p className="text-[13px] font-semibold text-ink-700">Needs your attention</p>
            {attention.length === 0 ? <p className="mt-1.5 flex items-center gap-1.5 text-[13px] text-pos"><CheckCircle2 aria-hidden className="h-4 w-4" />Nothing is waiting.</p> : (
              <ul className="mt-1.5 space-y-1.5">{attention.map((a) => <li key={a.key}><Link href={a.href} className={`flex items-start gap-2 rounded-xl px-3 py-2 text-[13px] ${a.tone === "bad" ? "bg-neg-tint text-neg" : "bg-warn-tint text-warn"}`}><AlertTriangle aria-hidden className="mt-0.5 h-4 w-4 shrink-0" /><span>{a.text}</span></Link></li>)}</ul>)}
          </div>
        </div>
      )}
    </Panel>
  );
}
