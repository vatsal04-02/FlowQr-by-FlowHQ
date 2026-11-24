"use client";
import { Search } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { LoginCheck, signIn, type UserRow } from "@/components/admin/LoginCheck";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { FilterSelect } from "@/components/ui/Form";
import { Panel } from "@/components/ui/kit";
import { fmtDate, timeAgo } from "@/lib/format";
import { useFetch } from "@/lib/use-api";

const PAGE = 25;
const STATES: [string, string][] = [["", "Everyone"], ["active", "Active"], ["deactivated", "Deactivated"], ["unverified", "Email not verified"], ["google_only", "Google-only"], ["no_login", "No way to log in"], ["admin", "Platform admins"]];

export default function Users() {
  const [q, setQ] = useState(""), [search, setSearch] = useState(""), [state, setState] = useState(""), [page, setPage] = useState(0);
  useEffect(() => { const t = setTimeout(() => { setSearch(q); setPage(0); }, 300); return () => clearTimeout(t); }, [q]);
  const { data, error, loading } = useFetch<{ total: number; totals: { all: number; unverified: number; deactivated: number; active_30d: number }; items: UserRow[] }>("/admin/users", { search, state, limit: PAGE, offset: page * PAGE });
  const t = data?.totals;
  return (
    <>
      <PageHeader title="Users" subtitle="Everyone who has a FlowQR login. Check whether an account exists, why someone can't log in, and help them." />
      <LoginCheck />
      {t && (
        <dl className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {([["Accounts", t.all], ["Logged in, last 30 days", t.active_30d], ["Email not verified", t.unverified], ["Deactivated", t.deactivated]] as const).map(([k, v]) => (
            <div key={k} className="panel p-4"><dt className="text-sm text-muted">{k}</dt><dd className="num mt-1 text-[28px] font-semibold leading-8">{v}</dd></div>))}
        </dl>
      )}
      <Panel title="All users" meta={data ? `${data.total} match` : undefined}
        action={<div className="flex flex-wrap gap-2">
          <label className="flex h-11 w-full items-center gap-2 rounded-full bg-surface-2 px-4 text-muted focus-within:ring-2 focus-within:ring-accent sm:w-64"><Search className="h-4 w-4" aria-hidden /><span className="sr-only">Search users</span>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Email, name, phone or business" className="focus-inner w-full bg-transparent text-sm text-ink outline-none placeholder:text-muted" /></label>
          <FilterSelect label="Show" value={state} onChange={(e) => { setState(e.target.value); setPage(0); }}>{STATES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</FilterSelect>
        </div>} flush>
        {error && <div className="p-3"><Alert tone="error">{error}</Alert></div>}
        {loading && !data ? <Skeleton className="m-3 h-64" /> : data && data.items.length === 0 ? <div className="p-3"><EmptyState title="No users match">Try a different search or filter.</EmptyState></div> : (
          <>
          <ul aria-label="Users" className="space-y-2 p-3 xl:hidden">{data?.items.map((u) => (
            <li key={u.id} className="adm-card-link rounded-xl border border-ink-100 bg-surface p-3.5">
              <div className="flex items-start justify-between gap-2"><Link href={`/admin/users/${u.id}`} className="min-w-0 break-all text-[15px] font-semibold text-accent-ink">{u.email}</Link>
                {!u.is_active ? <Badge tone="red">deactivated</Badge> : <Badge tone="green">active</Badge>}</div>
              <p className="mt-1 truncate text-[13px] text-ink-700">{u.businesses ? (u.business_names?.join(", ") ?? u.businesses) : "No business"}</p>
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-muted"><span>{signIn(u)}</span>{!u.email_verified && <Badge tone="amber">unverified</Badge>}</div>
              <p className="mt-1 text-xs text-muted">{u.last_login_at ? `Last login ${timeAgo(u.last_login_at)}` : "Never logged in"} · Joined {fmtDate(u.created_at)}</p>
              <Link href={`/admin/users/${u.id}`} className="mt-2.5 inline-flex min-h-11 items-center rounded-full bg-ink-solid px-4 text-[13px] font-semibold text-ink-on">View user</Link>
            </li>))}</ul>
          <div className="hidden overflow-x-auto xl:block"><table className="dt min-w-[860px]">
            <thead><tr><th>Person</th><th>Businesses</th><th>Sign-in</th><th>Status</th><th>Last login</th><th>Joined</th></tr></thead>
            <tbody>{data?.items.map((u) => (
              <tr key={u.id}>
                <td className="max-w-[260px]"><Link href={`/admin/users/${u.id}`} className="block truncate font-semibold text-accent-ink hover:underline">{u.email}</Link><span className="block truncate text-xs font-normal text-muted">{u.full_name}{u.phone ? ` · ${u.phone}` : ""}</span></td>
                <td className="max-w-[200px] truncate" title={u.business_names?.join(", ")}>{u.businesses ? (u.business_names?.join(", ") ?? u.businesses) + (u.businesses > 3 ? ` +${u.businesses - 3}` : "") : <span className="text-muted">None</span>}</td>
                <td className="whitespace-nowrap text-[13px]">{signIn(u)}</td>
                <td className="whitespace-nowrap"><span className="flex flex-wrap gap-1">{!u.is_active ? <Badge tone="red">deactivated</Badge> : <Badge tone="green">active</Badge>}{!u.email_verified && <Badge tone="amber">unverified</Badge>}{u.is_platform_admin && <Badge tone="blue">admin</Badge>}</span></td>
                <td className="whitespace-nowrap">{u.last_login_at ? timeAgo(u.last_login_at) : <span className="text-muted">Never</span>}</td>
                <td className="whitespace-nowrap text-muted">{fmtDate(u.created_at)}</td>
              </tr>))}</tbody>
          </table></div>
          </>
        )}
      </Panel>
      {data && data.total > PAGE && <div className="mt-4 flex items-center justify-between"><Button variant="secondary" size="sm" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</Button>
        <span className="text-sm text-muted">{page * PAGE + 1}–{Math.min(data.total, (page + 1) * PAGE)} of {data.total}</span><Button variant="secondary" size="sm" disabled={(page + 1) * PAGE >= data.total} onClick={() => setPage(page + 1)}>Next</Button></div>}
    </>
  );
}
