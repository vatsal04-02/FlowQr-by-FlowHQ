"use client";
import { AnimatePresence, motion, useMotionValue, useReducedMotion, useScroll, useSpring, useTransform } from "motion/react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { EASE } from "./motion";

/**
 * Depth and interaction for the hero:
 *  - HeroBackdrop: warm light pools, a dotted floor and a faint FlowQR ring, drifting with the pointer at different speeds (parallax).
 *  - Tilt: a card that leans toward the pointer in 3D and lifts its shadow.
 *  - RotatingWord: cycles the business types FlowQR is for.
 * All of it stands still under reduced motion and on touch screens.
 */
function usePointer() {
  const x = useMotionValue(0), y = useMotionValue(0);
  const reduced = useReducedMotion();
  useEffect(() => {
    if (reduced || window.matchMedia("(hover: none)").matches) return;
    const on = (e: PointerEvent) => { x.set(e.clientX / window.innerWidth - 0.5); y.set(e.clientY / window.innerHeight - 0.5); };
    window.addEventListener("pointermove", on, { passive: true });
    return () => window.removeEventListener("pointermove", on);
  }, [reduced, x, y]);
  return { x: useSpring(x, { stiffness: 60, damping: 20 }), y: useSpring(y, { stiffness: 60, damping: 20 }) };
}

export function HeroBackdrop() {
  const { x, y } = usePointer();
  // the pointer moves the layers sideways at different speeds; scrolling carries them up at different speeds too (the far glows trail the page, the near ones lead it), and the rings turn slowly
  const { scrollY } = useScroll();
  const reduced = useReducedMotion();
  const far = { x: useTransform(x, (v) => v * -40), y: useTransform([y, scrollY], ([v, s]: number[]) => v * -30 + (reduced ? 0 : s * 0.12)) };
  const near = { x: useTransform(x, (v) => v * 70), y: useTransform([y, scrollY], ([v, s]: number[]) => v * 50 + (reduced ? 0 : s * -0.1)) };
  const turn = useTransform(scrollY, [0, 1600], [0, reduced ? 0 : 55]);
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 -z-0 overflow-hidden">
      <motion.div style={far} className="absolute -left-[10%] -top-[20%] h-[720px] w-[720px] rounded-full bg-[radial-gradient(closest-side,rgba(254,106,5,.20),rgba(254,106,5,0))]" />
      <motion.div style={near} className="absolute -right-[8%] top-[18%] h-[640px] w-[640px] rounded-full bg-[radial-gradient(closest-side,rgba(255,178,122,.32),rgba(255,178,122,0))]" />
      <motion.div style={far} className="absolute left-[30%] top-[55%] h-[560px] w-[560px] rounded-full bg-[radial-gradient(closest-side,rgba(255,227,204,.75),rgba(255,227,204,0))]" />
      <div className="absolute inset-0 opacity-[.55] [background-image:radial-gradient(rgba(11,15,46,.14)_1px,transparent_1.2px)] [background-size:22px_22px] [mask-image:radial-gradient(ellipse_70%_60%_at_50%_45%,#000_30%,transparent_80%)]" />
      <motion.svg style={{ ...near, rotate: turn }} viewBox="0 0 600 600" className="absolute left-1/2 top-[38%] h-[900px] w-[900px] -translate-x-1/2 -translate-y-1/2 opacity-[.5]">
        {[290, 230, 170].map((r) => <circle key={r} cx="300" cy="300" r={r} fill="none" stroke="rgba(254,106,5,.10)" strokeWidth="1.2" />)}
      </motion.svg>
      <div className="absolute inset-x-0 bottom-0 h-40 bg-gradient-to-b from-transparent to-m-bg" />
    </div>
  );
}

export function Tilt({ children, depth = 10, className }: { children: ReactNode; depth?: number; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();
  const rx = useSpring(0, { stiffness: 150, damping: 15 }), ry = useSpring(0, { stiffness: 150, damping: 15 }), lift = useSpring(0, { stiffness: 150, damping: 18 });
  const shadow = useTransform(lift, (l) => `drop-shadow(0 ${12 + l * 18}px ${20 + l * 20}px rgba(11,15,46,${0.08 + l * 0.1}))`);
  function move(e: React.PointerEvent) {
    if (reduced || e.pointerType !== "mouse" || !ref.current) return;
    const r = ref.current.getBoundingClientRect();
    ry.set(((e.clientX - r.left) / r.width - 0.5) * depth * 2);
    rx.set(-((e.clientY - r.top) / r.height - 0.5) * depth * 2);
    lift.set(1);
  }
  const reset = () => { rx.set(0); ry.set(0); lift.set(0); };
  return (
    <div ref={ref} onPointerMove={move} onPointerLeave={reset} className={className} style={{ perspective: 900 }}>
      <motion.div style={{ rotateX: rx, rotateY: ry, filter: reduced ? undefined : shadow, transformStyle: "preserve-3d" }}>{children}</motion.div>
    </div>
  );
}

export function RotatingWord({ words, className }: { words: string[]; className?: string }) {
  const reduced = useReducedMotion();
  const [i, setI] = useState(0);
  useEffect(() => { if (reduced) return; const t = setInterval(() => setI((v) => (v + 1) % words.length), 2200); return () => clearInterval(t); }, [reduced, words.length]);
  return (
    <motion.span layout transition={{ duration: 0.35, ease: EASE }} className={`relative inline-flex overflow-hidden align-bottom ${className ?? ""}`}>
      <span className="sr-only">{words.join(", ")}</span>
      <AnimatePresence mode="wait" initial={false}>
        <motion.span key={words[i]} aria-hidden className="inline-block whitespace-nowrap" initial={{ y: "80%", opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: "-80%", opacity: 0 }} transition={{ duration: 0.3, ease: EASE }}>{words[i]}</motion.span>
      </AnimatePresence>
    </motion.span>
  );
}
