"use client";
import clsx from "clsx";
import { ArrowRight } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";
import { track } from "@/lib/track";

/** Pill button, regular weight. Primary: orange fill. `icon="arrow"` adds a plain arrow after the label. Text on orange is navy (white would be 2.9:1). */
export function MButton({ href, children, variant = "primary", icon = "none", lead, sub, className, event, onClick }: {
  href: string; children: ReactNode; variant?: "primary" | "secondary" | "dark"; icon?: "arrow" | "none"; lead?: ReactNode; sub?: string; className?: string; event?: string; onClick?: () => void;
}) {
  const base = "group inline-flex min-h-11 items-center gap-2 rounded-full text-[14px] font-normal tracking-[-.01em] transition-colors duration-200";
  const v = {
    primary: "bg-m-accent text-m-ink px-5 hover:bg-[#F06000]",
    dark: "bg-white text-m-navy px-5 hover:bg-white/90",
    secondary: "border border-m-ink/70 text-m-ink px-5 hover:bg-m-ink/[.04]",
  }[variant];
  return (
    <Link href={href} className={clsx(base, v, className)} onClick={() => { if (event) track(event); onClick?.(); }}>
      {lead && <span className="grid h-4 w-4 place-items-center" aria-hidden>{lead}</span>}
      {sub ? <span className="flex flex-col py-1 leading-tight"><span className="text-[10px] font-semibold uppercase tracking-[.04em] text-m-muted">{sub}</span><span>{children}</span></span> : children}
      {icon === "arrow" && <ArrowRight aria-hidden className="h-4 w-4 transition-transform duration-300 group-hover:translate-x-[3px]" strokeWidth={1.75} />}
    </Link>
  );
}

/** Label chip on bento cards (§5.3). */
export function Chip({ icon, children, tone = "white", className }: { icon?: ReactNode; children: ReactNode; tone?: "white" | "tint"; className?: string }) {
  return <span className={clsx("inline-flex h-8 items-center gap-1.5 rounded-[10px] px-3 t-small text-m-ink2", tone === "white" ? "bg-m-surface" : "bg-m-tint", className)}>{icon && <span aria-hidden className="text-m-accentStrong">{icon}</span>}{children}</span>;
}

/** Uppercase section badge ("SET UP IN ONE DAY"). Navy text on the peach tint; the orange dot carries the accent (orange text this small would miss 4.5:1). */
export function Badge({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={clsx("inline-flex h-7 items-center gap-2 rounded-full bg-m-tint px-3 text-[11px] font-semibold uppercase tracking-[.08em] text-m-ink2", className)}><span aria-hidden className="h-1.5 w-1.5 rounded-full bg-m-accent" />{children}</span>;
}

/** The Google "G" (the supplied image sits on a light grey square, so the round tile matches it). `size` is px, or a CSS length such as "0.8em" to scale with a heading. */
export function GoogleG({ size = 28, className }: { size?: number | string; className?: string }) {
  const css = typeof size === "number" ? `${size}px` : size;
  return <span aria-hidden className={clsx("inline-grid shrink-0 place-items-center overflow-hidden rounded-full bg-[#F5F5F5] ring-1 ring-m-line", className)} style={{ width: css, height: css }}><Image src="/marketing/google-g.webp" alt="" width={96} height={96} className="h-full w-full object-cover" /></span>;
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
