"use client";
import { ArrowUpRight } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Rise } from "./motion";

/**
 * "Made for your kind of business": the eight kinds of business the industries page covers, set very large and scrolling past, each one a link to its own block on /industries.
 * Nothing is invented: the names are the industries page's own list. The loop pauses on hover and has a pause button; under reduced motion it does not move and simply wraps.
 */
export function BusinessBand({ title, items, all }: { title: string; items: [string, string][]; all: string }) {
  const [paused, setPaused] = useState(false);
  const row = (dup: boolean) => items.map(([id, name]) => (
    <li key={(dup ? "b" : "a") + id} aria-hidden={dup || undefined} className={dup ? "motion-reduce:hidden" : undefined}>
      <Link href={`/industries#${id}`} tabIndex={dup ? -1 : undefined} className="group flex items-center gap-8 whitespace-nowrap">
        <span className="text-[clamp(34px,5.4vw,76px)] font-medium leading-[1.05] tracking-[-.045em] text-m-ink transition-colors duration-300 group-hover:text-m-accentText">{name}</span>
        <span aria-hidden className="h-3 w-3 shrink-0 rounded-full bg-m-accent" />
      </Link>
    </li>
  ));
  return (
    <section aria-labelledby="made-for-h" className="py-12 md:py-20">
      <div className="mkt-wrap flex flex-wrap items-end justify-between gap-x-8 gap-y-3">
        <Rise><h2 id="made-for-h" className="t-h2 max-w-[560px] text-m-ink">{title}</h2></Rise>
        <Rise delay={0.1}>
          <Link href="/industries" className="inline-flex min-h-11 items-center gap-1.5 text-[15px] font-medium text-m-ink2 transition-colors hover:text-m-ink">{all}<ArrowUpRight className="h-4 w-4" strokeWidth={1.75} aria-hidden /></Link>
        </Rise>
      </div>
      <div className="mt-8 overflow-hidden md:mt-12 motion-reduce:overflow-visible" style={{ maskImage: "linear-gradient(90deg, transparent, #000 7%, #000 93%, transparent)", WebkitMaskImage: "linear-gradient(90deg, transparent, #000 7%, #000 93%, transparent)" }}>
        <ul className="mkt-marquee flex w-max items-center gap-8 px-4 hover:[animation-play-state:paused] motion-reduce:w-auto motion-reduce:flex-wrap motion-reduce:gap-x-8 motion-reduce:gap-y-3 motion-reduce:px-[max(16px,calc((100vw-1120px)/2))]"
          style={{ animationDuration: "46s", animationPlayState: paused ? "paused" : undefined }}>
          {row(false)}{row(true)}
        </ul>
      </div>
      <div className="mt-4 flex justify-center motion-reduce:hidden">
        <button type="button" aria-pressed={paused} onClick={() => setPaused((p) => !p)} className="inline-flex min-h-11 items-center rounded-full px-4 text-[13px] font-medium text-m-muted hover:text-m-ink">{paused ? "Play scrolling" : "Pause scrolling"}</button>
      </div>
    </section>
  );
}
