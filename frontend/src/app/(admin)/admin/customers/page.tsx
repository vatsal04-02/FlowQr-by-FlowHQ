"use client";
import { Search } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { FilterSelect } from "@/components/ui/Form";
import { fmtDate } from "@/lib/format";
import { SUB_TONE, type TenantRow } from "@/lib/admin-ui";
import { useFetch } from "@/lib/use-api";

const PAGE = 25;

export default function Customers() {
  const [q, setQ] = useState(""), [search, setSearch] = useState(""), [status, setStatus] = useState(""), [page, setPage] = useState(0);
  useEffect(() => { const t = setTimeout(() => { setSearch(q); setPage(0); }, 300); return () => clearTimeout(t); }, [q]);
  const { data, error, loading } = useFetch<{ total: number; items: TenantRow[] }>("/admin/tenants", { search, status, limit: PAGE, offset: page * PAGE });
  return (
    <>
      <PageHeader title="Customers" subtitle="Businesses on FlowQR. Open one to manage its account, subscription and support status." />
      <Card pad={false} className="mb-4 p-3 sm:p-4"><div className="flex flex-wrap gap-2">
        <div className="relative min-w-[200px] flex-1"><Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" aria-hidden /><input aria-label="Search customers" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search business name" className="min-h-11 w-full rounded-xl border border-ink-200 pl-9 pr-3 text-sm sm:min-h-10" /></div>
        <FilterSelect label="Status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(0); }}><option value="">All statuses</option>{["trialing", "active", "past_due", "halted", "expired", "canceled", "suspended"].map((s) => <option key={s}>{s}</option>)}</FilterSelect>
      </div></Card>
      {error && <Alert tone="error">{error}</Alert>}
      {loading && !data ? <Skeleton className="h-64" /> : data && data.items.length === 0 ? <EmptyState title="No customers match">Try a different search or filter.</EmptyState> : (
        <Card pad={false}><div className="overflow-x-auto"><table className="w-full min-w-[820px] text-left text-sm">
          <thead className="border-b border-ink-100 bg-ink-50 text-xs uppercase tracking-wide text-ink-500"><tr>{["Business", "Owner", "Plan", "Locations", "Cards", "Support", "Joined"].map((h) => <th key={h} className="px-4 py-2.5 font-semibold">{h}</th>)}</tr></thead>
          <tbody>{data?.items.map((t) => (
            <tr key={t.id} className="border-b border-ink-100 last:border-0 hover:bg-ink-50/60">
              <td className="px-4 py-3"><Link href={`/admin/customers/${t.id}`} className="font-semibold text-brand-700 hover:underline">{t.name}</Link>{!t.is_active && <Badge tone="red">suspended</Badge>}<span className="block text-xs text-ink-500">{t.category}</span></td>
              <td className="px-4 text-ink-700">{t.owner_email}</td>
              <td className="px-4">{t.plan} <Badge tone={SUB_TONE[t.subscription_status ?? ""] ?? "gray"}>{t.subscription_status}</Badge></td>
              <td className="px-4 tabular-nums">{t.locations}</td><td className="px-4 tabular-nums">{t.cards}</td>
              <td className="px-4">{t.support_status !== "none" ? <Badge tone={t.support_status === "resolved" ? "green" : "amber"}>{t.support_status}</Badge> : <span className="text-ink-400">–</span>}</td>
              <td className="px-4">{fmtDate(t.created_at)}</td></tr>))}</tbody>
        </table></div></Card>
      )}
      {data && data.total > PAGE && <div className="mt-4 flex items-center justify-between"><Button variant="secondary" size="sm" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</Button><span className="text-sm text-ink-500">{page * PAGE + 1}–{Math.min(data.total, (page + 1) * PAGE)} of {data.total}</span><Button variant="secondary" size="sm" disabled={(page + 1) * PAGE >= data.total} onClick={() => setPage(page + 1)}>Next</Button></div>}
    </>
  );
}
