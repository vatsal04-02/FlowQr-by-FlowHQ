"use client";
import { useCallback, useEffect, useRef, useState } from "react";

/** A value that follows `value` only after it has stopped changing for `ms` (search boxes, filters: one request per pause, not per key). */
export function useDebounce<T>(value: T, ms = 250): T {
  const [v, setV] = useState(value);
  useEffect(() => { const h = window.setTimeout(() => setV(value), ms); return () => window.clearTimeout(h); }, [value, ms]);
  return v;
}

/** A stable function that runs `ms` after the last call. `.cancel()` drops a pending run, `.flush()` runs it now. */
export function useDebouncedCallback<A extends unknown[]>(fn: (...a: A) => void, ms = 400) {
  const f = useRef(fn); f.current = fn;
  const timer = useRef<number | undefined>(undefined);
  const last = useRef<A | null>(null);
  const cancel = useCallback(() => { window.clearTimeout(timer.current); last.current = null; }, []);
  const flush = useCallback(() => { window.clearTimeout(timer.current); if (last.current) { const a = last.current; last.current = null; f.current(...a); } }, []);
  const run = useCallback((...a: A) => { last.current = a; window.clearTimeout(timer.current); timer.current = window.setTimeout(flush, ms); }, [ms, flush]);
  useEffect(() => cancel, [cancel]);
  return Object.assign(run, { cancel, flush });
}

/** A stable function that runs at most once per `ms` (scroll, resize, rapid clicks on actions that cost money or send messages). The last call in a window still lands. */
export function useThrottledCallback<A extends unknown[]>(fn: (...a: A) => void, ms = 500) {
  const f = useRef(fn); f.current = fn;
  const at = useRef(0);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  return useCallback((...a: A) => {
    const wait = ms - (Date.now() - at.current);
    window.clearTimeout(timer.current);
    if (wait <= 0) { at.current = Date.now(); f.current(...a); }
    else timer.current = window.setTimeout(() => { at.current = Date.now(); f.current(...a); }, wait);
  }, [ms]);
}

export type SaveState = "idle" | "dirty" | "saving" | "saved" | "error";

/**
 * Autosave: call `touch()` whenever the person edits; `save` runs once they pause (`ms`), never twice at once, and again if they kept typing while it ran.
 * `state` drives <SaveStatus/>. The page also saves on tab close of a pending change by flushing when it becomes hidden.
 */
export function useAutosave(save: () => Promise<void>, ms = 900) {
  const [state, setState] = useState<SaveState>("idle");
  const [error, setError] = useState<string | null>(null);
  const fn = useRef(save); fn.current = save;
  const busy = useRef(false), again = useRef(false), dirty = useRef(false);
  const timer = useRef<number | undefined>(undefined);

  const run = useCallback(async () => {
    if (busy.current) { again.current = true; return; }
    busy.current = true; dirty.current = false; setState("saving");
    try { await fn.current(); setError(null); setState(again.current || dirty.current ? "dirty" : "saved"); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not save"); setState("error"); }
    finally { busy.current = false; if (again.current) { again.current = false; void run(); } }
  }, []);
  const touch = useCallback(() => { dirty.current = true; setState("dirty"); window.clearTimeout(timer.current); timer.current = window.setTimeout(() => void run(), ms); }, [ms, run]);
  const now = useCallback(() => { window.clearTimeout(timer.current); return run(); }, [run]);
  useEffect(() => {
    const hide = () => { if (document.visibilityState === "hidden" && dirty.current) { window.clearTimeout(timer.current); void run(); } };
    document.addEventListener("visibilitychange", hide);
    return () => { document.removeEventListener("visibilitychange", hide); window.clearTimeout(timer.current); };
  }, [run]);
  return { state, error, touch, now };
}

/** Run an action with the screen updated first. `apply` changes the UI at once and returns how to undo it; if `commit` fails, it is undone and the error is passed on. */
export async function optimistic<T>(apply: () => () => void, commit: () => Promise<T>): Promise<T> {
  const rollback = apply();
  try { return await commit(); } catch (e) { rollback(); throw e; }
}

/** True while a key is not being typed into a field (single-letter shortcuts must never steal typing). */
export const isTyping = (t: EventTarget | null) => {
  const el = t as HTMLElement | null;
  return !!el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || !!el.closest?.('[role="dialog"],[role="listbox"],[role="menu"]'));
};
