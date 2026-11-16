"use client";
import { trialTerms, usePlans } from "@/lib/plans";

/** "7-day free trial. <payment terms>" The length and the terms comes from the server, like the banner and the pricing page. */
export function TrialNote({ className }: { className?: string }) {
  const { trialDays, mandateRequired } = usePlans();
  return <p className={className}>{trialDays}&#8209;day free trial. {trialTerms(mandateRequired)}</p>;
}
