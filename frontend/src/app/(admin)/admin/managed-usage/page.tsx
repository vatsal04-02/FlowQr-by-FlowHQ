"use client";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { Alert, Badge, Card, CardHeader, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { fmtDate } from "@/lib/format";
import { useFetch } from "@/lib/use-api";

interface Allowance { used: number; limit: number }
interface Row { id: string; name: string; city: string | null; active: boolean; access_revoked: boolean; review_writings: Allowance; replies: Allowance; ai_calls: number; recorded_usd: number; repriced_usd: number; unpriced_calls: number; percent_of_allowance: number }
interface Usage {
  month_started: string;
  totals: { businesses: number; active: number; suspended: number; access_revoked: number; review_writings_used: number; review_writings_allowed: number; replies_used: number; replies_allowed: number; ai_calls: number;
    recorded_usd: number; repriced_usd: number; estimated_usd: number; unpriced_calls: number; near_limit: number };
  businesses: Row[];
  pricing: { price_configured: boolean; input_per_million_tokens_usd: number | null; output_per_million_tokens_usd: number | null; set_with: string; note: string };
}

const usd = (n: number) => `$${n.toFixed(n < 1 ? 4 : 2)}`;

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return <div className="rounded-2xl bg-surface p-4 shadow-sm"><p className="text-[13px] text-ink-500">{label}</p><p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>{sub && <p className="mt-0.5 text-xs text-ink-500">{sub}</p>}</div>;
}

function Bar({ used, limit, label }: { used: number; limit: number; label: string }) {
  const pct = limit ? Math.min(100, (used / limit) * 100) : 0;
  return (
    <div className="min-w-[110px]"><div className="flex justify-between text-xs tabular-nums"><span>{used}</span><span className="text-ink-500">of {limit}</span></div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-ink-100" role="progressbar" aria-label={label} aria-valuenow={used} aria-valuemin={0} aria-valuemax={limit}><div className={`h-full ${pct >= 100 ? "bg-red-500" : pct >= 80 ? "bg-amber-500" : "bg-brand-600"}`} style={{ width: `${pct}%` }} /></div></div>
  );
}

/** What the businesses FlowQR staff manage are using this month. Counts are from the same log the 200 + 200 limits are enforced against; cost is what was recorded, never a guess. */
export default function ManagedUsage() {
  const { data, error, loading } = useFetch<Usage>("/admin/managed-usage");
  const t = data?.totals;
  return (
    <>
      <Link href="/admin/customers" className="mb-4 inline-flex min-h-11 items-center gap-1.5 text-sm font-semibold text-brand-700 hover:underline"><ArrowLeft className="h-4 w-4" aria-hidden />All businesses</Link>
      <PageHeader eyebrow="Platform" title="Managed businesses: usage and cost" subtitle={data ? `Businesses set up by FlowQR staff, since ${fmtDate(data.month_started)}. Each has 200 AI review writings and 200 AI replies a month.` : "Businesses set up by FlowQR staff."} />
      {error && <Alert tone="error">{error}</Alert>}
      {loading && !data ? <Skeleton className="h-64" /> : data && t && (
        <>
          <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-5">
            <Tile label="Managed businesses" value={String(t.businesses)} sub={`${t.active} active${t.suspended ? ` · ${t.suspended} suspended` : ""}${t.access_revoked ? ` · ${t.access_revoked} access revoked` : ""}`} />
            <Tile label="AI review writings" value={String(t.review_writings_used)} sub={`of ${t.review_writings_allowed} allowed this month`} />
            <Tile label="AI replies" value={String(t.replies_used)} sub={`of ${t.replies_allowed} allowed this month`} />
            <Tile label="Estimated AI cost" value={usd(t.estimated_usd)} sub={`${t.ai_calls} model calls${t.near_limit ? ` · ${t.near_limit} near a limit` : ""}`} />
            <Tile label="Calls without a cost" value={String(t.unpriced_calls)} sub={t.unpriced_calls ? "not counted in the estimate" : "every call has a cost"} />
          </div>

          <Card className="mb-5"><CardHeader title="How the cost is worked out" />
            <p className="text-sm text-ink-700">{data.pricing.note}</p>
            <p className="mt-2 text-sm">{data.pricing.price_configured
              ? <>Configured prices: <b>${data.pricing.input_per_million_tokens_usd ?? 0}</b> per million input tokens, <b>${data.pricing.output_per_million_tokens_usd ?? 0}</b> per million output tokens. Recorded {usd(t.recorded_usd)} + priced from tokens {usd(t.repriced_usd)}.</>
              : <><Badge tone="amber">No prices configured</Badge> Set {data.pricing.set_with} on the server to price calls that did not record a cost. Until then only recorded costs ({usd(t.recorded_usd)}) are shown.</>}</p></Card>

          {data.businesses.length === 0 ? <EmptyState title="No managed businesses yet">Businesses you add from the Businesses page appear here.</EmptyState> : (
            <Card pad={false}><div className="overflow-x-auto"><table className="dt min-w-[860px]">
              <thead><tr>{["Business", "AI review writings", "AI replies", "Model calls", "Recorded cost", "Priced from tokens", "Without a cost"].map((h) => <th key={h} className="px-4 py-2.5 font-semibold">{h}</th>)}</tr></thead>
              <tbody>{data.businesses.map((b) => (
                <tr key={b.id} className="border-b border-ink-100 last:border-0">
                  <td className="px-4 py-3"><Link href={`/admin/customers/${b.id}`} className="font-semibold text-brand-700 hover:underline">{b.name}</Link>{!b.active && <Badge tone="red">suspended</Badge>}{b.access_revoked && <Badge tone="gray">access revoked</Badge>}
                    {b.city && <span className="block text-xs text-ink-500">{b.city}</span>}</td>
                  <td className="px-4"><Bar used={b.review_writings.used} limit={b.review_writings.limit} label={`${b.name} review writings`} /></td>
                  <td className="px-4"><Bar used={b.replies.used} limit={b.replies.limit} label={`${b.name} replies`} /></td>
                  <td className="px-4 tabular-nums">{b.ai_calls}</td><td className="px-4 tabular-nums">{usd(b.recorded_usd)}</td><td className="px-4 tabular-nums">{b.repriced_usd ? usd(b.repriced_usd) : "–"}</td>
                  <td className="px-4 tabular-nums">{b.unpriced_calls || "–"}</td></tr>))}</tbody>
            </table></div></Card>
          )}
        </>
      )}
    </>
  );
}
