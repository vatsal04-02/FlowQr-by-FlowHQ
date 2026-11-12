"use client";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Badge, Card, CardHeader, PageHeader, Skeleton } from "@/components/ui/Card";
import { fmtDate } from "@/lib/format";
import { useFetch } from "@/lib/use-api";

interface Row { id: string; action: string; created_at: string; user: string | null; tenant: string | null; meta: Record<string, unknown> }
const PAGE = 50;

export default function AdminAudit() {
  const [q, setQ] = useState(""), [action, setAction] = useState(""), [page, setPage] = useState(0);
  const audit = useFetch<Row[]>("/admin/audit", { action, limit: PAGE, offset: page * PAGE });
  const usage = useFetch<{ tenant_id: string; tenant: string; generations: number; errors: number; monthly_limit: number | null }[]>("/admin/ai-usage");
  return (
    <>
      <PageHeader eyebrow="Platform" title="Audit & AI usage" subtitle="Sensitive actions across the platform, and AI consumption per customer this month." />
      <Card className="mb-5" pad={false}><div className="p-5 sm:p-6"><CardHeader title="AI usage this month" /></div>
        {!usage.data ? <Skeleton className="m-5 h-24" /> : <div className="max-h-72 overflow-auto"><table className="dt"><thead className="sticky top-0 bg-ink-50"><tr>{["Business", "Generations", "Limit", "Errors"].map((h) => <th key={h} className="px-4 py-2.5">{h}</th>)}</tr></thead>
          <tbody>{usage.data.map((u) => { const pct = u.monthly_limit ? u.generations / u.monthly_limit : 0; return <tr key={u.tenant_id} className="border-b border-ink-100"><td className="px-4 py-2.5 font-semibold">{u.tenant}</td><td className="px-4 tabular-nums">{u.generations}{pct >= 0.9 && <Badge tone="red">near limit</Badge>}</td><td className="px-4 tabular-nums">{u.monthly_limit ?? "–"}</td><td className="px-4 tabular-nums">{u.errors}</td></tr>; })}</tbody></table></div>}
      </Card>
      <Card pad={false}>
        <div className="flex flex-wrap items-end justify-between gap-3 p-5 sm:p-6"><CardHeader title="Audit history" subtitle="Append-only" />
          <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); setAction(q); setPage(0); }}><input aria-label="Action prefix" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Action prefix e.g. admin." className="min-h-11 rounded-xl border border-ink-200 px-3 text-sm sm:min-h-10" /><Button type="submit" variant="secondary" size="sm">Filter</Button></form></div>
        {!audit.data ? <Skeleton className="m-5 h-40" /> : <div className="overflow-x-auto"><table className="dt min-w-[720px]"><thead><tr>{["When", "Action", "Business", "User", "Details"].map((h) => <th key={h} className="px-4 py-2.5">{h}</th>)}</tr></thead>
          <tbody>{audit.data.map((a) => <tr key={a.id} className="border-b border-ink-100 align-top"><td className="whitespace-nowrap px-4 py-2.5">{fmtDate(a.created_at, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</td><td className="px-4"><code className="text-xs">{a.action}</code></td><td className="px-4">{a.tenant ?? "–"}</td><td className="px-4 text-ink-500">{a.user ?? "–"}</td><td className="max-w-[260px] truncate px-4 font-mono text-xs text-ink-500" title={JSON.stringify(a.meta)}>{Object.keys(a.meta).length ? JSON.stringify(a.meta) : ""}</td></tr>)}</tbody></table></div>}
        <div className="flex justify-between p-4"><Button size="sm" variant="secondary" disabled={page === 0} onClick={() => setPage(page - 1)}>Newer</Button><Button size="sm" variant="secondary" disabled={(audit.data?.length ?? 0) < PAGE} onClick={() => setPage(page + 1)}>Older</Button></div>
      </Card>
    </>
  );
}
