import type { Metadata } from "next";
import { pageMeta } from "@/lib/site";

export const metadata: Metadata = pageMeta("/terms", "Terms of service", "The terms for using FlowQR by FlowHQ.");

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
