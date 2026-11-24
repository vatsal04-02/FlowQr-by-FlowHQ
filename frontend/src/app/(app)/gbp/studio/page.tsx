"use client";
import { Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { GbpFrame } from "@/components/gbp/GbpFrame";
import { PostCalendar } from "@/components/gbp/PostCalendar";
import { LibraryPanel, OverviewStrip, ReadinessCard, SeoPanel } from "@/components/gbp/StudioParts";
import { LinkButton } from "@/components/ui/Button";
import { Alert, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { Panel, Segmented, Status } from "@/components/ui/kit";
import type { Campaign, Overview } from "@/lib/marketing";
import { fmtWhen } from "@/lib/marketing";
import { useFetch } from "@/lib/use-api";

function Body({ gid }: { gid: string }) {
  const [tab, setTab] = useState<"campaigns" | "calendar" | "library" | "seo">("campaigns");
  const ov = useFetch<Overview>("/marketing/overview");
  const list = useFetch<{ campaigns: Campaign[] }>("/marketing/campaigns", { google_location_id: gid });
  return (
    <div className="space-y-5">
      <OverviewStrip o={ov.data} />
      <ReadinessCard />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Segmented label="Studio view" value={tab} onChange={setTab} options={[["campaigns", "Campaigns"], ["calendar", "Calendar"], ["library", "Media library"], ["seo", "Local search"]] as const} />
        <LinkButton href="/gbp/studio/new" icon={<Plus className="h-4 w-4" />}>New campaign</LinkButton>
      </div>
      {tab === "calendar" && <Panel title="Content calendar" meta="Scheduled, published and failed posts"><PostCalendar /></Panel>}
      {tab === "library" && <LibraryPanel />}
      {tab === "seo" && <SeoPanel gid={gid} />}
      {tab === "campaigns" && (list.error ? <Alert tone="error">{list.error}</Alert> : list.loading && !list.data ? <Skeleton className="h-40" /> : (list.data?.campaigns.length ?? 0) === 0 ? (
        <EmptyState title="No campaigns yet" action={<LinkButton href="/gbp/studio/new">Create your first campaign</LinkButton>}>Describe what you want to promote and FlowQR writes a week, a fortnight or a month of Google posts for you to review. Nothing goes on Google until you approve it.</EmptyState>
      ) : (
        <ul className="grid gap-3 md:grid-cols-2">
          {list.data!.campaigns.map((c) => (
            <li key={c.id}><Link href={`/gbp/studio/${c.id}`} className="block rounded-xl border border-ink-100 bg-surface p-4 transition-colors hover:bg-surface-2">
              <div className="flex items-start justify-between gap-2"><p data-words="skip" className="min-w-0 truncate text-[15px] font-semibold">{c.title}</p><Status tone={(c.counts.failed ?? 0) > 0 ? "bad" : (c.counts.generated ?? 0) > 0 ? "warn" : "ok"}>{(c.counts.failed ?? 0) > 0 ? "Needs attention" : (c.counts.generated ?? 0) > 0 ? "Review needed" : "On track"}</Status></div>
              <p className="mt-0.5 text-[13px] text-muted">{c.objective_label} · {c.duration_days} days · from {fmtWhen(c.start_date)}</p>
              <p className="mt-2 text-[13px] text-ink-700">{(["generated", "approved", "scheduled", "published", "failed"] as const).map((k) => `${c.counts[k] ?? 0} ${k}`).join(" · ")}</p>
            </Link></li>))}
        </ul>
      ))}
    </div>
  );
}

export default function StudioPage() {
  return (
    <>
      <PageHeader title="Google Marketing Studio" subtitle="Describe what you want to promote. FlowQR writes your Google posts; you approve every one." />
      <GbpFrame>{(gid) => <Body key={gid} gid={gid} />}</GbpFrame>
    </>
  );
}
