import { BadgeCheck, Database, HeartHandshake, ShieldCheck, Sparkles } from "lucide-react";
import type { Metadata } from "next";
import { Hero } from "@/components/marketing/Hero";
import { Chip, MButton, SectionHead } from "@/components/marketing/kit";
import { Rise } from "@/components/marketing/motion";
import { ScrollStatement } from "@/components/marketing/Sections";
import { en } from "@/content/marketing/en";
import { pageMeta } from "@/lib/site";

const c = en.about;
export const metadata: Metadata = pageMeta("/about", c.meta.title, c.meta.description);
const ICONS = [HeartHandshake, ShieldCheck, Database, BadgeCheck];

export default function About() {
  return (
    <>
      <Hero line1={c.hero.line1} line2={c.hero.line2} actions={<><MButton href="/demo" event="demo_cta_click">Book a demo</MButton><MButton href="#services" variant="secondary">FlowHQ services</MButton></>} />
      <ScrollStatement text={c.statement.text} strong={c.statement.strong} chip={<Sparkles className="h-[.6em] w-[.6em]" strokeWidth={2} />} />
      <section className="pb-24 md:pb-36">
        <div className="mkt-wrap">
          <Rise><SectionHead title="What we promise" /></Rise>
          <div className="mt-12 grid gap-3 md:grid-cols-2">
            {c.promises.map(([t, b], i) => { const I = ICONS[i]; return (
              <Rise key={t} y={24} blur={false} delay={(i % 2) * 0.1} className={`rounded-[20px] p-7 ${i === 0 || i === 3 ? "bg-m-tint" : "bg-m-surface shadow-[var(--shadow-card)]"}`}>
                <Chip tone={i === 0 || i === 3 ? "white" : "tint"} icon={<I className="h-3.5 w-3.5" strokeWidth={1.5} />}>Promise {i + 1}</Chip>
                <h3 className="mt-10 t-h3 text-m-ink">{t}</h3><p className="mt-3 max-w-[420px] text-[15px] text-m-muted">{b}</p>
              </Rise>
            ); })}
          </div>
        </div>
      </section>
      <section id="services" className="scroll-mt-24 pb-24 md:pb-36">
        <div className="mkt-wrap">
          <Rise className="rounded-[20px] bg-m-navy p-8 text-white md:p-14">
            <p className="t-small text-white/60">For custom systems</p>
            <h2 className="mt-4 max-w-[560px] t-h2">{c.services.title}</h2>
            <p className="mt-4 max-w-[520px] text-[15px] text-white/70">{c.services.body}</p>
            <MButton href="/demo" variant="dark" icon="arrow" className="mt-8">{c.services.cta}</MButton>
          </Rise>
        </div>
      </section>
    </>
  );
}
