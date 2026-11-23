"use client";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, PageHeader, Skeleton } from "@/components/ui/Card";
import { Input } from "@/components/ui/Form";
import { api, errorMessage } from "@/lib/api";
import { describeAudit, whenText } from "@/lib/audit-text";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-api";

interface Entry { id: string; action: string; by: string | null; entity_type: string | null; entity_id: string | null; meta: Record<string, unknown>; ip: string | null; at: string }
interface Page { entries: Entry[]; next_before: string | null }

/** Security & activity › Audit log. Each entry reads as a sentence; the raw record (action name, who, where from, the data) is under "Details". Entries cannot be edited. */
export default function AuditPage() {
  const { isAdmin, me } = useAuth();
  const [prefix, setPrefix] = useState("");
  const { data, error, loading } = useFetch<Page>(isAdmin ? "/workspace/audit-log" : null, { action: prefix, limit: 50 });
  const [more, setMore] = useState<Entry[]>([]);
  const [next, setNext] = useState<string | null | undefined>(undefined);
  const [err, setErr] = useState<string | null>(null);
  if (!isAdmin) return <><PageHeader title="Audit log" /><Alert tone="info">Only owners and admins can see the audit log.</Alert></>;
  const entries = [...(data?.entries ?? []), ...more];
  const cursor = next === undefined ? data?.next_before : next;
  async function load() { try { const r = await api<Page>("/workspace/audit-log", { params: { before: cursor ?? undefined, action: prefix, limit: 50 } }); setMore([...more, ...r.entries]); setNext(r.next_before); } catch (e) { setErr(errorMessage(e)); } }
  return (
    <>
      <PageHeader title="Audit log" subtitle="Who did what in your business: sign-ins, approvals, publishing, exports, access changes and AI actions. Entries cannot be edited." />
      <div className="mb-3 max-w-xs"><Input label="Filter" hint="Start of an action name, like post. or reply." placeholder="post." value={prefix} onChange={(e) => { setPrefix(e.target.value); setMore([]); setNext(undefined); }} /></div>
      {(error || err) && <div className="mb-3"><Alert tone="error">{error ?? err}</Alert></div>}
      <div className="overflow-hidden rounded-[18px] border border-set-line bg-set-surface">
        {loading && !data ? <Skeleton className="m-4 h-40" /> : entries.length === 0 ? <p className="p-4 text-sm font-medium text-set-soft">Nothing recorded for this filter.</p> : (
          <ul>
            {entries.map((e) => (
              <li key={e.id} className="border-t border-set-line first:border-t-0">
                <details className="group">
                  <summary className="set-focus flex min-h-[56px] cursor-pointer list-none items-center justify-between gap-3 px-4 py-2.5 [&::-webkit-details-marker]:hidden">
                    <span className="min-w-0"><span className="block text-[15px] font-bold text-set-ink">{describeAudit(e.action, e.by, me?.user.email)}</span><span className="block text-[13px] font-medium text-set-muted">{whenText(e.at)}</span></span>
                    <span className="shrink-0 text-[13px] font-bold text-set-action group-open:hidden">Details</span><span className="hidden shrink-0 text-[13px] font-bold text-set-action group-open:inline">Hide</span>
                  </summary>
                  <dl className="grid gap-x-4 gap-y-1 border-t border-set-line bg-set-paper px-4 py-3 text-[13px] font-medium sm:grid-cols-[110px_minmax(0,1fr)]">
                    <dt className="text-set-muted">Action</dt><dd className="break-all font-mono text-set-soft">{e.action}</dd>
                    <dt className="text-set-muted">By</dt><dd className="break-all text-set-soft">{e.by ?? "System"}</dd>
                    {e.ip && <><dt className="text-set-muted">From</dt><dd className="text-set-soft">{e.ip}</dd></>}
                    {e.entity_type && <><dt className="text-set-muted">About</dt><dd className="break-all text-set-soft">{e.entity_type}{e.entity_id ? ` ${e.entity_id}` : ""}</dd></>}
                    {Object.keys(e.meta).length > 0 && <><dt className="text-set-muted">Record</dt><dd className="break-all font-mono text-set-soft">{JSON.stringify(e.meta)}</dd></>}
                  </dl>
                </details>
              </li>
            ))}
          </ul>
        )}
      </div>
      {cursor && <div className="mt-3"><Button variant="secondary" size="sm" onClick={() => void load()}>Load older</Button></div>}
    </>
  );
}
