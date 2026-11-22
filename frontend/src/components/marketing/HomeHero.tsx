import clsx from "clsx";
import { Check } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";
import { HeroActions } from "./HeroActions";
import { GoogleG, WhatsAppLogo } from "./kit";

/**
 * The home page's first screen. Cream ground with a dot grid, a left-aligned headline, one outcome line, one supporting paragraph, one strong button, and three
 * white product cards (Google profile, review reply, WhatsApp) that float beside it. One "Sample data" note covers the cards, so no card carries its own chip. The in-card Approve
 * buttons are soft, so "Start free trial" is the only strong orange button on the screen.
 *
 * Motion is CSS only (.hh-in, .hh-float in globals.css) and is switched off for reduced motion. The nav and the trial bar above are shared with every marketing page and are not part of this file.
 */

const CARD = "hh-card rounded-[22px] border border-[#0D1230]/[.06] bg-white p-[22px] text-left shadow-[0_24px_40px_-24px_rgba(13,18,48,.35)] hover:shadow-[0_34px_50px_-26px_rgba(13,18,48,.5)]";
const TITLE = "font-[family-name:var(--font-tight)] text-[18px] font-bold leading-[1.15] tracking-[-.02em] text-[#0D1230]";
const BODY = "text-[14px] leading-[1.5] text-[#4A4F6E]";
const LABEL = "text-[12px] font-semibold uppercase tracking-[.08em]";
const SOFT_BTN = "inline-flex min-h-11 shrink-0 items-center rounded-full bg-[#FFE9D3] px-5 text-[14px] font-semibold text-[#9A3412] transition-colors hover:bg-[#FFDCBB]";

function Float({ children, delay, drift, className }: { children: ReactNode; delay: number; drift: [number, number]; className?: string }) {
  const style = { "--d": `${delay}s`, "--fd": `${drift[0]}s`, "--fl": `${drift[1]}s` } as CSSProperties;
  return <div style={style} className={clsx("hh-in", className)}><div className="hh-float">{children}</div></div>;
}

function GrowthScoreCard() {
  const c = 2 * Math.PI * 30;
  return (
    <div className={CARD}>
      <div className="flex items-center gap-3">
        <GoogleG size={38} />
        <div className="min-w-0">
          <p className={TITLE}>Google Business Profile</p>
          <p className="mt-1 flex items-center gap-1.5 text-[14px] font-medium text-[#15803D]"><span aria-hidden className="h-2 w-2 rounded-full bg-[#16A34A]" />Connected</p>
        </div>
      </div>
      <div className="mt-5 flex items-center gap-4">
        <svg role="img" aria-label="Growth score 85 out of 100" width="76" height="76" viewBox="0 0 76 76" className="shrink-0">
          <circle cx="38" cy="38" r="30" fill="none" stroke="#EDE7E1" strokeWidth="8" />
          <circle cx="38" cy="38" r="30" fill="none" stroke="#16A34A" strokeWidth="8" strokeLinecap="round" strokeDasharray={`${c * 0.85} ${c}`} transform="rotate(-90 38 38)" />
          <text x="38" y="46" textAnchor="middle" fontSize="24" fontWeight="700" fill="#0D1230">85</text>
        </svg>
        <div>
          <p className={TITLE}>Growth score</p>
          <p className="mt-1 text-[14px] font-medium text-[#15803D]">Good · 2 fixes to reach 100</p>
        </div>
      </div>
    </div>
  );
}

function ReviewCard() {
  return (
    <div className={CARD}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2.5">
          <GoogleG size={30} />
          <p className={clsx(LABEL, "text-[#4A4F6E]")}>New review</p>
        </div>
        <span role="img" aria-label="Five stars" className="text-[15px] leading-none tracking-[1px] text-[#E8A317]">★★★★★</span>
      </div>
      <div className="mt-4 rounded-[14px] bg-[#FFF1E3] p-3.5">
        <p className={clsx(LABEL, "text-[#9A3412]")}>Draft reply</p>
        <p className={clsx(BODY, "mt-1.5 text-[#0D1230]")}>Thank you for visiting us. We are glad you enjoyed it.</p>
      </div>
      <div className="mt-4 flex items-center justify-between gap-3">
        <p className="text-[14px] leading-tight text-[#4A4F6E]">AI drafts. You approve.</p>
        <button type="button" className={SOFT_BTN}>Approve</button>
      </div>
    </div>
  );
}

const STEPS = ["Agent drafts the offer", "You approve", "Sent on WhatsApp"];

function WhatsAppCard() {
  return (
    <div className={CARD}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2.5">
          <WhatsAppLogo size={38} />
          <p className={TITLE}>WhatsApp automation</p>
        </div>
        <span className="rounded-full bg-[#DCF5DF] px-2.5 py-1 text-[12px] font-semibold text-[#12351A]">On</span>
      </div>
      <p className="mt-4 max-w-[92%] rounded-[16px] rounded-bl-[5px] bg-[#DCF5DF] px-3.5 py-2.5 text-[14px] leading-[1.45] text-[#12351A]">Hi Asha, 10% off all sessions this week.</p>
      <ul className="mt-4 space-y-2">
        {STEPS.map((s) => (
          <li key={s} className="flex items-center gap-2.5 text-[14px] text-[#0D1230]">
            <span aria-hidden className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-[#16A34A] text-white"><Check className="h-3 w-3" strokeWidth={3} /></span>{s}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function HomeHero({ line1, line2, outcome, sub }: { line1: string; line2: string; outcome: string; sub: string }) {
  return (
    <section className="relative isolate -mt-[76px] overflow-hidden pb-16 pt-[120px] md:pb-[104px] md:pt-[132px]">
      {/* cream ground with a dot grid, fading into the page colour at the bottom */}
      <div aria-hidden className="hh-ground absolute inset-0 -z-10" />
      <div className="mkt-wrap !max-w-[1200px] !px-6">
        <div className="flex flex-wrap items-center gap-x-12 gap-y-14">
          <div className="min-w-0 flex-[1_1_520px]">
            <p className="hh-in inline-flex min-h-9 items-center gap-2.5 rounded-full border border-[#0D1230]/[.06] bg-white px-4 text-[14px] text-[#4A4F6E] shadow-[0_1px_2px_rgba(13,18,48,.05)]" style={{ "--d": "0s" } as CSSProperties}>
              <span aria-hidden className="h-2 w-2 rounded-full bg-[#F97316]" />
              <span><b className="font-semibold text-[#0D1230]">Google profile.</b> <b className="font-semibold text-[#0D1230]">Reviews.</b> <b className="font-semibold text-[#0D1230]">WhatsApp.</b></span>
            </p>
            <h1 className="mt-6 font-[family-name:var(--font-tight)] text-[clamp(2.6rem,5vw,4.75rem)] font-medium leading-[1.06] tracking-[-.05em] text-[#0D1230] [text-wrap:balance]">
              {line1} <span className="text-[#E8590C]">{line2}</span>
            </h1>
            <p className="mt-6 max-w-[560px] font-[family-name:var(--font-tight)] text-[clamp(1.35rem,2.2vw,1.75rem)] font-medium leading-[1.25] tracking-[-.03em] text-[#0D1230]">{outcome}</p>
            <p className="mt-4 max-w-[540px] font-[family-name:var(--font-inter)] text-[18px] leading-[1.6] text-[#4A4F6E]">{sub}</p>
            <div className="mt-9"><HeroActions /></div>
          </div>

          <div className="relative min-w-0 flex-[1_1_440px]">
            <div aria-hidden className="absolute left-1/2 top-1/2 -z-10 h-[460px] w-[460px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-[#FFD9B8] opacity-70 max-sm:h-[320px] max-sm:w-[320px]" />
            <div className="grid gap-5 sm:grid-cols-2 sm:items-start">
              <div className="flex flex-col gap-5">
                <Float delay={0.1} drift={[7, 0]}><GrowthScoreCard /></Float>
                <Float delay={0.45} drift={[8.5, -2]}><WhatsAppCard /></Float>
              </div>
              <div className="flex flex-col gap-5 sm:mt-[52px]">
                <Float delay={0.25} drift={[9, -1]}><ReviewCard /></Float>
              </div>
            </div>
            <p className="mt-5 text-center text-[13px] text-[#4A4F6E]">Sample data: names and numbers on these cards are examples.</p>
          </div>
        </div>
      </div>
    </section>
  );
}
