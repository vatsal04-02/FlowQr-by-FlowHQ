"use client";
import clsx from "clsx";
import { HelpCircle, Moon, Sun } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode, type RefObject } from "react";
import { locate, type Dest } from "@/lib/nav";
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

/** Sun / moon. The selected mode sits in a grey circle; switching grows the new theme out of the button. */
export function ThemeToggle({ vertical = false, small = false }: { vertical?: boolean; small?: boolean }) {
  const { resolved, setTheme } = useTheme();
  const b = (mode: "light" | "dark", Icon: typeof Sun, label: string) => (
    <button type="button" aria-label={label} aria-pressed={resolved === mode}
      onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); setTheme(mode, { x: r.left + r.width / 2, y: r.top + r.height / 2 }); }}
      className={clsx(iconBtn, small && "!h-9 !w-9", resolved === mode && "bg-surface text-accent-ink shadow-pill")}><Icon className="h-[18px] w-[18px]" strokeWidth={1.75} aria-hidden /></button>
  );
  return <div className={clsx("flex gap-0.5 rounded-full bg-surface-3 p-0.5", vertical && "flex-col")}>{b("light", Sun, "Light mode")}{b("dark", Moon, "Dark mode")}</div>;
}

/**
 * Page tabs: the pages that belong to the current destination (for example Results: Google activity, Reviews, QR & NFC, Campaigns, Reports), and a second row for
 * pages that share a theme (Your Google profile: Improve, Business info, Hours, Posts, Photos). It is the only secondary navigation, so there is one way to move around.
 * Underlined tabs scroll sideways on a phone and never wrap.
 */
export function SubNav({ path, dests, hidePrimaryOnWide }: { path: string; dests: Dest[]; hidePrimaryOnWide?: boolean }) {
  const l = locate(path);
  const ref = useRef<HTMLAnchorElement>(null);
  useEffect(() => { ref.current?.scrollIntoView({ block: "nearest", inline: "center" }); }, [path]);
  if (!l) return null;
  const dest = dests.find((d) => d.id === l.dest.id) ?? l.dest;
  const kids = dest.children ?? [];
  const child = kids.find((c) => c.href === l.child?.href) ?? null;
  const strip = (label: string, items: { href: string; label: string }[], on: (href: string) => boolean, small?: boolean, hideWide?: boolean) => (
    <nav aria-label={label} className={clsx("-mx-4 overflow-x-auto px-4 no-scrollbar sm:mx-0 sm:px-0", small ? "mb-3" : "mb-4", hideWide && "md:hidden")}>
      <ul className={clsx("flex w-max min-w-full gap-1 border-b border-ink-100", small && "border-b-0")}>
        {items.map((x) => {
          const active = on(x.href);
          return (
            <li key={x.href} className="shrink-0">
              <Link ref={active ? ref : undefined} href={x.href} aria-current={active ? "page" : undefined}
                className={clsx("relative inline-flex items-center whitespace-nowrap transition-colors",
                  small ? "min-h-11 rounded-full px-3 text-[13px] font-medium sm:min-h-9" : "min-h-11 px-3 text-sm font-medium",
                  small ? (active ? "bg-surface-3 text-ink" : "text-muted hover:text-ink") : (active ? "text-ink" : "text-muted hover:text-ink"))}>
                {x.label}
                {!small && active && <span aria-hidden className="absolute inset-x-3 -bottom-px h-0.5 rounded-full bg-accent" />}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
  return (
    <>
      {kids.length > 1 && strip(`${dest.label} pages`, kids, (h) => child?.href === h, false, hidePrimaryOnWide)}
      {child?.tabs && child.tabs.length > 1 && strip(`${child.label} sections`, child.tabs, (h) => l.tab?.href === h || (!l.tab && h === child.href), true)}
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
