import { BarChart3, Languages, Mic, Nfc, Printer, QrCode, RefreshCw, ScanLine, Sparkles } from "lucide-react";
import type { Metadata } from "next";
import { Hero } from "@/components/marketing/Hero";
import { CardOrderNote } from "@/components/marketing/PlansFromConfig";
import { Chip, MButton, MicroChip, SampleTag } from "@/components/marketing/kit";
import { CardRender, MiniCard, ReviewPageScreen } from "@/components/marketing/Mockups";
import { PhoneOrbit } from "@/components/marketing/PhoneOrbit";
import { Poster } from "@/components/marketing/Poster";
import { BentoCard, ComparisonTable, FAQ, FinalCTA, ScrollStatement, Stepper } from "@/components/marketing/Sections";
import { en } from "@/content/marketing/en";
import { pageMeta } from "@/lib/site";

const c = en.cards;
export const metadata: Metadata = pageMeta("/review-cards", c.meta.title, c.meta.description);

const ICONS = [ScanLine, RefreshCw, BarChart3, Printer];
const VISUALS = [
  <div key="a" className="relative w-[210px]"><div className="absolute -left-10 top-8 w-[150px] -rotate-6 opacity-90"><Poster /></div><div className="relative ml-10 w-[150px] rotate-3"><Poster /></div><MiniCard className="absolute -bottom-4 -right-8 w-[180px] !bg-m-navy !text-white" title="Card activated" sub="Counter card #A1042" /></div>,
  <div key="b" className="w-[280px] rounded-[18px] bg-m-surface p-4 shadow-[var(--shadow-card)]"><div className="flex justify-between"><p className="text-[13px] font-medium">Card #A1042</p><SampleTag /></div>
    <p className="mt-3 text-[11.5px] text-m-muted">Points to</p><p className="text-[13px] font-medium">Indiranagar · Review page</p>
    <p className="mt-3 rounded-[10px] bg-m-bg p-2.5 text-[11.5px] text-m-ink2">Printed code stays the same</p></div>,
  <div key="c" className="grid w-[280px] grid-cols-2 gap-2"><MiniCard icon={<QrCode className="h-3.5 w-3.5" strokeWidth={1.5} />} title="QR scans: 131" sub="This month" /><MiniCard icon={<Nfc className="h-3.5 w-3.5" strokeWidth={1.5} />} title="NFC taps: 72" sub="This month" /><MiniCard tone="tint" title="Visits: 178" sub="Reached the page" /><MiniCard tone="accent" title="To Google: 125" sub="Taps, not reviews" /><SampleTag className="col-span-2 justify-self-center" /></div>,
  <div key="d" className="w-[170px] -rotate-2"><Poster /></div>,
];

export default function ReviewCards() {
  return (
    <>
      <Hero line1={c.hero.line1} line2={c.hero.line2}
        actions={<><MButton href="/register" event="card_enquiry_submit">Order cards</MButton><MButton href="#how" variant="secondary" lead={<ScanLine className="h-4 w-4" strokeWidth={1.5} />}>How it works</MButton></>}
        center={<CardRender />} left={{ icon: <Nfc className="h-4 w-4" strokeWidth={1.5} />, text: c.hero.left }}
        chips={[<MicroChip key="a" icon={<QrCode className="h-3 w-3" strokeWidth={1.5} />}>{c.hero.chips[0]}</MicroChip>, <MicroChip key="b" icon={<RefreshCw className="h-3 w-3" strokeWidth={1.5} />}>{c.hero.chips[1]}</MicroChip>, <MicroChip key="c" icon={<ScanLine className="h-3 w-3" strokeWidth={1.5} />}>{c.hero.chips[2]}</MicroChip>]} />

      <PhoneOrbit line1={c.intro.line1} line2Pre={c.intro.line2Pre} accent={c.intro.accent} sub={c.intro.sub} screen={<ReviewPageScreen />}
        orbit={[
          { node: <MiniCard icon={<Languages className="h-3.5 w-3.5" strokeWidth={1.5} />} title="English, Hindi, Hinglish" className="w-[180px]" />, x: -320, y: -40, r: -8 },
          { node: <MiniCard icon={<Sparkles className="h-3.5 w-3.5" strokeWidth={1.5} />} title="Written from their answers" sub="Edit freely" className="w-[190px]" />, x: -260, y: 130, r: -3 },
          { node: <MiniCard tone="accent" title="Copy & continue to Google" sub="They post it themselves" className="w-[200px]" />, x: 300, y: -40, r: 7 },
          { node: <MiniCard tone="tint" icon={<Mic className="h-3.5 w-3.5" strokeWidth={1.5} />} title="Voice input" sub="Coming soon" className="w-[150px]" />, x: 280, y: 130, r: 4 },
        ]} />

      <ScrollStatement text={c.statement.text} strong={c.statement.strong} chip={<Sparkles className="h-[.6em] w-[.6em]" strokeWidth={2} />} />

      <section className="pb-24 md:pb-36">
        <div className="mkt-wrap grid gap-3 md:grid-cols-2">
          {c.bento.map(([chip, title, body], i) => { const I = ICONS[i]; return <BentoCard key={title} delay={(i % 2) * 0.1} tone={i === 0 || i === 3 ? "tint" : "white"} chip={<Chip tone={i === 0 || i === 3 ? "white" : "tint"} icon={<I className="h-3.5 w-3.5" strokeWidth={1.5} />}>{chip}</Chip>} title={title} body={body} visual={VISUALS[i]} />; })}
        </div>
      </section>

      <div id="how" className="scroll-mt-24"><Stepper title="How a card goes live" steps={c.steps.map(([title, body]) => ({ title, body }))} note={<CardOrderNote />} /></div>
      <ComparisonTable title={c.compare.title} sub={c.compare.sub} columns={c.compare.columns} rows={c.compare.rows.map(([feature, ...cells]) => ({ feature, cells }))} />
      <FAQ items={c.faq} />
      <FinalCTA line1={c.cta.line1} line2={c.cta.line2} primary="Order cards" />
    </>
  );
}
