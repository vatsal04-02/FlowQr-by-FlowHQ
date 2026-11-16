"use client";
import { X } from "lucide-react";
import { useEffect, useId, useRef, type ReactNode } from "react";

export function Modal({ open, onClose, title, children, footer }: { open: boolean; onClose: () => void; title: string; children: ReactNode; footer?: ReactNode }) {
  const titleId = useId();
  const panel = useRef<HTMLDivElement>(null);
  const lastFocus = useRef<Element | null>(null);

  useEffect(() => {
    if (!open) return;
    lastFocus.current = document.activeElement;
    const el = panel.current;
    const focusable = () => Array.from(el?.querySelectorAll<HTMLElement>('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])') ?? []);
    (focusable()[1] ?? focusable()[0] ?? el)?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); onClose(); }
      if (e.key === "Tab") {
        const f = focusable();
        if (!f.length) return;
        const first = f[0], last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.removeEventListener("keydown", onKey); document.body.style.overflow = prev; (lastFocus.current as HTMLElement | null)?.focus?.(); };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 grid items-end bg-[rgba(13,10,16,.45)] backdrop-blur-[8px] sm:place-items-center sm:p-4" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={panel} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}
        className="fq-enter flex max-h-[92dvh] w-full flex-col rounded-t-card bg-white shadow-lift outline-none sm:max-w-lg sm:rounded-card">
        <div className="flex items-center justify-between gap-3 px-6 pb-2 pt-5">
          <h2 id={titleId} className="text-lg font-semibold">{title}</h2>
          <button onClick={onClose} aria-label="Close dialog" className="tap grid place-items-center rounded-full bg-surface-2 text-ink hover:bg-surface-3"><X className="h-5 w-5" aria-hidden /></button>
        </div>
        <div className="overflow-y-auto px-6 py-4">{children}</div>
        {footer && <div className="flex flex-wrap justify-end gap-2 px-6 pb-[max(1.25rem,env(safe-area-inset-bottom))] pt-3">{footer}</div>}
      </div>
    </div>
  );
}
