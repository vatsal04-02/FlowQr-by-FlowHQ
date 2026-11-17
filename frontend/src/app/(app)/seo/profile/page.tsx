"use client";
import clsx from "clsx";
import { Check, ChevronRight } from "lucide-react";
import Link from "next/link";
import { Ring } from "@/components/charts/Bars";
import { CountUp } from "@/components/charts/CountUp";
import { SourceTag } from "@/components/seo/parts";
import { Card, Dashes, Title } from "@/components/seo/visuals";
import { Alert, Skeleton } from "@/components/ui/Card";
import { LinkButton } from "@/components/ui/Button";
import { useLocationScope } from "@/lib/location-scope";
import type { HealthCheck, ProfileHealth } from "@/lib/seo";
import { useFetch } from "@/lib/use-api";

// quickest fixes first (minutes), slowest last
const EFFORT = ["phone", "website", "hours", "category", "additional_categories", "unanswered", "description", "services", "photos", "posts"];
const MINUTES: Record<string, string> = { phone: "1 min", website: "1 min", hours: "2 min", category: "2 min", additional_categories: "2 min", unanswered: "5 min", description: "5 min", services: "5 min", photos: "10 min", posts: "10 min" };

/** GBP › Profile: the strength ring, then every check ordered by how long it takes, each opening its editor. Built only from the profile Google returned. */
export default function ProfilePage() {
  const { locationId } = useLocationScope();
  const q = useFetch<ProfileHealth>("/seo/profile-health", { location_id: locationId ?? "" });
  const d = q.data;
  return (
    <>
      <h1 className="mb-4 text-[22px] font-semibold leading-7 sm:text-[26px]">Profile</h1>
      {q.error && <Alert tone="error">{q.error}</Alert>}
      {q.loading && !d ? <Skeleton className="h-64" /> : !d || d.state === "no_location" ? (
        <Card><div className="flex flex-wrap items-center justify-between gap-3"><p className="text-[14px] text-muted">Connect a Google location first.</p><LinkButton href="/gbp/locations" variant="secondary" size="sm">Connect Google</LinkButton></div></Card>
      ) : (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 lg:gap-4">
          {d.locations.map((l) => {
            const checks = [...l.checks].sort((a, b) => (a.status === "ok" ? 1 : 0) - (b.status === "ok" ? 1 : 0) || EFFORT.indexOf(a.key) - EFFORT.indexOf(b.key));
            const done = l.checks.filter((c) => c.status === "ok").length;
            return (
              <Card key={l.id} label={l.title ?? "Location"} tone="accent">
                <Title right={<SourceTag source="google" />}><span data-words="skip">{l.title ?? "Location"}</span></Title>
                {l.state === "unavailable" ? (
                  <div className="mt-4 flex items-center gap-4"><Ring value={null} size={88} stroke={9} label="Not shared yet"><span className="text-muted">–</span></Ring><div className="min-w-0 flex-1"><Dashes bars={8} className="!h-4" /><p className="mt-2 text-[13px] text-muted">Waiting for Google.</p></div></div>
                ) : (
                  <>
                    <div className="mt-4 flex items-center gap-4">
                      <Ring value={l.completeness} size={88} stroke={9} label={`Profile ${l.completeness}% complete`}><b className="num text-[20px] font-semibold">{l.completeness === null ? "–" : <><CountUp value={l.completeness} />%</>}</b></Ring>
                      <div className="text-[14px]"><b className="num text-[17px] font-semibold">{done}/{l.checks.length}</b><span className="text-muted"> done</span></div>
                    </div>
                    <ul className="mt-4 divide-y divide-line">{checks.map((c) => <Row key={c.key} c={c} />)}</ul>
                  </>
                )}
              </Card>
            );
          })}
        </div>
      )}
    </>
  );
}

function Row({ c }: { c: HealthCheck }) {
  const ok = c.status === "ok";
  const body = (
    <>
      <span aria-hidden className={clsx("grid h-6 w-6 shrink-0 place-items-center rounded-full", ok ? "bg-pos-tint text-pos" : c.status === "missing" ? "border-2 border-neg" : "border-2 border-warn")}>{ok && <Check className="h-3.5 w-3.5" strokeWidth={3} />}</span>
      <span className={clsx("min-w-0 flex-1 text-[14px]", ok ? "text-muted" : "font-medium")}>{c.label}<span className="sr-only">: {ok ? "done" : c.status === "missing" ? "missing" : "could be better"}</span></span>
      {!ok && <span className="shrink-0 text-[12px] text-muted">{MINUTES[c.key] ?? ""}</span>}
      {!ok && c.link && <ChevronRight className="h-4 w-4 shrink-0 text-ink-400" aria-hidden />}
    </>
  );
  return <li>{!ok && c.link ? <Link href={c.link} className="flex min-h-11 items-center gap-3 py-1.5 hover:bg-surface-2">{body}</Link> : <div className="flex min-h-11 items-center gap-3 py-1.5">{body}</div>}</li>;
}
