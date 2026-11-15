"use client";
import clsx from "clsx";
import { Check, Minus } from "lucide-react";
import { useState, type ReactNode } from "react";
import { FEATURE_LABELS, rupees } from "@/lib/billing";
import type { Plan } from "@/lib/types";
import { Segmented } from "./ui/kit";

/**
 * Plans as one comparison, not three identical cards. Wide screens get a table (read across to compare, down to see what
 * each tier adds); phones get a plan switcher over a single list, so nothing hides off the edge of the screen.
 */
export function PlanCards({ plans, current, action }: { plans: Plan[]; current?: string | null; action: (p: Plan) => ReactNode }) {
  const features = Object.keys(FEATURE_LABELS).filter((k) => plans.some((p) => p.features.includes(k)));
  const [sel, setSel] = useState(plans.find((p) => p.code === "growth")?.code ?? plans[0]?.code ?? "");
  const rows: [string, (p: Plan) => ReactNode][] = [
    ["Locations", (p) => <span className="num font-medium">{p.max_locations}</span>],
    ["Team members", (p) => <span className="num font-medium">{p.max_staff}</span>],
    ["AI review generations / month", (p) => <span className="num font-medium">{p.review_generations.toLocaleString("en-IN")}</span>],
    ["AI review replies / month", (p) => <span className="num font-medium">{p.review_replies.toLocaleString("en-IN")}</span>],
    ["QR/NFC scans", () => <span className="font-medium">Unlimited</span>],
    ...features.map((k): [string, (p: Plan) => ReactNode] => [FEATURE_LABELS[k] ?? k, (p) => p.features.includes(k) ? <Check className="h-4 w-4 text-ok" aria-label="Included" /> : <Minus className="h-4 w-4 text-ink-300" aria-label="Not included" />]),
  ];
  const tint = (p: Plan) => (p.code === "growth" ? "bg-brand-50/50" : "");
  const one = plans.find((p) => p.code === sel) ?? plans[0];
  return (
    <>
      <div className="panel sm:hidden">
        <div className="border-b border-ink-100 p-3"><Segmented label="Choose a plan" value={sel} onChange={setSel} options={plans.map((p) => [p.code, p.name] as const)} className="w-full [&>button]:flex-1" /></div>
        {one && (
          <div className="p-4">
            <p className="text-xs font-semibold text-brand-700">{one.code === "growth" ? "Most popular" : current === one.code ? "Your plan" : " "}</p>
            <p className="num mt-1 text-[28px] font-bold leading-none tracking-tight">{rupees(one.price_paise)}<span className="text-sm font-medium text-ink-500"> / month</span></p>
            <p className="mt-1 text-xs text-ink-500">+ GST as applicable</p>
            <div className="mt-3">{action(one)}</div>
            <dl className="mt-3 divide-y divide-ink-100 text-sm">{rows.map(([label, cell]) => <div key={label} className="flex items-center justify-between gap-3 py-2"><dt className="text-ink-700">{label}</dt><dd>{cell(one)}</dd></div>)}</dl>
          </div>
        )}
      </div>

      <div className="panel hidden overflow-x-auto sm:block">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead>
            <tr className="align-bottom">
              <th scope="col" className="w-[30%] px-4 pb-4 pt-5"><span className="sr-only">Plan</span></th>
              {plans.map((p) => (
                <th key={p.code} scope="col" className={clsx("px-4 pb-4 pt-5", tint(p))}>
                  <span className="mb-1 block h-4 text-xs font-semibold text-brand-700">{p.code === "growth" ? "Most popular" : current === p.code ? "Your plan" : ""}</span>
                  <span className="block text-sm font-semibold">{p.name}</span>
                  <span className="num mt-1 block text-[26px] font-bold leading-none tracking-tight">{rupees(p.price_paise)}<span className="text-sm font-medium text-ink-500"> / month</span></span>
                  <span className="mt-1 block text-xs font-normal text-ink-500">+ GST as applicable</span>
                </th>
              ))}
            </tr>
            <tr><td className="px-4 pb-4" />{plans.map((p) => <td key={p.code} className={clsx("px-4 pb-4", tint(p))}>{action(p)}</td>)}</tr>
          </thead>
          <tbody>
            {rows.map(([label, cell]) => (
              <tr key={label} className="border-t border-ink-100">
                <th scope="row" className="px-4 py-2.5 text-[13px] font-medium text-ink-700">{label}</th>
                {plans.map((p) => <td key={p.code} className={clsx("px-4 py-2.5", tint(p))}>{cell(p)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
