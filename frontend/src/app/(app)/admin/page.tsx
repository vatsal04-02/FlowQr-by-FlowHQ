"use client";
import { Building2, MapPin, QrCode, Star } from "lucide-react";
import { Card, CardHeader, PageHeader, Skeleton, Stat } from "@/components/ui/Card";
import { fmtDate, fmtNum } from "@/lib/format";
import { useFetch } from "@/lib/use-api";

interface Stats { tenants: number; locations: number; cards_by_status: Record<string, number>; events: Record<string, number>; synced_reviews: number }
interface TenantRow { id: string; name: string; category: string | null; created_at: string; is_active: boolean; locations: number; cards: number; members: number }

export default function AdminHome() {
  const stats = useFetch<Stats>("/admin/stats");
  const tenants = useFetch<TenantRow[]>("/admin/tenants");
  const total = stats.data ? Object.values(stats.data.cards_by_status).reduce((a, b) => a + b, 0) : 0;
  return (
    <>
      <PageHeader title="Platform admin" subtitle="All businesses and cards across FlowQR." />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {!stats.data ? Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-28" />) : <>
          <Stat label="Businesses" value={fmtNum(stats.data.tenants)} icon={<Building2 className="h-5 w-5" />} />
          <Stat label="Locations" value={fmtNum(stats.data.locations)} icon={<MapPin className="h-5 w-5" />} tone="green" />
          <Stat label="Cards" value={fmtNum(total)} hint={`${stats.data.cards_by_status.active ?? 0} active · ${stats.data.cards_by_status.unassigned ?? 0} unassigned`} icon={<QrCode className="h-5 w-5" />} tone="flow" />
          <Stat label="Synced reviews" value={fmtNum(stats.data.synced_reviews)} icon={<Star className="h-5 w-5" />} tone="yellow" />
        </>}
      </div>
      <Card className="mt-5" pad={false}>
        <div className="p-5 sm:p-6"><CardHeader title="Businesses" /></div>
        <div className="overflow-x-auto"><table className="w-full min-w-[620px] text-left text-sm">
          <thead className="border-y border-ink-100 bg-ink-50 text-xs uppercase tracking-wide text-ink-500"><tr>{["Business", "Category", "Locations", "Cards", "Members", "Joined"].map((h) => <th key={h} className="px-4 py-2.5 font-semibold">{h}</th>)}</tr></thead>
          <tbody>{tenants.data?.map((t) => <tr key={t.id} className="border-b border-ink-100 last:border-0"><td className="px-4 py-3 font-semibold">{t.name}</td><td className="px-4">{t.category}</td><td className="px-4 tabular-nums">{t.locations}</td><td className="px-4 tabular-nums">{t.cards}</td><td className="px-4 tabular-nums">{t.members}</td><td className="px-4">{fmtDate(t.created_at)}</td></tr>)}</tbody>
        </table></div>
      </Card>
    </>
  );
}
