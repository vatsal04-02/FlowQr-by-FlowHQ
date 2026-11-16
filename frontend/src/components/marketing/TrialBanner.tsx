"use client";
import Link from "next/link";
import { TRIAL_TERMS, usePlans } from "@/lib/plans";
import { track } from "@/lib/track";

/** The slim bar above the nav. The trial length comes from the server (`TRIAL_DAYS`), exactly as on the pricing page, so it can never disagree with what the app gives. */
export function TrialBanner() {
  const { trialDays } = usePlans();
  return (
    <div className="bg-m-navy text-white">
      <p className="mkt-wrap flex min-h-10 flex-wrap items-center justify-center gap-x-3 gap-y-0.5 py-2 text-center text-[13.5px]">
        <span>Start your {trialDays}&#8209;day free trial. {TRIAL_TERMS}</span>
        <Link href="/register" onClick={() => track("signup_cta_click")} className="font-medium text-m-accent300 underline underline-offset-4 hover:text-white focus-visible:!outline-white">Sign up</Link>
      </p>
    </div>
  );
}
