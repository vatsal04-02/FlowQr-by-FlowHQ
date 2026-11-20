import { BadgeCheck, CalendarCheck, Layers, MousePointerClick, Nfc, QrCode, ScanLine, Search, Sparkles, Star, TrendingUp } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { Hero } from "@/components/marketing/Hero";
import { BusinessBand } from "@/components/marketing/BusinessBand";
import { HeroFloaters } from "@/components/marketing/HeroFloaters";
import { HeroActions } from "@/components/marketing/HeroActions";
import { MButton, MicroChip } from "@/components/marketing/kit";
import { AgentShowcase } from "@/components/marketing/AgentShowcase";
import { WhatsAppShowcase } from "@/components/marketing/WhatsAppShowcase";
import { StorySection } from "@/components/marketing/HomeSections";
import { StepConnectArt, StepCounterArt, StepReviewsArt } from "@/components/marketing/HomeVisuals";
import { MiniCard, OverviewScreen } from "@/components/marketing/Mockups";
import { PhoneOrbit } from "@/components/marketing/PhoneOrbit";
import { PinnedSteps } from "@/components/marketing/PinnedSteps";
import { FaqScroller } from "@/components/marketing/FaqScroller";
import { ComparisonTable, FinalCTA } from "@/components/marketing/Sections";
import { en } from "@/content/marketing/en";
import { pageMeta, SITE_URL } from "@/lib/site";

const c = en.home;
export const metadata: Metadata = pageMeta("/", c.meta.title, c.meta.description);

// JSON-LD: what FlowQR is and who makes it. No ratings, no review counts, no prices.
const jsonLd = {
  "@context": "https://schema.org",
  "@graph": [
    { "@type": "Organization", name: "FlowHQ", url: SITE_URL },
    { "@type": "SoftwareApplication", name: "FlowQR", applicationCategory: "BusinessApplication", operatingSystem: "Web", url: SITE_URL, publisher: { "@type": "Organization", name: "FlowHQ" },
      description: c.meta.description },
  ],
};

const ROW_ICONS = [Layers, Sparkles, BadgeCheck, QrCode, MousePointerClick, ScanLine];

export default function Home() {
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />
      {/* S1 Hero */}
      <Hero line1={c.hero.line1} line2={c.hero.line2} typed={c.hero.typed} sub={c.hero.sub}
        actions={<HeroActions />} floaters={<HeroFloaters />} />

      {/* Made for: the kinds of business, large and scrolling, each linking to its block on /industries */}
      <BusinessBand title={c.hero.bandTitle} items={en.industries.list.map(([id, name]) => [id, name] as [string, string])} />

      {/* The three agents, animated */}
      <AgentShowcase title={c.team.title} sub={c.team.sub} />

      {/* The WhatsApp Marketing AI Agent, directly below the GBP AI Agent */}
      <div className="mt-8 md:mt-14"><WhatsAppShowcase learnMoreHref="/whatsapp-marketing-ai-agent" /></div>


      {/* S3 + S4 Brand intro and phone with orbiting cards */}
      <PhoneOrbit line1={c.intro.line1} line2Pre={c.intro.line2Pre} accent={c.intro.accent} sub={c.intro.sub} screen={<OverviewScreen />}
        orbit={[
          { node: <MiniCard icon={<Star className="h-3.5 w-3.5" strokeWidth={1.5} />} title="★★★★★ New review" sub="Reply drafted" className="w-[170px]" />, x: -330, y: -40, r: -9 },
          { node: <MiniCard icon={<QrCode className="h-3.5 w-3.5" strokeWidth={1.5} />} title="QR scans: 63" sub="Sample data" className="w-[140px]" />, x: -250, y: 120, r: -4 },
          { node: <MiniCard icon={<Nfc className="h-3.5 w-3.5" strokeWidth={1.5} />} title="NFC taps: 41" sub="Sample data" className="w-[140px]" />, x: -120, y: -110, r: 3 },
          { node: <MiniCard tone="accent" icon={<CalendarCheck className="h-3.5 w-3.5" strokeWidth={1.5} />} title="Google post scheduled" sub="Diwali offer" className="w-[180px]" />, x: 300, y: -60, r: 8 },
          { node: <MiniCard icon={<BadgeCheck className="h-3.5 w-3.5" strokeWidth={1.5} />} title="Approve 3 replies" className="w-[150px]" />, x: 150, y: -120, r: -3 },
          { node: <MiniCard tone="tint" icon={<TrendingUp className="h-3.5 w-3.5" strokeWidth={1.5} />} title="Profile 92% complete" sub="Sample data" className="w-[170px]" />, x: 280, y: 130, r: 5 },
        ]} />

      {/* G. Local storytelling: people check Google first */}
      <StorySection c={c.story} />

      {/* A. How it works: three connected steps */}
      <PinnedSteps title={c.how.title} sub={c.how.sub} steps={c.how.steps} art={[<StepConnectArt key="1" />, <StepCounterArt key="2" />, <StepReviewsArt key="3" />]} />

      {/* E. Comparison */}
      <ComparisonTable tight title={c.compare.title} sub={c.compare.sub} columns={c.compare.columns} note={c.compare.note}
        rows={c.compare.rows.map(([feature, ...cells], i) => { const I = ROW_ICONS[i]; return { feature, cells, icon: <I className="h-3.5 w-3.5" strokeWidth={1.5} /> }; })} />

      {/* S8 FAQ */}
      <FaqScroller sub="Straight answers about reviews, replies, Google and cost." items={c.faq.map(([q, a]) => [q, a === "PRICING_LINK" ? <span key="pricing">Plans are in rupees on our <Link href="/pricing" className="text-m-accentStrong underline">pricing page</Link>. Cards are sold separately.</span> : a])} />

      {/* Final CTA */}
      <FinalCTA line1={c.cta.line1} line2={c.cta.line2} />
    </>
  );
}
