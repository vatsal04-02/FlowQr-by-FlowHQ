"use client";
import clsx from "clsx";
import { CornerDownLeft, MapPin, MessageSquare, QrCode, Search, Star } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { ROWS } from "@/components/settings/model";
import { useAuth } from "@/lib/auth";
import type { Dest } from "@/lib/nav";

type Entry = { key: string; label: string; hint: string; href: string; icon: Dest["icon"] };

/** Every page this person can see (and each page's sibling pages and tabs), flattened. */
const navPages = (dests: Dest[]): Entry[] => dests.flatMap((d) => [
  { key: d.href, label: d.label, hint: d.desc, href: d.href, icon: d.icon },
  ...(d.children ?? []).filter((c) => c.href !== d.href).flatMap((c) => [
    { key: c.href, label: c.label, hint: d.label, href: c.href, icon: d.icon },
    ...(c.tabs ?? []).filter((t) => t.href !== c.href).map((t) => ({ key: t.href, label: t.label, hint: `${d.label} · ${c.label}`, href: t.href, icon: d.icon })),
  ]),
]);

/** The settings pages (the sidebar lists Settings as one item): those this person may open, found by title or what is on them. */
const settingsPages = (admin: boolean, wa: boolean): Entry[] => {
  // billing and the audit log are for owners and admins only; WhatsApp shows while the server has it switched on
  return ROWS.filter((r) => (!r.only || admin) && (r.id !== "whatsapp" || wa)).map((r) => ({ key: r.href, label: r.title, hint: `Settings · ${r.sub}`, href: r.href, icon: r.icon }));
};
const pagesOf = (dests: Dest[], admin: boolean, wa: boolean): Entry[] => [...navPages(dests), ...settingsPages(admin, wa)];

/**
 * Ctrl/⌘ K: jump to any page, or search reviews by reviewer or text (opens the reviews inbox with that search). Keyboard first:
 * type, Arrow Up/Down, Enter; Esc closes and focus returns to where it was.
 */
export function CommandPalette({ open, onClose, dests }: { open: boolean; onClose: () => void; dests: Dest[] }) {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [i, setI] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const last = useRef<Element | null>(null);
  const listId = useId();

  const { isAdmin, me } = useAuth();
  const waOn = !!me?.integrations.whatsapp_enabled;
  const all = useMemo(() => pagesOf(dests, isAdmin, waOn), [dests, isAdmin, waOn]);
  // GET /search (reviews by reviewer or words, locations, cards), 200 ms after typing stops
  const [found, setFound] = useState<Entry[]>([]);
  useEffect(() => {
    const t = q.trim();
    if (t.length < 2) { setFound([]); return; }
    let live = true;
    const h = window.setTimeout(() => {
      type Hit = { id: string; label: string; hint: string; href: string };
      api<{ reviews: Hit[]; locations: Hit[]; cards: Hit[] }>("/search", { params: { q: t } }).then((r) => {
        if (!live) return;
        setFound([
          ...r.reviews.map((x) => ({ key: `r-${x.id}`, label: x.label, hint: x.hint, href: x.href, icon: Star })),
          ...r.locations.map((x) => ({ key: `l-${x.id}`, label: x.label, hint: x.hint, href: x.href, icon: MapPin })),
          ...r.cards.map((x) => ({ key: `c-${x.id}`, label: x.label, hint: x.hint, href: x.href, icon: QrCode })),
        ]);
      }).catch(() => { if (live) setFound([]); });
    }, 200);
    return () => { live = false; window.clearTimeout(h); };
  }, [q]);
  const results = useMemo(() => {
    const t = q.trim().toLowerCase();
    const pages = t ? all.filter((p) => `${p.label} ${p.hint}`.toLowerCase().includes(t)) : all;
    const search: Entry[] = t ? [{ key: "search-reviews", label: `Search reviews for “${q.trim()}”`, hint: "GBP Manager · Reviews & replies", href: `/gbp/reviews?q=${encodeURIComponent(q.trim())}`, icon: MessageSquare }] : [];
    return [...pages.slice(0, 7), ...found, ...search];
  }, [q, all, found]);

  useEffect(() => {
    if (!open) return;
    last.current = document.activeElement;
    setQ(""); setI(0);
    requestAnimationFrame(() => input.current?.focus());
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prev; (last.current as HTMLElement | null)?.focus?.(); };
  }, [open]);
  useEffect(() => setI(0), [q]);

  if (!open) return null;
  const go = (e: Entry | undefined) => { if (!e) return; onClose(); router.push(e.href); };
  return (
    <div className="fixed inset-0 z-[70] grid items-start justify-items-center bg-[rgba(13,10,16,.45)] px-4 pt-[12vh] backdrop-blur-[8px]" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div role="dialog" aria-modal="true" aria-label="Search and jump" className="fq-enter w-full max-w-[560px] overflow-hidden rounded-card bg-surface shadow-lift">
        <div className="flex items-center gap-3 px-5 pt-4">
          <Search className="h-5 w-5 shrink-0 text-muted" aria-hidden />
          <input ref={input} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Jump to a page or search reviews…" aria-label="Search pages and reviews"
            role="combobox" aria-expanded="true" aria-controls={listId} aria-activedescendant={results[i] ? `${listId}-${i}` : undefined}
            onKeyDown={(e) => {
              if (e.key === "Escape") { e.preventDefault(); onClose(); }
              else if (e.key === "ArrowDown") { e.preventDefault(); setI((n) => Math.min(results.length - 1, n + 1)); }
              else if (e.key === "ArrowUp") { e.preventDefault(); setI((n) => Math.max(0, n - 1)); }
              else if (e.key === "Enter") { e.preventDefault(); go(results[i]); }
            }}
            className="focus-inner h-12 w-full bg-transparent text-base text-ink outline-none placeholder:text-muted-soft" />
          <kbd className="hidden rounded-md bg-surface-2 px-1.5 py-0.5 font-sans text-xs text-muted sm:block">Esc</kbd>
        </div>
        <ul id={listId} role="listbox" aria-label="Results" className="max-h-[52vh] overflow-y-auto p-2">
          {results.length === 0 && <li className="px-3 py-6 text-center text-sm text-muted">No page matches. Try a different word.</li>}
          {results.map((r, n) => (
            <li key={r.key} id={`${listId}-${n}`} role="option" aria-selected={n === i} onMouseEnter={() => setI(n)} onClick={() => go(r)}
              className={clsx("flex cursor-pointer items-center gap-3 rounded-full py-1.5 pl-1.5 pr-4", n === i && "bg-surface-2")}>
              <span className={clsx("grid h-9 w-9 shrink-0 place-items-center rounded-full", n === i ? "bg-ink-solid text-ink-on" : "bg-surface-2")}><r.icon className="h-4 w-4" strokeWidth={1.75} aria-hidden /></span>
              <span className="min-w-0 flex-1"><span className="block truncate font-medium">{r.label}</span><span className="block truncate text-xs text-muted">{r.hint}</span></span>
              {n === i && <CornerDownLeft className="h-4 w-4 shrink-0 text-muted" aria-hidden />}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
