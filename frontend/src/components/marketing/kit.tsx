"use client";
import clsx from "clsx";
import { ArrowRight, Plus } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { track } from "@/lib/track";

/** DESIGN.md §5.2. Primary: orange pill with a white circle holding + or →. Text on orange is navy (white would be 2.9:1). */
export function MButton({ href, children, variant = "primary", icon = "plus", lead, sub, className, event, onClick }: {
  href: string; children: ReactNode; variant?: "primary" | "secondary" | "dark"; icon?: "plus" | "arrow" | "none"; lead?: ReactNode; sub?: string; className?: string; event?: string; onClick?: () => void;
}) {
  const base = "group inline-flex min-h-11 items-center gap-2 rounded-full text-[14px] font-medium tracking-[-.01em] transition-colors duration-200";
  const v = {
    primary: "bg-m-accent text-m-ink pl-5 pr-1.5 hover:bg-[#F06000]",
    dark: "bg-white text-m-navy pl-5 pr-1.5 hover:bg-white/90",
    secondary: "border border-m-ink/70 text-m-ink px-5 hover:bg-m-ink/[.04]",
  }[variant];
  return (
    <Link href={href} className={clsx(base, v, className)} onClick={() => { if (event) track(event); onClick?.(); }}>
      {lead && <span className="grid h-4 w-4 place-items-center" aria-hidden>{lead}</span>}
      {sub ? <span className="flex flex-col py-1 leading-tight"><span className="text-[10px] font-semibold uppercase tracking-[.04em] text-m-muted">{sub}</span><span>{children}</span></span> : children}
      {variant !== "secondary" && icon !== "none" && (
        <span aria-hidden className="grid h-8 w-8 place-items-center rounded-full bg-white text-m-accentStrong">
          {icon === "plus" ? <Plus className="h-4 w-4 transition-transform duration-300 group-hover:rotate-90" strokeWidth={2} /> : <ArrowRight className="h-4 w-4 transition-transform duration-300 group-hover:translate-x-[3px]" strokeWidth={2} />}
        </span>
      )}
    </Link>
  );
}

/** Label chip on bento cards (§5.3). */
export function Chip({ icon, children, tone = "white", className }: { icon?: ReactNode; children: ReactNode; tone?: "white" | "tint"; className?: string }) {
  return <span className={clsx("inline-flex h-8 items-center gap-1.5 rounded-[10px] px-3 t-small text-m-ink2", tone === "white" ? "bg-m-surface" : "bg-m-tint", className)}>{icon && <span aria-hidden className="text-m-accentStrong">{icon}</span>}{children}</span>;
}

/** Micro chip (hero right side). */
export function MicroChip({ icon, children }: { icon: ReactNode; children: ReactNode }) {
  return <span className="inline-flex h-7 items-center gap-1.5 rounded-lg bg-m-surface px-2.5 t-micro text-m-ink2 shadow-[0_1px_2px_rgba(11,15,46,.06)]"><span aria-hidden className="text-m-accentStrong">{icon}</span>{children}</span>;
}

/** "Coming soon" marker for anything not built yet (docs/marketing-site/FEATURE_STATUS.md). */
export function SoonChip({ className }: { className?: string }) {
  return <span className={clsx("inline-flex h-5 items-center rounded-full bg-m-ink/[.06] px-2 text-[10.5px] font-semibold uppercase tracking-[.04em] text-m-muted", className)}>Coming soon</span>;
}

/** Every number inside a UI mockup sits under this tag. */
export function SampleTag({ className, onDark }: { className?: string; onDark?: boolean }) {
  return <span className={clsx("pointer-events-none inline-flex h-[18px] items-center rounded-full px-2 text-[9.5px] font-semibold uppercase tracking-[.06em]", onDark ? "bg-white/15 text-white/80" : "bg-m-ink/[.06] text-m-muted", className)}>Sample data</span>;
}

/** Centered section heading + subline. */
export function SectionHead({ title, sub, align = "center", id }: { title: ReactNode; sub?: ReactNode; align?: "center" | "left"; id?: string }) {
  return (
    <div className={align === "center" ? "mx-auto max-w-[720px] text-center" : "max-w-[720px]"}>
      <h2 id={id} className="t-h2 text-m-ink">{title}</h2>
      {sub && <p className={clsx("mt-4 text-[15px] text-m-muted", align === "center" && "mx-auto max-w-[520px]")}>{sub}</p>}
    </div>
  );
}

/** The accent word in a headline. */
export const Accent = ({ children }: { children: ReactNode }) => <span className="text-m-accentText">{children}</span>;
