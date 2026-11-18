"use client";

import clsx from "clsx";
import { AnimatePresence, motion, useMotionValue, useSpring, type HTMLMotionProps, type MotionValue, type SpringOptions } from "motion/react";
import * as React from "react";

/**
 * A custom mouse pointer for one area of a page (adapted from the supplied "cursor" component: MouseTrackerProvider, Pointer, PointerFollower).
 * Put <CursorProvider> inside the area; it follows the mouse over its parent element.
 *
 * Differences from the original, so it stays usable:
 * - It only runs for a real mouse (a fine pointer that can hover) and never when the person asked for reduced motion. On touch screens nothing is drawn and nothing is hidden.
 * - Over a link, a button or a form field the custom pointer steps aside and the normal system cursor comes back (so people can see what is clickable).
 * - The system cursor is hidden only while the custom pointer is showing.
 * - The follower glides with a spring instead of snapping.
 * - Position lives in motion values, so moving the mouse does not re-render React on every move.
 * Not wired in: tailwind-merge (the project does not use it); clsx is enough because the default classes are never overridden.
 */

export type MouseTrackerContextType = {
  x: MotionValue<number>;
  y: MotionValue<number>;
  active: boolean;
  /** true when the pointer is drawn in the window (fixed) rather than inside its parent element */
  fixed: boolean;
  wrapperRef: React.RefObject<HTMLDivElement | null>;
  pointerRef: React.RefObject<HTMLDivElement | null>;
};

const MouseTrackerContext = React.createContext<MouseTrackerContextType | undefined>(undefined);

export const useMouseTracker = (): MouseTrackerContextType => {
  const context = React.useContext(MouseTrackerContext);
  if (!context) throw new Error("useMouseTracker must be used within MouseTrackerProvider");
  return context;
};

const INTERACTIVE = "a, button, input, select, textarea, label, summary, [role='button'], [role='link'], [role='switch'], [role='dialog']";

export type MouseTrackerProviderProps = React.ComponentProps<"div"> & { children: React.ReactNode; /** follow the mouse over the whole window (use for a whole page: it stays under the mouse while the page scrolls) */ fixed?: boolean };

function MouseTrackerProvider({ ref, children, className, fixed = false, ...rest }: MouseTrackerProviderProps) {
  const x = useMotionValue(0);
  const y = useMotionValue(0);
  const [active, setActive] = React.useState(false);
  const wrapperRef = React.useRef<HTMLDivElement>(null);
  const pointerRef = React.useRef<HTMLDivElement>(null);
  React.useImperativeHandle(ref, () => wrapperRef.current as HTMLDivElement);

  React.useEffect(() => {
    const wrapper = wrapperRef.current;
    const container = wrapper?.parentElement;
    if (!wrapper || !container) return;
    // Only for a real mouse, and never under reduced motion.
    const mouse = window.matchMedia("(hover: hover) and (pointer: fine)");
    const calm = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (!mouse.matches || calm.matches) return;

    if (getComputedStyle(container).position === "static") container.style.position = "relative";

    const move = (e: MouseEvent) => {
      const over = (e.target as Element | null)?.closest?.(INTERACTIVE);
      if (over) { setActive(false); return; }
      const bounds = fixed ? { left: 0, top: 0 } : container.getBoundingClientRect();
      x.set(e.clientX - bounds.left);
      y.set(e.clientY - bounds.top);
      setActive(true);
    };
    const leave = () => setActive(false);

    container.addEventListener("mousemove", move);
    container.addEventListener("mouseleave", leave);
    return () => {
      container.removeEventListener("mousemove", move);
      container.removeEventListener("mouseleave", leave);
      container.style.cursor = "";
    };
  }, [x, y, fixed]);

  // The system cursor is hidden only while the custom pointer is on show.
  React.useEffect(() => {
    const container = wrapperRef.current?.parentElement;
    if (container) container.style.cursor = active ? "none" : "";
  }, [active]);

  return (
    <MouseTrackerContext.Provider value={{ x, y, active, fixed, wrapperRef, pointerRef }}>
      <div ref={wrapperRef} data-role="tracker-wrapper" aria-hidden className={clsx("pointer-events-none inset-0 overflow-hidden", fixed ? "fixed z-[80]" : "absolute z-[3]", className)} {...rest}>
        {children}
      </div>
    </MouseTrackerContext.Provider>
  );
}

export type PointerProps = HTMLMotionProps<"div"> & { children: React.ReactNode };

function Pointer({ ref, className, style, children, ...rest }: PointerProps) {
  const { x, y, active, fixed, pointerRef } = useMouseTracker();
  React.useImperativeHandle(ref, () => pointerRef.current as HTMLDivElement);
  return (
    <AnimatePresence>
      {active && (
        <motion.div ref={pointerRef} data-role="custom-pointer" className={clsx("pointer-events-none z-[9999] -translate-x-1/2 -translate-y-1/2", fixed ? "fixed" : "absolute", className)}
          style={{ top: y, left: x, ...style }} initial={{ scale: 0, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0, opacity: 0 }} {...rest}>
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export type Anchor = "top" | "top-left" | "top-right" | "bottom" | "bottom-left" | "bottom-right" | "left" | "right" | "center";

export type PointerFollowerProps = HTMLMotionProps<"div"> & { align?: Anchor; gap?: number; transition?: SpringOptions; children: React.ReactNode };

function PointerFollower({ ref, align = "bottom-right", gap = 20, transition = { stiffness: 380, damping: 34, mass: 0.6 }, children, className, style, ...rest }: PointerFollowerProps) {
  const { x, y, active, fixed } = useMouseTracker();
  const followerRef = React.useRef<HTMLDivElement>(null);
  React.useImperativeHandle(ref, () => followerRef.current as HTMLDivElement);
  const sx = useSpring(x, transition);
  const sy = useSpring(y, transition);

  // Where the label sits relative to the pointer: the same eight positions as the original. It is measured from the label's own size.
  const [size, setSize] = React.useState({ w: 0, h: 0 });
  React.useEffect(() => {
    const box = followerRef.current?.getBoundingClientRect();
    if (box && (Math.round(box.width) !== size.w || Math.round(box.height) !== size.h)) setSize({ w: Math.round(box.width), h: Math.round(box.height) });
  }, [active, children, size.w, size.h]);
  const { w, h } = size;
  const off = {
    center: { x: 0, y: 0 }, top: { x: 0, y: -(h / 2 + gap) }, "top-left": { x: -(w / 2 + gap), y: -(h / 2 + gap) }, "top-right": { x: w / 2 + gap, y: -(h / 2 + gap) },
    bottom: { x: 0, y: h / 2 + gap }, "bottom-left": { x: -(w / 2 + gap), y: h / 2 + gap }, "bottom-right": { x: w / 2 + gap, y: h / 2 + gap },
    left: { x: -(w / 2 + gap), y: 0 }, right: { x: w / 2 + gap, y: 0 },
  }[align];

  return (
    <AnimatePresence>
      {active && (
        <motion.div ref={followerRef} data-role="pointer-follower" className={clsx("pointer-events-none z-[9998] -translate-x-1/2 -translate-y-1/2 font-medium", fixed ? "fixed" : "absolute", className)}
          style={{ top: sy, left: sx, marginLeft: off.x, marginTop: off.y, ...style }} initial={{ scale: 0, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0, opacity: 0 }} {...rest}>
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export {
  MouseTrackerProvider, Pointer, PointerFollower,
  type MouseTrackerContextType as CursorContextType,
  type MouseTrackerProviderProps as CursorProviderProps,
  type PointerProps as CursorProps,
  type PointerFollowerProps as CursorFollowProps,
};
