"use client";
import clsx from "clsx";
import { AlertTriangle, ArrowRight, Check, CircleSlash } from "lucide-react";
import Link from "next/link";
import { SourceTag, Unavailable, when } from "@/components/seo/parts";
import { Alert, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { Panel } from "@/components/ui/kit";
import { useLocationScope } from "@/lib/location-scope";
import type { HealthCheck, ProfileHealth } from "@/lib/seo";
import { useFetch } from "@/lib/use-api";

const ICON = { ok: Check, warn: AlertTriangle, missing: CircleSlash } as const;
const TONE = { ok: "bg-pos-tint text-pos", warn: "bg-warn-tint text-warn", missing: "bg-neg-tint text-neg" } as const;
const WORDS = { ok: "Done", warn: "Could be better", missing: "Missing" } as const;

function Row({ c }: { c: HealthCheck }) {
  const Icon = ICON[c.status];
  return (
    <li className="flex items-start gap-3 py-2.5 first:pt-0 last:pb-0">
      <span aria-hidden className={clsx("mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full", TONE[c.status])}><Icon className="h-3.5 w-3.5" strokeWidth={2.5} /></span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{c.label}<span className="sr-only">: {WORDS[c.status]}</span></p>
        <p className="text-[13px] text-muted">{c.detail}</p>
      </div>
      {c.link && c.status !== "ok" && <Link href={c.link} className="inline-flex min-h-9 shrink-0 items-center gap-1 text-[13px] font-semibold text-accent-ink hover:underline">Fix<ArrowRight className="h-3.5 w-3.5" aria-hidden /></Link>}
    </li>
  );
}

/** Local SEO › Google Profile Health: the checklist behind the score. Built only from the profile Google returned; a location Google has not shared is "unavailable", never failing. */
export default function ProfileHealthPage() {
  const { locationId } = useLocationScope();
  const q = useFetch<ProfileHealth>("/seo/profile-health", { location_id: locationId ?? "" });
  const d = q.data;
  const h = d?.health;
  return (
    <>
      <PageHeader title="Google Profile Health" subtitle="What to fix on your Google profile so customers can find and trust you. Checked against the profile Google last shared with FlowQR." />
      {q.error && <Alert tone="error" title="We couldn't load your profile health">{q.error}</Alert>}
      {q.loading && !d && <Skeleton className="h-64" />}
      {d?.state === "no_location" && <EmptyState title="Connect a Google location first" action={<Link href="/gbp/locations" className="font-semibold text-accent-ink hover:underline">Connect Google</Link>}>Profile health reads the Business Profile Google returns for your location.</EmptyState>}
      {d && d.state === "ok" && (
        <div className="space-y-4">
          <section aria-label="Business Health Score" className="panel !rounded-[16px] p-4">
            <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-[15px] font-semibold">Business Health Score</h2><SourceTag source="flowqr" /></div>
            {h && h.score !== null ? (
              <div className="mt-3 flex flex-wrap items-center gap-x-8 gap-y-3">
                <p className="num text-[44px] font-semibold leading-none tracking-[-.03em]">{h.score}<span className="text-lg font-medium text-muted"> / 100</span></p>
                <ul className="grid min-w-0 flex-1 gap-x-6 gap-y-1 sm:grid-cols-2">
                  {h.components.map((c) => (
                    <li key={c.key} className="flex items-baseline justify-between gap-3 text-[13px]"><span className="text-muted">{c.label}</span>
                      <span className="num font-semibold">{c.available && c.value !== null ? `${Math.round(c.value * 100)}%` : "No data"}</span></li>
                  ))}
                </ul>
              </div>
            ) : <Unavailable className="mt-3" title="Not enough real data for a score yet">{h?.message ?? "Connect Google and let it sync."}</Unavailable>}
            {h && <p className="mt-3 text-xs text-muted">{h.formula} Measures without real data are left out, never counted as zero. The thresholds are FlowQR&rsquo;s own heuristics, not Google&rsquo;s rules.</p>}
          </section>

          <div className="grid gap-4 lg:grid-cols-2">
            {d.locations.map((l) => (
              <Panel dense key={l.id} title={l.title ?? "Location"} meta={l.completeness !== null ? `${l.completeness}% of core fields` : undefined} action={<SourceTag source="google" />}>
                {l.state === "unavailable"
                  ? <Unavailable title="Google hasn't shared this profile yet">{l.reason}</Unavailable>
                  : <>
                      <ul className="divide-y divide-ink-100">{l.checks.map((c) => <Row key={c.key} c={c} />)}</ul>
                      <p className="mt-3 text-xs text-muted">Profile as Google reported it on {when(l.fetched_at)}. Changes you make show here after the next daily refresh.</p>
                    </>}
              </Panel>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
