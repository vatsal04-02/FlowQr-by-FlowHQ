"use client";
import clsx from "clsx";
import { HelpCircle, LogOut, Moon, Sun } from "lucide-react";
import { motion } from "motion/react";
import Link from "next/link";
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode, type RefObject } from "react";
import { locate, NAV, sectionHref, type Item, type Section } from "@/lib/nav";
import { useTheme } from "@/lib/theme";

/** Close a popover on outside press or Escape (focus goes back to its trigger). */
export function useDismiss(ref: RefObject<HTMLElement | null>, open: boolean, close: () => void, trigger?: RefObject<HTMLElement | null>) {
  useEffect(() => {
    if (!open) return;
    const down = (e: MouseEvent | TouchEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) close(); };
    const key = (e: globalThis.KeyboardEvent) => { if (e.key === "Escape") { close(); trigger?.current?.focus(); } };
    document.addEventListener("mousedown", down); document.addEventListener("touchstart", down); document.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", down); document.removeEventListener("touchstart", down); document.removeEventListener("keydown", key); };
  }, [ref, open, close, trigger]);
}

export const iconBtn = "relative grid h-11 w-11 shrink-0 place-items-center rounded-full text-ink transition-colors hover:bg-surface-2";

/** A button in the top bar that opens a small floating card underneath it. */
export function PopoverButton({ label, icon, children, align = "right", dot, className, buttonClass }: {
  label: string; icon: ReactNode; children: (close: () => void) => ReactNode; align?: "left" | "right"; dot?: boolean; className?: string; buttonClass?: string;
}) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null), btn = useRef<HTMLButtonElement>(null);
  useDismiss(wrap, open, () => setOpen(false), btn);
  return (
    <div ref={wrap} className={clsx("relative", className)}>
      <button ref={btn} type="button" aria-label={label} aria-expanded={open} aria-haspopup="dialog" onClick={() => setOpen((o) => !o)} className={buttonClass ?? iconBtn}>
        {icon}{dot && <span aria-hidden className="absolute right-[11px] top-[10px] h-2 w-2 rounded-full bg-accent ring-2 ring-surface" />}
      </button>
      {open && (
        <div role="dialog" aria-label={label} className={clsx("fq-enter absolute top-[calc(100%+10px)] z-50 w-[min(92vw,340px)] rounded-card bg-surface p-2 text-sm shadow-lift", align === "right" ? "right-0" : "left-0")}>
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}

/** The four sections as one pill; the black indicator slides to the current one (spring 380/32, DESIGN.md §8). */
export function SectionNav({ path }: { path: string }) {
  const here = locate(path)?.section.id;
  return (
    <nav aria-label="Main" className="pill flex h-14 items-center p-1.5">
      <ul className="flex">
        {NAV.map((s) => {
          const on = here === s.id;
          return (
            <li key={s.id}>
              <Link href={sectionHref(s)} aria-current={on ? "page" : undefined}
                className={clsx("relative grid h-11 place-items-center rounded-full px-3.5 text-sm font-medium transition-colors xl:px-5", on ? "text-ink-on" : "text-ink hover:bg-surface-2")}>
                {on && <motion.span layoutId="fq-section-indicator" aria-hidden className="absolute inset-0 rounded-full bg-ink-solid" transition={{ type: "spring", stiffness: 380, damping: 32 }} />}
                <span className="relative whitespace-nowrap">{s.label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

/** Sun / moon. The selected mode sits in a grey circle; switching grows the new theme out of the button. */
export function ThemeToggle({ vertical = true }: { vertical?: boolean }) {
  const { resolved, setTheme } = useTheme();
  const b = (mode: "light" | "dark", Icon: typeof Sun, label: string) => (
    <button type="button" aria-label={label} aria-pressed={resolved === mode}
      onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); setTheme(mode, { x: r.left + r.width / 2, y: r.top + r.height / 2 }); }}
      className={clsx(iconBtn, resolved === mode && "bg-surface-2")}><Icon className="h-[18px] w-[18px]" strokeWidth={1.75} aria-hidden /></button>
  );
  return <div className={clsx("pill flex gap-1.5 p-1", vertical ? "w-[52px] flex-col" : "")}>{b("light", Sun, "Light mode")}{b("dark", Moon, "Dark mode")}</div>;
}

/**
 * Left rail: the current section's pages as icons. Hover or keyboard focus opens a labelled flyout over the content (180 ms in, 120 ms
 * out, Esc closes); Arrow Up/Down move between pages. The flyout is a visual label for the icons, so it is hidden from assistive tech and
 * out of the tab order; every icon link carries its own name.
 */
export function Rail({ section, path, util }: { section: Section; path: string; util: ReactNode }) {
  const current = locate(path)?.item;
  const [open, setOpen] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  const wrap = useRef<HTMLDivElement>(null);
  const show = () => { window.clearTimeout(timer.current); setOpen(true); };
  const hide = (ms = 120) => { window.clearTimeout(timer.current); timer.current = window.setTimeout(() => setOpen(false), ms); };
  useEffect(() => () => window.clearTimeout(timer.current), []);
  useEffect(() => setOpen(false), [path]);
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") { setOpen(false); return; }
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const links = Array.from(wrap.current?.querySelectorAll<HTMLAnchorElement>("[data-rail]") ?? []);
    const i = links.indexOf(document.activeElement as HTMLAnchorElement);
    if (i < 0) return;
    e.preventDefault();
    links[(i + (e.key === "ArrowDown" ? 1 : -1) + links.length) % links.length]?.focus();
    setOpen(true);
  };
  return (
    <aside aria-label="Pages in this section" className="sticky top-5 z-40 hidden min-h-[max(580px,calc(100dvh-136px))] flex-col gap-5 self-start lg:flex">
      <ThemeToggle />
      <div ref={wrap} className="relative mt-14" onMouseEnter={show} onMouseLeave={() => hide()} onFocus={show}
        onBlur={(e) => { if (!wrap.current?.contains(e.relatedTarget as Node)) hide(0); }} onKeyDown={onKey}>
        <nav aria-label={`${section.label} pages`} className="pill flex w-[52px] flex-col gap-1.5 p-1">
          {section.items.map((it) => <RailLink key={it.href} item={it} on={current?.href === it.href} />)}
        </nav>
        <div aria-hidden className={clsx("absolute left-full top-[-4px] pl-3 transition-[opacity,transform] duration-[180ms]", open ? "visible translate-x-0 opacity-100" : "invisible -translate-x-1.5 opacity-0")}>
          <div className="w-[264px] rounded-card bg-surface p-2 shadow-lift">
            <p className="px-3 pb-1.5 pt-2.5 text-xs font-medium text-muted">{section.label}</p>
            {section.items.map((it) => {
              const on = current?.href === it.href;
              return (
                <Link key={it.href} href={it.href} tabIndex={-1} className={clsx("flex items-center gap-3 rounded-full py-1.5 pl-1.5 pr-3 transition-colors hover:bg-surface-2", on && "bg-surface-2")}>
                  <span className={clsx("grid h-9 w-9 shrink-0 place-items-center rounded-full", on ? "bg-ink-solid text-ink-on" : "bg-surface-2")}><it.icon className="h-[17px] w-[17px]" strokeWidth={1.75} /></span>
                  <span className="min-w-0"><span className="block truncate font-medium">{it.label}</span><span className="block truncate text-xs text-muted">{it.desc}</span></span>
                </Link>
              );
            })}
          </div>
        </div>
      </div>
      <div className="pill mt-auto flex w-[52px] flex-col gap-1.5 p-1">{util}</div>
    </aside>
  );
}

function RailLink({ item, on }: { item: Item; on: boolean }) {
  return (
    <Link data-rail href={item.href} aria-label={item.label} aria-current={on ? "page" : undefined}
      className={clsx(iconBtn, on && "!bg-ink-solid !text-ink-on")}>
      <item.icon className="h-[18px] w-[18px]" strokeWidth={1.75} aria-hidden />
    </Link>
  );
}

/** Help and log out, pinned to the bottom of the rail (and in the account menu on phones). */
export function UtilButtons({ onLogout, help }: { onLogout: () => void; help: ReactNode }) {
  return (
    <>
      {help}
      <button type="button" aria-label="Log out" onClick={onLogout} className={iconBtn}><LogOut className="h-[18px] w-[18px]" strokeWidth={1.75} aria-hidden /></button>
    </>
  );
}

/** Phones and tablets: the four sections as a floating pill at the bottom (DESIGN.md §9). */
export function MobileBar({ path }: { path: string }) {
  const here = locate(path)?.section.id;
  return (
    <nav aria-label="Primary" className="pill fixed inset-x-4 bottom-[calc(14px+env(safe-area-inset-bottom))] z-40 flex gap-0.5 p-1.5 lg:hidden">
      {NAV.map((s) => {
        const on = here === s.id;
        return (
          <Link key={s.id} href={sectionHref(s)} aria-current={on ? "page" : undefined}
            className={clsx("flex h-[52px] min-w-0 flex-1 flex-col items-center justify-center gap-0.5 rounded-full text-[11px] font-semibold leading-[14px] transition-colors", on ? "bg-ink-solid text-ink-on" : "text-muted")}>
            <s.icon className="h-[18px] w-[18px]" strokeWidth={on ? 2.1 : 1.75} aria-hidden /><span className="truncate px-1">{s.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}

/**
 * Under the top bar: on phones the section's pages as a chip scroller (the rail's job on desktop), and on every screen the sibling pages
 * of the current item as small pills (for example Cards | Designs & export).
 */
export function SubNav({ path, section }: { path: string; section: Section | null }) {
  const l = locate(path);
  const chipRef = useRef<HTMLAnchorElement>(null);
  useEffect(() => { chipRef.current?.scrollIntoView({ block: "nearest", inline: "center" }); }, [path]);
  if (!l) return null;
  const items = section?.items ?? l.section.items;
  return (
    <>
      <nav aria-label={`${l.section.label} pages (scroll)`} className="-mx-4 mb-4 overflow-x-auto px-4 pb-1 no-scrollbar lg:hidden">
        <ul className="flex gap-2">
          {items.map((it) => {
            const on = l.item.href === it.href;
            return (
              <li key={it.href} className="shrink-0">
                <Link ref={on ? chipRef : undefined} href={it.href} aria-current={on ? "page" : undefined}
                  className={clsx("inline-flex h-10 items-center whitespace-nowrap rounded-full px-4 text-sm font-medium shadow-pill transition-colors", on ? "bg-ink-solid text-ink-on" : "bg-surface text-ink")}>{it.label}</Link>
              </li>
            );
          })}
        </ul>
      </nav>
      {l.item.sub && (
        <nav aria-label={`${l.item.label} pages`} className="mb-5">
          <ul className="inline-flex max-w-full flex-wrap gap-1 rounded-full bg-surface p-1 shadow-pill">
            {l.item.sub.map((x) => {
              const on = l.sub?.href === x.href;
              return <li key={x.href}><Link href={x.href} aria-current={on ? "page" : undefined}
                className={clsx("inline-flex min-h-10 items-center whitespace-nowrap rounded-full px-4 text-sm font-medium transition-colors sm:min-h-9", on ? "bg-ink-solid text-ink-on" : "text-muted hover:text-ink")}>{x.label}</Link></li>;
            })}
          </ul>
        </nav>
      )}
    </>
  );
}

export type Notice = { id: string; tone: "warn" | "bad" | "info"; title: string; body: string; href: string; cta: string };

export function HelpMenu({ supportEmail, onSearch, align = "right", inRail }: { supportEmail: string | null | undefined; onSearch: () => void; align?: "left" | "right"; inRail?: boolean }) {
  return (
    <PopoverButton label="Help" align={align} className={inRail ? "[&>[role=dialog]]:bottom-0 [&>[role=dialog]]:left-[calc(100%+12px)] [&>[role=dialog]]:top-auto" : undefined}
      icon={<HelpCircle className="h-[18px] w-[18px]" strokeWidth={1.75} aria-hidden />}>
      {(close) => (
        <div className="p-1">
          <p className="px-2 pb-1 pt-1.5 text-xs font-medium text-muted">Help</p>
          <button type="button" onClick={() => { close(); onSearch(); }} className="flex w-full items-center justify-between gap-3 rounded-full px-3 py-2.5 text-left font-medium hover:bg-surface-2">
            Search and jump to any page<kbd className="rounded-md bg-surface-2 px-1.5 py-0.5 font-sans text-xs text-muted">Ctrl K</kbd>
          </button>
          {supportEmail
            ? <a href={`mailto:${supportEmail}`} className="block rounded-full px-3 py-2.5 font-medium hover:bg-surface-2">Email support <span className="font-normal text-muted">({supportEmail})</span></a>
            : <p className="px-3 py-2.5 text-muted">A support address hasn&rsquo;t been set up on this server yet.</p>}
          <div className="flex gap-3 px-3 pb-1.5 pt-1 text-[13px] text-muted"><Link href="/privacy" className="hover:text-ink hover:underline">Privacy</Link><Link href="/terms" className="hover:text-ink hover:underline">Terms</Link></div>
        </div>
      )}
    </PopoverButton>
  );
}
