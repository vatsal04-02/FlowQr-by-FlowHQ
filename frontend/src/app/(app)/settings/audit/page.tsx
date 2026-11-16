"use client";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, PageHeader, Skeleton } from "@/components/ui/Card";
import { Input } from "@/components/ui/Form";
import { Panel } from "@/components/ui/kit";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-api";

interface Entry { id: string; action: string; by: string | null; entity_type: string | null; entity_id: string | null; meta: Record<string, unknown>; ip: string | null; at: string }
interface Page { entries: Entry[]; next_before: string | null }

export default function AuditPage() {
  const { isAdmin } = useAuth();
  const [prefix, setPrefix] = useState("");
  const { data, error, loading } = useFetch<Page>(isAdmin ? "/workspace/audit-log" : null, { action: prefix, limit: 50 });
  const [more, setMore] = useState<Entry[]>([]);
  const [next, setNext] = useState<string | null | undefined>(undefined);
  const [err, setErr] = useState<string | null>(null);
  if (!isAdmin) return <><PageHeader eyebrow="Settings" title="Audit" /><Alert tone="info">Only owners and admins can see the audit log.</Alert></>;
  const entries = [...(data?.entries ?? []), ...more];
  const cursor = next === undefined ? data?.next_before : next;
  async function load() { try { const r = await api<Page>("/workspace/audit-log", { params: { before: cursor ?? undefined, action: prefix, limit: 50 } }); setMore([...more, ...r.entries]); setNext(r.next_before); } catch (e) { setErr(errorMessage(e)); } }
  return (
    <>
      <PageHeader eyebrow="Settings" title="Audit log" subtitle="Who did what in your business: sign-ins, approvals, publishing, exports, access changes and AI actions. Entries cannot be edited." />
      <div className="mb-3 max-w-xs"><Input label="Filter by action prefix" placeholder="e.g. post. or agent." value={prefix} onChange={(e) => { setPrefix(e.target.value); setMore([]); setNext(undefined); }} /></div>
      {(error || err) && <Alert tone="error">{error ?? err}</Alert>}
      <Panel flush>{loading && !data ? <Skeleton className="m-4 h-40" /> : entries.length === 0 ? <p className="p-4 text-sm text-ink-500">Nothing recorded for this filter.</p> : (
        <div className="overflow-x-auto"><table className="dt min-w-[640px]"><thead><tr><th>When</th><th>Action</th><th>By</th><th>Details</th></tr></thead><tbody>{entries.map((e) => (
          <tr key={e.id}><td className="whitespace-nowrap text-ink-500">{new Date(e.at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</td><td className="font-mono text-[13px]">{e.action}</td><td>{e.by ?? <span className="text-ink-400">system</span>}</td>
            <td className="max-w-[320px] truncate text-[13px] text-ink-500" title={JSON.stringify(e.meta)}>{Object.keys(e.meta).length ? JSON.stringify(e.meta) : e.entity_type ?? ""}</td></tr>))}</tbody></table></div>)}</Panel>
      {cursor && <div className="mt-3"><Button variant="secondary" size="sm" onClick={() => void load()}>Load older</Button></div>}
    </>
  );
}
