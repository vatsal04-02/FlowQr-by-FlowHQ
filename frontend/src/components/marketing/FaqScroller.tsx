"use client";
import type { CSSProperties, ReactNode } from "react";
import { useState } from "react";
import { Rise } from "./motion";

/**
 * The home page's FAQ as two rows of cards that drift past in opposite directions (adapted from the supplied "habit FAQ scroller": FaqCard, HorizontalScroller, FaqSection). The
 * questions and answers are the page's own (content/marketing/en.ts), nothing added.
 *
 * Reading comes first, so: hovering a row pauses it, there is a Pause button, and under reduced motion nothing moves at all: the cards simply wrap into a grid. Only the first copy of a row is
 * for screen readers and the keyboard; the extra copies that make the loop seamless are aria-hidden and inert. Markup is the same on the server and in the browser (CSS `motion-reduce:` does the rest).
 */

/** White cards with one small accent: a thin orange top edge. */
function FaqCard({ question, answer }: { question: string; answer: ReactNode }) {
  return (
    <li className="flex w-[286px] shrink-0 flex-col gap-3 rounded-[18px] border-t-[3px] border-m-accent bg-m-surface p-5 shadow-[var(--shadow-card)] sm:w-[340px] sm:p-6 motion-reduce:w-full">
      <h3 className="text-[17px] font-medium leading-snug tracking-[-.02em] text-m-ink sm:text-[18px]">{question}</h3>
      <p className="text-[14.5px] leading-relaxed text-m-muted">{answer}</p>
    </li>
  );
}

function Row({ items, reverse, speed, paused, label }: { items: [string, ReactNode][]; reverse?: boolean; speed: string; paused: boolean; label: string }) {
  const style: CSSProperties = { animationDuration: speed, animationPlayState: paused ? "paused" : undefined };
  const set = (copy: number) => (
    <ul key={copy} aria-label={copy === 0 ? label : undefined} aria-hidden={copy > 0 || undefined} {...(copy > 0 ? { inert: true } : {})}
      className={"flex shrink-0 items-stretch gap-4 pr-4 sm:gap-5 sm:pr-5" + (copy > 0 ? " motion-reduce:!hidden" : "") + " motion-reduce:w-full motion-reduce:flex-col motion-reduce:pr-0 sm:motion-reduce:grid sm:motion-reduce:grid-cols-2 lg:motion-reduce:grid-cols-3"}>
      {items.map(([q, a]) => <FaqCard key={q} question={q} answer={a} />)}
    </ul>
  );
  return (
    <div className="overflow-hidden motion-reduce:overflow-visible motion-reduce:px-[max(16px,calc((100vw-1080px)/2))]"
      style={{ maskImage: "linear-gradient(90deg, transparent, #000 6%, #000 94%, transparent)", WebkitMaskImage: "linear-gradient(90deg, transparent, #000 6%, #000 94%, transparent)" }}>
      {/* four copies; the loop moves by two of them, so it joins up without a jump at any screen width */}
      <div className={(reverse ? "mkt-marquee-rev" : "mkt-marquee") + " flex w-max hover:[animation-play-state:paused] motion-reduce:block motion-reduce:w-full"} style={style}>
        {[0, 1, 2, 3].map(set)}
      </div>
    </div>
  );
}

export function FaqScroller({ items, title = "Frequently asked questions", sub }: { items: [string, ReactNode][]; title?: string; sub?: string }) {
  const [paused, setPaused] = useState(false);
  const half = Math.ceil(items.length / 2);
  return (
    <section aria-labelledby="faq-h" className="py-12 md:py-16">
      <div className="mkt-wrap">
        <Rise><div className="mx-auto max-w-[620px] text-center">
          <h2 id="faq-h" className="t-h2 text-m-ink">{title}</h2>
          {sub && <p className="mt-4 text-[16px] leading-relaxed text-m-muted">{sub}</p>}
        </div></Rise>
      </div>
      <div className="mt-9 space-y-4 py-2 sm:space-y-5 md:mt-12">
        <Row items={items.slice(0, half)} speed="75s" paused={paused} label="Common questions, first group" />
        <Row items={items.slice(half)} reverse speed="65s" paused={paused} label="Common questions, second group" />
      </div>
      <div className="mt-4 flex justify-center motion-reduce:hidden">
        <button type="button" aria-pressed={paused} onClick={() => setPaused((p) => !p)} className="inline-flex min-h-11 items-center rounded-full px-4 text-[13px] font-medium text-m-muted hover:text-m-ink">{paused ? "Play scrolling" : "Pause scrolling"}</button>
      </div>
    </section>
  );
}
