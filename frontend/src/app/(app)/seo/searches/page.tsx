"use client";
import { Search } from "lucide-react";
import Link from "next/link";
import { SourceTag, Unavailable, when } from "@/components/seo/parts";
import { Alert, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { Panel } from "@/components/ui/kit";
import { fmtNum } from "@/lib/format";
import { useLocationScope } from "@/lib/location-scope";
import type { SeoOverview } from "@/lib/seo";
import { useFetch } from "@/lib/use-api";

/**
 * Visibility › Searches people use: the words customers typed on Google before they saw your business, with how many people used them each month, as Google reports it. This is NOT
 * a ranking: it says what people look for, not where you appear. Positions are on "Where you appear on Google Maps" and come from a different source. Nothing is shown until Google shares it.
 */
export default function SearchesPage() {
  const { locationId } = useLocationScope();
  const q = useFetch<SeoOverview>("/seo/overview", { location_id: locationId ?? "" });
  const d = q.data;
  const t = d?.google_terms;
  const top = Math.max(1, ...(t?.terms ?? []).map((x) => x.value ?? 0));
  return (
    <>
      <PageHeader title="Searches people use" subtitle="The words customers typed on Google before they saw your business. This tells you what people look for. It does not say where you appear." />
      {q.error && <Alert tone="error" title="We couldn't load this">{q.error}</Alert>}
      {q.loading && !d && <Skeleton className="h-64" />}
      {d?.state === "no_location" && <EmptyState icon={<Search className="h-5 w-5" />} title="Connect a Google location first" action={<Link href="/gbp/locations" className="font-semibold text-accent-ink hover:underline">Connect Google</Link>}>These words come from your Google Business Profile.</EmptyState>}
      {d && d.state !== "no_location" && (
        <Panel dense title="Most used words" meta={t ? `monthly, ${t.months.join(", ") || "latest month"}` : undefined} action={<SourceTag source="google" />}>
          {!t ? <Unavailable title="Google hasn't shared these numbers with FlowQR yet">When Google shares them, the words people used before finding your business appear here.</Unavailable> : (
            <>
              <ul className="divide-y divide-ink-100">
                {t.terms.map((x) => (
                  <li key={x.keyword} className="py-2.5 first:pt-0">
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="min-w-0 text-[14px] font-medium">{x.keyword}</span>
                      <span className="num shrink-0 text-[14px] font-semibold">{x.value === null ? "A few people" : fmtNum(x.value)}</span>
                    </div>
                    <span aria-hidden className="mt-1.5 block h-1.5 overflow-hidden rounded-full bg-surface-3"><span className="block h-full rounded-full bg-accent" style={{ width: `${x.value === null ? 3 : Math.max(3, (x.value / top) * 100)}%` }} /></span>
                    <p className="mt-1 text-xs text-muted">{x.tracked ? "You also track this on Google Maps." : <><Link href="/seo/rankings" className="font-semibold text-accent-ink hover:underline">Track this word</Link> to see where you appear for it.</>}</p>
                  </li>
                ))}
              </ul>
              <p className="mt-3 text-xs text-muted">{t.note} Updated {when(t.fetched_at)}. When Google counts only a few people it gives no exact number, so none is shown.</p>
            </>
          )}
        </Panel>
      )}
    </>
  );
}
