"use client";
import { Lock } from "lucide-react";
import Link from "next/link";
import { usePlans } from "@/lib/plans";
import type { Role } from "@/lib/types";

/**
 * What a page shows when it is opened (a pasted link, a bookmark, an old email) but its feature is not in the business's plan. The menus already leave such pages out; this is the calm
 * answer for the link that still points at one, instead of a screen that fails.
 */
export function PlanLocked({ title, feature, planName, role }: { title: string; feature: string; planName: string | null; role: Role | null }) {
  const { plans } = usePlans();
  const have = plans.filter((p) => p.features.includes(feature)).sort((a, b) => a.price_paise - b.price_paise);
  const names = have.map((p) => p.name);
  const can = role === "owner" || role === "admin";
  return (
    <div className="mx-auto max-w-lg py-16 text-center">
      <span className="mx-auto mb-5 grid h-12 w-12 place-items-center rounded-full bg-surface-2 text-ink-500"><Lock className="h-5 w-5" aria-hidden /></span>
      <h1 className="text-xl font-semibold text-ink">{title} is not part of {planName ? `your ${planName} plan` : "your plan"}</h1>
      <p className="mt-2 text-[15px] text-muted">{names.length ? `It is included in ${names.join(" and ")}.` : "It is not available on your plan."} {can ? "You can change your plan at any time." : "Ask your account owner to change the plan."}</p>
      <div className="mt-6 flex flex-wrap justify-center gap-3">
        {can && <Link href="/settings/billing" className="inline-flex min-h-11 items-center justify-center rounded-full bg-ink-solid px-6 text-sm font-semibold text-ink-on">See plans</Link>}
        <Link href="/overview" className="inline-flex min-h-11 items-center justify-center rounded-full bg-surface-2 px-6 text-sm font-semibold text-ink ring-1 ring-ink-100">Back to Home</Link>
      </div>
    </div>
  );
}
