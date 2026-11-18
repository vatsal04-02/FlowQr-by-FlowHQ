import clsx from "clsx";
import type { CSSProperties, ReactNode } from "react";
import { GoogleG, SampleTag } from "./kit";

/**
 * The cards that float around the home hero. Each one is a small, real-looking piece of the product (a Google profile, a drafted reply with its Approve button, the Growth score,
 * a local-rank grid, a Google post, the customer-actions chart), drawn differently on purpose: different widths, one navy card among the white ones, no repeated icon-in-a-square.
 * Each carries one plain sentence on what the feature does.
 *
 * Motion is CSS only (.fc-in / .fc-float in globals.css), so the server and the browser draw the same markup: on load the cards start stacked behind the headline and are dealt out to
 * their places one after another, then each drifts up and down slowly. Under reduced motion they sit still.
 *
 * From 1280px wide they sit in the empty space either side of the headline. Below that there is no space beside it, so only the first two are shown, one a little to the left and one
 * a little to the right, under the buttons. Every number on a card is sample data and says so.
 */

const FACE = "rounded-[16px] shadow-[0_0_0_1px_rgba(11,15,46,.06),0_1px_2px_rgba(11,15,46,.05),0_24px_48px_-20px_rgba(11,15,46,.30)]";
const LABEL = "text-[13px] font-medium leading-tight tracking-[-.01em]";
const CAPTION = "text-[12px] leading-snug text-m-muted sm:text-[12.5px]";

function GoogleCard() {
  return (
    <div className={clsx(FACE, "bg-m-navy p-3.5 text-left")}>
      <div className="flex items-center gap-3">
        <GoogleG size={36} />
        <div className="min-w-0">
          <p className={clsx(LABEL, "text-[13.5px] text-white")}>Google Business Profile</p>
          <p className="mt-1 flex items-center gap-1.5 text-[11.5px] text-white/65"><span aria-hidden className="h-1.5 w-1.5 rounded-full bg-[#4FD18B]" />Connected</p>
        </div>
      </div>
      <p className="mt-3 text-[12px] leading-snug text-white/75 sm:text-[12.5px]">Connect once. Your reviews, posts and profile details sit in one place.</p>
    </div>
  );
}

export function ReplyCard() {
  return (
    <div className={clsx(FACE, "bg-white p-3.5 text-left")}>
      <div className="flex items-center justify-between">
        <p className="text-[11px] font-semibold uppercase tracking-[.06em] text-m-muted">New review</p>
        <span aria-label="Five stars" className="text-[12px] leading-none tracking-[1px] text-[#E8B04A]">★★★★★</span>
      </div>
      <div className="mt-2 rounded-[10px] bg-[#F7F5F2] p-2.5">
        <p className="text-[10.5px] font-semibold uppercase tracking-[.05em] text-m-accentStrong">Draft reply</p>
        <p className="mt-1 text-[12px] leading-snug text-m-ink2">Thank you for visiting us. We are glad you enjoyed it.</p>
      </div>
      <div className="mt-2.5 flex items-center justify-between gap-2">
        <p className="text-[11.5px] leading-tight text-m-muted">AI drafts. You approve.</p>
        <span className="shrink-0 rounded-full bg-m-accent px-3 py-1 text-[11.5px] font-medium text-m-ink">Approve</span>
      </div>
    </div>
  );
}

export function GrowthCard() {
  const c = 2 * Math.PI * 22;
  return (
    <div className={clsx(FACE, "bg-white p-3.5 text-left")}>
      <div className="flex items-center gap-3">
        <svg aria-hidden width="56" height="56" viewBox="0 0 56 56" className="shrink-0">
          <circle cx="28" cy="28" r="22" fill="none" stroke="#EAE6E0" strokeWidth="6" />
          <circle cx="28" cy="28" r="22" fill="none" stroke="#157347" strokeWidth="6" strokeLinecap="round" strokeDasharray={`${c * 0.85} ${c}`} transform="rotate(-90 28 28)" />
          <text x="28" y="34" textAnchor="middle" fontSize="18" fontWeight="600" fill="#0B0F2E">85</text>
        </svg>
        <div className="min-w-0">
          <p className={clsx(LABEL, "text-m-ink")}>Growth score</p>
          <p className="mt-1 text-[12px] leading-tight text-[#157347]">Good · 2 fixes to reach 100</p>
        </div>
      </div>
      <p className={clsx(CAPTION, "mt-2.5")}>One score for reviews, replies and your profile.</p>
      <SampleTag className="mt-2" />
    </div>
  );
}

// Ranks for a 3 x 3 grid of points around the business: green is the top three, amber is further down.
const RANKS = [2, 1, 2, 3, 2, 3, 4, 3, 6];
function RankCard() {
  return (
    <div className={clsx(FACE, "bg-white p-3.5 text-left")}>
      <div className="flex items-center justify-between gap-2">
        <p className={clsx(LABEL, "text-m-ink")}>Local rankings</p>
        <SampleTag className="shrink-0 whitespace-nowrap" />
      </div>
      <div aria-hidden className="mt-2.5 grid grid-cols-3 gap-x-1 gap-y-1 rounded-[10px] bg-[#EDEFE8] p-2" style={{ backgroundImage: "linear-gradient(rgba(11,15,46,.05) 1px, transparent 1px), linear-gradient(90deg, rgba(11,15,46,.05) 1px, transparent 1px)", backgroundSize: "18px 18px" }}>
        {RANKS.map((r, i) => (
          <span key={i} className={clsx("mx-auto grid h-6 w-6 place-items-center rounded-full text-[11px] font-semibold shadow-[0_1px_2px_rgba(11,15,46,.15)]", r <= 3 ? "bg-[#157347] text-white" : "bg-[#E8B04A] text-m-ink")}>{r}</span>
        ))}
      </div>
      <p className={clsx(CAPTION, "mt-2.5")}>See where you show up in Google Maps for the words you choose.</p>
    </div>
  );
}

function PostCard() {
  return (
    <div className={clsx(FACE, "bg-white p-3 text-left")}>
      <div className="relative h-[74px] overflow-hidden rounded-[10px] bg-gradient-to-br from-m-tint2 via-m-accent300 to-m-accent">
        <span aria-hidden className="absolute -right-5 -top-6 h-20 w-20 rounded-full bg-white/30" />
        <span aria-hidden className="absolute -right-1 bottom-[-30px] h-16 w-16 rounded-full bg-white/25" />
        <p className="absolute bottom-2 left-3 text-[15px] font-semibold tracking-[-.02em] text-m-ink">Diwali offer</p>
      </div>
      <div className="mt-2.5 flex items-start justify-between gap-2">
        <p className={clsx(CAPTION, "min-w-0")}>Write and schedule posts for your offers and events.</p>
        <span className="mt-px shrink-0 rounded-full bg-m-ink/[.06] px-2 py-0.5 text-[11px] font-medium text-m-ink2">Scheduled</span>
      </div>
    </div>
  );
}

function ActionsCard() {
  const calls = "0,26 10,25 20,27 30,22 40,24 50,19 60,23 70,20 80,24 90,21 100,23 110,19 120,22";
  const dirs = "0,18 10,15 20,17 30,9 40,14 50,6 60,13 70,8 80,12 90,7 100,11 110,6 120,9";
  const web = "0,23 10,22 20,23 30,18 40,21 50,15 60,20 70,16 80,19 90,15 100,18 110,14 120,17";
  return (
    <div className={clsx(FACE, "bg-white p-3.5 text-left")}>
      <div className="flex items-center justify-between gap-2">
        <p className={clsx(LABEL, "text-m-ink")}>Customer actions</p>
        <SampleTag className="shrink-0 whitespace-nowrap" />
      </div>
      <svg aria-hidden viewBox="0 0 120 32" preserveAspectRatio="none" className="mt-2.5 h-[52px] w-full overflow-visible">
        <path d="M0 31.5H120" stroke="#EAE6E0" strokeWidth="1" vectorEffect="non-scaling-stroke" />
        <polyline points={dirs} fill="none" stroke="#2457D6" strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
        <polyline points={web} fill="none" stroke="#E8B04A" strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
        <polyline points={calls} fill="none" stroke="#0F8F86" strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
      </svg>
      <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-m-ink2">
        <li className="flex items-center gap-1.5"><span aria-hidden className="h-1.5 w-1.5 rounded-full bg-[#0F8F86]" />Calls</li>
        <li className="flex items-center gap-1.5"><span aria-hidden className="h-1.5 w-1.5 rounded-full bg-[#2457D6]" />Directions</li>
        <li className="flex items-center gap-1.5"><span aria-hidden className="h-1.5 w-1.5 rounded-full bg-[#E8B04A]" />Website clicks</li>
      </ul>
      <p className={clsx(CAPTION, "mt-2")}>Counted the way Google reports them.</p>
    </div>
  );
}

type Card = {
  id: string; node: ReactNode; side: "l" | "r"; top: number; inset: string; width: string;
  /** where the card starts when it is dealt out: sideways toward the middle, up or down to the headline's height, and how far turned */
  from: [string, string, string];
  delay: number; drift: [number, number, number];
  /** shown below 1280px as well, or only beside the headline */
  small?: boolean;
};

const CARDS: Card[] = [
  { id: "google", node: <GoogleCard />, side: "l", top: 100, inset: "clamp(16px,2.2vw,44px)", width: "clamp(222px,17.2vw,262px)", from: ["34vw", "150px", "-14deg"], delay: 0.55, drift: [7, 0, 0.5], small: true },
  { id: "replies", node: <ReplyCard />, side: "r", top: 112, inset: "clamp(16px,2.2vw,44px)", width: "clamp(224px,17.4vw,264px)", from: ["-34vw", "120px", "13deg"], delay: 0.7, drift: [8, -1.5, -0.6], small: true },
  { id: "growth", node: <GrowthCard />, side: "l", top: 268, inset: "clamp(48px,5.6vw,100px)", width: "clamp(206px,15.6vw,236px)", from: ["30vw", "-10px", "9deg"], delay: 0.85, drift: [6.5, -2.5, 0.7] },
  { id: "rank", node: <RankCard />, side: "r", top: 290, inset: "clamp(60px,6.6vw,116px)", width: "clamp(206px,15.4vw,226px)", from: ["-30vw", "-30px", "-10deg"], delay: 1.0, drift: [7.5, 2, -0.5] },
  { id: "posts", node: <PostCard />, side: "l", top: 458, inset: "clamp(16px,2.2vw,44px)", width: "clamp(214px,16.4vw,248px)", from: ["34vw", "-170px", "-12deg"], delay: 1.15, drift: [8.5, 0, 0.4] },
  { id: "actions", node: <ActionsCard />, side: "r", top: 534, inset: "clamp(20px,2.6vw,52px)", width: "clamp(224px,17.2vw,260px)", from: ["-34vw", "-200px", "12deg"], delay: 1.3, drift: [7, -2, 0.6] },
];

export function HeroFloaters() {
  return (
    <ul aria-label="What FlowQR does" className="relative mx-auto mt-9 flex max-w-[380px] list-none flex-col gap-3 px-4 xl:pointer-events-none xl:absolute xl:inset-0 xl:z-0 xl:mx-0 xl:mt-0 xl:block xl:max-w-none xl:p-0">
      {CARDS.map((c) => {
        const style = { "--xt": `${c.top}px`, "--xs": c.inset, "--xw": c.width, "--xsx": c.from[0], "--xsy": c.from[1], "--xsr": c.from[2], "--d": `${c.delay}s`, "--fd": `${c.drift[0]}s`, "--fl": `${c.drift[1]}s`, "--fr": `${c.drift[2]}deg` } as CSSProperties;
        return (
          <li key={c.id} style={style}
            className={clsx("fc-in min-w-0 max-xl:w-[90%] max-xl:odd:self-start max-xl:even:self-end xl:absolute xl:top-[var(--xt)] xl:w-[var(--xw)]", c.side === "l" ? "xl:left-[var(--xs)]" : "xl:right-[var(--xs)]", !c.small && "hidden xl:block")}>
            <div className="fc-float h-full">{c.node}</div>
          </li>
        );
      })}
    </ul>
  );
}
