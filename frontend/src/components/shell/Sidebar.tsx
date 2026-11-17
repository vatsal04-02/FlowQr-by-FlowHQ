"use client";
import clsx from "clsx";
import { ChevronDown, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";
import { GROUP_LABEL, locate, type Dest, type Group } from "@/lib/nav";
import { badgeFor, childBadge, type Counts } from "@/lib/use-counts";
import { Logo } from "../ui/Brand";
import { ThemeToggle } from "./parts";

export const SIDEBAR_W = { open: 232, rail: 68 } as const;

/**
 * The one left sidebar (tablet and desktop). Expanded it is 232px with the page names visible; collapsed it is a 68px icon rail (names move into tooltips and accessible
 * names). The page you are on is marked by an orange bar, and the pages inside the current destination fold open underneath it. Phones use the bottom bar instead.
 */
export function Sidebar({ path, dests, collapsed, onToggle, help, counts = null }: { path: string; dests: Dest[]; collapsed: boolean; onToggle: () => void; help: ReactNode; counts?: Counts | null }) {
  const here = locate(path);
  const [shut, setShut] = useState<Record<string, boolean>>({});  // destinations the person folded away by hand
  const groups: Group[] = ["main", "tools", "assistant", "account"];
  return (
    <aside aria-label="Main navigation" style={{ width: collapsed ? SIDEBAR_W.rail : SIDEBAR_W.open }}
      className="fixed inset-y-0 left-0 z-40 hidden flex-col border-r border-ink-100 bg-surface transition-[width] duration-200 ease-out motion-reduce:transition-none md:flex">
      <div className={clsx("flex h-16 shrink-0 items-center gap-2.5", collapsed ? "justify-center" : "px-4")}>
        <Logo href="/overview" auto markOnly={collapsed} tagline={false} size={collapsed ? 32 : 30} label="FlowQR home" className="px-1" />
      </div>

      <nav aria-label="Pages" className="min-h-0 flex-1 overflow-y-auto px-2.5 pb-3 pt-1">
        {groups.map((g) => {
          const items = dests.filter((d) => d.group === g);
          if (!items.length) return null;
          return (
            <div key={g} className={clsx(g !== "main" && "mt-4")}>
              {GROUP_LABEL[g] && !collapsed && <p className="px-3 pb-1 text-[12px] font-medium text-muted">{GROUP_LABEL[g]}</p>}
              {GROUP_LABEL[g] && collapsed && <div aria-hidden className="mx-3 mb-1 mt-1 border-t border-ink-100" />}
              <ul className="space-y-0.5">
                {items.map((d) => {
                  const on = here?.dest.id === d.id;
                  const kids = d.children ?? [];
                  const open = on && !collapsed && kids.length > 1 && !shut[d.id];
                  const badge = badgeFor(d.id, counts);
                  return (
                    <li key={d.id}>
                      <div className="relative flex items-center">
                        <Link href={d.href} data-on={on ? "" : undefined} title={collapsed ? d.label : undefined} aria-current={on && (kids.length < 2 || collapsed || shut[d.id]) ? "page" : undefined}
                          className={clsx("group relative flex min-h-11 flex-1 items-center gap-3 rounded-[10px] text-[14px] transition-colors md:min-h-10",
                            collapsed ? "justify-center px-0" : "pl-3 pr-2", on ? "bg-surface-2 font-semibold text-ink" : "font-medium text-ink-700 hover:bg-surface-2 hover:text-ink")}>
                          {/* the active marker springs in and out rather than appearing (the bar is always there, scaled to nothing when inactive) */}
                          <span aria-hidden className={clsx("absolute inset-y-2 left-0 w-[3px] origin-center rounded-r-full bg-accent transition-transform duration-300 ease-spring motion-reduce:transition-none", on ? "scale-y-100" : "scale-y-0")} />
                          <d.icon className={clsx("h-[19px] w-[19px] shrink-0 transition-[transform,color] duration-200 ease-spring group-hover:scale-110 motion-reduce:transition-none motion-reduce:group-hover:scale-100", on ? "text-accent-ink" : "text-ink-500 group-hover:text-ink")} strokeWidth={on ? 2 : 1.75} aria-hidden />
                          {collapsed ? <span className="sr-only">{d.label}</span> : <span className="min-w-0 flex-1 truncate">{d.label}</span>}
                          {badge !== null && (
                            <span className={clsx("num grid min-w-[20px] place-items-center rounded-full bg-accent px-1.5 text-[11px] font-semibold leading-5 text-on-accent motion-safe:animate-[fq-badge_.45s_cubic-bezier(.3,1.35,.5,1)_both]",
                              collapsed ? "absolute right-1.5 top-0.5 !min-w-[18px] !px-1 !leading-[18px] ring-2 ring-surface" : on && kids.length > 1 ? "mr-8" : "")}>
                              <span aria-hidden>{badge > 99 ? "99+" : badge}</span><span className="sr-only">{badge} waiting</span>
                            </span>
                          )}
                        </Link>
                        {!collapsed && on && kids.length > 1 && (
                          <button type="button" aria-label={open ? `Hide ${d.label} pages` : `Show ${d.label} pages`} aria-expanded={open} onClick={() => setShut((s) => ({ ...s, [d.id]: !s[d.id] }))}
                            className="absolute right-1 grid h-8 w-8 place-items-center rounded-lg text-ink-500 hover:bg-surface-3 hover:text-ink">
                            <ChevronDown className={clsx("h-4 w-4 transition-transform", open && "rotate-180")} aria-hidden />
                          </button>
                        )}
                      </div>
                      {open && (
                        <ul className="mb-1 ml-[22px] mt-0.5 space-y-0.5 border-l border-ink-100 pl-2">
                          {kids.map((c) => {
                            const cOn = here?.child?.href === c.href;
                            return (
                              <li key={c.href}>
                                <Link href={c.href} aria-current={cOn ? "page" : undefined}
                                  className={clsx("group/kid relative flex min-h-9 items-center rounded-lg px-3 text-[13px] transition-colors", cOn ? "bg-accent-tint font-semibold text-accent-ink" : "text-ink-600 hover:bg-surface-2 hover:text-ink")}>
                                  <span className="min-w-0 flex-1 truncate transition-transform duration-200 ease-out group-hover/kid:translate-x-0.5 motion-reduce:transition-none motion-reduce:group-hover/kid:translate-x-0">{c.label}</span>
                                  {childBadge(c.href, counts) !== null && <span className="num ml-2 rounded-full bg-surface-3 px-1.5 text-[11px] font-semibold leading-[18px] text-ink-700"><span aria-hidden>{childBadge(c.href, counts)}</span><span className="sr-only"> waiting</span></span>}
                                </Link>
                              </li>
                            );
                          })}
                        </ul>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
      </nav>

      <div className={clsx("flex shrink-0 items-center gap-1 border-t border-ink-100 p-2.5", collapsed ? "flex-col" : "justify-between")}>
        <div className={clsx("flex items-center gap-1", collapsed && "flex-col")}>
          {help}
          {!collapsed && <ThemeToggle small />}
        </div>
        <button type="button" onClick={onToggle} aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="grid h-11 w-11 place-items-center rounded-full text-ink-500 transition-colors hover:bg-surface-2 hover:text-ink">
          {collapsed ? <PanelLeftOpen className="h-[18px] w-[18px]" strokeWidth={1.75} aria-hidden /> : <PanelLeftClose className="h-[18px] w-[18px]" strokeWidth={1.75} aria-hidden />}
        </button>
      </div>
    </aside>
  );
}
