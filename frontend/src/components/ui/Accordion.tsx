"use client";
import clsx from "clsx";
import { ChevronRight } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

/** A disclosure that opens by growing (grid rows 0fr to 1fr) instead of jumping. Keyboard and screen-reader behaviour is the button + region pattern. Reduced motion: instant (global rule). */
export function Accordion({ summary, children, className }: { summary: ReactNode; children: ReactNode; className?: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div className={className}>
      <button type="button" aria-expanded={open} aria-controls={id} onClick={() => setOpen((o) => !o)} className="inline-flex !min-h-9 items-center gap-1 text-[13px] font-semibold text-accent-ink">
        <ChevronRight className={clsx("h-4 w-4 transition-transform duration-300 ease-spring", open && "rotate-90")} aria-hidden />{summary}
      </button>
      <div id={id} role="region" className={clsx("grid transition-[grid-template-rows] duration-300 ease-out", open ? "grid-rows-[1fr]" : "grid-rows-[0fr]")}>
        <div className="min-h-0 overflow-hidden"><div className="pt-1" inert={!open}>{children}</div></div>
      </div>
    </div>
  );
}
