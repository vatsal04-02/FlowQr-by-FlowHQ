import type { Metadata } from "next";
import { pageMeta } from "@/lib/site";

export const metadata: Metadata = pageMeta("/cookie-policy", "Cookie policy", "The cookies and device storage FlowQR uses, and why there is no cookie banner.");

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
