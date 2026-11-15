"use client";
import clsx from "clsx";
import { ArrowRight, BarChart3, CalendarDays, Image as ImageIcon, MessageSquare, QrCode, Store } from "lucide-react";
import Link from "next/link";
import type { CSSProperties, ReactNode } from "react";
import { Alert, PageHeader, Skeleton } from "@/components/ui/Card";
import type { PostItem, ReportSummary } from "@/lib/agent";
import { fmtNum, timeAgo } from "@/lib/format";
import type { RGAnalytics } from "@/lib/review-growth";
import type { Overview } from "@/lib/types";
import { useFetch } from "@/lib/use-api";
import { useGbp } from "@/lib/use-gbp";

function Module({ i, icon, title, href, cta, children, status, hero }: {
  i: number; icon: ReactNode; title: string; href: string; cta: string; children: ReactNode; status?: { text: string; tone: "ok" | "warn" | "bad" | "idle" }; hero?: boolean;
}) {
  const tone = { ok: "bg-pos-tint text-pos", warn: "bg-warn-tint text-warn", bad: "bg-neg-tint text-neg", idle: "bg-surface-2 text-muted" };
  return (
    <Link href={href} style={{ "--d": `${i * 60}ms` } as CSSProperties}
      className={clsx("rv lift group flex min-h-[220px] flex-col rounded-card p-5 sm:p-6", hero ? "hero-grad" : "bg-surface shadow-card")}>
      <div className="flex items-start justify-between gap-3">
        <span className={clsx("grid h-11 w-11 place-items-center rounded-full", hero ? "bg-white/20 text-pure-white" : "bg-surface-2")} aria-hidden>{icon}</span>
        {status && <span className={clsx("rounded-full px-2.5 py-0.5 text-xs font-medium", hero ? "scrim" : tone[status.tone])}>{status.text}</span>}
      </div>
      <h2 className="mt-4 text-lg font-semibold">{title}</h2>
      <div className={clsx("mt-1 flex-1 text-sm", hero ? "" : "text-muted")}>{children}</div>
      <span className={clsx("mt-4 inline-flex items-center gap-1.5 text-sm font-semibold", hero ? "scrim self-start !px-3 !py-1" : "text-accent-ink")}>{cta}<ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" aria-hidden /></span>
    </Link>
  );
}

const Big = ({ children }: { children: ReactNode }) => <span className="num block text-[32px] font-semibold leading-9 tracking-[-.02em] text-ink">{children}</span>;

/**
 * GBP Manager › Overview: the six Google Business capabilities on one screen, each with its live status and the next step. Everything here
 * is read from data FlowQR already stores (opening this page never calls Google); each module opens the full workspace.
 */
export default function GbpOverview() {
  const gbp = useGbp();
  const gid = gbp.gid;
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  const to = new Date(), from = new Date(); from.setDate(to.getDate() - 29);
  const ov = useFetch<Overview>("/analytics/overview", { from: iso(from), to: iso(to) });
  const drafts = useFetch<{ total: number }>("/reviews", { reply_state: "draft", limit: 1 });
  const opt = useFetch<{ score: number | null; checks: { state: string }[] }>(gid ? `/agent/profile/${gid}/optimize` : null);
  const posts = useFetch<{ posts: PostItem[] }>("/posts", { limit: 50 });
  const lib = useFetch<{ items: { status: string; google_url: string | null }[] }>(gid ? `/gbp/${gid}/library` : null);
  const rg = useFetch<RGAnalytics>("/review-growth/analytics", { from: iso(from), to: iso(to) });
  const rep = useFetch<ReportSummary>("/reports/summary");

  const o = ov.data?.reviews;
  const todo = opt.data?.checks.filter((c) => c.state === "missing" || c.state === "improve").length ?? 0;
  const scheduled = posts.data?.posts.filter((p) => p.status === "scheduled") ?? [];
  const lastPub = posts.data?.posts.filter((p) => p.published_at).map((p) => p.published_at!).sort().pop();
  const waitingPosts = posts.data?.posts.filter((p) => p.status === "awaiting_approval").length ?? 0;
  const photoQueue = lib.data?.items.filter((m) => ["awaiting_approval", "scheduled", "publishing"].includes(m.status)).length ?? 0;
  const processing = lib.data?.items.filter((m) => m.status === "published" && !m.google_url).length ?? 0;
  const g = rep.data?.google_performance;
  const gNow = g?.available ? g.locations.reduce((a, l) => a + l.last_28_days, 0) : null;
  const gPrev = g?.available ? g.locations.reduce((a, l) => a + l.previous_28_days, 0) : null;
  const t = rg.data?.totals;
  const connected = !!gbp.conn && gbp.selected.length > 0;

  return (
    <>
      <PageHeader title="Google Business" subtitle="Everything you manage on Google, in one place. Nothing goes live on Google until you approve it." />
      {!gbp.loading && !connected && <div className="mb-6"><Alert tone="warning" title="Google isn't connected yet" action={<Link href="/gbp/locations" className="inline-flex min-h-10 items-center rounded-full bg-white px-4 text-sm font-semibold">Connect Google</Link>}>
        Review campaigns and cards work without it. Profile, replies, posts, photos and performance need a connected Google Business Profile.</Alert></div>}
      <div className="grid gap-5 sm:grid-cols-2 sm:gap-6 xl:grid-cols-3">
        <Module i={0} hero icon={<MessageSquare className="h-5 w-5" />} title="AI review replies" href="/ai" cta="Review drafts"
          status={o ? { text: `${fmtNum(o.awaiting_reply)} need a reply`, tone: o.awaiting_reply ? "warn" : "ok" } : undefined}>
          {!o ? <Skeleton className="h-10 !bg-white/20" /> : <><span className="num block text-[40px] font-semibold leading-[44px]">{fmtNum(drafts.data?.total ?? 0)}</span><span className="scrim mt-1">drafts waiting for approval</span></>}
        </Module>
        <Module i={1} icon={<Store className="h-5 w-5" />} title="Profile optimizer" href="/gbp/info" cta="See suggestions"
          status={opt.data?.score != null ? { text: `Score ${opt.data.score}`, tone: opt.data.score >= 80 ? "ok" : "warn" } : undefined}>
          {opt.loading && !opt.data ? <Skeleton className="h-10" /> : opt.data ? <><Big>{todo}</Big>{todo === 1 ? "thing" : "things"} to improve on your profile</> : "Connect Google to check your profile."}
        </Module>
        <Module i={2} icon={<QrCode className="h-5 w-5" />} title="Review growth" href="/gbp/campaigns" cta="Open campaigns" status={t ? { text: "Last 30 days", tone: "idle" } : undefined}>
          {!t ? <Skeleton className="h-10" /> : <><Big>{fmtNum(t.scans)}</Big>QR scans · {fmtNum(t.google_redirects)} continued to Google. A click isn&rsquo;t proof of a review.</>}
        </Module>
        <Module i={3} icon={<CalendarDays className="h-5 w-5" />} title="Google posts" href="/gbp/posts" cta="Plan posts"
          status={waitingPosts ? { text: `${waitingPosts} to approve`, tone: "warn" } : scheduled.length ? { text: `${scheduled.length} scheduled`, tone: "ok" } : { text: "None scheduled", tone: "idle" }}>
          {!posts.data ? <Skeleton className="h-10" /> : <><Big>{scheduled.length}</Big>scheduled · {lastPub ? `last published ${timeAgo(lastPub)}` : "nothing published yet"}</>}
        </Module>
        <Module i={4} icon={<ImageIcon className="h-5 w-5" />} title="Photos" href="/gbp/photos" cta="Manage photos"
          status={processing ? { text: `${processing} processing at Google`, tone: "idle" } : photoQueue ? { text: `${photoQueue} in the queue`, tone: "warn" } : undefined}>
          {!connected ? "Connect Google to add photos." : !lib.data ? <Skeleton className="h-10" /> : <><Big>{photoQueue}</Big>photos waiting, scheduled or sending. Upload, approve and pick a time.</>}
        </Module>
        <Module i={5} icon={<BarChart3 className="h-5 w-5" />} title="Performance" href="/overview/performance" cta="See insights"
          status={gNow !== null && gPrev ? { text: `${gNow >= gPrev ? "↗" : "↘"} ${Math.abs(Math.round(((gNow - gPrev) / gPrev) * 100))}% vs the 28 days before`, tone: gNow >= gPrev ? "ok" : "bad" } : undefined}>
          {rep.loading && !rep.data ? <Skeleton className="h-10" /> : gNow !== null ? <><Big>{fmtNum(gNow)}</Big>customer actions on Google in the last 28 days (reported by Google)</> : (g?.note ?? "Google hasn't shared performance yet.")}
        </Module>
      </div>
    </>
  );
}
