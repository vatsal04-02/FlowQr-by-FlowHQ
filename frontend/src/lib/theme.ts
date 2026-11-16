"use client";
import { useEffect, useSyncExternalStore } from "react";
import { THEME_KEY as KEY } from "./theme-boot";

/**
 * Light / dark / system for the logged-in app (DESIGN.md §8). The choice lives in localStorage on this device; the root layout's inline
 * script applies it before first paint so there is no flash. Marketing and public QR pages never get the dashboard palette.
 */
export type ThemeMode = "light" | "dark" | "system";
const EVT = "fq-theme-change";

function read(): ThemeMode {
  try { const v = localStorage.getItem(KEY); return v === "light" || v === "dark" ? v : "system"; } catch { return "system"; }
}
const systemDark = () => typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches;
export const resolve = (m: ThemeMode): "light" | "dark" => (m === "system" ? (systemDark() ? "dark" : "light") : m);

function subscribe(cb: () => void) {
  const mq = window.matchMedia("(prefers-color-scheme: dark)");
  window.addEventListener(EVT, cb); window.addEventListener("storage", cb); mq.addEventListener("change", cb);
  return () => { window.removeEventListener(EVT, cb); window.removeEventListener("storage", cb); mq.removeEventListener("change", cb); };
}

function paint(mode: ThemeMode) {
  document.documentElement.dataset.theme = resolve(mode);
}

/**
 * Switch theme. When `from` (the toggle's position) is given and the browser supports view transitions, the new theme grows out of the
 * toggle as a circle (600 ms); otherwise it simply switches. Reduced motion always switches instantly.
 */
export function setTheme(mode: ThemeMode, from?: { x: number; y: number }) {
  const apply = () => {
    try { if (mode === "system") localStorage.removeItem(KEY); else localStorage.setItem(KEY, mode); } catch { /* private mode: this tab only */ }
    paint(mode);
    window.dispatchEvent(new Event(EVT));
  };
  const before = document.documentElement.dataset.theme;
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const doc = document as Document & { startViewTransition?: (cb: () => void) => { ready: Promise<void> } };
  if (!from || reduce || !doc.startViewTransition || before === resolve(mode)) { apply(); return; }
  const { x, y } = from;
  const r = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
  const t = doc.startViewTransition(apply);
  void t.ready.then(() => {
    document.documentElement.animate({ clipPath: [`circle(0 at ${x}px ${y}px)`, `circle(${r}px at ${x}px ${y}px)`] },
      { duration: 600, easing: "cubic-bezier(.2,.7,.2,1)", pseudoElement: "::view-transition-new(root)" });
  }).catch(() => undefined);
}

/** The current choice and what it resolves to right now. */
export function useTheme() {
  const mode = useSyncExternalStore(subscribe, read, () => "system" as ThemeMode);
  const resolved = useSyncExternalStore(subscribe, () => resolve(read()), () => "light" as const);
  return { mode, resolved, setTheme };
}

/**
 * Puts the dashboard palette on <html> while an app shell is mounted, and keeps "system" in step with the OS setting.
 * Removed again on unmount, so logging out to a marketing or auth page shows that page's own palette.
 */
export function useAppChrome() {
  const { mode } = useTheme();
  useEffect(() => {
    const el = document.documentElement;
    el.classList.add("fq-app");
    return () => { el.classList.remove("fq-app"); delete el.dataset.theme; };
  }, []);
  useEffect(() => { paint(mode); }, [mode]);
}
