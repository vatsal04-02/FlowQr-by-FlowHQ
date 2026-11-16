"use client";
import { Check, Circle, Plus, QrCode, ScanLine, PenLine, UserCheck } from "lucide-react";
import Link from "next/link";
import { LineChart } from "@/components/charts/LineChart";
import { Funnel, StatusBadge, useCampaigns } from "@/components/review-growth/shared";
import { LinkButton } from "@/components/ui/Button";
import { Alert, EmptyState, PageHeader, Skeleton, Stat } from "@/components/ui/Card";
import { Panel } from "@/components/ui/kit";
import { useAuth } from "@/lib/auth";
import { fmtNum, fmtPct } from "@/lib/format";
import type { RGAnalytics, RGSettings } from "@/lib/review-growth";
import { useFetch } from "@/lib/use-api";

const HOW = [
  [QrCode, "Customer scans your QR code", "A fast, branded page opens on their phone. No app, no account."],
  [PenLine, "They type a few words", "Keywords, a sentence or a whole review. Nothing is mandatory."],
  [UserCheck, "They confirm their own words", "AI organises them (or they write it themselves), they confirm it, and post it on Google themselves."],
] as const;

export default function ReviewGrowthOverview() {
  const { isAdmin } = useAuth();
  const campaigns = useCampaigns();
  const stats = useFetch<RGAnalytics>("/review-growth/analytics");
  const settings = useFetch<RGSettings>("/review-growth/settings");
  const list = campaigns.data ?? [];
  const t = stats.data?.totals;
  const missingLinks = (settings.data?.locations ?? []).filter((l) => !l.review_url);

  const checklist: [string, boolean, string | null][] = [
    ["Create your first QR campaign", list.length > 0, "/gbp/campaigns"],
    ["Add your Google review link", !!settings.data && settings.data.locations.length > 0 && missingLinks.length === 0, "/reputation/assistant/settings"],
    ["AI drafting is configured", !!settings.data?.ai.configured, null],
    ["Download and place your QR code", list.some((c) => c.stats.scans > 0), "/gbp/campaigns"],
  ];

  return (
    <>
      <PageHeader title="Setup guide" subtitle="Make it easy for happy customers to say so, in their own words. Last 30 days."
        actions={isAdmin ? <LinkButton href="/gbp/campaigns?new=1" size="sm" icon={<Plus className="h-4 w-4" />}>New QR campaign</LinkButton> : undefined} />

      {campaigns.loading && !campaigns.data ? <Skeleton className="h-60" /> : list.length === 0 ? (
        <div className="space-y-5">
          <EmptyState icon={<QrCode className="h-5 w-5" />} title="No QR campaigns yet"
            action={isAdmin ? <LinkButton href="/gbp/campaigns?new=1" size="sm">Create your first campaign</LinkButton> : undefined}>
            A campaign is a QR code for one of your locations. Put it on your counter, receipts or table cards.
          </EmptyState>
          <ol className="grid gap-3 sm:grid-cols-3">
            {HOW.map(([Icon, title, body], i) => (
              <li key={title} className="panel p-4"><span className="grid h-8 w-8 place-items-center rounded-lg bg-brand-50 text-brand-700"><Icon className="h-4 w-4" aria-hidden /></span>
                <p className="mt-3 text-sm font-semibold">{i + 1}. {title}</p><p className="mt-1 text-[13px] text-ink-500">{body}</p></li>))}
          </ol>
        </div>
      ) : (
        <div className="space-y-4">
          {missingLinks.length > 0 && (
            <Alert tone="warning" title="A location has no Google review link" action={<LinkButton href="/reputation/assistant/settings" size="sm" variant="secondary">Add link</LinkButton>}>
              Customers can finish their review, but can&rsquo;t continue to Google: {missingLinks.map((l) => l.name).join(", ")}.
            </Alert>
          )}
          {settings.data && !settings.data.ai.configured && <Alert tone="info" title="AI drafting isn't configured on this server">Customers can still write their own review and continue to Google.</Alert>}
          {settings.data?.ai.degraded && <Alert tone="warning" title="AI writing help is paused" action={<LinkButton href="/reputation/assistant" size="sm" variant="secondary">See why</LinkButton>}>{settings.data.ai.degraded.message} Customers can still write their own review.</Alert>}

          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="Page opened" value={fmtNum(t?.scans)} hint={t ? `${fmtNum(t.unique_visitors)} unique visitors` : undefined} icon={<ScanLine className="h-4 w-4" />} />
            <Stat label="Started a review" value={fmtNum(t?.feedback_submitted)} hint={t?.scans ? `${fmtPct(t.feedback_submitted / t.scans)} of visits` : undefined} />
            <Stat label="Confirmed their review" value={fmtNum(t?.drafts_approved)} hint={t ? `${fmtNum(t.drafts_generated)} AI drafts · ${fmtNum(t.manual_selected)} written by customers` : undefined} />
            <Stat label="Continued to Google" value={fmtNum(t?.google_redirects)} hint="Taps, not published reviews" />
          </div>

          <div className="grid gap-4 lg:grid-cols-[1fr_1.35fr]">
            <Panel title="Funnel" meta="30 days" action={<Link href="/gbp/campaigns" className="text-[13px] font-medium text-brand-700 hover:underline">Full analytics</Link>}>
              {stats.data ? <Funnel steps={stats.data.funnel} /> : <Skeleton className="h-40" />}
            </Panel>
            <Panel title="Activity over time">
              {stats.data ? <LineChart ariaLabel="QR scans, feedback and Google clicks over time" data={stats.data.series} height={230}
                series={[{ key: "scans", label: "Scans", color: "rgb(var(--c-accent))" }, { key: "feedback_submitted", label: "Feedback", color: "rgb(var(--c-ink-solid))", dash: "6 4" }, { key: "google_redirects", label: "To Google", color: "rgb(var(--c-pos))", dash: "2 4" }]} /> : <Skeleton className="h-56" />}
            </Panel>
          </div>

          <div className="grid gap-4 lg:grid-cols-[1.35fr_1fr]">
            <Panel title="Campaigns" action={<Link href="/gbp/campaigns" className="text-[13px] font-medium text-brand-700 hover:underline">Manage</Link>} flush>
              <div className="overflow-x-auto"><table className="dt min-w-[520px]">
                <thead><tr><th>Campaign</th><th>Status</th><th className="!text-right">Scans</th><th className="!text-right">Approved</th><th className="!text-right">To Google</th></tr></thead>
                <tbody>{list.slice(0, 6).map((c) => (
                  <tr key={c.id}><td><Link href={`/gbp/campaigns/${c.id}`} className="font-medium text-brand-700 hover:underline">{c.name}</Link><p className="text-xs text-ink-500">{c.location_name ?? "No location"}</p></td>
                    <td><StatusBadge status={c.status} /></td><td className="n">{fmtNum(c.stats.scans)}</td><td className="n">{fmtNum(c.stats.drafts_approved)}</td><td className="n">{fmtNum(c.stats.google_redirects)}</td></tr>))}</tbody>
              </table></div>
            </Panel>
            <Panel title="Getting started">
              <ul className="space-y-2.5 text-sm">
                {checklist.map(([label, done, href]) => (
                  <li key={label} className="flex items-start gap-2.5">
                    {done ? <Check className="mt-0.5 h-4 w-4 shrink-0 text-ok" aria-label="Done" /> : <Circle className="mt-0.5 h-4 w-4 shrink-0 text-ink-300" aria-label="To do" />}
                    {href && !done ? <Link href={href} className="font-medium text-brand-700 hover:underline">{label}</Link> : <span className={done ? "text-ink-500" : ""}>{label}</span>}
                  </li>))}
              </ul>
            </Panel>
          </div>
          <p className="max-w-2xl text-xs text-ink-500">&ldquo;Continued to Google&rdquo; counts customers who tapped the button. FlowQR can&rsquo;t tell whether they then posted a review.</p>
        </div>
      )}
    </>
  );
}
