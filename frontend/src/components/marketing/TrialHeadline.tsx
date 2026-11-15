"use client";
import { usePlans } from "@/lib/plans";

/** "Start your 14-day free trial": the trial length comes from the server. The number and "day" stay together (non-breaking hyphen). */
export function TrialHeadline() {
  const { trialDays } = usePlans();
  return <>Start your {trialDays}&#8209;day free trial</>;
}
