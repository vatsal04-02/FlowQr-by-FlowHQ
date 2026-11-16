"use client";
import clsx from "clsx";
import { Info } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

/**
 * A small "what does this mean?" tooltip for unfamiliar numbers. Works on hover, keyboard focus and tap (it toggles on click),
 * closes on Escape or when you tap elsewhere, and is announced to screen readers through aria-describedby.
 */
export function Hint({ label, text, align = "start", dark = false }: { label: string; text: string; align?: "start" | "end"; dark?: boolean }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const root = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);
  return (
    <span ref={root} className="relative inline-flex" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <button type="button" aria-label={`What does “${label}” mean?`} aria-expanded={open} aria-describedby={open ? id : undefined}
        onClick={() => setOpen((o) => !o)} onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} onKeyDown={(e) => { if (e.key === "Escape") setOpen(false); }}
        className={clsx("-m-2 grid h-8 w-8 place-items-center rounded-full transition-colors", dark ? "text-white/60 hover:text-white" : "text-ink-400 hover:text-navy")}>
        <Info className="h-4 w-4" strokeWidth={1.75} aria-hidden />
      </button>
      {open && (
        <span role="tooltip" id={id} className={clsx("fq-enter absolute top-full z-30 mt-2 w-56 max-w-[calc(100vw-3rem)] rounded-lg bg-navy px-3 py-2 text-left text-[13px] font-normal leading-snug text-white shadow-pop", align === "end" ? "right-0" : "left-0")}>
          {text}
        </span>
      )}
    </span>
  );
}
