"use client";
import { Building2, CreditCard, LifeBuoy, MapPin, QrCode, ShieldAlert, Sparkles, Star } from "lucide-react";
import Link from "next/link";
import { LineChart } from "@/components/charts/LineChart";
import { Card, CardHeader, PageHeader, Skeleton, Stat } from "@/components/ui/Card";
import { rupees } from "@/lib/billing";
import { fmtNum } from "@/lib/format";
import { useFetch } from "@/lib/use-api";

interface Stats {
  tenants: number; suspended_tenants: number; open_support: number; locations: number; synced_reviews: number; cards_by_status: Record<string, number>;
  events: Record<string, number>; subscriptions_by_status: Record<string, number>; mrr_paise: number; revenue_paise: { subscription: number; card_order: number };
  signups_30d: { date: string; count: number }[]; ai_generations_this_month: number;
}

export default function AdminHome() {
  const { data: s } = useFetch<Stats>("/admin/stats");
  const cards = s ? Object.values(s.cards_by_status).reduce((a, b) => a + b, 0) : 0;
  return (
    <>
      <PageHeader title="Platform overview" subtitle="Everything across all FlowQR customers." />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {!s ? Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-28" />) : <>
          <Stat label="Customers" value={fmtNum(s.tenants)} icon={<Building2 className="h-5 w-5" />} hint={`${s.suspended_tenants} suspended`} />
          <Stat label="MRR (Razorpay)" value={rupees(s.mrr_paise)} icon={<CreditCard className="h-5 w-5" />} tone="green" hint={`${s.subscriptions_by_status.active ?? 0} active · ${s.subscriptions_by_status.trialing ?? 0} trialing`} />
          <Stat label="Software revenue" value={rupees(s.revenue_paise.subscription)} icon={<CreditCard className="h-5 w-5" />} tone="green" hint="Captured subscription payments" />
          <Stat label="Card sales" value={rupees(s.revenue_paise.card_order)} icon={<QrCode className="h-5 w-5" />} tone="flow" hint="Tracked separately from software" />
          <Stat label="Cards" value={fmtNum(cards)} icon={<QrCode className="h-5 w-5" />} tone="flow" hint={`${s.cards_by_status.active ?? 0} active · ${s.cards_by_status.unassigned ?? 0} unassigned`} />
          <Stat label="Locations" value={fmtNum(s.locations)} icon={<MapPin className="h-5 w-5" />} />
          <Stat label="Synced reviews" value={fmtNum(s.synced_reviews)} icon={<Star className="h-5 w-5" />} tone="yellow" />
          <Stat label="AI this month" value={fmtNum(s.ai_generations_this_month)} icon={<Sparkles className="h-5 w-5" />} tone="yellow" />
        </>}
      </div>
      <div className="mt-5 grid gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2"><CardHeader title="New customers" subtitle="Last 30 days" />{s ? <LineChart ariaLabel="New customers per day" data={s.signups_30d} series={[{ key: "count", label: "Sign-ups", color: "#2F6FE4" }]} height={200} /> : <Skeleton className="h-52" />}</Card>
        <Card><CardHeader title="Needs attention" />
          <ul className="space-y-2 text-sm">
            <li><Link href="/admin/customers?status=past_due" className="flex min-h-11 items-center gap-2 rounded-xl p-2 hover:bg-ink-50"><ShieldAlert className="h-4 w-4 text-amber-600" aria-hidden />Past-due subscriptions: <b>{s?.subscriptions_by_status.past_due ?? 0}</b></Link></li>
            <li><Link href="/admin/customers?status=halted" className="flex min-h-11 items-center gap-2 rounded-xl p-2 hover:bg-ink-50"><ShieldAlert className="h-4 w-4 text-red-600" aria-hidden />Halted: <b>{s?.subscriptions_by_status.halted ?? 0}</b></Link></li>
            <li><Link href="/admin/customers?support=open" className="flex min-h-11 items-center gap-2 rounded-xl p-2 hover:bg-ink-50"><LifeBuoy className="h-4 w-4 text-brand-600" aria-hidden />Open support: <b>{s?.open_support ?? 0}</b></Link></li>
          </ul>
        </Card>
      </div>
    </>
  );
}
