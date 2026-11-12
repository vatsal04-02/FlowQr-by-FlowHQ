"use client";
import { LifeBuoy, ShieldAlert } from "lucide-react";
import Link from "next/link";
import { LineChart } from "@/components/charts/LineChart";
import { PageHeader, Skeleton } from "@/components/ui/Card";
import { KV, Panel } from "@/components/ui/kit";
import { rupees } from "@/lib/billing";
import { fmtNum } from "@/lib/format";
import { useFetch } from "@/lib/use-api";

interface Stats {
  tenants: number; suspended_tenants: number; open_support: number; locations: number; synced_reviews: number; cards_by_status: Record<string, number>;
  events: Record<string, number>; subscriptions_by_status: Record<string, number>; mrr_paise: number; revenue_paise: { subscription: number; card_order: number };
  signups_30d: { date: string; count: number }[]; ai_generations_this_month: number;
}

const CARD_ORDER: [string, string][] = [["active", "bg-ok"], ["assigned", "bg-brand-600"], ["unassigned", "bg-ink-300"], ["paused", "bg-amber-300"], ["deactivated", "bg-amber-500"], ["lost", "bg-red-600"]];

export default function AdminHome() {
  const { data: s } = useFetch<Stats>("/admin/stats");
  const cards = s ? Object.values(s.cards_by_status).reduce((a, b) => a + b, 0) : 0;
  return (
    <>
      <PageHeader eyebrow="Platform" title="Platform overview" subtitle="Everything across all FlowQR customers." />
      {!s ? <div className="grid gap-4 lg:grid-cols-3"><Skeleton className="h-44" /><Skeleton className="h-44" /><Skeleton className="h-44" /></div> : (
        <div className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-3">
            <Panel title="Revenue" meta="software and cards kept separate">
              <dl className="divide-y divide-ink-100">
                {[["MRR (Razorpay)", rupees(s.mrr_paise), `${s.subscriptions_by_status.active ?? 0} active · ${s.subscriptions_by_status.trialing ?? 0} trialing`], ["Software revenue", rupees(s.revenue_paise.subscription), "Captured subscription payments"], ["Card sales", rupees(s.revenue_paise.card_order), "Tracked separately from software"]].map(([k, v, h]) => (
                  <div key={k} className="flex items-baseline justify-between gap-3 py-2.5 first:pt-0 last:pb-0"><div><dt className="text-sm font-medium">{k}</dt><dd className="text-xs text-ink-500">{h}</dd></div><dd className="num text-xl font-bold tracking-tight">{v}</dd></div>))}
              </dl>
            </Panel>
            <Panel title="Card inventory" meta={`${fmtNum(cards)} cards`} action={<Link href="/admin/cards" className="text-[13px] font-medium text-brand-700 hover:underline">Manage</Link>}>
              <div className="flex h-2.5 overflow-hidden rounded-full bg-ink-100" role="img" aria-label={`Card inventory: ${CARD_ORDER.map(([k]) => `${s.cards_by_status[k] ?? 0} ${k}`).join(", ")}`}>
                {CARD_ORDER.map(([k, c]) => (s.cards_by_status[k] ?? 0) > 0 && <span key={k} className={c} style={{ width: `${((s.cards_by_status[k] ?? 0) / Math.max(1, cards)) * 100}%` }} />)}
              </div>
              <ul className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">{CARD_ORDER.map(([k, c]) => <li key={k} className="flex items-center justify-between gap-2"><span className="flex items-center gap-2 capitalize"><span aria-hidden className={`h-2 w-2 rounded-full ${c}`} />{k}</span><b className="num font-semibold">{s.cards_by_status[k] ?? 0}</b></li>)}</ul>
            </Panel>
            <Panel title="Needs attention" flush>
              <ul className="divide-y divide-ink-100 text-sm">
                {[["/admin/customers?status=past_due", s.subscriptions_by_status.past_due ?? 0, "Past-due subscriptions", <ShieldAlert key="a" className="h-4 w-4 text-amber-600" aria-hidden />],
                  ["/admin/customers?status=halted", s.subscriptions_by_status.halted ?? 0, "Halted subscriptions", <ShieldAlert key="b" className="h-4 w-4 text-red-600" aria-hidden />],
                  ["/admin/customers?support=open", s.open_support, "Open support issues", <LifeBuoy key="c" className="h-4 w-4 text-brand-600" aria-hidden />],
                  ["/admin/customers?status=suspended", s.suspended_tenants, "Suspended customers", <ShieldAlert key="d" className="h-4 w-4 text-ink-400" aria-hidden />]].map(([href, n, label, icon]) => (
                  <li key={href as string}><Link href={href as string} className="flex min-h-11 items-center justify-between gap-2 px-4 py-2 hover:bg-ink-50/60"><span className="flex items-center gap-2">{icon}{label as string}</span><b className="num font-semibold">{n as number}</b></Link></li>))}
              </ul>
            </Panel>
          </div>
          <div className="grid gap-4 lg:grid-cols-[1.7fr_1fr]">
            <Panel title="New customers" meta="last 30 days"><LineChart ariaLabel="New customers per day" data={s.signups_30d} series={[{ key: "count", label: "Sign-ups", color: "#1B46B8" }]} height={200} /></Panel>
            <Panel title="Platform totals" flush><div className="px-4 py-1"><KV rows={[["Customers", <span key="a" className="num">{fmtNum(s.tenants)}</span>], ["Locations", <span key="b" className="num">{fmtNum(s.locations)}</span>], ["Synced reviews", <span key="c" className="num">{fmtNum(s.synced_reviews)}</span>], ["AI generations this month", <span key="d" className="num">{fmtNum(s.ai_generations_this_month)}</span>]]} /></div></Panel>
          </div>
        </div>
      )}
    </>
  );
}
