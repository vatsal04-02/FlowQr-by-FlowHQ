import type { Metadata } from "next";
import { pageMeta } from "@/lib/site";

export const metadata: Metadata = pageMeta("/privacy", "Privacy policy", "How FlowQR collects, uses and protects personal data.");

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
