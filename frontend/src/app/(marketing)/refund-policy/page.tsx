import type { Metadata } from "next";
import { RefundPending } from "@/components/marketing/RefundPending";
import { pageMeta } from "@/lib/site";

// Not indexed while it is a "not published yet" notice. The real policy text must come from FlowHQ and counsel: nothing in this repository is a refund policy.
export const metadata: Metadata = { ...pageMeta("/refund-policy", "Refund policy", "FlowQR refund and cancellation policy."), robots: { index: false, follow: true } };

export default function RefundPolicy() {
  return <RefundPending />;
}
