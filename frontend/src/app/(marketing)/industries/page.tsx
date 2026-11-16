import { MapPin, Tag } from "lucide-react";
import type { Metadata } from "next";
import Image from "next/image";
import { Hero } from "@/components/marketing/Hero";
import { IndustryTabs } from "@/components/marketing/IndustryTabs";
import { Chip, MButton } from "@/components/marketing/kit";
import { Rise } from "@/components/marketing/motion";
import { FinalCTA } from "@/components/marketing/Sections";
import { en } from "@/content/marketing/en";
import { pageMeta } from "@/lib/site";

const c = en.industries;
export const metadata: Metadata = pageMeta("/industries", c.meta.title, c.meta.description);

export default function Industries() {
  return (
    <>
      <Hero line1={c.hero.line1} line2={c.hero.line2} actions={<MButton href="/register" event="signup_cta_click">Sign up</MButton>} />
      <IndustryTabs items={c.list.map(([id, name]) => [id, name])} />
      <div className="mkt-wrap space-y-3 pb-16 pt-8">
        {c.list.map(([id, name, where, topics], i) => (
          <Rise key={id} y={24} blur={false}>
            <section id={id} aria-labelledby={`${id}-h`} className="mkt-card grid scroll-mt-40 overflow-hidden md:grid-cols-[.9fr_1.1fr]">
              <div className={`relative min-h-[240px] ${i % 2 ? "md:order-2" : ""}`}><Image src={`/marketing/${id}.jpg`} alt="" fill sizes="(min-width: 768px) 480px, 100vw" className="object-cover" /></div>
              <div className="p-7 md:p-10">
                <h2 id={`${id}-h`} className="t-h3 text-m-ink">{name}</h2>
                <p className="mt-6 t-small text-m-muted">What to put where</p>
                <p className="mt-2 flex gap-2 text-[16px] text-m-ink2"><MapPin className="mt-1 h-4 w-4 shrink-0 text-m-accentStrong" strokeWidth={1.5} aria-hidden />{where}</p>
                <p className="mt-6 t-small text-m-muted">Topics customers can pick on the review page</p>
                <div className="mt-3 flex flex-wrap gap-2">{topics.map((t) => <Chip key={t} tone="tint" icon={<Tag className="h-3.5 w-3.5" strokeWidth={1.5} />}>{t}</Chip>)}</div>
              </div>
            </section>
          </Rise>
        ))}
        <p className="pt-4 text-center text-[13px] text-m-muted">{c.note}</p>
        <p className="text-center text-[12px] leading-relaxed text-m-muted">Pictures: <a className="underline" href="https://commons.wikimedia.org/w/index.php?curid=16489092">Beauty salon, Deccan Odyssey</a> by Simon Pielow, CC BY-SA 2.0; <a className="underline" href="https://commons.wikimedia.org/wiki/File:A_store_inside_Moazzam_Jahi_Market_in_Hyderabad.jpg">A store inside Moazzam Jahi Market, Hyderabad</a> by Mouryan, CC BY-SA 4.0; <a className="underline" href="https://commons.wikimedia.org/w/index.php?curid=150240815">Kebab &amp; Curry Indian Restaurant</a> by Chongkian, CC BY-SA 4.0. Via Wikimedia Commons.</p>
      </div>
      <FinalCTA line1={c.cta.line1} line2={c.cta.line2} />
    </>
  );
}
