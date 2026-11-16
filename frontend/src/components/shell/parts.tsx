"use client";
import clsx from "clsx";
import { Check, ChevronDown, HelpCircle, Moon, Sun } from "lucide-react";
import { Sheet } from "../ui/Sheet";
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
 * Page tabs: the pages inside the current section, and a lighter second row for pages that share a theme. At most four tabs, sharing the width equally, so no
 * label is ever cut on a 390px phone. A section with more pages shows the current page as a button that opens a list (one sheet), never a cut-off strip.
 */
export function SubNav({ path, dests, hidePrimaryOnWide }: { path: string; dests: Dest[]; hidePrimaryOnWide?: boolean }) {
  const l = locate(path);
  const [pick, setPick] = useState<null | { label: string; items: { href: string; label: string }[]; on: string | null }>(null);
  if (!l) return null;
  const dest = dests.find((d) => d.id === l.dest.id) ?? l.dest;
  const kids = dest.children ?? [];
  const child = kids.find((c) => c.href === l.child?.href) ?? null;
  const row = (label: string, items: { href: string; label: string }[], current: string | null, small?: boolean, hideWide?: boolean) => {
    if (items.length > 4) {
      const now = items.find((x) => x.href === current) ?? items[0];
      return (
        <nav aria-label={label} className={clsx(small ? "mb-3" : "mb-4", hideWide && "md:hidden")}>
          <button type="button" aria-haspopup="dialog" onClick={() => setPick({ label, items, on: current })}
            className="flex min-h-11 w-full items-center justify-between gap-3 rounded-[12px] bg-surface px-3 text-[14px] font-medium ring-1 ring-line hover:bg-surface-2 sm:w-auto sm:min-w-[240px]">
            <span className="truncate">{now.label}</span><ChevronDown className="h-4 w-4 shrink-0 text-ink-400" aria-hidden />
          </button>
        </nav>
      );
    }
    return (
      <nav aria-label={label} className={clsx(small ? "mb-3" : "mb-4", hideWide && "md:hidden")}>
        <ul className={clsx("grid gap-1", small ? "rounded-[12px] bg-surface-2 p-1" : "border-b border-line")} style={{ gridTemplateColumns: `repeat(${items.length}, minmax(0, 1fr))` }}>
          {items.map((x) => {
            const active = x.href === current;
            return (
              <li key={x.href} className="min-w-0">
                <Link href={x.href} aria-current={active ? "page" : undefined}
                  className={clsx("relative flex min-h-11 items-center justify-center whitespace-nowrap px-2 text-center font-medium transition-colors",
                    small ? clsx("rounded-[10px] text-[13px] sm:min-h-9", active ? "bg-surface text-ink shadow-card" : "text-muted hover:text-ink")
                      : clsx("text-[14px]", active ? "text-ink" : "text-muted hover:text-ink"))}>
                  {x.label}
                  {!small && active && <span aria-hidden className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-ink-solid" />}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    );
  };
  const tabNow = child?.tabs ? (l.tab?.href ?? child.href) : null;
  return (
    <>
      {kids.length > 1 && row(`${dest.label} pages`, kids, child?.href ?? null, false, hidePrimaryOnWide)}
      {child?.tabs && child.tabs.length > 1 && row(`${child.label} sections`, child.tabs, tabNow, true)}
      <Sheet open={!!pick} onClose={() => setPick(null)} title={pick?.label.replace(/ (pages|sections)$/, "") ?? ""}>
        <ul className="pb-2">
          {pick?.items.map((x) => (
            <li key={x.href}><Link href={x.href} onClick={() => setPick(null)} aria-current={x.href === pick.on ? "page" : undefined}
              className={clsx("flex min-h-12 items-center justify-between rounded-[12px] px-3 text-[15px]", x.href === pick.on ? "bg-surface-2 font-semibold" : "hover:bg-surface-2")}>
              {x.label}{x.href === pick.on && <Check className="h-4 w-4" aria-hidden />}</Link></li>
          ))}
        </ul>
      </Sheet>
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
