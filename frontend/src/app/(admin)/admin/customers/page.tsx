"use client";
import { Globe, Plus, Search } from "lucide-react";
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
import { STATUS_LABEL, STATUS_TONE, type SiteConfig } from "@/lib/sites";

const PAGE = 25;

/** The business directory. The URL stays /admin/customers so every existing link keeps working. A business here may have no FlowQR login at all: staff manage it, and its cards work regardless. */
export default function Businesses() {
  const router = useRouter();
  const toast = useToast();
  const [q, setQ] = useState(""), [search, setSearch] = useState(""), [status, setStatus] = useState(""), [origin, setOrigin] = useState(""), [onboarding, setOnboarding] = useState(""), [website, setWebsite] = useState(""), [page, setPage] = useState(0);
  const [adding, setAdding] = useState(false);
  useEffect(() => { const t = setTimeout(() => { setSearch(q); setPage(0); }, 300); return () => clearTimeout(t); }, [q]);
  // links from the Overview (?status=past_due) open the list already filtered
  useEffect(() => { const st = new URLSearchParams(window.location.search).get("status"); if (st) setStatus(st); }, []);
  const { data, error, loading, reload } = useFetch<{ total: number; items: TenantRow[] }>("/admin/tenants", { search, status, origin, onboarding, website, limit: PAGE, offset: page * PAGE });
  const cfg = useFetch<SiteConfig>("/admin/sites/config");
  const sitesOn = !!cfg.data?.enabled;
  const filtered = !!(search || status || origin || onboarding || website);
  return (
    <>
      <PageHeader eyebrow="Platform" title="Businesses" subtitle="Every business on FlowQR: shops you set up for them, and businesses with their own login. Open one to manage its locations, cards and access."
        actions={<><Link href="/admin/managed-usage" className="inline-flex min-h-11 items-center rounded-full bg-surface px-4 text-sm font-semibold shadow-pill hover:bg-ink-50 sm:min-h-10">Usage and cost</Link><Button className="!rounded-full" icon={<Plus className="h-4 w-4" />} onClick={() => setAdding(true)}>Add business</Button></>} />
      <Card pad={false} className="mb-4 p-3 sm:p-4"><div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap">
        <div className="relative col-span-2 min-w-[200px] sm:flex-1"><Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" aria-hidden /><input aria-label="Search businesses" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, email, city, phone or ID" className="min-h-11 w-full rounded-xl border border-ink-200 pl-9 pr-3 text-sm sm:min-h-10" /></div>
        <FilterSelect label="Set up by" value={origin} onChange={(e) => { setOrigin(e.target.value); setPage(0); }}><option value="">Everyone</option><option value="admin">Set up by FlowQR staff</option><option value="self_service">Signed up themselves</option></FilterSelect>
        <FilterSelect label="Onboarding" value={onboarding} onChange={(e) => { setOnboarding(e.target.value); setPage(0); }}><option value="">Any stage</option>{Object.entries(ONBOARDING).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</FilterSelect>
        <FilterSelect label="Website" value={website} onChange={(e) => { setWebsite(e.target.value); setPage(0); }}><option value="">Any</option><option value="wants">Asked us to build one</option><option value="built">We built one</option><option value="none">No website yet</option></FilterSelect>
        <FilterSelect label="Subscription" value={status} onChange={(e) => { setStatus(e.target.value); setPage(0); }}><option value="">All plans</option>{["trialing", "active", "manual", "past_due", "halted", "expired", "canceled", "suspended"].map((s) => <option key={s}>{s}</option>)}</FilterSelect>
      </div></Card>
      {error && <Alert tone="error">{error}</Alert>}
      {loading && !data ? <Skeleton className="h-64" /> : data && data.items.length === 0 ? (
        <EmptyState title={filtered ? "No businesses match" : "No businesses yet"} action={filtered ? undefined : <Button onClick={() => setAdding(true)}>Add business</Button>}>{filtered ? "Try a different search or filter." : "Add the first shop to start assigning cards."}</EmptyState>
      ) : (
        <>
        <ul aria-label="Businesses" className="space-y-2 lg:hidden">
          {data?.items.map((t) => {
            const o = ONBOARDING[t.onboarding_status ?? "incomplete"];
            return (
              <li key={t.id} className="rounded-xl border border-ink-100 bg-surface p-3.5">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0"><Link href={`/admin/customers/${t.id}`} className="block truncate text-[15px] font-semibold text-brand-700">{t.name}</Link>
                    <p className="truncate text-xs text-ink-500">{[t.category, t.city].filter(Boolean).join(" · ") || "No category"}</p></div>
                  {!t.is_active ? <Badge tone="red">suspended</Badge> : t.origin === "admin" ? <Badge tone="gray">{t.managed_access === "managed" ? "managed" : t.plan ?? "managed"}</Badge> : <Badge tone={SUB_TONE[t.subscription_status ?? ""] ?? "gray"}>{t.plan} · {t.subscription_status}</Badge>}
                </div>
                <p className="mt-2 truncate text-[13px] text-ink-700">{t.contact_name ?? "No contact"}{(t.owner_email || t.email) ? ` · ${t.owner_email ?? t.email}` : ""}</p>
                <p className="mt-1 text-xs text-ink-500">{t.locations} location{t.locations === 1 ? "" : "s"} · {t.cards} card{t.cards === 1 ? "" : "s"} ({t.active_cards ?? 0} live) · Added {fmtDate(t.created_at)}</p>
                <div className="mt-2.5 flex flex-wrap items-center gap-2"><Badge tone={o.tone}>{o.label}</Badge>
                  <Link href={`/admin/customers/${t.id}`} className="ml-auto inline-flex min-h-11 items-center rounded-full bg-ink-solid px-4 text-[13px] font-semibold text-ink-on">View details</Link></div>
              </li>);
          })}
        </ul>
        <Card pad={false} className="hidden lg:block"><div className="overflow-x-auto"><table className="dt min-w-[1240px]">
          <thead><tr>{["Business", "Contact", "Phone", "Locations", "Cards", "Live", "Stage", "Website", "Access", "Added"].map((h) => <th key={h} className="px-4 py-2.5 font-semibold">{h}</th>)}</tr></thead>
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
                <td className="px-4 text-xs">{t.site_status ? (
                    <><Badge tone={STATUS_TONE[t.site_status] ?? "gray"}>{STATUS_LABEL[t.site_status] ?? t.site_status}</Badge><Link href={`/admin/customers/${t.id}/website`} className="mt-1 block font-semibold text-brand-700 hover:underline">Open editor</Link></>
                  ) : (
                    <>{t.website_interest === "wants_site" ? <Badge tone="amber">Wants a website</Badge> : t.website_interest === "has_site" ? <Badge tone="gray">Has its own</Badge> : t.website_interest === "not_now" ? <Badge tone="gray">Not now</Badge> : <span className="text-ink-400">Not asked</span>}
                      {sitesOn ? <Link href={`/admin/customers/${t.id}?website=create`} className="mt-1 inline-flex min-h-8 items-center gap-1 font-semibold text-brand-700 hover:underline"><Globe className="h-3.5 w-3.5" aria-hidden />Generate site</Link>
                        : cfg.data ? <span className="mt-1 block text-ink-400">Builder is off</span> : null}</>
                  )}</td>
                <td className="px-4 text-xs">{t.origin === "admin" ? (t.managed_access === "revoked" ? <Badge tone="red">managed: revoked</Badge> : t.managed_access === "managed" ? <Badge tone="green">managed by FlowQR</Badge> : <Badge tone="gray">{t.plan}</Badge>) : <Badge tone={SUB_TONE[t.subscription_status ?? ""] ?? "gray"}>{t.plan} · {t.subscription_status}</Badge>}</td>
                <td className="whitespace-nowrap px-4">{fmtDate(t.created_at)}</td></tr>);
          })}</tbody>
        </table></div></Card>
        </>
      )}
      {data && data.total > PAGE && <div className="mt-4 flex items-center justify-between"><Button variant="secondary" size="sm" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</Button><span className="text-sm text-ink-500">{page * PAGE + 1}–{Math.min(data.total, (page + 1) * PAGE)} of {data.total}</span><Button variant="secondary" size="sm" disabled={(page + 1) * PAGE >= data.total} onClick={() => setPage(page + 1)}>Next</Button></div>}
      {adding && <Modal open onClose={() => setAdding(false)} title="Add a business"><AddBusinessForm onCancel={() => setAdding(false)} onCreated={(b) => { setAdding(false); toast(`${b.name} was added. Now assign it a card from the Cards screen.`); void reload(); router.push(`/admin/customers/${b.id}`); }} /></Modal>}
    </>
  );
}
