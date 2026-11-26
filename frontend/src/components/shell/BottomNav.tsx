"use client";
import clsx from "clsx";
import { motion } from "motion/react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { BOTTOM_IDS, bottomActive, type Dest } from "@/lib/nav";
import { badgeFor, type Counts } from "@/lib/use-counts";

/** The bar is 72px tall (docs/DESIGN_SETTINGS_MOBILE.md §6); the page keeps matching bottom padding so nothing hides behind it. */
const BAR = "72px";

/**
 * Phone navigation: a flat 72px bar with the four places of the app (Home, AI, Google, Settings): a 22px icon in a 56x30 pill, a 12px name always visible, the current one in a soft
 * indigo pill with a heavier navy label, above the home indicator. Nothing hides behind a "More" menu: every page lives inside one of the four (the pages of the current place are a swipeable
 * row at the top of the page). Hidden from tablet width up, where the sidebar takes over. The pill glides to the pressed item at once (not when the next page has loaded);
 * reduced motion skips the glide (MotionConfig in the app shell). AI carries the number of things waiting for the owner.
 */
export function BottomNav({ path, dests, counts = null }: { path: string; dests: Dest[]; counts?: Counts | null }) {
  const [pending, setPending] = useState<string | null>(null);
  useEffect(() => { setPending(null); }, [path]);               // the page arrived: the real route takes over
  const active = pending ?? bottomActive(path);
  const items = BOTTOM_IDS.map((id) => dests.find((d) => d.id === id)).filter((d): d is Dest => !!d);
  const item = "set-focus relative flex h-[72px] w-full flex-col items-center justify-center gap-1 px-0.5";
  return (
    <nav aria-label="Primary" className="fixed inset-x-0 bottom-0 z-[55] border-t border-set-line bg-set-surface pb-[env(safe-area-inset-bottom)] md:hidden" style={{ minHeight: BAR }}>
      <ul className="grid h-[72px] px-1" style={{ gridTemplateColumns: `repeat(${items.length || 1}, minmax(0, 1fr))` }}>
        {items.map((d) => {
          const on = active === d.id;
          const badge = badgeFor(d.id, counts);
          return (
            <li key={d.id}>
              <Link href={d.href} aria-current={bottomActive(path) === d.id ? "page" : undefined} onClick={() => setPending(d.id)} className={item}>
                <span className="relative grid h-[30px] w-14 place-items-center rounded-full">
                  {on && <motion.span layoutId="bar-pill" aria-hidden className="absolute inset-0 rounded-full bg-set-info-bg" transition={{ type: "spring", stiffness: 420, damping: 38 }} />}
                  <d.icon aria-hidden className={clsx("relative h-[22px] w-[22px]", on ? "text-set-navy dark:text-set-ink" : "text-set-soft")} strokeWidth={1.8} />
                  {badge !== null && (
                    <span className="num absolute -right-0.5 top-[-3px] grid min-w-[18px] place-items-center rounded-full bg-accent px-1 text-[11px] font-semibold leading-[18px] text-on-accent ring-2 ring-set-surface">
                      <span aria-hidden>{badge > 99 ? "99+" : badge}</span><span className="sr-only">{badge} waiting</span>
                    </span>
                  )}
                </span>
                <span className={clsx("text-[12px] leading-[14px]", on ? "font-extrabold text-set-navy dark:text-set-ink" : "font-semibold text-set-soft")}>{d.short ?? d.label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
