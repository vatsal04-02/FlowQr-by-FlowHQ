import type { Metadata } from "next";
import { pageMeta } from "@/lib/site";

// Not indexed until the owner and a lawyer have confirmed the draft text (docs/DPDP_ARTIFACTS.md). Remove `robots` then.
export const metadata: Metadata = { ...pageMeta("/refund-policy", "Refund and cancellation policy", "How cancelling, payments and refunds work for FlowQR."), robots: { index: false, follow: true } };

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
