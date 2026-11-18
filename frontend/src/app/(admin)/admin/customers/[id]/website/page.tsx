"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { SiteEditor } from "@/components/admin/site/SiteEditor";
import { Alert, Skeleton } from "@/components/ui/Card";
import { useFetch } from "@/lib/use-api";
import type { SiteConfig, SiteInfo } from "@/lib/sites";

/** The website editor for one business. The URL is under /admin/customers so every existing business link keeps working. */
export default function BusinessWebsite() {
  const { id } = useParams<{ id: string }>();
  const cfg = useFetch<SiteConfig>("/admin/sites/config");
  const summary = useFetch<{ enabled: boolean; site: SiteInfo | null }>(`/admin/tenants/${id}/site`);
  if (cfg.error || summary.error) return <Alert tone="error">{cfg.error ?? summary.error}</Alert>;
  if (!cfg.data || !summary.data) return <Skeleton className="h-96" />;
  if (!cfg.data.enabled) return <Alert tone="info" title="Websites are switched off">The website builder is off on this server. <Link href={`/admin/customers/${id}`} className="font-semibold underline">Back to the business</Link></Alert>;
  if (!summary.data.site) return <Alert tone="info" title="No website yet">Create one from the Website card on the business page. <Link href={`/admin/customers/${id}`} className="font-semibold underline">Go to the business</Link></Alert>;
  return <SiteEditor siteId={summary.data.site.id} tenantId={id} />;
}
