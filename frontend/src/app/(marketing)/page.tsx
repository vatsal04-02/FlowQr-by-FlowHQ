import { BadgeCheck, CalendarCheck, Eye, MessageSquareReply, Nfc, QrCode, ScanLine, Search, Settings2, Sparkles, Star, Store, TrendingUp, Wallet } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { Hero } from "@/components/marketing/Hero";
import { HeroFlow } from "@/components/marketing/HeroFlow";
import { Chip, MButton, MicroChip } from "@/components/marketing/kit";
import { AgentShowcase } from "@/components/marketing/AgentShowcase";
import { ArcDiagram, MiniCard, OverviewScreen, ProfileBeforeAfter } from "@/components/marketing/Mockups";
import { PhoneOrbit } from "@/components/marketing/PhoneOrbit";
import { BentoCard, BentoWide, ComparisonTable, FAQ, FinalCTA, HowItWorks, Marquee, ScrollStatement, type MarqueeItem } from "@/components/marketing/Sections";
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

const ROW_ICONS = [MessageSquareReply, Sparkles, Nfc, Settings2, Star, ScanLine, Wallet];
const ORBIT_ICONS = [Star, QrCode, Nfc, CalendarCheck, BadgeCheck, TrendingUp];
const MARQUEE: MarqueeItem[] = [
  { kind: "photo", src: "/marketing/photos/street-bangalore.jpg", alt: "Shops along Commercial Street, Bangalore" },
  { kind: "accent", label: c.marquee[0][1], title: c.marquee[0][0], icon: <BadgeCheck className="h-4 w-4" strokeWidth={1.5} /> },
  { kind: "photo", src: "/marketing/photos/salon.jpg", alt: "A small salon with two chairs" },
  { kind: "tint", label: c.marquee[1][1], title: c.marquee[1][0], icon: <CalendarCheck className="h-4 w-4" strokeWidth={1.5} /> },
  { kind: "photo", src: "/marketing/photos/sweet-shop.jpg", alt: "A sweet shop counter stacked with mithai" },
  { kind: "accent", label: c.marquee[2][1], title: c.marquee[2][0], icon: <QrCode className="h-4 w-4" strokeWidth={1.5} /> },
  { kind: "photo", src: "/marketing/photos/market-store.jpg", alt: "A store sign in Moazzam Jahi Market, Hyderabad" },
  { kind: "tint", label: c.marquee[3][1], title: c.marquee[3][0], icon: <Eye className="h-4 w-4" strokeWidth={1.5} /> },
  { kind: "accent", label: c.marquee[4][1], title: c.marquee[4][0], icon: <Sparkles className="h-4 w-4" strokeWidth={1.5} /> },
];

export default function Home() {
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />
      {/* S1 Hero */}
      <Hero line1={c.hero.line1} line2={c.hero.line2} sub={c.hero.sub}
        kicker={<span className="inline-flex items-center gap-2 rounded-full bg-m-surface/80 py-1.5 pl-1.5 pr-4 text-[14px] font-medium text-m-ink2 shadow-[var(--shadow-card)] backdrop-blur"><span className="grid h-7 w-7 place-items-center rounded-full bg-m-tint text-m-accentStrong"><Store className="h-3.5 w-3.5" strokeWidth={1.75} /></span>{c.hero.forLabel} <span className="text-m-accentStrong">{c.hero.forAccent}</span></span>}
        actions={<>
          <MButton href="/demo" event="demo_cta_click">{c.hero.primary}</MButton>
          <MButton href="#agents" variant="secondary" lead={<Search className="h-4 w-4" strokeWidth={1.5} />}>See how it works</MButton>
        </>}
        flow={<HeroFlow note={c.hero.left} captions={["One card, tap or scan", "Your customer's review page", "Every Google review, answered"]}
          chips={[<MicroChip key="a" icon={<Sparkles className="h-3 w-3" strokeWidth={1.5} />}>{c.hero.chips[0]}</MicroChip>, <MicroChip key="b" icon={<BadgeCheck className="h-3 w-3" strokeWidth={1.5} />}>{c.hero.chips[1]}</MicroChip>, <MicroChip key="c" icon={<Nfc className="h-3 w-3" strokeWidth={1.5} />}>{c.hero.chips[2]}</MicroChip>]} />} />

      {/* The three agents, animated */}
      <AgentShowcase title={c.team.title} sub={c.team.sub} />


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

      {/* S5 Statement */}
      <ScrollStatement tight text={c.statement.text} strong={c.statement.strong} chip={<QrCode className="h-[.6em] w-[.6em]" strokeWidth={2} />} />

      {/* How it works: one row, three steps */}
      <HowItWorks title={c.how.title} steps={c.how.steps} />

      {/* S6 Bento */}
      <section className="pb-10 md:pb-14">
        <div className="mkt-wrap space-y-3">
          <BentoWide chip={<Chip tone="tint" icon={<CalendarCheck className="h-3.5 w-3.5" strokeWidth={1.5} />}>{c.bento.wide.chip}</Chip>} title={c.bento.wide.title} body={c.bento.wide.body}
            photo="/marketing/photos/sweet-shop.jpg" photoAlt="A sweet shop counter in Rajasthan, stacked with mithai"
            toast={<MiniCard icon={<BadgeCheck className="h-3.5 w-3.5" strokeWidth={1.5} />} title={c.bento.wide.toast[0]} sub={c.bento.wide.toast[1]} className="w-[210px] !bg-m-navy !text-white" />} />
          <div className="grid gap-3 md:grid-cols-2">
            <BentoCard tone="tint" chip={<Chip icon={<Store className="h-3.5 w-3.5" strokeWidth={1.5} />}>{c.bento.left.chip}</Chip>} title={c.bento.left.title} body={c.bento.left.body} visual={<ProfileBeforeAfter />} />
            <BentoCard delay={0.1} chip={<Chip tone="tint" icon={<QrCode className="h-3.5 w-3.5" strokeWidth={1.5} />}>{c.bento.right.chip}</Chip>} title={c.bento.right.title} body={c.bento.right.body} visual={<ArcDiagram />} />
          </div>
        </div>
      </section>

      {/* S7 Comparison */}
      <ComparisonTable tight title={c.compare.title} sub={c.compare.sub} columns={c.compare.columns}
        rows={c.compare.rows.map(([feature, ...cells], i) => { const I = ROW_ICONS[i]; return { feature, cells, icon: <I className="h-3.5 w-3.5" strokeWidth={1.5} /> }; })} />

      {/* S8 FAQ */}
      <FAQ tight items={c.faq.map(([q, a]) => [q, a === "PRICING_LINK" ? <span key="pricing">Plans are in rupees on our <Link href="/pricing" className="text-m-accentStrong underline">pricing page</Link>. Cards are sold separately.</span> : a])} />

      {/* S9 Marquee + final CTA */}
      <Marquee items={MARQUEE} />
      <FinalCTA line1={c.cta.line1} line2={c.cta.line2} />
    </>
  );
}
