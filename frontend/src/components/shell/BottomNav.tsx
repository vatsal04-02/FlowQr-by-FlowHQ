"use client";
import clsx from "clsx";
import { X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { MoreGlyph } from "@/components/icons/Nav";
import { BOTTOM_IDS, bottomActive, moreFor, type Dest, type MoreTint } from "@/lib/nav";
import type { Role } from "@/lib/types";

/** The bar is 72px tall (docs/DESIGN_SETTINGS_MOBILE.md §6); the More sheet sits directly above it, so both read the same number. */
const BAR = "72px";

/**
 * Phone navigation: a flat 72px bar with five fixed destinations (Home, Reviews, Google, Growth, More): a 22px icon in a 56x30 pill, a 12px name always visible, the current one in a
 * soft indigo pill with a heavier navy label, above the home indicator. The page keeps matching bottom padding so nothing hides behind it. Hidden from tablet width up, where the sidebar
 * takes over. The pill glides to the pressed item at once (not when the next page has loaded); reduced motion skips the glide (MotionConfig in the app shell).
 */
export function BottomNav({ path, dests, moreOpen, onMore }: { path: string; dests: Dest[]; moreOpen: boolean; onMore: (open: boolean) => void }) {
  const [pending, setPending] = useState<string | null>(null);
  useEffect(() => { setPending(null); }, [path]);               // the page arrived: the real route takes over
  const active = pending ?? bottomActive(path);
  const four = BOTTOM_IDS.map((id) => dests.find((d) => d.id === id)).filter((d): d is Dest => !!d);
  const item = "set-focus relative flex h-[72px] w-full flex-col items-center justify-center gap-1 px-0.5";
  const cell = (Icon: Dest["icon"], on: boolean, label: string, sr?: string) => (
    <>
      <span className="relative grid h-[30px] w-14 place-items-center rounded-full">
        {on && <motion.span layoutId="bar-pill" aria-hidden className="absolute inset-0 rounded-full bg-set-info-bg" transition={{ type: "spring", stiffness: 420, damping: 38 }} />}
        <Icon aria-hidden className={clsx("relative h-[22px] w-[22px]", on ? "text-set-navy dark:text-set-ink" : "text-set-soft")} strokeWidth={1.8} />
      </span>
      <span aria-hidden={sr ? true : undefined} className={clsx("text-[12px] leading-[14px]", on ? "font-extrabold text-set-navy dark:text-set-ink" : "font-semibold text-set-soft")}>{label}</span>
      {sr && <span className="sr-only">{sr}</span>}
    </>
  );
  return (
    <nav aria-label="Primary" className="fixed inset-x-0 bottom-0 z-[55] border-t border-set-line bg-set-surface pb-[env(safe-area-inset-bottom)] md:hidden">
      <ul className="grid h-[72px] grid-cols-5 px-1">
        {four.map((d) => {
          const on = active === d.id && !moreOpen;
          return (
            <li key={d.id}>
              <Link href={d.href} aria-current={bottomActive(path) === d.id && !moreOpen ? "page" : undefined} onClick={() => setPending(d.id)} className={item}>
                {cell(d.icon, on, d.short ?? d.label, d.short ? d.label : undefined)}
              </Link>
            </li>
          );
        })}
        <li>
          <button type="button" aria-haspopup="dialog" aria-expanded={moreOpen} onClick={() => onMore(!moreOpen)} className={item}>
            {cell(MoreGlyph, active === "more" || moreOpen, "More")}
          </button>
        </li>
      </ul>
    </nav>
  );
}

/** The tile's icon colours: the same group tints as Settings (tokens in globals.css). */
const TINT: Record<MoreTint, string> = {
  connect: "bg-set-t-connect text-set-i-connect", business: "bg-set-t-business text-set-i-business", prefs: "bg-set-t-prefs text-set-i-prefs",
  billing: "bg-set-t-billing text-set-i-billing", security: "bg-set-t-security text-set-i-security",
};

/**
 * The More sheet: everything that is not one of the four main places, in three labelled groups of two-column tiles (56px high, a tinted 32px icon, a plain name). It rises from just above
 * the bar over a navy scrim, closes with its button, the scrim, Escape or by choosing a page, keeps keyboard focus inside while open and returns focus to the More button.
 * Motion respects the reduced-motion setting (MotionConfig in the app shell).
 */
export function MoreSheet({ open, onClose, role, whatsapp = false, onSearch, supportEmail }: { open: boolean; onClose: () => void; role: Role | null; whatsapp?: boolean; onSearch: () => void; supportEmail: string | null | undefined }) {
  const panel = useRef<HTMLDivElement>(null);
  const closeBtn = useRef<HTMLButtonElement>(null);
  const back = useRef<Element | null>(null);
  const groups = moreFor(role, { whatsapp });

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
    const f = Array.from(panel.current?.querySelectorAll<HTMLElement>("a[href],button:not([disabled])") ?? []);
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  };

  const tile = "set-focus flex min-h-14 items-center gap-2.5 rounded-[14px] border border-set-line bg-set-surface px-3 text-left text-[14px] font-bold leading-tight text-set-ink active:bg-set-paper";
  return (
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-50 md:hidden" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.18 }} onKeyDown={onKey}>
          <button type="button" aria-label="Close menu" tabIndex={-1} onClick={onClose} className="absolute inset-0 bg-set-navy/50" />
          <motion.div ref={panel} role="dialog" aria-modal="true" aria-label="More"
            initial={{ y: "100%" }} animate={{ y: 0 }} exit={{ y: "100%" }} transition={{ type: "spring", stiffness: 420, damping: 42 }}
            style={{ bottom: `calc(${BAR} + env(safe-area-inset-bottom))`, maxHeight: `calc(100dvh - ${BAR} - env(safe-area-inset-bottom) - 16px)` }}
            className="absolute inset-x-0 flex flex-col gap-4 overflow-y-auto overscroll-contain rounded-t-3xl bg-set-paper px-4 pb-5 pt-2.5 shadow-[0_-8px_30px_rgba(20,22,58,.18)]">
            <span aria-hidden className="mx-auto h-[5px] w-10 shrink-0 rounded-full bg-set-line-strong" />
            <div className="-mt-1 flex items-center justify-between">
              <h2 className="text-xl font-extrabold text-set-ink">More</h2>
              <button ref={closeBtn} type="button" onClick={onClose} aria-label="Close" className="set-focus -mr-2 grid h-11 w-11 place-items-center rounded-full text-set-soft hover:bg-set-surface"><X className="h-5 w-5" aria-hidden /></button>
            </div>
            {groups.map((g) => (
              <section key={g.label} aria-label={g.label} className="space-y-2">
                <h3 className="px-0.5 text-[13px] font-extrabold text-set-soft">{g.label}</h3>
                <ul className="grid grid-cols-2 gap-2.5">
                  {g.items.map((it) => {
                    const icon = <span aria-hidden className={clsx("grid h-8 w-8 shrink-0 place-items-center rounded-xl", TINT[it.tint])}><it.icon className="h-[18px] w-[18px]" strokeWidth={1.8} /></span>;
                    return (
                      <li key={it.label}>
                        {it.help ? (
                          supportEmail
                            ? <a href={`mailto:${supportEmail}`} onClick={onClose} className={tile}>{icon}<span className="min-w-0">{it.label}</span></a>
                            : <button type="button" onClick={() => { onClose(); onSearch(); }} className={clsx(tile, "w-full")}>{icon}<span className="min-w-0">{it.label}</span></button>
                        ) : (
                          <Link href={it.href} onClick={onClose} className={tile}>{icon}<span className="min-w-0">{it.label}</span></Link>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </section>
            ))}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
