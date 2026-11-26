"use client";
import Link from "next/link";
import { LinkButton } from "@/components/ui/Button";
import { Alert, PageHeader, Skeleton } from "@/components/ui/Card";
import { Meter, Panel, Status } from "@/components/ui/kit";
import { fmtNum } from "@/lib/format";
import { useFetch } from "@/lib/use-api";

interface U { used_this_month: number; monthly_limit: number; plan: string; provider: { configured: boolean; name: string | null; model: string | null; paused: { code: string; message: string } | null }; by_kind: { kind: string; status: string; count: number }[]; daily: { day: string; count: number }[]; recent_problems: { kind: string; error: string; at: string }[]; note: string }
const KIND: Record<string, string> = { review_assist: "Customer review assistant", reply_draft: "Reply drafts", post_draft: "Post drafts", agent_draft: "Agent drafts", review_generate: "Customer review generator" };

interface Q { label: string; generated: number; decided: number; accepted: number; acceptance_rate: number | null; median_edit_ratio: number | null; rejected: number; regenerated: number; top_reject_reasons: [string, number][] }
const REASON: Record<string, string> = { owner_rejected: "You rejected it", dismissed: "You dismissed it", canceled: "You cancelled it", regenerated: "You asked for a new one" };

/** AI Output Acceptance Rate: how often you keep what the AI wrote without substantial rewriting. A rate is shown only once something has been decided. */
function Acceptance() {
  const { data } = useFetch<{ accept_rule: string; kinds: Record<string, Q> }>("/agent/ai-quality");
  if (!data) return <Skeleton className="h-40" />;
  const rows = Object.values(data.kinds);
  return (
    <Panel title="How much of what the AI writes you keep" meta="last 90 days" flush>
      <table className="dt"><thead><tr><th>Output</th><th className="!text-right">Written</th><th className="!text-right">Decided</th><th className="!text-right">Kept as is</th><th className="!text-right">Acceptance</th><th>Why not kept</th></tr></thead>
        <tbody>{rows.map((r) => (
          <tr key={r.label}><td className="font-medium">{r.label}</td><td className="num !text-right">{r.generated}</td><td className="num !text-right">{r.decided}</td><td className="num !text-right">{r.accepted}</td>
            <td className="num !text-right font-semibold">{r.acceptance_rate === null ? "–" : `${Math.round(r.acceptance_rate * 100)}%`}</td>
            <td className="text-[13px] text-ink-500">{r.top_reject_reasons.length ? r.top_reject_reasons.map(([k, n]) => `${REASON[k] ?? k} (${n})`).join(", ") : r.decided ? "" : "Nothing decided yet"}</td></tr>))}</tbody></table>
      <p className="p-3 text-xs text-ink-500">Kept as is = {data.accept_rule.toLowerCase()}. A low number means the AI needs more of your business facts, not that you are doing anything wrong: add them in Business brain.</p>
    </Panel>
  );
}

export default function AiUsage() {
  const { data: u, error } = useFetch<U>("/workspace/ai-usage");
  if (error) return <Alert tone="error">{error}</Alert>;
  if (!u) return <Skeleton className="h-64" />;
  const over = u.used_this_month >= u.monthly_limit;
  return (
    <>
      <PageHeader title="Usage & limits" subtitle="How much AI your plan allows, how much you have used, and whether the AI provider is working right now." />
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="This month"><p className="num text-3xl font-bold">{fmtNum(u.used_this_month)} <span className="text-lg font-medium text-ink-400">/ {fmtNum(u.monthly_limit)}</span></p>
          <div className="mt-2"><Meter value={u.used_this_month} max={u.monthly_limit} label="AI uses this month" tone={over ? "bad" : "info"} /></div>
          {over && <div className="mt-3"><Alert tone="warning" title="Limit reached">Drafts are paused until next month or a plan change. Customers can still write their own reviews.</Alert></div>}
          {!over && u.monthly_limit > 0 && u.used_this_month / u.monthly_limit >= 0.8 && <div className="mt-3"><Alert tone="warning" title="Over 80% used" action={<LinkButton href="/settings/billing" size="sm" variant="inverse">See plans</LinkButton>}>A bigger plan raises the monthly limit. Nothing stops until the limit is reached.</Alert></div>}
          <p className="mt-3 text-xs text-ink-500">{u.note}</p></Panel>
        <Panel title="AI provider" action={<Status tone={!u.provider.configured ? "warn" : u.provider.paused ? "warn" : "ok"}>{!u.provider.configured ? "Setup required" : u.provider.paused ? "Paused" : "Configured"}</Status>}>
          <p className="text-sm text-ink-700">{!u.provider.configured ? "No AI provider is configured on this server, so nothing can be drafted. The platform owner has to add a key." : u.provider.paused ? u.provider.paused.message : `Using ${u.provider.name}${u.provider.model ? ` (${u.provider.model})` : ""}. Health is judged from real requests, not a ping.`}</p>
          <p className="mt-3 text-[13px] text-ink-500">What customers see on the review page is set in <Link className="text-brand-700 underline" href="/reputation/assistant">AI Review Assistant</Link>.</p></Panel>
      </div>
      <div className="mt-4"><Acceptance /></div>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Panel title="By feature" flush>{u.by_kind.length === 0 ? <p className="p-4 text-sm text-ink-500">No AI use yet this month.</p> : <table className="dt"><thead><tr><th>Feature</th><th>Result</th><th className="!text-right">Count</th></tr></thead><tbody>{u.by_kind.map((k) => <tr key={k.kind + k.status}><td>{KIND[k.kind] ?? k.kind}</td><td>{k.status}</td><td className="n">{k.count}</td></tr>)}</tbody></table>}</Panel>
        <Panel title="Recent problems" flush>{u.recent_problems.length === 0 ? <p className="p-4 text-sm text-ink-500">No failed AI requests lately.</p> : <ul className="divide-y divide-ink-100">{u.recent_problems.map((p, i) => <li key={i} className="px-4 py-2.5 text-sm"><p className="font-medium">{KIND[p.kind] ?? p.kind}</p><p className="text-[13px] text-ink-500">{p.error || "Failed"}</p></li>)}</ul>}</Panel>
      </div>
    </>
  );
}
