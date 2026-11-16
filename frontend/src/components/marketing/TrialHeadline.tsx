"use client";
import { trialTerms, usePlans } from "@/lib/plans";

/** "Start your 7-day free trial": the trial length comes from the server. The number and "day" stay together (non-breaking hyphen). */
export function TrialHeadline() {
  const { trialDays } = usePlans();
  return <>Start your {trialDays}&#8209;day free trial</>;
}

/** The default sign-in pitch: what the trial needs (read from the server), then what FlowQR does. */
export function TrialPitch() {
  const { mandateRequired } = usePlans();
  return <>{trialTerms(mandateRequired)} Connect your Google profile, put a FlowQR card on your counter, and approve everything before it goes live.</>;
}
