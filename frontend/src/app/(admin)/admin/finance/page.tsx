"use client";
import { useState } from "react";
import { Alert, Badge, Card, CardHeader, PageHeader, Skeleton } from "@/components/ui/Card";
import { Input } from "@/components/ui/Form";
import { rupees } from "@/lib/billing";
import { useFetch } from "@/lib/use-api";

interface M { value: number | string | Record<string, number> | null; status: "actual" | "estimated" | "missing"; note: string | null; needs: string | null }
interface Finance {
  revenue: Record<string, M | string>;
  economics: Record<string, unknown> & { cost_lines_inr: Record<string, M>; missing_variable_inputs: string[] };
  reading_guide: string;
}
interface Costs {
  month: string; total_usd: number | null; complete: boolean; note: string; unpriced_calls_and_units: number;
  ai: { usd: number | null; calls: number; unpriced_calls: number; failed_calls: number; refused_calls: number; by_feature: { feature: string; calls: number; usd: number | null; unpriced_calls: number }[]; priced: boolean };
  api: { usd: number | null; units: number; failed_units: number; refused_units: number; unpriced_units: number; priced: boolean; by_operation: { provider: string; operation: string; feature: string; units: number; failed_units: number; refused_units: number; usd: number; unpriced_units: number }[] };
  by_business: { tenant_id: string | null; name: string; ai_calls: number; ai_usd: number; api_units: number; api_usd: number; total_usd: number; ai_unpriced_calls: number }[];
}

const TONE = { actual: "green", estimated: "amber", missing: "red" } as const;
const LABEL: Record<string, string> = {
  mrr_paise: "MRR (paid subscriptions)", arr_paise: "ARR (run-rate)", mrr_at_risk_paise: "MRR at risk (payment failing)", paid_subscribers: "Paid subscribers", plan_distribution: "Paid subscribers by plan",
  new_paid_subscribers: "New paid subscribers", upgrades: "Upgrades", downgrades: "Downgrades", mrr_lost_paise: "MRR lost (cancelled or lapsed)", trials_in_progress: "Free trials in progress",
  comped_subscriptions: "Comped (free, given by an admin)", promotional_growth_activations: "Free Growth months started", promotional_growth_active_now: "Free Growth months active now",
  free_to_paid_conversion: "Free to paid conversion", card_revenue_paise: "Card revenue (one-time)", card_revenue_refunded_paise: "Card revenue refunded", subscription_cash_collected_paise: "Subscription cash collected",
  ai_and_google_api: "AI and Google API", payment_processing: "Payment processing", card_manufacturing: "Card manufacturing (provisional cost)", card_fulfilment: "Card fulfilment", hosting: "Hosting", support: "Support",
  contribution_margin_inr: "Contribution margin", contribution_margin_pct: "Contribution margin %", revenue_per_paid_business_inr: "Revenue per paid business", variable_ai_api_cost_per_business_inr: "AI + Google API cost per business",
  customer_acquisition_cost_inr: "Customer acquisition cost", monthly_paid_churn: "Monthly paid churn", lifetime_value_inr: "Lifetime value", ltv_to_cac: "LTV / CAC", cac_payback_months: "CAC payback (months)", break_even_paid_businesses: "Break-even paid businesses",
  known_variable_costs_inr: "Variable costs that are known",
};

function show(key: string, v: M["value"]) {
  if (v === null || v === undefined) return "Not available";
  if (typeof v === "object") return Object.entries(v).map(([k, n]) => `${k}: ${n}`).join(", ") || "None";
  if (typeof v === "string") return v;
  if (key.endsWith("_paise")) return rupees(v);
  if (key.endsWith("_inr")) return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(v);
  if (key.endsWith("_pct") || key === "monthly_paid_churn" || key === "free_to_paid_conversion") return key.endsWith("_pct") ? `${v}%` : `${(v * 100).toFixed(1)}%`;
  return String(v);
}

function Rows({ rows }: { rows: [string, M][] }) {
  return (
    <ul className="divide-y divide-line text-sm">
      {rows.map(([k, m]) => (
        <li key={k} className="flex flex-col gap-1 py-2.5 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
          <div className="min-w-0"><p className="font-medium">{LABEL[k] ?? k.replace(/_/g, " ")}</p>{m.note && <p className="text-xs text-muted">{m.note}</p>}{m.needs && <p className="text-xs text-neg">Needs: {m.needs}</p>}</div>
          <div className="flex shrink-0 items-center gap-2"><span className="num font-semibold">{show(k, m.value)}</span><Badge tone={TONE[m.status]}>{m.status}</Badge></div>
        </li>
      ))}
    </ul>
  );
}

const isM = (x: unknown): x is M => !!x && typeof x === "object" && "status" in (x as object);

/** Platform admin: revenue, costs and unit economics. Nothing here is a guess dressed as a number: each figure says whether it is measured, estimated or missing. */
export default function AdminFinance() {
  const [month, setMonth] = useState("");
  const fin = useFetch<Finance>("/admin/finance", { month });
  const cost = useFetch<Costs>("/admin/costs", { month });
  const rev = fin.data ? (Object.entries(fin.data.revenue).filter(([k, v]) => k !== "month" && isM(v)) as [string, M][]) : [];
  const eco = fin.data ? (Object.entries(fin.data.economics).filter(([k, v]) => !["month", "cost_lines_inr", "missing_variable_inputs"].includes(k) && isM(v)) as [string, M][]) : [];
  const lines = fin.data ? (Object.entries(fin.data.economics.cost_lines_inr) as [string, M][]) : [];
  return (
    <>
      <PageHeader title="Finance and usage" subtitle="What was earned, what it cost, and how much of that is measured." actions={<div className="w-44"><Input label="Month" type="month" value={month} onChange={(e) => setMonth(e.target.value)} /></div>} />
      <div className="mb-5"><Alert tone="info" title="How to read this page">{fin.data?.reading_guide ?? "actual = measured. estimated = measured plus an assumption or a figure you configured. missing = an input was never provided; it is never treated as zero."}</Alert></div>
      {fin.error && <Alert tone="error">{fin.error}</Alert>}
      {!fin.data ? <Skeleton className="h-64" /> : (
        <div className="space-y-6">
          <Card><CardHeader title="Revenue" subtitle="MRR counts only subscriptions paid through the payment provider. The free card month, trials and comped subscriptions are not revenue." /><Rows rows={rev} /></Card>
          <Card><CardHeader title="Costs" subtitle="Each line is a figure you configured or a measurement. A missing line is not zero." /><Rows rows={lines} />
            {fin.data.economics.missing_variable_inputs.length > 0 && <div className="mt-3"><Alert tone="warning" title="No margin can be shown yet">A margin needs every variable cost: still missing {fin.data.economics.missing_variable_inputs.join(", ").replace(/_/g, " ")}.</Alert></div>}</Card>
          <Card><CardHeader title="Unit economics" /><Rows rows={eco} /></Card>
        </div>
      )}

      <h2 className="mb-3 mt-10 text-[15px] font-semibold">AI and Google usage ({cost.data?.month ?? "this month"})</h2>
      {!cost.data ? <Skeleton className="h-48" /> : (
        <div className="space-y-6">
          <Alert tone={cost.data.complete ? "success" : "warning"} title={cost.data.complete ? (cost.data.ai.calls + cost.data.api.units + cost.data.api.failed_units === 0 ? "No AI or Google calls yet this month" : "Every call in this period is priced") : `${cost.data.unpriced_calls_and_units} call(s) have no price configured`}>{cost.data.note} Total with configured prices: {cost.data.total_usd === null ? "n/a" : `$${cost.data.total_usd.toFixed(2)}`}.</Alert>
          <div className="grid gap-4 sm:grid-cols-2">
            <Card><CardHeader title="AI model calls" subtitle={`${cost.data.ai.calls} calls, ${cost.data.ai.failed_calls} failed, ${cost.data.ai.refused_calls} refused by a budget`} />
              <ul className="divide-y divide-line text-sm">{cost.data.ai.by_feature.map((f) => <li key={f.feature} className="flex justify-between py-2"><span>{f.feature.replace(/_/g, " ")}</span><span className="num">{f.calls} calls · {f.usd === null ? "unpriced" : `$${f.usd.toFixed(4)}`}{f.unpriced_calls ? ` (${f.unpriced_calls} unpriced)` : ""}</span></li>)}</ul></Card>
            <Card><CardHeader title="Google API requests" subtitle={`${cost.data.api.units} made, ${cost.data.api.failed_units} failed, ${cost.data.api.refused_units} refused before spending`} />
              <ul className="divide-y divide-line text-sm">{cost.data.api.by_operation.map((o, i) => <li key={i} className="flex justify-between gap-3 py-2"><span>{o.provider} {o.operation} <span className="text-muted">({o.feature.replace(/_/g, " ")})</span></span><span className="num">{o.units} · {o.unpriced_units ? "unpriced" : `$${o.usd.toFixed(3)}`}{o.refused_units ? ` · ${o.refused_units} refused` : ""}</span></li>)}</ul></Card>
          </div>
          <Card><CardHeader title="By business" subtitle="Highest first. Set a business's own ceilings from its Customers page." />
            <div className="overflow-x-auto"><table className="w-full min-w-[520px] text-left text-sm"><thead><tr className="text-xs text-muted"><th className="py-1.5">Business</th><th>AI calls</th><th>AI $</th><th>Google units</th><th>Google $</th><th>Total $</th></tr></thead>
              <tbody>{cost.data.by_business.map((b) => <tr key={b.tenant_id ?? "platform"} className="border-t border-line"><td className="py-2">{b.name}</td><td className="num">{b.ai_calls}</td><td className="num">{b.ai_usd.toFixed(4)}</td><td className="num">{b.api_units}</td><td className="num">{b.api_usd.toFixed(3)}</td><td className="num font-medium">{b.total_usd.toFixed(3)}</td></tr>)}</tbody></table></div></Card>
        </div>
      )}
    </>
  );
}
