"use client";
import { TRIAL_TERMS, usePlans } from "@/lib/plans";

/** "7-day free trial. No card needed." The length comes from the server, like the banner and the pricing page. */
export function TrialNote({ className }: { className?: string }) {
  const { trialDays } = usePlans();
  return <p className={className}>{trialDays}&#8209;day free trial. {TRIAL_TERMS}</p>;
}
