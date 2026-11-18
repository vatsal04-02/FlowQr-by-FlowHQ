"use client";
import { Contact, type LegalInfo } from "@/components/marketing/LegalShell";
import { useFetch } from "@/lib/use-api";

/** The public refund page while the policy has not been written and approved. It says so plainly and invents no terms: no refund promise, no deadline, no conditions. It states only what the
 *  Terms of service already say about cancelling. Replace this component with the approved text (owner and lawyer action: docs/LAUNCH_READINESS_CHECKLIST.md). */
export function RefundPending() {
  const { data } = useFetch<LegalInfo>("/legal/info");
  return (
    <div className="mkt-wrap max-w-3xl py-16 sm:py-20">
      <h1 className="t-h2 text-m-ink">Refund policy</h1>
      <div className="mt-10 space-y-4 rounded-[20px] bg-m-surface p-6 text-[15px] leading-relaxed text-m-ink2 sm:p-10">
        <p><b>Our refund and cancellation policy has not been published yet.</b></p>
        <p>Until it is, please write to <Contact info={data ?? null} /> about any payment, cancellation or refund question, and we will answer you directly.</p>
        <p>You can cancel a subscription yourself at any time in Settings, Billing. What happens to your access when you cancel is described in our <a className="underline" href="/terms">Terms of service</a>.</p>
      </div>
    </div>
  );
}
