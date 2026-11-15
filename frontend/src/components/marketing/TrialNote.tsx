"use client";
import { trialTerms, usePlans } from "@/lib/plans";

/** "7-day free trial. Card required, no charge until the trial ends." The length and the card rule comes from the server, like the banner and the pricing page. */
export function TrialNote({ className }: { className?: string }) {
  const { trialDays, cardRequired } = usePlans();
  return <p className={className}>{trialDays}&#8209;day free trial. {trialTerms(cardRequired)}</p>;
}
