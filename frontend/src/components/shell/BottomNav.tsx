"use client";
import clsx from "clsx";
import { ChevronRight, LayoutGrid, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useEffect, useRef, type KeyboardEvent } from "react";
import { BOTTOM_IDS, bottomActive, moreFor, type Dest } from "@/lib/nav";
import type { Role } from "@/lib/types";

/**
 * Phone navigation: five fixed destinations with an icon and a visible name each (Home, Reviews, Visibility, Results, More). Every target is at least 56px tall, the bar sits
 * above the home indicator (safe-area inset) and the page keeps a matching bottom padding so nothing hides behind it. Hidden from tablet width up, where the sidebar takes over.
 */
export function BottomNav({ path, dests, moreOpen, onMore }: { path: string; dests: Dest[]; moreOpen: boolean; onMore: (open: boolean) => void }) {
  const active = bottomActive(path);
  const four = BOTTOM_IDS.map((id) => dests.find((d) => d.id === id)).filter((d): d is Dest => !!d);
  const base = "relative flex !min-h-[56px] flex-col items-center justify-center gap-0.5 px-1 text-[11px] font-semibold leading-[14px] transition-colors";
  return (
    <nav aria-label="Primary" className="fixed inset-x-0 bottom-0 z-40 border-t border-ink-100 bg-surface pb-[env(safe-area-inset-bottom)] md:hidden">
      <ul className="grid grid-cols-5">
        {four.map((d) => {
          const on = active === d.id && !moreOpen;
          return (
            <li key={d.id}>
              <Link href={d.href} aria-current={on ? "page" : undefined} className={clsx(base, "w-full", on ? "text-accent-ink" : "text-ink-500 active:text-ink")}>
                {on && <span aria-hidden className="absolute inset-x-5 top-0 h-[3px] rounded-b-full bg-accent" />}
                <d.icon className="h-[22px] w-[22px]" strokeWidth={on ? 2.1 : 1.75} aria-hidden /><span>{d.label}</span>
              </Link>
            </li>
          );
        })}
        <li>
          <button type="button" aria-haspopup="dialog" aria-expanded={moreOpen} onClick={() => onMore(!moreOpen)}
            className={clsx(base, "w-full", active === "more" || moreOpen ? "text-accent-ink" : "text-ink-500 active:text-ink")}>
            {(active === "more" || moreOpen) && <span aria-hidden className="absolute inset-x-5 top-0 h-[3px] rounded-b-full bg-accent" />}
            <LayoutGrid className="h-[22px] w-[22px]" strokeWidth={active === "more" || moreOpen ? 2.1 : 1.75} aria-hidden /><span>More</span>
          </button>
        </li>
      </ul>
    </nav>
  );
}

/**
 * The More sheet: everything that is not one of the four main places, in three named groups. It slides up over the page, closes with its button, the backdrop, Escape or by choosing a
 * page, keeps keyboard focus inside while open and returns focus to the More button. Motion respects the reduced-motion setting (MotionConfig in the app shell).
 */
export function MoreSheet({ open, onClose, role, onSearch, supportEmail }: { open: boolean; onClose: () => void; role: Role | null; onSearch: () => void; supportEmail: string | null | undefined }) {
  const panel = useRef<HTMLDivElement>(null);
  const closeBtn = useRef<HTMLButtonElement>(null);
  const back = useRef<Element | null>(null);
  const groups = moreFor(role);

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

  const row = "flex !min-h-[52px] w-full items-center gap-3 rounded-xl px-3 text-left transition-colors active:bg-surface-3 hover:bg-surface-2";
  return (
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-50 md:hidden" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.18 }} onKeyDown={onKey}>
          <button type="button" aria-label="Close menu" tabIndex={-1} onClick={onClose} className="absolute inset-0 bg-black/45" />
          <motion.div ref={panel} role="dialog" aria-modal="true" aria-label="More"
            initial={{ y: "100%" }} animate={{ y: 0 }} exit={{ y: "100%" }} transition={{ type: "spring", stiffness: 420, damping: 40 }}
            className="absolute inset-x-0 bottom-0 max-h-[88dvh] overflow-y-auto overscroll-contain rounded-t-[20px] bg-surface pb-[calc(20px+env(safe-area-inset-bottom))] shadow-lift">
            <div className="sticky top-0 z-10 flex items-center justify-between bg-surface px-4 pb-1 pt-3">
              <div className="flex items-center gap-3"><span aria-hidden className="h-1 w-9 rounded-full bg-ink-200" /><h2 className="text-lg font-semibold">More</h2></div>
              <button ref={closeBtn} type="button" onClick={onClose} aria-label="Close" className="grid h-11 w-11 place-items-center rounded-full text-ink-600 hover:bg-surface-2"><X className="h-5 w-5" aria-hidden /></button>
            </div>
            <div className="space-y-4 px-2 pt-1">
              {groups.map((g) => (
                <section key={g.label} aria-label={g.label}>
                  <h3 className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-[.06em] text-ink-400">{g.label}</h3>
                  <ul>
                    {g.items.map((it) => (
                      <li key={it.label}>
                        {it.help ? (
                          supportEmail
                            ? <a href={`mailto:${supportEmail}`} onClick={onClose} className={row}><Ico it={it} /><Text it={it} desc={`Email ${supportEmail}`} /></a>
                            : <button type="button" onClick={() => { onClose(); onSearch(); }} className={row}><Ico it={it} /><Text it={it} desc="Search the app for a page" /></button>
                        ) : (
                          <Link href={it.href} onClick={onClose} className={row}><Ico it={it} /><Text it={it} /><ChevronRight className="h-4 w-4 shrink-0 text-ink-300" aria-hidden /></Link>
                        )}
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

const Ico = ({ it }: { it: { icon: Dest["icon"] } }) => <span aria-hidden className="grid h-9 w-9 shrink-0 place-items-center rounded-[10px] bg-surface-2 text-ink-700"><it.icon className="h-[18px] w-[18px]" strokeWidth={1.75} /></span>;
const Text = ({ it, desc }: { it: { label: string; desc: string }; desc?: string }) => <span className="min-w-0 flex-1"><span className="block truncate text-[15px] font-medium">{it.label}</span><span className="block truncate text-[13px] text-muted">{desc ?? it.desc}</span></span>;
