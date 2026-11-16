"use client";
import { X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, type KeyboardEvent, type ReactNode } from "react";

/**
 * One sheet for the whole app: slides up from the bottom on a phone, a centred panel from tablet width. Closes with its button, the backdrop or Escape; keeps focus inside
 * while open and gives it back to whatever opened it. Motion follows the reduced-motion setting (MotionConfig in the app shell).
 */
export function Sheet({ open, onClose, title, children, footer }: { open: boolean; onClose: () => void; title: string; children: ReactNode; footer?: ReactNode }) {
  const panel = useRef<HTMLDivElement>(null);
  const closeBtn = useRef<HTMLButtonElement>(null);
  const back = useRef<Element | null>(null);
  useEffect(() => {
    if (!open) return;
    back.current = document.activeElement;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeBtn.current?.focus();
    return () => { document.body.style.overflow = prev; (back.current as HTMLElement | null)?.focus?.(); };
  }, [open]);
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") { e.stopPropagation(); onClose(); return; }
    if (e.key !== "Tab") return;
    const f = Array.from(panel.current?.querySelectorAll<HTMLElement>("a[href],button:not([disabled]),select,input,textarea") ?? []);
    if (!f.length) return;
    if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
    else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
  };
  return (
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-[55] flex items-end justify-center md:items-center md:p-6" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.15 }} onKeyDown={onKey}>
          <button type="button" aria-label="Close" tabIndex={-1} onClick={onClose} className="absolute inset-0 bg-black/40" />
          <motion.div ref={panel} role="dialog" aria-modal="true" aria-label={title}
            initial={{ y: 40, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: 40, opacity: 0 }} transition={{ duration: 0.2, ease: [0.2, 0.7, 0.2, 1] }}
            className="relative max-h-[88dvh] w-full overflow-y-auto overscroll-contain rounded-t-[16px] bg-surface pb-[calc(16px+env(safe-area-inset-bottom))] md:max-w-[440px] md:rounded-[16px] md:pb-4">
            <div className="sticky top-0 z-10 flex items-center justify-between gap-3 bg-surface px-4 pb-2 pt-3">
              <h2 className="text-[17px] font-semibold">{title}</h2>
              <button ref={closeBtn} type="button" onClick={onClose} aria-label="Close" className="grid h-11 w-11 place-items-center rounded-[12px] text-ink-600 hover:bg-surface-2"><X className="h-5 w-5" aria-hidden /></button>
            </div>
            <div className="px-4">{children}</div>
            {footer && <div className="mt-4 flex flex-col gap-2 px-4 sm:flex-row sm:justify-end">{footer}</div>}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
