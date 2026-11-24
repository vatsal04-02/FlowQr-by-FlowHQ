"use client";
import { AlertTriangle, CheckCircle2, LifeBuoy, ShieldAlert } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { LineChart } from "@/components/charts/LineChart";
import { Badge, PageHeader, Skeleton } from "@/components/ui/Card";
import { KV, Panel } from "@/components/ui/kit";
import { rupees } from "@/lib/billing";
import { SUB_TONE, type TenantRow } from "@/lib/admin-ui";
import { fmtDate, fmtNum } from "@/lib/format";
import { useFetch } from "@/lib/use-api";

interface Stats {
  tenants: number; suspended_tenants: number; open_support: number; locations: number; synced_reviews: number; cards_by_status: Record<string, number>;
  events: Record<string, number>; subscriptions_by_status: Record<string, number>; mrr_paise: number; revenue_paise: { subscription: number; card_order: number };
  signups_30d: { date: string; count: number }[]; ai_generations_this_month: number;
}
interface M { value: number | string | Record<string, number> | null; status: "actual" | "estimated" | "missing" }
interface Finance { revenue: Record<string, M | string>; economics: Record<string, unknown> }
interface Sub { tenant_id: string; tenant: string; plan: string; status: string; current_period_end: string | null; next_charge_at: string | null; cancel_at_period_end: boolean }
interface Pay { id: string; tenant: string; status: string; amount_paise: number; created_at: string; failure_reason: string | null; error_description: string | null }
interface Audit { id: string; action: string; created_at: string; user: string | null; tenant: string | null }
interface Ops { status: "ok" | "warn" | "critical" | "unknown"; counts: Record<string, number> }

const num = (m: M | string | undefined): number | null => (m && typeof m === "object" && m.status !== "missing" && typeof m.value === "number" ? m.value : null);
const CARD_ORDER: [string, string][] = [["active", "bg-ok"], ["assigned", "bg-brand-600"], ["unassigned", "bg-ink-300"], ["paused", "bg-amber-300"], ["deactivated", "bg-amber-500"], ["lost", "bg-red-600"]];

function Kpi({ label, value, hint, href, tone }: { label: string; value: ReactNode; hint?: string; href?: string; tone?: "bad" | "warn" }) {
  const body = (
    <>
      <span className="block text-[12px] font-medium text-muted">{label}</span>
      <span className={`num mt-0.5 block text-[22px] font-semibold leading-7 tracking-tight sm:text-2xl ${tone === "bad" ? "text-neg" : tone === "warn" ? "text-warn" : ""}`}>{value}</span>
      {hint && <span className="mt-0.5 block text-[12px] leading-4 text-ink-500">{hint}</span>}
    </>
  );
  const cls = "adm-card-link block min-w-0 rounded-xl border border-ink-100 bg-surface px-3 py-2.5 sm:px-4 sm:py-3";
  return href ? <Link href={href} className={`${cls} hover:bg-surface-2`}>{body}</Link> : <div className={cls}>{body}</div>;
}

/** The operator's first screen: how big is the business, what does it earn, and what needs a person right now. Every figure is read from the platform's own data; a figure that cannot be measured is shown as "n/a", never as zero. */
export default function AdminHome() {
  const stats = useFetch<Stats>("/admin/stats");
  const fin = useFetch<Finance>("/admin/finance");
  const subs = useFetch<Sub[]>("/admin/subscriptions", { limit: 200 });
  const pays = useFetch<Pay[]>("/admin/payments", { status: "failed", limit: 50 });
  const audit = useFetch<Audit[]>("/admin/audit", { limit: 8 });
  const fresh = useFetch<{ total: number; items: TenantRow[] }>("/admin/tenants", { limit: 5 });
  const ops = useFetch<Ops>("/admin/ops");
  const s = stats.data;
  const r = fin.data?.revenue;
  const cards = s ? Object.values(s.cards_by_status).reduce((a, b) => a + b, 0) : 0;
  const paying = num(r?.paid_subscribers);
  const mrr = num(r?.mrr_paise), arr = num(r?.arr_paise), churn = num(fin.data?.economics.monthly_paid_churn as M | undefined);
  const trials = s?.subscriptions_by_status.trialing ?? null;
  const failed30 = (pays.data ?? []).filter((p) => Date.now() - +new Date(p.created_at) < 30 * 864e5);
  const soon = (subs.data ?? []).filter((x) => ["active", "past_due"].includes(x.status) && (x.next_charge_at || x.current_period_end)).map((x) => ({ ...x, at: x.next_charge_at || x.current_period_end! }))
    .filter((x) => +new Date(x.at) > Date.now() - 864e5 && +new Date(x.at) < Date.now() + 14 * 864e5).sort((a, b) => +new Date(a.at) - +new Date(b.at)).slice(0, 5);
  const attention: { href: string; text: string; n: number; icon: ReactNode }[] = s ? [
    { href: "/admin/billing", n: failed30.length, text: "Failed payments (30 days)", icon: <AlertTriangle className="h-4 w-4 text-neg" aria-hidden /> },
    { href: "/admin/customers?status=past_due", n: s.subscriptions_by_status.past_due ?? 0, text: "Past-due subscriptions", icon: <ShieldAlert className="h-4 w-4 text-warn" aria-hidden /> },
    { href: "/admin/customers?status=halted", n: s.subscriptions_by_status.halted ?? 0, text: "Halted subscriptions", icon: <ShieldAlert className="h-4 w-4 text-neg" aria-hidden /> },
    { href: "/admin/customers?status=suspended", n: s.suspended_tenants, text: "Suspended clients", icon: <ShieldAlert className="h-4 w-4 text-ink-400" aria-hidden /> },
    { href: "/admin/queue", n: s.open_support, text: "Open support issues", icon: <LifeBuoy className="h-4 w-4 text-brand-600" aria-hidden /> },
    ...(ops.data && (ops.data.counts.critical || ops.data.counts.warn) ? [{ href: "/admin/ops", n: (ops.data.counts.critical ?? 0) + (ops.data.counts.warn ?? 0), text: "System checks need attention", icon: <AlertTriangle className="h-4 w-4 text-neg" aria-hidden /> }] : []),
  ] : [];
  const open = attention.filter((a) => a.n > 0);
  return (
    <>
      {ops.data?.status === "critical" && (
        <Link href="/admin/ops" className="mb-4 flex min-h-11 items-center gap-3 rounded-xl border border-[#F4C7C1] bg-[#FDEAE8] px-4 py-3 text-[14px] text-[#A4200F]">
          <AlertTriangle aria-hidden className="h-5 w-5 shrink-0" /><span className="min-w-0 flex-1"><b className="font-semibold">{ops.data.counts.critical} critical item{ops.data.counts.critical === 1 ? "" : "s"} on System health.</b> Open it to see what to do.</span><span className="shrink-0 font-semibold underline">Open</span>
        </Link>
      )}
      <PageHeader eyebrow="Platform" title="Operator overview" subtitle="Clients, revenue and what needs you, across all of FlowQR." />
      {!s ? <div className="grid grid-cols-2 gap-3 lg:grid-cols-4"><Skeleton className="h-20" /><Skeleton className="h-20" /><Skeleton className="h-20" /><Skeleton className="h-20" /></div> : (
        <div className="space-y-4">
          <ul aria-label="Key numbers" className="grid grid-cols-2 gap-2 sm:gap-3 lg:grid-cols-4">
            <li><Kpi label="Total clients" value={fmtNum(s.tenants)} hint={`${fmtNum(s.locations)} locations`} href="/admin/customers" /></li>
            <li><Kpi label="Paying clients" value={paying === null ? "n/a" : fmtNum(paying)} hint="Active, paid via provider" href="/admin/customers?status=active" /></li>
            <li><Kpi label="On trial" value={trials === null ? "n/a" : fmtNum(trials)} hint="Not revenue" href="/admin/customers?status=trialing" /></li>
            <li><Kpi label="MRR" value={mrr === null ? "n/a" : rupees(mrr)} hint="Paid subscriptions at list price" href="/admin/finance" /></li>
            <li><Kpi label="ARR (run-rate)" value={arr === null ? "n/a" : rupees(arr)} hint="MRR x 12, an estimate" href="/admin/finance" /></li>
            <li><Kpi label="Total revenue" value={rupees(s.revenue_paise.subscription + s.revenue_paise.card_order)} hint={`Software ${rupees(s.revenue_paise.subscription)} · cards ${rupees(s.revenue_paise.card_order)}`} href="/admin/billing" /></li>
            <li><Kpi label="Monthly churn" value={churn === null ? "n/a" : `${(churn * 100).toFixed(1)}%`} hint={churn === null ? "Not enough data to measure" : "Paid subscribers lost"} href="/admin/finance" /></li>
            <li><Kpi label="Failed payments" value={pays.data ? failed30.length : "…"} hint="Last 30 days" tone={failed30.length ? "bad" : undefined} href="/admin/billing" /></li>
          </ul>

          <div className="grid gap-4 lg:grid-cols-3">
            <Panel title="Needs attention" flush meta={open.length ? `${open.length} open` : undefined}>
              {open.length === 0 ? <p className="flex items-center gap-2 px-4 py-4 text-sm text-pos"><CheckCircle2 aria-hidden className="h-4 w-4" />Nothing is waiting.</p> : (
                <ul className="divide-y divide-ink-100 text-sm">{open.map((a) => (
                  <li key={a.href + a.text}><Link href={a.href} className="flex min-h-11 items-center justify-between gap-2 px-4 py-2 hover:bg-ink-50/60"><span className="flex min-w-0 items-center gap-2">{a.icon}<span className="truncate">{a.text}</span></span><b className="num font-semibold">{a.n}</b></Link></li>))}</ul>)}
            </Panel>
            <Panel title="Upcoming renewals" meta="next 14 days" flush>
              {!subs.data ? <Skeleton className="m-4 h-20" /> : soon.length === 0 ? <p className="px-4 py-4 text-sm text-muted">No renewals due in the next 14 days.</p> : (
                <ul className="divide-y divide-ink-100 text-sm">{soon.map((x) => (
                  <li key={x.tenant_id}><Link href={`/admin/customers/${x.tenant_id}`} className="flex min-h-11 items-center justify-between gap-2 px-4 py-2 hover:bg-ink-50/60"><span className="min-w-0"><span className="block truncate font-medium">{x.tenant}</span><span className="block text-xs text-ink-500">{x.plan}{x.cancel_at_period_end ? " · cancels" : ""}</span></span><span className="shrink-0 text-xs tabular-nums">{fmtDate(x.at)}</span></Link></li>))}</ul>)}
            </Panel>
            <Panel title="Newest clients" flush action={<Link href="/admin/customers" className="text-[13px] font-medium text-brand-700 hover:underline">All</Link>}>
              {!fresh.data ? <Skeleton className="m-4 h-20" /> : (
                <ul className="divide-y divide-ink-100 text-sm">{fresh.data.items.map((t) => (
                  <li key={t.id}><Link href={`/admin/customers/${t.id}`} className="flex min-h-11 items-center justify-between gap-2 px-4 py-2 hover:bg-ink-50/60"><span className="min-w-0"><span className="block truncate font-medium">{t.name}</span><span className="block text-xs text-ink-500">{fmtDate(t.created_at)}</span></span>
                    {t.subscription_status ? <Badge tone={SUB_TONE[t.subscription_status] ?? "gray"}>{t.subscription_status}</Badge> : null}</Link></li>))}</ul>)}
            </Panel>
          </div>

          <div className="grid gap-4 lg:grid-cols-[1.7fr_1fr]">
            <Panel title="New clients" meta="last 30 days"><LineChart ariaLabel="New clients per day" data={s.signups_30d} series={[{ key: "count", label: "Sign-ups", color: "#FE6A05" }]} height={200} /></Panel>
            <Panel title="Recent activity" flush action={<Link href="/admin/audit" className="text-[13px] font-medium text-brand-700 hover:underline">Audit log</Link>}>
              {!audit.data ? <Skeleton className="m-4 h-24" /> : audit.data.length === 0 ? <p className="px-4 py-4 text-sm text-muted">No activity yet.</p> : (
                <ul className="divide-y divide-ink-100 text-sm">{audit.data.map((a) => (
                  <li key={a.id} className="px-4 py-2"><span className="block truncate font-mono text-[12px]">{a.action}</span><span className="block truncate text-xs text-ink-500">{[a.tenant, a.user].filter(Boolean).join(" · ") || "system"} · {fmtDate(a.created_at)}</span></li>))}</ul>)}
            </Panel>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Panel title="Card inventory" meta={`${fmtNum(cards)} cards`} action={<Link href="/admin/cards" className="text-[13px] font-medium text-brand-700 hover:underline">Manage</Link>}>
              <div className="flex h-2.5 overflow-hidden rounded-full bg-ink-100" role="img" aria-label={`Card inventory: ${CARD_ORDER.map(([k]) => `${s.cards_by_status[k] ?? 0} ${k}`).join(", ")}`}>
                {CARD_ORDER.map(([k, c]) => (s.cards_by_status[k] ?? 0) > 0 && <span key={k} className={c} style={{ width: `${((s.cards_by_status[k] ?? 0) / Math.max(1, cards)) * 100}%` }} />)}
              </div>
              <ul className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">{CARD_ORDER.map(([k, c]) => <li key={k} className="flex items-center justify-between gap-2"><span className="flex items-center gap-2 capitalize"><span aria-hidden className={`h-2 w-2 rounded-full ${c}`} />{k}</span><b className="num font-semibold">{s.cards_by_status[k] ?? 0}</b></li>)}</ul>
            </Panel>
            <Panel title="Platform totals" flush><div className="px-4 py-1"><KV rows={[["Synced reviews", <span key="c" className="num">{fmtNum(s.synced_reviews)}</span>], ["AI generations this month", <span key="d" className="num">{fmtNum(s.ai_generations_this_month)}</span>], ["Subscriptions by status", <span key="e" className="num text-right">{Object.entries(s.subscriptions_by_status).map(([k, v]) => `${k} ${v}`).join(" · ") || "none"}</span>]]} /></div></Panel>
          </div>
        </div>
      )}
    </>
  );
}
