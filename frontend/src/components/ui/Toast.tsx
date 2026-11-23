"use client";
import clsx from "clsx";
import { CheckCircle2, X, XCircle } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";

export type ToastOptions = {
  /** a button inside the message: "Undo" after a delete, "Try again" after a failure */
  action?: { label: string; onClick: () => void };
  /** how long it stays, in ms (an action keeps it longer so there is time to use it) */
  duration?: number;
};
type Toast = { id: number; tone: "success" | "error"; message: string; action?: ToastOptions["action"]; duration: number };
type Push = (message: string, tone?: Toast["tone"], opts?: ToastOptions) => void;
const Ctx = createContext<{ push: Push } | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const timers = useRef(new Map<number, number>());
  const drop = useCallback((id: number) => { window.clearTimeout(timers.current.get(id)); timers.current.delete(id); setItems((t) => t.filter((x) => x.id !== id)); }, []);
  const arm = useCallback((id: number, ms: number) => { window.clearTimeout(timers.current.get(id)); timers.current.set(id, window.setTimeout(() => drop(id), ms)); }, [drop]);
  const push = useCallback<Push>((message, tone = "success", opts) => {
    const id = Date.now() + Math.random();
    const duration = opts?.duration ?? (opts?.action ? 8000 : tone === "error" ? 6000 : 3500);
    setItems((t) => [...t.slice(-3), { id, tone, message, action: opts?.action, duration }]);
    arm(id, duration);
  }, [arm]);
  return (
    <Ctx.Provider value={{ push }}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 bottom-28 z-[60] flex flex-col items-center gap-2 px-4 lg:bottom-6" aria-live="polite">
        <AnimatePresence initial={false}>
        {items.map((t) => (
          // hovering or focusing a message holds it open (time to read it or press Undo); leaving restarts a short wait
          <motion.div key={t.id} layout role={t.tone === "error" ? "alert" : "status"} initial={{ opacity: 0, y: 18, scale: 0.94 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 8, scale: 0.96 }} transition={{ type: "spring", stiffness: 460, damping: 34 }}
            onMouseEnter={() => window.clearTimeout(timers.current.get(t.id))} onMouseLeave={() => arm(t.id, 2500)}
            onFocus={() => window.clearTimeout(timers.current.get(t.id))} onBlur={() => arm(t.id, 2500)}
            className={clsx("pointer-events-auto flex max-w-md items-center gap-2.5 rounded-full py-2 pl-5 pr-2 text-sm font-medium shadow-lift", t.tone === "success" ? "bg-ink-solid text-ink-on" : "bg-neg text-pure-white dark:text-pure-ink")}>
            {t.tone === "success" ? <CheckCircle2 className="h-4 w-4 shrink-0 text-accent" aria-hidden /> : <XCircle className="h-4 w-4 shrink-0" aria-hidden />}
            <span className="min-w-0 py-1">{t.message}</span>
            {t.action && <button type="button" onClick={() => { drop(t.id); t.action?.onClick(); }} className="tap shrink-0 rounded-full bg-white/15 px-3.5 text-[13px] font-semibold hover:bg-white/25">{t.action.label}</button>}
            <button type="button" aria-label="Dismiss" onClick={() => drop(t.id)} className="grid h-8 w-8 shrink-0 place-items-center rounded-full opacity-70 hover:bg-white/15 hover:opacity-100"><X className="h-3.5 w-3.5" aria-hidden /></button>
          </motion.div>
        ))}
        </AnimatePresence>
      </div>
    </Ctx.Provider>
  );
}
export const useToast = () => { const c = useContext(Ctx); if (!c) throw new Error("ToastProvider missing"); return c.push; };

/**
 * Delete-with-undo. The change is made on screen at once (`apply`), the toast offers Undo for 8 s, and only when the time runs out is `commit` sent to the server.
 * Undo puts the screen back and nothing is ever sent. Leaving the page early commits (a person who walked away meant it).
 */
export function useUndoable() {
  const push = useToast();
  const pending = useRef(new Set<() => void>());
  return useCallback((message: string, o: { apply: () => void; revert: () => void; commit: () => Promise<unknown>; onError?: (e: unknown) => void; label?: string }) => {
    o.apply();
    let state: "wait" | "undone" | "sent" = "wait";
    const send = () => { if (state !== "wait") return; state = "sent"; pending.current.delete(send); o.commit().catch((e) => { o.revert(); if (o.onError) o.onError(e); else push(e instanceof Error ? e.message : "That could not be saved, so it was put back.", "error"); }); };
    pending.current.add(send);
    window.addEventListener("pagehide", send, { once: true });
    push(message, "success", { duration: 7000, action: { label: o.label ?? "Undo", onClick: () => { if (state === "wait") { state = "undone"; pending.current.delete(send); o.revert(); } } } });
    window.setTimeout(send, 7400);
  }, [push]);
}
