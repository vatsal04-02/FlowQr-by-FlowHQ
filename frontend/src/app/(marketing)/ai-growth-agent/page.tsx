import { BookOpen, CheckCircle2, ClipboardList, History, ListChecks, ShieldCheck, Sparkles, XCircle } from "lucide-react";
import type { Metadata } from "next";
import { Hero } from "@/components/marketing/Hero";
import { Chip, MButton, MicroChip, SampleTag, SectionHead } from "@/components/marketing/kit";
import { MiniCard, PlanCard } from "@/components/marketing/Mockups";
import { Rise } from "@/components/marketing/motion";
import { BentoCard, FAQ, FinalCTA, ScrollStatement } from "@/components/marketing/Sections";
import { en } from "@/content/marketing/en";
import { pageMeta } from "@/lib/site";

const c = en.agent;
export const metadata: Metadata = pageMeta("/ai-growth-agent", c.meta.title, c.meta.description);

const ICONS = [ClipboardList, ListChecks, History, BookOpen];
const VISUALS = [
  <PlanCard key="a" className="rotate-[-2deg]" />,
  <div key="b" className="flex w-[280px] flex-col gap-2"><MiniCard title="Reply to Rahul K." sub="Waiting for approval" /><MiniCard title="Weekend offer post" sub="Waiting for approval" /><MiniCard tone="accent" title="Approve 2 drafts" /></div>,
  <div key="c" className="w-[290px] rounded-[18px] bg-m-surface p-4 shadow-[var(--shadow-card)]"><div className="flex justify-between"><p className="text-[13px] font-medium">Activity</p><SampleTag /></div>
    <ul className="mt-3 space-y-2 text-[12px]">
      <li className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-[#157347]" strokeWidth={1.5} aria-hidden />Reply published · Google confirmed</li>
      <li className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-[#157347]" strokeWidth={1.5} aria-hidden />Post published · Google confirmed</li>
      <li className="flex items-start gap-2"><XCircle className="mt-px h-4 w-4 shrink-0 text-[#B42318]" strokeWidth={1.5} aria-hidden /><span>Reply failed · Google rate limit<span className="block text-m-muted">The reason is shown; nothing is hidden</span></span></li>
    </ul></div>,
  <div key="d" className="w-[280px] rounded-[18px] bg-m-surface p-4 shadow-[var(--shadow-card)]"><p className="text-[13px] font-medium">Business knowledge</p>
    <dl className="mt-3 space-y-2 text-[12px]">{[["Services", "Physiotherapy, sports rehab"], ["Timings", "Mon–Sat, 9 am – 8 pm"], ["Brand voice", "Warm, short, no jargon"], ["Never say", "Cures, guarantees"]].map(([k, v]) => <div key={k} className="flex justify-between gap-3"><dt className="text-m-muted">{k}</dt><dd className="text-right">{v}</dd></div>)}</dl></div>,
];

export default function AiGrowthAgent() {
  return (
    <>
      <Hero line1={c.hero.line1} line2={c.hero.line2}
        actions={<><MButton href="/demo" event="demo_cta_click">Book a demo</MButton><MButton href="#workflow" variant="secondary" lead={<Sparkles className="h-4 w-4" strokeWidth={1.5} />}>How it works</MButton></>}
        center={<PlanCard />} left={{ icon: <ClipboardList className="h-4 w-4" strokeWidth={1.5} />, text: c.hero.left }}
        chips={[<MicroChip key="a" icon={<ClipboardList className="h-3 w-3" strokeWidth={1.5} />}>{c.hero.chips[0]}</MicroChip>, <MicroChip key="b" icon={<ShieldCheck className="h-3 w-3" strokeWidth={1.5} />}>{c.hero.chips[1]}</MicroChip>, <MicroChip key="c" icon={<History className="h-3 w-3" strokeWidth={1.5} />}>{c.hero.chips[2]}</MicroChip>]} />

      <section id="workflow" className="mkt-section scroll-mt-24">
        <div className="mkt-wrap">
          <Rise><SectionHead title="From signal to activity log" sub="Every task follows the same steps, and you can see each one." /></Rise>
          <ol className="mt-12 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {c.workflow.map(([t, b], i) => (
              <Rise as="li" key={t} delay={i * 0.05} y={16} blur={false} className={`rounded-[20px] p-5 ${i === 4 ? "bg-m-accent text-m-ink" : "bg-m-surface shadow-[var(--shadow-card)]"}`}>
                <span className="text-[12px] font-semibold tabular-nums opacity-60">{String(i + 1).padStart(2, "0")}</span>
                <p className="mt-3 text-[18px] font-medium tracking-[-.02em]">{t}</p>
                <p className={`mt-1 text-[13px] ${i === 4 ? "text-m-ink/80" : "text-m-muted"}`}>{b}</p>
              </Rise>
            ))}
          </ol>
        </div>
      </section>

      <section className="pb-24 md:pb-36">
        <div className="mkt-wrap grid gap-3 md:grid-cols-2">
          {c.bento.map(([chip, title, body], i) => { const I = ICONS[i]; return <BentoCard key={title} delay={(i % 2) * 0.1} tone={i === 0 || i === 3 ? "tint" : "white"} chip={<Chip tone={i === 0 || i === 3 ? "white" : "tint"} icon={<I className="h-3.5 w-3.5" strokeWidth={1.5} />}>{chip}</Chip>} title={title} body={body} visual={VISUALS[i]} />; })}
        </div>
      </section>

      <ScrollStatement text={c.statement.text} strong={c.statement.strong} chip={<BookOpen className="h-[.6em] w-[.6em]" strokeWidth={2} />} />
      <FAQ items={c.faq} />
      <FinalCTA line1={c.cta.line1} line2={c.cta.line2} />
    </>
  );
}
