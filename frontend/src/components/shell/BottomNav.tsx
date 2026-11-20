"use client";
import clsx from "clsx";
import { ChevronRight, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { MoreGlyph } from "@/components/icons/Nav";
import { BOTTOM_IDS, bottomActive, moreFor, type Dest } from "@/lib/nav";
import type { Role } from "@/lib/types";

/**
 * Phone navigation: a floating glass dock with five fixed destinations (Home, Reviews, GBP, Growth, More), an icon and a visible name each, every target at least 56px tall, above the
 * home indicator, with matching bottom padding on the page so nothing hides behind it. Hidden from tablet width up, where the sidebar takes over.
 * It answers the tap before the page does: the highlight starts gliding to the pressed item at once (not when the next page has loaded), the glyph lifts and fills in, and the press gives
 * a small squeeze. Reduced motion skips the glide and the squeeze (MotionConfig in the app shell).
 */
export function BottomNav({ path, dests, moreOpen, onMore }: { path: string; dests: Dest[]; moreOpen: boolean; onMore: (open: boolean) => void }) {
  const [pending, setPending] = useState<string | null>(null);
  useEffect(() => { setPending(null); }, [path]);               // the page arrived: the real route takes over
  const active = pending ?? bottomActive(path);
  const four = BOTTOM_IDS.map((id) => dests.find((d) => d.id === id)).filter((d): d is Dest => !!d);
  const item = "relative flex !min-h-[56px] w-full flex-col items-center justify-center gap-[3px] rounded-[18px] px-1 text-[12px] font-semibold leading-[14px] transition-colors duration-300";
  const pill = <motion.span layoutId="dock-on" aria-hidden className="absolute inset-0.5 rounded-[18px] bg-accent-tint shadow-[inset_0_1px_0_rgb(255_255_255/.6)]" transition={{ type: "spring", stiffness: 380, damping: 34, mass: 0.9 }} />;
  const glyph = (Icon: Dest["icon"], on: boolean) => (
    <motion.span aria-hidden className="relative grid place-items-center" animate={{ y: on ? -1.5 : 0, scale: on ? 1.08 : 1 }} transition={{ type: "spring", stiffness: 420, damping: 26 }}>
      <Icon className="h-[23px] w-[23px]" strokeWidth={on ? 1.9 : 1.7} />
    </motion.span>
  );
  const tap = { scale: 0.9 };
  return (
    <nav aria-label="Primary" className="fixed inset-x-3 bottom-[calc(10px+env(safe-area-inset-bottom))] z-40 md:hidden">
      <ul className="dock grid grid-cols-5 rounded-[24px] p-1">
        {four.map((d) => {
          const on = active === d.id && !moreOpen;
          return (
            <li key={d.id}>
              <Link href={d.href} aria-current={bottomActive(path) === d.id && !moreOpen ? "page" : undefined} data-on={on ? "" : undefined} onClick={() => setPending(d.id)}
                className={clsx(item, on ? "text-accent-ink" : "text-ink-500 active:text-ink")}>
                {on && pill}
                <motion.span className="relative flex flex-col items-center gap-[3px]" whileTap={tap} transition={{ type: "spring", stiffness: 500, damping: 30 }}>
                  {glyph(d.icon, on)}
                  {d.short ? <><span aria-hidden>{d.short}</span><span className="sr-only">{d.label}</span></> : <span>{d.label}</span>}
                </motion.span>
              </Link>
            </li>
          );
        })}
        <li>
          <button type="button" aria-haspopup="dialog" aria-expanded={moreOpen} data-on={active === "more" || moreOpen ? "" : undefined} onClick={() => onMore(!moreOpen)}
            className={clsx(item, active === "more" || moreOpen ? "text-accent-ink" : "text-ink-500 active:text-ink")}>
            {(active === "more" || moreOpen) && pill}
            <motion.span className="relative flex flex-col items-center gap-[3px]" whileTap={tap} transition={{ type: "spring", stiffness: 500, damping: 30 }}>
              {glyph(MoreGlyph, active === "more" || moreOpen)}
              <span>More</span>
            </motion.span>
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
                  <h3 className="px-3 pb-1 text-[13px] font-medium text-muted">{g.label}</h3>
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
