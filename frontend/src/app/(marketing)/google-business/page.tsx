import { BadgeCheck, CalendarCheck, Image as ImageIcon, Inbox, MapPin, MessageSquareReply, ShieldCheck, Sparkles, Store } from "lucide-react";
import type { Metadata } from "next";
import { Hero } from "@/components/marketing/Hero";
import { Chip, MButton, MicroChip, SampleTag, SectionHead } from "@/components/marketing/kit";
import { InboxCard, MiniCard, PlanCard } from "@/components/marketing/Mockups";
import { Rise } from "@/components/marketing/motion";
import { BentoCard, FAQ, FinalCTA, ScrollStatement, Stepper } from "@/components/marketing/Sections";
import { en } from "@/content/marketing/en";
import { pageMeta } from "@/lib/site";

const c = en.google;
export const metadata: Metadata = pageMeta("/google-business", c.meta.title, c.meta.description);

const ICONS = [Inbox, Sparkles, CalendarCheck, ImageIcon];
const VISUALS = [
  <InboxCard key="a" className="rotate-[-2deg]" />,
  <div key="b" className="w-[290px] rounded-[18px] bg-m-surface p-4 shadow-[var(--shadow-card)]"><div className="flex justify-between"><p className="text-[13px] font-medium">Reply</p><SampleTag /></div>
    <ol className="mt-4 flex items-center gap-2 text-[11.5px] font-medium">{["Draft", "Approved", "Published"].map((t, i) => <li key={t} className="flex items-center gap-1.5"><span className={`grid h-5 w-5 place-items-center rounded-full text-[10px] ${i < 2 ? "bg-[#157347] text-white" : "bg-m-accent text-m-ink"}`}>{i < 2 ? "✓" : 3}</span>{t}{i < 2 && <span className="h-px w-4 bg-m-line" />}</li>)}</ol>
    <p className="mt-4 rounded-[12px] bg-m-bg p-3 text-[12px] leading-snug">Thank you, Rahul. We&rsquo;re sorry about the wait and have added an evening slot so visits run on time.</p>
    <p className="mt-2 text-[11px] text-[#157347]">Marked replied after Google confirmed</p></div>,
  <div key="c" className="w-[280px] rounded-[18px] bg-m-surface p-4 shadow-[var(--shadow-card)]"><div className="flex justify-between"><p className="text-[13px] font-medium">New Google post</p><SampleTag /></div>
    <p className="mt-3 rounded-[12px] border border-m-line p-3 text-[12px] leading-snug">Evening slots now open on weekdays. Call or book online.</p>
    <div className="mt-3 flex items-center justify-between text-[11.5px] text-m-muted"><span>Fri, 6:00 pm</span><span className="rounded-full bg-m-tint px-2 py-0.5 font-medium text-m-accentStrong">Waiting for approval</span></div></div>,
  <div key="d" className="w-[280px] rounded-[18px] bg-m-surface p-4 shadow-[var(--shadow-card)]"><div className="flex justify-between"><p className="text-[13px] font-medium">Photos · Indiranagar</p><SampleTag /></div>
    <div className="mt-3 grid grid-cols-3 gap-2">{["#EDE4D9", "#E2DBD0", "#F1E9DF", "#E6DED3", "#EFE6DC", "#DDD5CA"].map((b, i) => <span key={i} className="aspect-square rounded-lg" style={{ background: b }} />)}</div></div>,
];

export default function GoogleBusiness() {
  return (
    <>
      <Hero line1={c.hero.line1} line2={c.hero.line2}
        actions={<><MButton href="/demo" event="demo_cta_click">Book a demo</MButton><MButton href="#connect" variant="secondary" lead={<Store className="h-4 w-4" strokeWidth={1.5} />}>How connecting works</MButton></>}
        center={<InboxCard />} left={{ icon: <Store className="h-4 w-4" strokeWidth={1.5} />, text: c.hero.left }}
        chips={[<MicroChip key="a" icon={<ShieldCheck className="h-3 w-3" strokeWidth={1.5} />}>{c.hero.chips[0]}</MicroChip>, <MicroChip key="b" icon={<BadgeCheck className="h-3 w-3" strokeWidth={1.5} />}>{c.hero.chips[1]}</MicroChip>, <MicroChip key="c" icon={<MapPin className="h-3 w-3" strokeWidth={1.5} />}>{c.hero.chips[2]}</MicroChip>]} />

      <section className="pb-24 md:pb-36">
        <div className="mkt-wrap grid gap-3 md:grid-cols-2">
          {c.bento.map(([chip, title, body], i) => { const I = ICONS[i]; return <BentoCard key={title} delay={(i % 2) * 0.1} tone={i === 0 || i === 3 ? "tint" : "white"} chip={<Chip tone={i === 0 || i === 3 ? "white" : "tint"} icon={<I className="h-3.5 w-3.5" strokeWidth={1.5} />}>{chip}</Chip>} title={title} body={body} visual={VISUALS[i]} />; })}
        </div>
      </section>

      <ScrollStatement text={c.statement.text} strong={c.statement.strong} chip={<MessageSquareReply className="h-[.6em] w-[.6em]" strokeWidth={2} />} />

      <div id="connect" className="scroll-mt-24"><Stepper title="How connecting works" steps={c.steps.map(([title, body]) => ({ title, body }))} note={c.stepsNote} /></div>

      <section className="pb-24 md:pb-36">
        <div className="mkt-wrap">
          <Rise><SectionHead title="Insights you can act on" sub="Searches, calls, direction requests and website clicks from Google, next to your reviews and your daily plan." /></Rise>
          <div className="mt-12 grid items-center gap-6 md:grid-cols-[1.4fr_1fr]">
            <Rise className="mkt-card p-6">
              <div className="flex items-center justify-between"><p className="text-[13px] font-medium">How customers found you</p><SampleTag /></div>
              <div className="mt-6 flex h-[180px] items-end gap-2">{[6, 8, 7, 10, 9, 12, 11, 14, 13, 16, 15, 18].map((b, i) => <span key={i} className="flex flex-1 flex-col justify-end overflow-hidden rounded-t-[3px]" style={{ height: `${b * 5.2}%` }}><span className="bg-m-tint2" style={{ height: "45%" }} /><span className="flex-1 bg-m-accent" /></span>)}</div>
              <div className="mt-4 flex gap-4 text-[12px] text-m-muted"><span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-sm bg-m-accent" />Search</span><span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-sm bg-m-tint2" />Maps</span></div>
            </Rise>
            <div className="flex flex-col items-center gap-3"><PlanCard /><MiniCard icon={<CalendarCheck className="h-3.5 w-3.5" strokeWidth={1.5} />} title="Post scheduled for Friday" sub="Waiting for your approval" className="w-[290px]" /></div>
          </div>
        </div>
      </section>

      <FAQ items={c.faq} />
      <FinalCTA line1={c.cta.line1} line2={c.cta.line2} />
    </>
  );
}
