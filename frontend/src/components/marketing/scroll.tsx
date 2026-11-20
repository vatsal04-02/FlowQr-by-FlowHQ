"use client";
import { motion, useReducedMotion, useScroll, useSpring, useTransform, type MotionValue } from "motion/react";
import { useRef, type ReactNode } from "react";
import { EASE } from "./motion";

/**
 * Scroll-linked motion for the public site. It is added ON TOP of the existing layout: nothing here moves a block to a new place, resizes it or changes what it says; it only adds motion while
 * the page is scrolled. Reduced motion: the markup is the same for everyone (so the server and the browser always agree) and CSS (`motion-reduce:`) switches the movement off, which leaves the
 * content simply in place; the one-time draws and pops finish instantly. None of it blocks reading or clicking.
 */

/** One spring for every scroll-linked effect: the movement follows the scrollbar but glides (a little lag, no jitter), like a smooth-scroll page, without taking over the browser's own scrolling. */
const SOFT = { stiffness: 110, damping: 26, mass: 0.35 } as const;

/** A 3px line along the very top of the screen that fills as you read down the page. Hidden for people who asked for reduced motion. */
export function ScrollProgress() {
  const { scrollYProgress } = useScroll();
  const scaleX = useSpring(scrollYProgress, { stiffness: 120, damping: 28, mass: 0.4 });
  return <motion.div aria-hidden className="pointer-events-none fixed inset-x-0 top-0 z-[60] h-[3px] origin-left bg-m-accent motion-reduce:hidden" style={{ scaleX }} />;
}

/** Drifts its content up or down a little as the block crosses the screen, at a different speed from the page: depth. Used for glows and illustrations behind text. `speed` is in pixels each way. */
export function Parallax({ children, speed = 40, className }: { children?: ReactNode; speed?: number; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start end", "end start"] });
  const p = useSpring(scrollYProgress, SOFT);
  const y = useTransform(p, [0, 1], [speed, -speed]);
  return <motion.div ref={ref} aria-hidden={children ? undefined : true} className={`${className ?? ""} motion-reduce:!transform-none`} style={{ y }}>{children}</motion.div>;
}

/** A block that settles into place as it scrolls into view: it starts slightly smaller, lower and tipped back, and is fully in place by the time it is 55% up the screen. Scrubbed (it follows the scroll, forwards and back). */
export function ScrollSettle({ children, className, from = 0.94 }: { children: ReactNode; className?: string; from?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start end", "start 0.45"] });
  const p = useSpring(scrollYProgress, SOFT);
  const scale = useTransform(p, [0, 1], [from, 1]);
  const y = useTransform(p, [0, 1], [48, 0]);
  const rotateX = useTransform(p, [0, 1], [8, 0]);
  return (
    <div ref={ref} className={className} style={{ perspective: 1000 }}>
      <motion.div className="motion-reduce:!transform-none" style={{ scale, y, rotateX, transformOrigin: "50% 100%" }}>{children}</motion.div>
    </div>
  );
}

/** A block that eases away as you scroll past it: it fades, lifts a little and shrinks slightly (the hero text as the page moves on). Scrubbed, so it comes back when you scroll up. */
export function ScrollFade({ children, className }: { children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end start"] });
  const p = useSpring(scrollYProgress, SOFT);
  const opacity = useTransform(p, [0, 0.75], [1, 0]);
  const y = useTransform(p, [0, 1], [0, -56]);
  const scale = useTransform(p, [0, 1], [1, 0.97]);
  return <motion.div ref={ref} className={`${className ?? ""} motion-reduce:!opacity-100 motion-reduce:!transform-none`} style={{ opacity, y, scale }}>{children}</motion.div>;
}

function Word({ p, i, n, children }: { p: MotionValue<number>; i: number; n: number; children: string }) {
  const start = i / n;
  const opacity = useTransform(p, [start, Math.min(1, start + 1.8 / n)], [0.2, 1]);
  return <motion.span className="inline-block motion-reduce:!opacity-100" style={{ opacity }}>{children}</motion.span>;
}

/** A sentence whose words light up one after another as it scrolls up through the middle of the screen. Scrubbed (follows the scroll both ways). Renders as a span, so it can sit inside a paragraph. */
export function ScrollWords({ text, className }: { text: string; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start 0.92", "start 0.5"] });
  const p = useSpring(scrollYProgress, SOFT);
  const words = text.split(" ");
  return (
    <motion.span ref={ref} className={`block ${className ?? ""}`}>
      {words.map((w, i) => <span key={i}><Word p={p} i={i} n={words.length}>{w}</Word>{i < words.length - 1 ? " " : ""}</span>)}
    </motion.span>
  );
}

/** A line that draws itself (left to right, or top to bottom) once, when it comes into view. */
export function Draw({ className, vertical = false, delay = 0 }: { className?: string; vertical?: boolean; delay?: number }) {
  const reduced = useReducedMotion();
  return (
    <motion.span aria-hidden className={className} style={{ transformOrigin: vertical ? "50% 0%" : "0% 50%" }}
      initial={vertical ? { scaleY: 0 } : { scaleX: 0 }} whileInView={vertical ? { scaleY: 1 } : { scaleX: 1 }} viewport={{ once: true, amount: 1 }}
      transition={{ duration: reduced ? 0 : 0.6, ease: EASE, delay: reduced ? 0 : delay }} />
  );
}

/** A small mark that pops in once, after a delay (the arrow at the end of a drawn line). */
export function PopIn({ className, delay = 0, children }: { className?: string; delay?: number; children: ReactNode }) {
  const reduced = useReducedMotion();
  return (
    <motion.span aria-hidden className={className} initial={{ opacity: 0, scale: 0.4 }} whileInView={{ opacity: 1, scale: 1 }} viewport={{ once: true, amount: 1 }}
      transition={reduced ? { duration: 0 } : { type: "spring", stiffness: 420, damping: 18, delay }}>{children}</motion.span>
  );
}
