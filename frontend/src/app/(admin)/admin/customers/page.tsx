"use client";
import { Plus, Search } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AddBusinessForm } from "@/components/admin/AddBusinessForm";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { FilterSelect } from "@/components/ui/Form";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { fmtDate } from "@/lib/format";
import { ONBOARDING, SUB_TONE, type TenantRow } from "@/lib/admin-ui";
import { useFetch } from "@/lib/use-api";

const PAGE = 25;

/** The business directory. The URL stays /admin/customers so every existing link keeps working. A business here may have no FlowQR login at all: staff manage it, and its cards work regardless. */
export default function Businesses() {
  const router = useRouter();
  const toast = useToast();
  const [q, setQ] = useState(""), [search, setSearch] = useState(""), [status, setStatus] = useState(""), [origin, setOrigin] = useState(""), [onboarding, setOnboarding] = useState(""), [page, setPage] = useState(0);
  const [adding, setAdding] = useState(false);
  useEffect(() => { const t = setTimeout(() => { setSearch(q); setPage(0); }, 300); return () => clearTimeout(t); }, [q]);
  const { data, error, loading, reload } = useFetch<{ total: number; items: TenantRow[] }>("/admin/tenants", { search, status, origin, onboarding, limit: PAGE, offset: page * PAGE });
  const filtered = !!(search || status || origin || onboarding);
  return (
    <>
      <PageHeader eyebrow="Platform" title="Businesses" subtitle="Every business on FlowQR: shops you set up for them, and businesses with their own login. Open one to manage its locations, cards and access."
        actions={<><Link href="/admin/managed-usage" className="inline-flex min-h-11 items-center rounded-full bg-surface px-4 text-sm font-semibold shadow-pill hover:bg-ink-50 sm:min-h-10">Usage and cost</Link><Button className="!rounded-full" icon={<Plus className="h-4 w-4" />} onClick={() => setAdding(true)}>Add business</Button></>} />
      <Card pad={false} className="mb-4 p-3 sm:p-4"><div className="flex flex-wrap gap-2">
        <div className="relative min-w-[200px] flex-1"><Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" aria-hidden /><input aria-label="Search businesses" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, contact, city or phone" className="min-h-11 w-full rounded-xl border border-ink-200 pl-9 pr-3 text-sm sm:min-h-10" /></div>
        <FilterSelect label="Set up by" value={origin} onChange={(e) => { setOrigin(e.target.value); setPage(0); }}><option value="">Everyone</option><option value="admin">Set up by FlowQR staff</option><option value="self_service">Signed up themselves</option></FilterSelect>
        <FilterSelect label="Onboarding" value={onboarding} onChange={(e) => { setOnboarding(e.target.value); setPage(0); }}><option value="">Any stage</option>{Object.entries(ONBOARDING).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</FilterSelect>
        <FilterSelect label="Subscription" value={status} onChange={(e) => { setStatus(e.target.value); setPage(0); }}><option value="">All plans</option>{["trialing", "active", "manual", "past_due", "halted", "expired", "canceled", "suspended"].map((s) => <option key={s}>{s}</option>)}</FilterSelect>
      </div></Card>
      {error && <Alert tone="error">{error}</Alert>}
      {loading && !data ? <Skeleton className="h-64" /> : data && data.items.length === 0 ? (
        <EmptyState title={filtered ? "No businesses match" : "No businesses yet"} action={filtered ? undefined : <Button onClick={() => setAdding(true)}>Add business</Button>}>{filtered ? "Try a different search or filter." : "Add the first shop to start assigning cards."}</EmptyState>
      ) : (
        <Card pad={false}><div className="overflow-x-auto"><table className="dt min-w-[1080px]">
          <thead><tr>{["Business", "Contact", "Phone", "Locations", "Cards", "Live", "Stage", "Access", "Added"].map((h) => <th key={h} className="px-4 py-2.5 font-semibold">{h}</th>)}</tr></thead>
          <tbody>{data?.items.map((t) => {
            const o = ONBOARDING[t.onboarding_status ?? "incomplete"];
            return (
              <tr key={t.id} className="border-b border-ink-100 last:border-0 hover:bg-ink-50/60">
                <td className="px-4 py-3"><Link href={`/admin/customers/${t.id}`} className="font-semibold text-brand-700 hover:underline">{t.name}</Link>{!t.is_active && <Badge tone="red">suspended</Badge>}
                  <span className="block text-xs text-ink-500">{[t.category, t.city].filter(Boolean).join(" · ")}</span></td>
                <td className="px-4 text-ink-700">{t.contact_name ?? <span className="text-ink-400">–</span>}{t.owner_email && <span className="block text-xs text-ink-500">{t.owner_email}</span>}{!t.owner_email && t.email && <span className="block text-xs text-ink-500">{t.email}</span>}</td>
                <td className="whitespace-nowrap px-4 tabular-nums">{t.phone ?? <span className="text-ink-400">–</span>}</td>
                <td className="px-4 tabular-nums">{t.locations}</td><td className="px-4 tabular-nums">{t.cards}</td><td className="px-4 tabular-nums">{t.active_cards ?? 0}</td>
                <td className="px-4"><Badge tone={o.tone}>{o.label}</Badge>{t.agreement_recorded && <span className="block text-xs text-ink-500">Agreement recorded</span>}</td>
                <td className="px-4 text-xs">{t.origin === "admin" ? (t.managed_access === "revoked" ? <Badge tone="red">managed: revoked</Badge> : t.managed_access === "managed" ? <Badge tone="green">managed by FlowQR</Badge> : <Badge tone="gray">{t.plan}</Badge>) : <Badge tone={SUB_TONE[t.subscription_status ?? ""] ?? "gray"}>{t.plan} · {t.subscription_status}</Badge>}</td>
                <td className="whitespace-nowrap px-4">{fmtDate(t.created_at)}</td></tr>);
          })}</tbody>
        </table></div></Card>
      )}
      {data && data.total > PAGE && <div className="mt-4 flex items-center justify-between"><Button variant="secondary" size="sm" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</Button><span className="text-sm text-ink-500">{page * PAGE + 1}–{Math.min(data.total, (page + 1) * PAGE)} of {data.total}</span><Button variant="secondary" size="sm" disabled={(page + 1) * PAGE >= data.total} onClick={() => setPage(page + 1)}>Next</Button></div>}
      {adding && <Modal open onClose={() => setAdding(false)} title="Add a business"><AddBusinessForm onCancel={() => setAdding(false)} onCreated={(b) => { setAdding(false); toast(`${b.name} was added. Now assign it a card from the Cards screen.`); void reload(); router.push(`/admin/customers/${b.id}`); }} /></Modal>}
    </>
  );
}
