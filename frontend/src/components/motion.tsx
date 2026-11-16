"use client";
import clsx from "clsx";
import { useEffect, useRef, useState, type CSSProperties, type ElementType, type ReactNode } from "react";

const reduced = () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/**
 * Eases children in once when scrolled into view. Content is visible on the server and for anything already
 * on screen at load (no flash, no hidden content without JS); only below-the-fold content is armed to animate.
 */
export function Reveal({ children, delay = 0, as: Tag = "div", className }: {
  children: ReactNode; delay?: number; as?: ElementType; className?: string;
}) {
  const ref = useRef<HTMLElement>(null);
  const [state, setState] = useState<"idle" | "armed" | "in">("idle");
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (reduced() || typeof IntersectionObserver === "undefined" || el.getBoundingClientRect().top < window.innerHeight * 0.92) { setState("in"); return; }
    setState("armed");
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { setState("in"); io.disconnect(); } }, { threshold: 0.15, rootMargin: "0px 0px -6% 0px" });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return (
    <Tag ref={ref} style={{ "--d": `${delay}ms` } as CSSProperties}
      className={clsx(state !== "idle" && "reveal", state === "in" && "in", className)}>
      {children}
    </Tag>
  );
}
