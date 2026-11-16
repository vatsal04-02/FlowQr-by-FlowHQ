"use client";
import { motion, useReducedMotion } from "motion/react";
import type { ReactNode } from "react";

/** DESIGN.md §6 motion. Under reduced motion every effect becomes a plain 200ms fade: no blur, no movement. */
export const EASE = [0.22, 1, 0.36, 1] as const;

/** Words rise 24px and un-blur, 60ms apart (hero headlines). `accent` words render in the accent colour. */
export function BlurWords({ text, className, delay = 0, as = "span" }: { text: string; className?: string; delay?: number; as?: "span" | "div" }) {
  const reduced = useReducedMotion();
  const words = text.split(" ");
  const Tag = as === "div" ? motion.div : motion.span;
  return (
    <Tag className={className} initial="hidden" animate="show">
      <span className="sr-only">{text}</span>
      {words.map((w, i) => (
        <motion.span key={i} aria-hidden className="inline-block whitespace-pre"
          variants={reduced
            ? { hidden: { opacity: 0.01, y: 0, filter: "blur(0px)" }, show: { opacity: 1, y: 0, filter: "blur(0px)", transition: { duration: 0.2 } } }
            : { hidden: { opacity: 0.01, y: 24, filter: "blur(8px)" }, show: { opacity: 1, y: 0, filter: "blur(0px)", transition: { duration: 0.7, ease: EASE, delay: delay + i * 0.06 } } }}>
          {w}{i < words.length - 1 ? " " : ""}
        </motion.span>
      ))}
    </Tag>
  );
}

/** Rises 16px (or `y`) and un-blurs when 20% of it is in view. */
export function Rise({ children, className, delay = 0, y = 16, blur = true, as = "div" }: { children: ReactNode; className?: string; delay?: number; y?: number; blur?: boolean; as?: "div" | "li" | "section" }) {
  const reduced = useReducedMotion();
  const Tag = as === "li" ? motion.li : as === "section" ? motion.section : motion.div;
  return (
    <Tag className={className} initial={reduced ? { opacity: 0 } : { opacity: 0, y, filter: blur ? "blur(8px)" : "blur(0px)" }}
      whileInView={reduced ? { opacity: 1, y: 0, filter: "blur(0px)" } : { opacity: 1, y: 0, filter: "blur(0px)" }} viewport={{ once: true, amount: 0.2 }}
      transition={reduced ? { duration: 0.2 } : { duration: 0.7, ease: EASE, delay }}>
      {children}
    </Tag>
  );
}

/** Pops in from scale .9 (hero chips, arc nodes). */
export function Pop({ children, className, delay = 0 }: { children: ReactNode; className?: string; delay?: number }) {
  const reduced = useReducedMotion();
  return (
    <motion.div className={className} initial={reduced ? { opacity: 0 } : { opacity: 0, scale: 0.9 }} whileInView={{ opacity: 1, scale: 1 }} viewport={{ once: true, amount: 0.3 }}
      transition={reduced ? { duration: 0.2 } : { duration: 0.5, ease: EASE, delay }}>{children}</motion.div>
  );
}
