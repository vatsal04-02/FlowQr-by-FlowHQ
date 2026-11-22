import clsx from "clsx";
import { Check } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";
import { HeroActions } from "./HeroActions";
import { GoogleG, SampleTag, WhatsAppLogo } from "./kit";

/**
 * The home page's first screen. Cream ground with a dot grid, a left-aligned headline, one outcome line, one supporting paragraph, one strong button, and four
 * white product cards (Google profile + growth score, review reply, WhatsApp automation, WhatsApp offer) that float beside it. The type is kept small enough that the whole
 * screen fits in one laptop window. The in-card Approve buttons are soft, so "Start free trial" is the only strong orange button on the screen.
 *
 * Motion is CSS only (.hh-in, .hh-float in globals.css) and is switched off for reduced motion. The nav and the trial bar above are shared with every marketing page and are not part of this file.
 */

const CARD = "hh-card rounded-[20px] border border-[#0D1230]/[.06] bg-white p-[18px] text-left shadow-[0_24px_40px_-24px_rgba(13,18,48,.35)] hover:shadow-[0_34px_50px_-26px_rgba(13,18,48,.5)]";
const TITLE = "font-[family-name:var(--font-tight)] text-[15px] font-bold leading-[1.15] tracking-[-.02em] text-[#0D1230]";
const BODY = "text-[13px] leading-[1.45] text-[#4A4F6E]";
const LABEL = "text-[11px] font-semibold uppercase tracking-[.08em]";
const SOFT_BTN = "inline-flex min-h-11 shrink-0 items-center rounded-full bg-[#FFE9D3] px-4 text-[13px] font-semibold text-[#9A3412] transition-colors hover:bg-[#FFDCBB]";

function Float({ children, delay, drift }: { children: ReactNode; delay: number; drift: [number, number] }) {
  const style = { "--d": `${delay}s`, "--fd": `${drift[0]}s`, "--fl": `${drift[1]}s` } as CSSProperties;
  return <div style={style} className="hh-in"><div className="hh-float">{children}</div></div>;
}

function GrowthScoreCard() {
  const c = 2 * Math.PI * 24;
  return (
    <div className={CARD}>
      <div className="flex items-center gap-2.5">
        <GoogleG size={30} />
        <div className="min-w-0">
          <p className={TITLE}>Google Business Profile</p>
          <p className="mt-0.5 flex items-center gap-1.5 text-[12px] font-medium text-[#15803D]"><span aria-hidden className="h-1.5 w-1.5 rounded-full bg-[#16A34A]" />Connected</p>
        </div>
      </div>
      <div className="mt-4 flex items-center gap-3">
        <svg role="img" aria-label="Growth score 85 out of 100" width="60" height="60" viewBox="0 0 60 60" className="shrink-0">
          <circle cx="30" cy="30" r="24" fill="none" stroke="#EDE7E1" strokeWidth="7" />
          <circle cx="30" cy="30" r="24" fill="none" stroke="#16A34A" strokeWidth="7" strokeLinecap="round" strokeDasharray={`${c * 0.85} ${c}`} transform="rotate(-90 30 30)" />
          <text x="30" y="37" textAnchor="middle" fontSize="20" fontWeight="700" fill="#0D1230">85</text>
        </svg>
        <div>
          <p className={TITLE}>Growth score</p>
          <p className="mt-0.5 text-[12px] font-medium text-[#15803D]">Good · 2 fixes to reach 100</p>
        </div>
      </div>
      <p className={clsx(BODY, "mt-3")}>One score for reviews, replies and your profile.</p>
      <SampleTag className="mt-2.5" />
    </div>
  );
}

function ReviewCard() {
  return (
    <div className={CARD}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <GoogleG size={26} />
          <p className={clsx(LABEL, "text-[#4A4F6E]")}>New review</p>
        </div>
        <span role="img" aria-label="Five stars" className="text-[13px] leading-none tracking-[1px] text-[#E8A317]">★★★★★</span>
      </div>
      <div className="mt-3 rounded-[12px] bg-[#FFF1E3] p-3">
        <p className={clsx(LABEL, "text-[#9A3412]")}>Draft reply</p>
        <p className={clsx(BODY, "mt-1 text-[#0D1230]")}>Thank you for visiting us. We are glad you enjoyed it.</p>
      </div>
      <div className="mt-3 flex items-center justify-between gap-3">
        <p className="text-[12.5px] leading-tight text-[#4A4F6E]">AI drafts. You approve.</p>
        <button type="button" className={SOFT_BTN}>Approve</button>
      </div>
    </div>
  );
}

const STEPS: [string, string][] = [["Agent drafts the offer", "Written for your customers"], ["You approve", "Nothing sends before this"], ["Sent on WhatsApp", "Straight to your customers"]];

function WhatsAppAutomationCard() {
  return (
    <div className={CARD}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <WhatsAppLogo size={30} />
          <p className={TITLE}>WhatsApp automation</p>
        </div>
        <span className="rounded-full bg-[#DCF5DF] px-2 py-0.5 text-[11px] font-semibold text-[#12351A]">On</span>
      </div>
      <ul className="mt-3.5 space-y-2.5">
        {STEPS.map(([s, d]) => (
          <li key={s} className="flex items-start gap-2.5">
            <span aria-hidden className="mt-px grid h-[18px] w-[18px] shrink-0 place-items-center rounded-full bg-[#16A34A] text-white"><Check className="h-2.5 w-2.5" strokeWidth={3.5} /></span>
            <span className="text-[13px] font-medium leading-tight text-[#0D1230]">{s}<span className="mt-0.5 block text-[12px] font-normal text-[#4A4F6E]">{d}</span></span>
          </li>
        ))}
      </ul>
      <SampleTag className="mt-3" />
    </div>
  );
}

function WhatsAppOfferCard() {
  return (
    <div className={CARD}>
      <div className="flex items-center gap-2">
        <WhatsAppLogo size={26} />
        <p className={TITLE}>WhatsApp offer</p>
      </div>
      <SampleTag className="mt-2" />
      <p className="mt-2.5 max-w-[94%] rounded-[14px] rounded-bl-[4px] bg-[#DCF5DF] px-3 py-2 text-[13px] leading-[1.4] text-[#12351A]">Hi Asha, 10% off all sessions this week.</p>
      <div className="mt-3 flex items-center justify-between gap-3">
        <p className="text-[12.5px] leading-tight text-[#4A4F6E]">You approve before it sends.</p>
        <button type="button" className={SOFT_BTN}>Approve</button>
      </div>
    </div>
  );
}

export function HomeHero({ line1, line2, outcome, sub }: { line1: string; line2: string; outcome: string; sub: string }) {
  return (
    <section className="relative isolate -mt-[76px] overflow-hidden pb-14 pt-[104px] md:pb-20 md:pt-[112px]">
      {/* cream ground with a dot grid, fading into the page colour at the bottom */}
      <div aria-hidden className="hh-ground absolute inset-0 -z-10" />
      <div className="mkt-wrap !max-w-[1200px] !px-6">
        <div className="flex flex-wrap items-center gap-x-12 gap-y-12">
          <div className="min-w-0 flex-[1_1_480px]">
            <p className="hh-in inline-flex min-h-8 items-center gap-2 rounded-full border border-[#0D1230]/[.06] bg-white px-3.5 text-[13px] text-[#4A4F6E] shadow-[0_1px_2px_rgba(13,18,48,.05)]" style={{ "--d": "0s" } as CSSProperties}>
              <span aria-hidden className="h-2 w-2 rounded-full bg-[#F97316]" />
              <span><b className="font-semibold text-[#0D1230]">Google profile.</b> <b className="font-semibold text-[#0D1230]">Reviews.</b> <b className="font-semibold text-[#0D1230]">WhatsApp.</b></span>
            </p>
            <h1 className="mt-8 font-[family-name:var(--font-tight)] text-[clamp(2rem,3.5vw,3.25rem)] font-medium leading-[1.12] tracking-[-.045em] text-[#0D1230] [text-wrap:balance]">
              {line1} <span className="text-[#E8590C]">{line2}</span>
            </h1>
            <p className="mt-9 max-w-[480px] font-[family-name:var(--font-tight)] text-[clamp(1.1rem,1.5vw,1.3rem)] font-medium leading-[1.4] tracking-[-.025em] text-[#0D1230]">{outcome}</p>
            <p className="mt-5 max-w-[470px] font-[family-name:var(--font-inter)] text-[15.5px] leading-[1.7] text-[#4A4F6E]">{sub}</p>
            <div className="mt-10"><HeroActions /></div>
          </div>

          <div className="relative min-w-0 flex-[1_1_440px]">
            <div aria-hidden className="absolute left-1/2 top-1/2 -z-10 h-[420px] w-[420px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-[#FFD9B8] opacity-70 max-sm:h-[300px] max-sm:w-[300px]" />
            <div className="grid gap-4 sm:grid-cols-2 sm:items-start">
              <div className="flex flex-col gap-4">
                <Float delay={0.1} drift={[7, 0]}><GrowthScoreCard /></Float>
                <Float delay={0.45} drift={[8.5, -2]}><WhatsAppAutomationCard /></Float>
              </div>
              <div className="flex flex-col gap-4 sm:mt-[52px]">
                <Float delay={0.25} drift={[9, -1]}><ReviewCard /></Float>
                <Float delay={0.6} drift={[7.5, -3]}><WhatsAppOfferCard /></Float>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
