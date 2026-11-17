"use client";
import { useEffect } from "react";

/**
 * Cards marked `data-tilt` lean a few degrees toward the pointer and catch a moving sheen (the CSS is `.tilt` in globals.css). One listener for the whole app instead of one per card.
 * Off for touch screens and for reduced motion; the card still lifts a little on hover without it.
 */
export function TiltEffect() {
  useEffect(() => {
    const fine = window.matchMedia("(hover: hover) and (pointer: fine)"), calm = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (!fine.matches || calm.matches) return;
    let last: HTMLElement | null = null;
    const reset = (el: HTMLElement | null) => { if (el) { el.style.setProperty("--rx", "0deg"); el.style.setProperty("--ry", "0deg"); } };
    const move = (e: PointerEvent) => {
      const el = (e.target as Element | null)?.closest?.("[data-tilt]") as HTMLElement | null;
      if (last && last !== el) reset(last);
      last = el;
      if (!el) return;
      const r = el.getBoundingClientRect(), x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
      el.style.setProperty("--mx", `${x * 100}%`); el.style.setProperty("--my", `${y * 100}%`);
      el.style.setProperty("--ry", `${((x - 0.5) * 5).toFixed(2)}deg`); el.style.setProperty("--rx", `${((0.5 - y) * 4).toFixed(2)}deg`);
    };
    const leave = () => { reset(last); last = null; };
    document.addEventListener("pointermove", move, { passive: true });
    document.addEventListener("pointerleave", leave);
    return () => { document.removeEventListener("pointermove", move); document.removeEventListener("pointerleave", leave); };
  }, []);
  return null;
}
