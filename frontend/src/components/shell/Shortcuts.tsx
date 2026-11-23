"use client";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { isTyping } from "@/lib/hooks";
import type { Dest } from "@/lib/nav";
import { Modal } from "../ui/Modal";

/** "g" then a letter jumps to a page (like Gmail and Linear). Only pages this person can see are listed. */
const GO: { key: string; id: string; label: string }[] = [
  { key: "h", id: "home", label: "Home" },
  { key: "r", id: "reviews", label: "Reviews" },
  { key: "p", id: "seo", label: "GBP (your Google profile)" },
  { key: "g", id: "growth", label: "Growth" },
  { key: "l", id: "locations", label: "Locations" },
  { key: "a", id: "assistant", label: "AI Assistant" },
  { key: "t", id: "tasks", label: "Tasks & Approvals" },
  { key: "s", id: "settings", label: "Settings" },
  { key: "b", id: "billing", label: "Billing" },
];

const Kbd = ({ children }: { children: React.ReactNode }) => <kbd className="inline-grid min-w-6 place-items-center rounded-md bg-surface-2 px-1.5 py-0.5 font-sans text-xs font-semibold text-ink ring-1 ring-line">{children}</kbd>;

/**
 * App-wide keyboard shortcuts, always off while typing in a field or with a dialog open. Ctrl/⌘ K stays in AppShell.
 *   ?  this list    /  search    g then h/r/p/g/l/a/t/s/b  go to a page
 */
export function Shortcuts({ dests, onSearch, helpOpen, onHelpClose, onHelp }: { dests: Dest[]; onSearch: () => void; helpOpen: boolean; onHelp: () => void; onHelpClose: () => void }) {
  const router = useRouter();
  const pending = useRef<number | undefined>(undefined);
  const armed = useRef(false);
  const [hint, setHint] = useState(false);
  const go = GO.filter((g) => dests.some((d) => d.id === g.id));

  useEffect(() => {
    const disarm = () => { armed.current = false; setHint(false); window.clearTimeout(pending.current); };
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || isTyping(e.target)) return;
      const k = e.key.toLowerCase();
      if (armed.current) {
        const hit = go.find((g) => g.key === k);
        disarm();
        const d = hit && dests.find((x) => x.id === hit.id);
        if (d) { e.preventDefault(); router.push(d.href); }
        return;
      }
      if (e.key === "?") { e.preventDefault(); onHelp(); }
      else if (e.key === "/") { e.preventDefault(); onSearch(); }
      else if (k === "g" && !e.shiftKey) { armed.current = true; setHint(true); pending.current = window.setTimeout(disarm, 1500); }
    };
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); window.clearTimeout(pending.current); };
  }, [dests, go, router, onHelp, onSearch]);

  return (
    <>
      {hint && <div role="status" className="fq-enter pointer-events-none fixed bottom-6 left-1/2 z-[65] hidden -translate-x-1/2 rounded-full bg-ink-solid px-4 py-2 text-[13px] font-medium text-ink-on shadow-lift lg:block">Go to… <span className="opacity-70">{go.map((g) => g.key).join(" ")}</span></div>}
      <Modal open={helpOpen} onClose={onHelpClose} title="Keyboard shortcuts">
        <div className="grid gap-x-8 gap-y-5 sm:grid-cols-2">
          <section aria-label="General">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">General</h3>
            <ul className="space-y-2 text-sm">
              <li className="flex items-center justify-between gap-3">Search and jump<span className="flex gap-1"><Kbd>Ctrl</Kbd><Kbd>K</Kbd></span></li>
              <li className="flex items-center justify-between gap-3">Search<Kbd>/</Kbd></li>
              <li className="flex items-center justify-between gap-3">This list<Kbd>?</Kbd></li>
              <li className="flex items-center justify-between gap-3">Close anything<Kbd>Esc</Kbd></li>
            </ul>
          </section>
          <section aria-label="Go to">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Go to a page</h3>
            <ul className="space-y-2 text-sm">
              {go.map((g) => <li key={g.key} className="flex items-center justify-between gap-3">{g.label}<span className="flex items-center gap-1"><Kbd>G</Kbd><span className="text-xs text-muted">then</span><Kbd>{g.key.toUpperCase()}</Kbd></span></li>)}
            </ul>
          </section>
        </div>
        <p className="mt-5 text-xs text-muted">Shortcuts are off while you type in a box.</p>
      </Modal>
    </>
  );
}
