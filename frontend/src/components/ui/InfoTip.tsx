"use client";
import { Info } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

/** A small "i" that opens a one-line explanation under it. Keeps the card quiet by default; the words are one tap away (and read by screen readers when open). */
export function InfoTip({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <>
      <button type="button" aria-label={label} aria-expanded={open} aria-controls={id} onClick={() => setOpen((v) => !v)}
        className="grid h-11 w-11 place-items-center rounded-full text-muted transition-colors hover:bg-surface-2 hover:text-ink md:h-8 md:w-8"><Info className="h-4 w-4" aria-hidden /></button>
      {open && <p id={id} className="fq-enter absolute inset-x-4 top-12 z-10 rounded-[12px] bg-ink-solid px-3 py-2 text-[13px] leading-snug text-ink-on shadow-lift lg:inset-x-5">{children}</p>}
    </>
  );
}
