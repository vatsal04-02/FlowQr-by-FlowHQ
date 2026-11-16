import type { Metadata } from "next";
import { pageMeta } from "@/lib/site";

export const metadata: Metadata = pageMeta("/refund-policy", "Refund policy", "FlowQR refund and cancellation policy.");

// Structure only. The policy text must come from FlowHQ (and counsel); nothing here is a policy.
export default function RefundPolicy() {
  return (
    <div className="mkt-wrap max-w-3xl py-16 sm:py-20">
      <h1 className="t-h2 text-m-ink">Refund policy</h1>
      <div className="mt-10 space-y-6 rounded-[20px] bg-m-surface p-6 text-[15px] leading-relaxed text-m-ink2 sm:p-10">
        {["Subscriptions", "Cancellations", "Printed cards and posters", "How to request a refund", "Contact"].map((h) => (
          <section key={h}><h2 className="text-xl font-medium text-m-ink">{h}</h2><p className="mt-2 text-m-muted">[LEGAL TEXT TO BE PROVIDED]</p></section>
        ))}
      </div>
    </div>
  );
}
