"use client";
import { motion, useReducedMotion, useScroll, useTransform, type MotionValue } from "motion/react";
import { useRef, type ReactNode } from "react";
import { PhoneFrame } from "./Mockups";
import { Rise } from "./motion";

/**
 * 03 → 04: a huge two-line headline, then a phone that rises from below as you scroll, soft rings scaling in behind it, and UI cards that
 * fan out from behind the phone to tilted spots. Scroll-linked; under reduced motion everything simply sits in place.
 */
type Orbit = { node: ReactNode; x: number; y: number; r: number };

export function PhoneOrbit({ line1, line2Pre, accent, sub, screen, orbit }: { line1: string; line2Pre: string; accent: string; sub: string; screen: ReactNode; orbit: Orbit[] }) {
  const ref = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start end", "end start"] });
  const rise = useTransform(scrollYProgress, [0.05, 0.42], ["55%", "0%"]);
  const ring = useTransform(scrollYProgress, [0.05, 0.42], [0.8, 1]);
  const fan = useTransform(scrollYProgress, [0.25, 0.5], [0, 1]);
  return (
    <section ref={ref} className="relative overflow-hidden pb-6 pt-16 md:pt-32">
      <div className="mkt-wrap text-center">
        <Rise><h2 className="t-display-xl text-m-ink max-sm:!text-[length:min(34px,9vw)] max-sm:!leading-[1]">{line1}<br />{line2Pre} <span className="text-m-accentText">{accent}</span></h2></Rise>
        <Rise delay={0.1}><p className="mx-auto mt-5 max-w-[340px] t-small text-m-muted max-sm:!text-[14px] max-sm:!leading-relaxed md:mt-6 md:max-w-none">{sub}</p></Rise>
      </div>
      <div className="relative mx-auto mt-10 h-[600px] max-w-[1080px] md:mt-16">
        <div aria-hidden className="absolute left-1/2 top-[40px] -translate-x-1/2"><motion.div style={{ scale: reduced ? 1 : ring }}>
          {[620, 480, 340].map((s, i) => <span key={s} className="absolute left-1/2 top-[260px] -translate-x-1/2 -translate-y-1/2 rounded-full" style={{ width: s, height: s, background: i === 2 ? "rgba(255,227,204,.55)" : i === 1 ? "rgba(255,241,230,.7)" : "rgba(255,241,230,.45)" }} />)}
        </motion.div></div>
        <div className="absolute inset-x-0 top-0 hidden h-full md:block">
          {orbit.map((o, i) => <OrbitCard key={i} o={o} fan={fan} reduced={!!reduced} />)}
        </div>
        <div className="absolute left-1/2 top-[40px] -translate-x-1/2"><motion.div style={{ y: reduced ? 0 : rise }}>
          <PhoneFrame>{screen}</PhoneFrame>
        </motion.div></div>
        <div aria-hidden className="pointer-events-none absolute inset-x-0 bottom-0 h-28 bg-gradient-to-t from-m-bg to-transparent" />
      </div>
    </section>
  );
}

function OrbitCard({ o, fan, reduced }: { o: Orbit; fan: MotionValue<number>; reduced: boolean }) {
  const x = useTransform(fan, [0, 1], [0, o.x]);
  const y = useTransform(fan, [0, 1], [80, o.y]);
  const rotate = useTransform(fan, [0, 1], [0, o.r]);
  const opacity = useTransform(fan, [0, 0.4, 1], [0, 1, 1]);
  return (
    <div className="absolute left-1/2 top-[150px] -translate-x-1/2"><motion.div style={reduced ? { x: o.x, y: o.y, rotate: o.r } : { x, y, rotate, opacity }}>
      {o.node}
    </motion.div></div>
  );
}
