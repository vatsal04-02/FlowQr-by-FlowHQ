"use client";
import { X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

/** Open modals, oldest first. Only the newest one handles Esc and Tab, so a confirm dialog opened over a form closes alone. */
const stack: symbol[] = [];

export function Modal({ open, onClose, title, children, footer }: { open: boolean; onClose: () => void; title: string; children: ReactNode; footer?: ReactNode }) {
  const titleId = useId();
  const panel = useRef<HTMLDivElement>(null);
  const lastFocus = useRef<Element | null>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;  // the effect below must not re-run (and steal focus) whenever a parent re-renders with a new inline onClose
  const [host, setHost] = useState<HTMLElement | null>(null);
  useEffect(() => { setHost(document.body); }, []);  // drawn on <body>, so no card, panel or animated parent can ever move a dialog (a transformed ancestor re-anchors fixed children)

  useEffect(() => {
    if (!open) return;
    lastFocus.current = document.activeElement;
    const el = panel.current;
    const focusable = () => Array.from(el?.querySelectorAll<HTMLElement>('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])') ?? []);
    (focusable()[1] ?? focusable()[0] ?? el)?.focus();
    const me = Symbol("modal"); stack.push(me);
    const onKey = (e: KeyboardEvent) => {
      if (stack[stack.length - 1] !== me) return;
      if (e.key === "Escape") { e.stopPropagation(); closeRef.current(); }
      if (e.key === "Tab") {
        const f = focusable();
        if (!f.length) return;
        const first = f[0], last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow, prevHtml = document.documentElement.style.overflow;
    document.body.style.overflow = "hidden"; document.documentElement.style.overflow = "hidden";  // iPhones ignore the body alone: lock the root too so the page behind never moves
    return () => { stack.splice(stack.indexOf(me), 1); document.removeEventListener("keydown", onKey); document.body.style.overflow = prev; document.documentElement.style.overflow = prevHtml; (lastFocus.current as HTMLElement | null)?.focus?.(); };
  }, [open]);

  if (!host) return null;
  return createPortal(
    <AnimatePresence>
    {open && (
    <motion.div key="modal" className="fixed inset-0 z-[56] grid items-end bg-[rgba(13,10,16,.45)] sm:place-items-center sm:p-4 sm:backdrop-blur-[8px]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }} onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <motion.div ref={panel} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}
        initial={{ opacity: 0, y: 28, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 16, scale: 0.98 }} transition={{ type: "spring", stiffness: 420, damping: 34 }}
        className="flex max-h-[92dvh] w-full flex-col rounded-t-card bg-white shadow-lift outline-none sm:max-w-lg sm:rounded-card">
        <div className="flex items-center justify-between gap-3 px-5 pb-1 pt-4 sm:px-6 sm:pb-2 sm:pt-5">
          <h2 id={titleId} className="text-lg font-semibold">{title}</h2>
          <button onClick={onClose} aria-label="Close dialog" className="tap grid place-items-center rounded-full bg-surface-2 text-ink hover:bg-surface-3"><X className="h-5 w-5" aria-hidden /></button>
        </div>
        <div className="overflow-y-auto overscroll-contain px-5 py-3 [-webkit-overflow-scrolling:touch] sm:px-6 sm:py-4">{children}</div>
        {footer && <div className="flex flex-wrap justify-end gap-2 px-5 pb-[max(1rem,env(safe-area-inset-bottom))] pt-3 sm:px-6 sm:pb-[max(1.25rem,env(safe-area-inset-bottom))]">{footer}</div>}
      </motion.div>
    </motion.div>
    )}
    </AnimatePresence>,
    host,
  );
}
