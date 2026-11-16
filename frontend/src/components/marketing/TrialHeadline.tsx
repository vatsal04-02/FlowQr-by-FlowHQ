"use client";
import { TRIAL_TERMS, usePlans } from "@/lib/plans";

/** "Start your 7-day free trial": the trial length comes from the server. The number and "day" stay together (non-breaking hyphen). */
export function TrialHeadline() {
  const { trialDays } = usePlans();
  return <>Start your {trialDays}&#8209;day free trial</>;
}

/** The default sign-in pitch: no card needed, then what FlowQR does. */
export function TrialPitch() {
  return <>{TRIAL_TERMS} Connect your Google profile, put a FlowQR card on your counter, and approve everything before it goes live.</>;
}
