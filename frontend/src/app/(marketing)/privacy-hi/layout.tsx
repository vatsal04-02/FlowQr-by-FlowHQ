import type { Metadata } from "next";
import { pageMeta } from "@/lib/site";

export const metadata: Metadata = pageMeta("/privacy-hi", "गोपनीयता नीति (हिंदी)", "FlowQR व्यक्तिगत डेटा कैसे जुटाता, उपयोग करता और सुरक्षित रखता है।");

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
