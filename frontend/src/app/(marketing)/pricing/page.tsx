import type { Metadata } from "next";
import { Hero } from "@/components/marketing/Hero";
import { MButton, SectionHead } from "@/components/marketing/kit";
import { Rise } from "@/components/marketing/motion";
import { CardAddOn, PlanCards, PlanCompare } from "@/components/marketing/PlansFromConfig";
import { FAQ, FinalCTA } from "@/components/marketing/Sections";
import { en } from "@/content/marketing/en";
import { pageMeta } from "@/lib/site";

const c = en.pricing;
export const metadata: Metadata = pageMeta("/pricing", c.meta.title, c.meta.description);

export default function Pricing() {
  return (
    <>
      <Hero line1={c.hero.line1} line2={c.hero.line2} actions={<><MButton href="/register">Start free trial</MButton><MButton href="/demo" variant="secondary">Book a demo</MButton></>} />
      <section className="pb-24">
        <div className="mkt-wrap"><PlanCards /></div>
      </section>
      <section className="pb-24"><div className="mkt-wrap"><CardAddOn /></div></section>
      <section className="pb-12">
        <div className="mkt-wrap">
          <Rise><SectionHead title="Compare plans" /></Rise>
          <div className="mt-12"><PlanCompare /></div>
        </div>
      </section>
      <FAQ items={c.faq} />
      <FinalCTA line1={c.cta.line1} line2={c.cta.line2} />
    </>
  );
}
