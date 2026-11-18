import type { Metadata } from "next";
import { Inter_Tight } from "next/font/google";
import { FooterCards } from "@/components/marketing/FooterCards";
import { Nav } from "@/components/marketing/Nav";
import { SiteCursor } from "@/components/marketing/SiteCursor";
import { ScrollProgress } from "@/components/marketing/scroll";
import { TrialBanner } from "@/components/marketing/TrialBanner";
import { SITE_URL } from "@/lib/site";

// The public marketing site (docs/marketing-site). Its own layout, fonts and tokens; the logged-in app's routes and styles are untouched.
const tight = Inter_Tight({ subsets: ["latin"], weight: ["400", "500", "600"], display: "swap", variable: "--font-tight" });

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  openGraph: { type: "website", siteName: "FlowQR by FlowHQ", locale: "en_IN" },
  twitter: { card: "summary_large_image" },
};

export default function MarketingLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className={`${tight.variable} mkt min-h-dvh overflow-x-clip`}>
      <ScrollProgress />
      <SiteCursor />
      <TrialBanner />
      <Nav />
      <main id="content">{children}</main>
      <FooterCards />
    </div>
  );
}
