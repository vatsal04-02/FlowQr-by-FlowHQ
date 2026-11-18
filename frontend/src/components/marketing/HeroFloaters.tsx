import clsx from "clsx";
import { CalendarCheck, MapPin, Star } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";
import { GoogleG, SampleTag } from "./kit";

/**
 * The cards that float around the home hero. Each one is a small piece of the real product with one plain sentence on what it does:
 * Google profile, review replies, Growth score, local rankings, Google posts, customer actions.
 *
 * Motion is CSS only (see .fc-in / .fc-float in globals.css), so the server and the browser draw the same markup: on load the cards start stacked behind the headline and
 * are dealt out to their places one after another, then each drifts up and down slowly. Under reduced motion they just sit still.
 *
 * From 1280px wide they sit in the empty space either side of the headline. Below that there is no space beside it, so the first four become a tidy two-column
 * grid under the buttons (the phone's first screen is still the heading and the two buttons). Every number on a card is sample data and says so.
 */

function Ring({ value }: { value: number }) {
  const c = 2 * Math.PI * 15;
  return (
    <svg aria-hidden width="40" height="40" viewBox="0 0 40 40" className="shrink-0">
      <circle cx="20" cy="20" r="15" fill="none" stroke="#EAE6E0" strokeWidth="4.5" />
      <circle cx="20" cy="20" r="15" fill="none" stroke="#157347" strokeWidth="4.5" strokeLinecap="round" strokeDasharray={`${(c * value) / 100} ${c}`} transform="rotate(-90 20 20)" />
      <text x="20" y="24.2" textAnchor="middle" fontSize="12" fontWeight="600" fill="#0B0F2E">{value}</text>
    </svg>
  );
}

function Spark() {
  return (
    <svg aria-hidden viewBox="0 0 120 30" preserveAspectRatio="none" className="mt-2 h-7 w-full">
      <defs><linearGradient id="fc-spark" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#2457D6" stopOpacity=".28" /><stop offset="1" stopColor="#2457D6" stopOpacity="0" /></linearGradient></defs>
      <path d="M0 24 L8 22 L16 25 L24 14 L32 20 L40 9 L48 17 L56 12 L64 21 L72 8 L80 15 L88 11 L96 18 L104 13 L112 16 L120 10 L120 30 L0 30 Z" fill="url(#fc-spark)" />
      <path d="M0 24 L8 22 L16 25 L24 14 L32 20 L40 9 L48 17 L56 12 L64 21 L72 8 L80 15 L88 11 L96 18 L104 13 L112 16 L120 10" fill="none" stroke="#2457D6" strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

const Tile = ({ children }: { children: ReactNode }) => <span aria-hidden className="grid h-8 w-8 shrink-0 place-items-center rounded-[10px] bg-m-tint text-m-accentStrong">{children}</span>;

function Bars() {
  return (
    <span aria-hidden className="grid h-8 w-8 shrink-0 place-items-center rounded-[10px] bg-m-tint text-m-accentStrong">
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M3 13V8M8 13V3M13 13V6" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" /></svg>
    </span>
  );
}

type Card = {
  id: string; title: string; text: string; icon: ReactNode; extra?: ReactNode; below?: ReactNode; sample?: boolean;
  side: "l" | "r"; top: number; inset: string;
  /** where the card starts when it is dealt out: sideways toward the middle, up or down to the headline's height, and how far turned */
  from: [string, string, string];
  delay: number; drift: [number, number, number];
  /** shown below 1280px (the grid) as well, or only beside the headline */
  small?: boolean;
};

const CARDS: Card[] = [
  { id: "google", title: "Google Business Profile", text: "Connect once. Your reviews, posts and profile details sit in one place.", icon: <GoogleG size={32} />,
    extra: <span className="inline-flex items-center gap-1.5 text-[11px] font-medium text-[#157347]"><span aria-hidden className="h-1.5 w-1.5 rounded-full bg-[#157347]" />Connected</span>,
    side: "l", top: 104, inset: "clamp(16px,2.2vw,44px)", from: ["34vw", "150px", "-14deg"], delay: 0.55, drift: [7, 0, 0.5], small: true },
  { id: "replies", title: "Review replies", text: "AI drafts the reply in your voice. You read it and approve it.", icon: <Tile><Star className="h-4 w-4" strokeWidth={1.75} /></Tile>,
    extra: <span aria-label="Five stars" className="text-[13px] leading-none tracking-[1px] text-[#E8B04A]">★★★★★</span>,
    side: "r", top: 132, inset: "clamp(16px,2.2vw,44px)", from: ["-34vw", "120px", "13deg"], delay: 0.7, drift: [8, -1.5, -0.6], small: true },
  { id: "growth", title: "Growth score", text: "One score for reviews, replies and your profile, with the fixes that raise it.", icon: <Ring value={85} />, sample: true,
    side: "l", top: 262, inset: "clamp(56px,6.4vw,112px)", from: ["30vw", "-10px", "9deg"], delay: 0.85, drift: [6.5, -2.5, 0.7], small: true },
  { id: "rank", title: "Local rankings", text: "See where you show up in Google Maps for the words you choose.", icon: <Tile><MapPin className="h-4 w-4" strokeWidth={1.75} /></Tile>,
    extra: <span className="rounded-full bg-m-tint px-2 py-0.5 text-[11px] font-semibold text-m-accentStrong">Rank 2</span>, sample: true,
    side: "r", top: 288, inset: "clamp(48px,5.6vw,100px)", from: ["-30vw", "-30px", "-10deg"], delay: 1.0, drift: [7.5, 2, -0.5], small: true },
  { id: "posts", title: "Google posts", text: "Write and schedule posts for your offers and events.", icon: <Tile><CalendarCheck className="h-4 w-4" strokeWidth={1.75} /></Tile>,
    extra: <span className="rounded-full bg-m-ink/[.06] px-2 py-0.5 text-[11px] font-medium text-m-ink2">Scheduled</span>,
    side: "l", top: 468, inset: "clamp(16px,2.2vw,44px)", from: ["34vw", "-170px", "-12deg"], delay: 1.15, drift: [8.5, 0, 0.4] },
  { id: "actions", title: "Customer actions", text: "Calls, directions and website clicks, as Google reports them.", icon: <Bars />, below: <Spark />, sample: true,
    side: "r", top: 462, inset: "clamp(24px,3vw,60px)", from: ["-34vw", "-200px", "12deg"], delay: 1.3, drift: [7, -2, 0.6] },
];

export function HeroFloaters() {
  return (
    <ul aria-label="What FlowQR does" className="relative mx-auto mt-9 grid max-w-[520px] list-none grid-cols-2 gap-3 px-4 sm:gap-4 xl:pointer-events-none xl:absolute xl:inset-0 xl:z-0 xl:mx-0 xl:mt-0 xl:block xl:max-w-none xl:p-0">
      {CARDS.map((c) => {
        const style = { "--xt": `${c.top}px`, "--xs": c.inset, "--xsx": c.from[0], "--xsy": c.from[1], "--xsr": c.from[2], "--d": `${c.delay}s`, "--fd": `${c.drift[0]}s`, "--fl": `${c.drift[1]}s`, "--fr": `${c.drift[2]}deg` } as CSSProperties;
        return (
          <li key={c.id} style={style}
            className={clsx("fc-in min-w-0 xl:absolute xl:top-[var(--xt)] xl:w-[clamp(206px,16.4vw,246px)]", c.side === "l" ? "xl:left-[var(--xs)]" : "xl:right-[var(--xs)]", !c.small && "hidden xl:block")}>
            <div className="fc-float h-full">
              <div className="h-full rounded-[18px] border border-white/90 bg-white/[.88] p-3 text-left shadow-[0_22px_48px_-22px_rgba(11,15,46,.30),0_2px_6px_rgba(11,15,46,.05)] backdrop-blur-md sm:p-3.5">
                <div className="flex items-center gap-2.5">
                  {c.icon}
                  <p className="min-w-0 flex-1 text-[13px] font-medium leading-tight tracking-[-.01em] text-m-ink">{c.title}</p>
                </div>
                {c.below}
                <p className="mt-2 text-[12px] leading-snug text-m-muted sm:text-[12.5px]">{c.text}</p>
                {(c.extra || c.sample) && <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1.5">{c.extra}{c.sample && <SampleTag />}</div>}
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
