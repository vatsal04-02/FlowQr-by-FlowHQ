import type { Metadata } from "next";
import { pageMeta } from "@/lib/site";

export const metadata: Metadata = pageMeta("/data-deletion", "Delete your data", "How to delete your FlowQR account and data.");

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
