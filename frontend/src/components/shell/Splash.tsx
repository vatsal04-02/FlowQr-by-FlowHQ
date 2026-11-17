"use client";
import { motion } from "motion/react";

/**
 * The FlowQR start-up screen: the brand sheet's reversed lockup on navy, assembled in about a second while the app signs you in and loads. The three squares pop in one after another, the
 * orange leaf swings out from the corner, the letters of "flowqr" rise in turn, "by FlowHQ" settles under "flow", and a thin orange line fills along the bottom edge. When the app is ready
 * the whole screen lifts away (see AppShell, which keeps it up for a minimum time so the animation always finishes). `quick` is for a reload inside the same tab: same pictures, played
 * at 2.5x speed. Reduced motion: the lockup simply appears (MotionConfig in the shell), and this screen leaves with a plain fade.
 * Geometry matches `LogoMark` (components/ui/Brand.tsx): squares 45 on a 100 grid, 12 radius, 10 gap, the leaf in the lower right.
 */
const SQ = 45, R = 12, GAP = 10, NAVY = "#11173F", ORANGE = "#FE6A05";
const LEAF = `M${SQ + GAP + 6} ${SQ + GAP}H100A45 45 0 0 1 ${SQ + GAP} 100V${SQ + GAP + 6}Q${SQ + GAP} ${SQ + GAP} ${SQ + GAP + 6} ${SQ + GAP}Z`;
const pop = (i: number, k: number) => ({ type: "spring" as const, stiffness: 520, damping: 22, delay: i * 0.07 * k });

export function Splash({ quick = false }: { quick?: boolean }) {
  const k = quick ? 0.4 : 1;
  const squares: [number, number][] = [[0, 0], [SQ + GAP, 0], [0, SQ + GAP]];
  return (
    <motion.div role="status" aria-label="Loading FlowQR" className="fixed inset-0 z-[100] grid place-items-center overflow-hidden" style={{ background: NAVY }}
      initial={{ opacity: 1 }} exit={{ opacity: 0, scale: 1.04 }} transition={{ duration: 0.38, ease: [0.2, 0.7, 0.2, 1] }}>
      {/* a soft orange glow behind the mark, so the navy is not flat */}
      <motion.span aria-hidden className="absolute h-[60vmax] w-[60vmax] rounded-full" style={{ background: "radial-gradient(closest-side, rgba(254,106,5,.16), transparent)" }}
        initial={{ opacity: 0, scale: 0.6 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.9 * k + 0.2, ease: "easeOut" }} />
      <div className="relative flex items-center gap-[clamp(12px,3vw,22px)]">
        <svg viewBox="0 0 100 100" aria-hidden className="h-[clamp(60px,15vw,92px)] w-[clamp(60px,15vw,92px)] overflow-visible">
          {squares.map(([x, y], i) => (
            <motion.rect key={i} x={x} y={y} width={SQ} height={SQ} rx={R} fill="#fff" style={{ transformBox: "fill-box", transformOrigin: "center" }}
              initial={{ scale: 0.4, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={pop(i, k)} />
          ))}
          <motion.path d={LEAF} fill={ORANGE} style={{ transformBox: "fill-box", transformOrigin: "100% 100%" }}
            initial={{ scale: 0.15, opacity: 0, rotate: -35 }} animate={{ scale: 1, opacity: 1, rotate: 0 }} transition={{ type: "spring", stiffness: 380, damping: 18, delay: 0.24 * k }} />
        </svg>
        <div>
          <p aria-hidden className="flex font-brand font-bold lowercase leading-[.95] tracking-[-.035em]" style={{ fontSize: "clamp(46px, 11.5vw, 70px)" }}>
            {"flowqr".split("").map((ch, i) => (
              <motion.span key={i} className="inline-block" style={{ color: i >= 4 ? ORANGE : "#fff" }}
                initial={{ y: "55%", opacity: 0, filter: "blur(6px)" }} animate={{ y: 0, opacity: 1, filter: "blur(0px)" }}
                transition={{ type: "spring", stiffness: 420, damping: 30, delay: (0.3 + i * 0.05) * k }}>{ch}</motion.span>
            ))}
          </p>
          <motion.p aria-hidden className="mt-[.5em] font-brand font-semibold" style={{ fontSize: "clamp(11px, 2.6vw, 16px)", color: "rgba(255,255,255,.62)" }}
            initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.72 * k, duration: 0.3 }}>by FlowHQ</motion.p>
        </div>
      </div>
      <motion.span aria-hidden className="absolute bottom-0 left-0 h-[3px]" style={{ background: ORANGE }} initial={{ width: "0%" }} animate={{ width: "100%" }} transition={{ duration: 1.05 * k + 0.1, ease: [0.4, 0, 0.2, 1] }} />
    </motion.div>
  );
}
