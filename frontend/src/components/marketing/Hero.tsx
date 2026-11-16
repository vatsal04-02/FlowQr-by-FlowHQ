import clsx from "clsx";
import type { ReactNode } from "react";
import { HeroBackdrop, Tilt } from "./Depth";
import { BlurWords, Pop, Rise } from "./motion";

/**
 * DESIGN.md §1 / 01-hero.png: centred two-line headline (line 2 in accent), two pill buttons, then a faint 3-column grid with + crosshairs
 * at every intersection, fading at the edges. Left: icon + one line. Centre: a product card. Right: stacked micro-chips.
 */
export function Hero({ line1, line2, actions, center, left, chips, sub, leftNode, rightNode, below, kicker, flow }: {
  line1: string; line2: string; actions?: ReactNode; center?: ReactNode; left?: { icon: ReactNode; text: string }; chips?: ReactNode[]; sub?: string;
  /** Richer side columns (a product card each) instead of the one-line left text and the chips. */
  leftNode?: ReactNode; rightNode?: ReactNode; below?: ReactNode; kicker?: ReactNode;
  /** One flow strip in place of the three-column product grid. The hero is also tightened so the strip starts higher on the page. */
  flow?: ReactNode;
}) {
  return (
    <section className={clsx("relative isolate -mt-[76px] overflow-hidden", flow ? "pb-12 pt-[112px] md:pb-14 md:pt-[108px]" : "pb-16 pt-[140px] md:pb-24 md:pt-[188px]")}>
      <HeroBackdrop />
      <div className="relative mkt-wrap text-center">
        {kicker && <Rise className={clsx("flex justify-center", flow ? "mb-4" : "mb-6")}>{kicker}</Rise>}
        <h1 className={clsx("t-display mx-auto text-m-ink", !flow && "max-w-[900px]", flow && "max-w-[980px] max-sm:!text-[length:min(8.7vw,38px)] max-sm:!leading-[1.08] sm:!text-[clamp(30px,4.9vw,46px)] sm:!leading-[1.08] sm:!tracking-[-.035em] lg:!text-[clamp(40px,3.7vw,54px)]")}>
          <BlurWords as="div" text={line1} />
          <BlurWords as="div" text={line2} delay={0.18} className="text-m-accentText" />
        </h1>
        {sub && <Rise delay={0.3}><p className={clsx("mx-auto text-pretty text-[17px] leading-relaxed text-m-ink2 md:text-[19px]", flow ? "mt-4 max-w-[640px] lg:max-w-[860px]" : "mt-6 max-w-[640px]")}>{sub}</p></Rise>}
        {actions && <Rise delay={0.35} className={clsx("flex flex-wrap items-center justify-center gap-2.5", flow ? "mt-5" : "mt-7")}>{actions}</Rise>}
      </div>
      {flow && <div className="relative mx-auto mt-7 max-w-[1120px] px-4 md:mt-6">{flow}</div>}
      {center && (
        <div className="relative mx-auto mt-14 max-w-[1200px] px-4 md:mt-16">
          <Grid wide={!!(leftNode || rightNode)} />
          <div className={leftNode || rightNode ? "relative mx-auto grid max-w-[1120px] items-center gap-10 lg:grid-cols-[1fr_1.1fr_1fr] lg:gap-6 lg:py-12" : "relative mx-auto grid max-w-[880px] items-center gap-10 md:grid-cols-[1fr_1.45fr_1fr] md:gap-0 md:py-14"}>
            {leftNode ? <Rise delay={0.45} className="order-2 flex justify-center lg:order-1 lg:justify-end"><Tilt>{leftNode}</Tilt></Rise> : <div className="order-2 hidden md:order-1 md:block md:pr-10">
              {left && <Rise delay={0.5}><span className="grid h-9 w-9 place-items-center rounded-lg bg-m-surface text-m-accentStrong shadow-[0_1px_2px_rgba(11,15,46,.06)]" aria-hidden>{left.icon}</span><p className="mt-4 max-w-[220px] t-small text-m-ink2">{left.text}</p></Rise>}
            </div>}
            <div className="order-1 flex justify-center md:order-2">{leftNode || rightNode ? <Tilt depth={8}>{center}</Tilt> : center}</div>
            {rightNode ? <Rise delay={0.55} className="order-3 flex justify-center lg:justify-start"><Tilt>{rightNode}</Tilt></Rise> : <div className="order-3 hidden flex-col items-end gap-2.5 md:flex md:pl-10">
              {chips?.map((c, i) => <Pop key={i} delay={0.7 + i * 0.08}>{c}</Pop>)}
            </div>}
          </div>
          {left && !leftNode && <p className="mx-auto mt-8 max-w-[300px] text-center t-small text-m-ink2 md:hidden">{left.text}</p>}
          {below}
        </div>
      )}
    </section>
  );
}

/** The faint grid: lines at the column edges with a + at every crossing, masked to fade out. Decorative. */
function Grid({ wide }: { wide?: boolean }) {
  const xs = wide ? ["calc(50% - 560px)", "calc(50% - 190px)", "calc(50% + 190px)", "calc(50% + 560px)"] : ["calc(50% - 440px)", "calc(50% - 185px)", "calc(50% + 185px)", "calc(50% + 440px)"];
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 hidden md:block" style={{ maskImage: "radial-gradient(ellipse 60% 70% at 50% 50%, #000 55%, transparent 100%)", WebkitMaskImage: "radial-gradient(ellipse 60% 70% at 50% 50%, #000 55%, transparent 100%)" }}>
      <div className="absolute inset-x-0 top-0 h-px bg-m-line" />
      <div className="absolute inset-x-0 bottom-0 h-px bg-m-line" />
      {xs.map((x) => <div key={x} className="absolute inset-y-[-40px] w-px bg-m-line" style={{ left: x }} />)}
      {["0%", "100%"].flatMap((y) => xs.map((x) => (
        <span key={y + x} className="absolute -translate-x-1/2 -translate-y-1/2 text-m-ink/40" style={{ top: y, left: x }}>
          <svg width="9" height="9" viewBox="0 0 9 9"><path d="M4.5 0v9M0 4.5h9" stroke="currentColor" /></svg>
        </span>
      )))}
    </div>
  );
}
