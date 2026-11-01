import { Check } from "lucide-react";
import { FEATURE_LABELS, rupees } from "@/lib/billing";
import type { Plan } from "@/lib/types";

export function PlanCards({ plans, current, action }: { plans: Plan[]; current?: string | null; action: (p: Plan) => React.ReactNode }) {
  return (
    <div className="grid gap-5 lg:grid-cols-3">
      {plans.map((p) => (
        <article key={p.code} className={`flex flex-col rounded-2xl border bg-white p-6 shadow-card ${p.code === "growth" ? "border-brand-500 ring-2 ring-brand-500/20" : "border-ink-100"}`}>
          {p.code === "growth" && <span className="mb-3 w-fit rounded-full bg-brand-600 px-3 py-0.5 text-xs font-semibold text-white">Most popular</span>}
          <h3 className="text-xl font-semibold">{p.name}</h3>
          <p className="mt-3"><span className="font-display text-4xl font-semibold">{rupees(p.price_paise)}</span><span className="text-ink-500"> / month</span></p>
          <p className="text-xs text-ink-500">+ GST as applicable</p>
          <ul className="mt-5 flex-1 space-y-2.5 text-sm text-ink-700">
            <li className="flex gap-2"><Check className="mt-0.5 h-4 w-4 shrink-0 text-g-green" aria-hidden /><b>{p.max_locations}</b>&nbsp;{p.max_locations === 1 ? "location" : "locations"}</li>
            <li className="flex gap-2"><Check className="mt-0.5 h-4 w-4 shrink-0 text-g-green" aria-hidden /><b>{p.monthly_ai_generations.toLocaleString("en-IN")}</b>&nbsp;AI generations / month</li>
            <li className="flex gap-2"><Check className="mt-0.5 h-4 w-4 shrink-0 text-g-green" aria-hidden />Up to <b>{p.max_staff}</b>&nbsp;team members</li>
            <li className="flex gap-2"><Check className="mt-0.5 h-4 w-4 shrink-0 text-g-green" aria-hidden />Unlimited QR/NFC scans</li>
            {p.features.map((f) => <li key={f} className="flex gap-2"><Check className="mt-0.5 h-4 w-4 shrink-0 text-g-green" aria-hidden />{FEATURE_LABELS[f] ?? f}</li>)}
          </ul>
          <div className="mt-6">{action(p)}</div>
          {current === p.code && <p className="mt-2 text-center text-sm font-semibold text-g-green">Your current plan</p>}
        </article>
      ))}
    </div>
  );
}
