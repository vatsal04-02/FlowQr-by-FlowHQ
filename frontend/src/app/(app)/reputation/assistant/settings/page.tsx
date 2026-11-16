"use client";
import { Check, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { BusinessContext } from "@/components/review-growth/BusinessContext";
import { ReviewLinkEditor } from "@/components/review-growth/shared";
import { Alert, Badge, PageHeader, Skeleton } from "@/components/ui/Card";
import { KV, Meter, Panel, Status } from "@/components/ui/kit";
import { useAuth } from "@/lib/auth";
import { fmtNum } from "@/lib/format";
import type { RGSettings } from "@/lib/review-growth";
import { useFetch } from "@/lib/use-api";

export default function ReviewGrowthSettings() {
  const { isAdmin } = useAuth();
  const { data: s, error, reload } = useFetch<RGSettings>("/review-growth/settings");

  return (
    <>
      <PageHeader eyebrow="Review Growth" title="Settings" subtitle="Google review links, AI status and how customer data is handled." />
      {error && <Alert tone="error">{error}</Alert>}
      {!s && !error && <Skeleton className="h-80" />}
      {s && (
        <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
          <div className="space-y-4">
            <Panel title="Google review links" meta="one per location, shared by its campaigns">
              {s.locations.length === 0 ? <p className="text-sm text-ink-500">Add a location first. <Link href="/gbp/locations" className="font-medium text-brand-700 hover:underline">Go to Locations</Link></p> : (
                <ul className="divide-y divide-ink-100">
                  {s.locations.map((l) => (
                    <li key={l.id} className="py-4 first:pt-0 last:pb-0">
                      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                        <p className="font-semibold">{l.name}</p>
                        {l.review_url ? <Badge tone="green"><Check className="h-3 w-3" aria-hidden />Link set</Badge> : <Badge tone="amber">No link yet</Badge>}
                      </div>
                      {l.review_url_kind === "listing" && <Alert tone="warning">This looks like your general Google listing, not the direct review link. Customers would land on your listing and have to find the review button themselves. In your Google Business Profile choose <b>Get more reviews</b> and paste that link (it ends in <code>/review</code>), or connect your Business Profile so we can use the direct link.</Alert>}
                      {l.review_url_kind === "unknown" && <p className="mb-2 text-xs text-ink-500">This is a short Google link. Open it on a phone to check that it lands on the &ldquo;Write a review&rdquo; box.</p>}
                      {isAdmin ? <ReviewLinkEditor locationId={l.id} current={l.review_url} source={l.review_url_source} googleAvailable={l.google_link_available} onSaved={() => void reload()} />
                        : <p className="break-all text-sm text-ink-500">{l.review_url ?? "Ask an owner or admin to add the link."}</p>}
                    </li>))}
                </ul>)}
              <p className="mt-4 text-xs text-ink-500">{s.google_connected ? "Your Google Business Profile is connected, so the link can be taken from it." : <>Connect your Google Business Profile to fetch links automatically. <Link href="/gbp/locations" className="font-medium text-brand-700 hover:underline">Google connection</Link></>} Links are checked to be Google addresses, but FlowQR can&rsquo;t open them to confirm they lead to the right place. Test yours with a phone before printing.</p>
            </Panel>
            <BusinessContext canEdit={isAdmin} />
          </div>

          <div className="space-y-4">
            <Panel title="AI drafting">
              <div className="space-y-3 text-sm">
                <p className="flex items-center justify-between"><span className="text-ink-500">Status</span><Status tone={s.ai.configured ? "ok" : "warn"}>{s.ai.configured ? `On (${s.ai.provider})` : "Not configured"}</Status></p>
                <div><p className="mb-1.5 flex justify-between"><span className="text-ink-500">This month</span><b className="num">{fmtNum(s.ai.used_this_month)} / {fmtNum(s.ai.monthly_limit)}</b></p>
                  <Meter value={s.ai.used_this_month} max={s.ai.monthly_limit || 1} label="AI drafts used this month" /></div>
                <KV rows={[["Drafts per customer", s.limits.max_drafts_per_customer], ["Campaigns allowed", s.limits.max_campaigns]]} />
              </div>
            </Panel>
            <Panel title="Customer data">
              <KV rows={[["Name, phone, email", "Never collected"], ["Answers & drafts kept for", `${s.retention_days} days`], ["Funnel counts kept", "Yes (no text)"]]} />
              <p className="mt-3 text-xs text-ink-500">After {s.retention_days} days, what customers typed and the drafts are deleted automatically. Counts like scans and clicks remain so your analytics stay accurate. Deleting a campaign permanently erases all of its data immediately.</p>
            </Panel>
            <Panel title="Our principles" action={<ShieldCheck className="h-4 w-4 text-ok" aria-hidden />}>
              <ul className="space-y-2.5 text-[13px] text-ink-700">{s.principles.map((p) => <li key={p} className="flex gap-2"><Check className="mt-0.5 h-4 w-4 shrink-0 text-ok" aria-hidden />{p}</li>)}</ul>
            </Panel>
          </div>
        </div>
      )}
    </>
  );
}
