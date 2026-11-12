"use client";
import { LinkButton } from "@/components/ui/Button";
import { PlanCards } from "@/components/PlanCards";
import { usePlans } from "@/lib/plans";

/** Live plans from the API (with a built-in fallback), as one comparison table. Each action starts the free trial. */
export function LandingPlans() {
  const { plans } = usePlans();
  return <PlanCards plans={plans} action={(p) => <LinkButton href="/register" size="sm" variant={p.code === "growth" ? "primary" : "secondary"} className="w-full">Start free trial</LinkButton>} />;
}

export function TrialNote() {
  const { trialDays } = usePlans();
  return <>{trialDays}-day free trial with Growth features. No card needed. Cancel any time.</>;
}
