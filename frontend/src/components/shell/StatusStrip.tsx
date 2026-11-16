"use client";
import clsx from "clsx";
import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { LinkButton } from "../ui/Button";
import { Sheet } from "../ui/Sheet";
import type { Notice } from "./parts";

const DOT = { bad: "bg-neg", warn: "bg-warn", info: "bg-accent" } as const;

/**
 * Account status in one 40px line (plan inactive, payment failed, email not verified, deletion scheduled) instead of a banner on every page. Tapping it opens a sheet with each
 * item and its one action. The most serious item is the one shown in the line; the rest are counted.
 */
export function StatusStrip({ notices }: { notices: Notice[] }) {
  const [open, setOpen] = useState(false);
  if (!notices.length) return null;
  const order = { bad: 0, warn: 1, info: 2 } as const;
  const list = [...notices].sort((a, b) => order[a.tone] - order[b.tone]);
  const top = list[0];
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} aria-haspopup="dialog"
        className="relative mb-4 flex !min-h-10 h-10 w-full items-center gap-2.5 rounded-[12px] bg-surface px-3 text-left text-[14px] ring-1 ring-line transition-colors hover:bg-surface-2 after:absolute after:-inset-y-0.5 after:inset-x-0">
        <span aria-hidden className={clsx("h-2 w-2 shrink-0 rounded-full", DOT[top.tone])} />
        <span className="min-w-0 flex-1 truncate font-medium">{top.title}</span>
        {list.length > 1 && <span className="shrink-0 text-[13px] text-muted">+{list.length - 1}</span>}
        <span className="hidden shrink-0 text-[13px] font-medium text-accent-ink sm:inline">{top.cta}</span>
        <ChevronRight className="h-4 w-4 shrink-0 text-ink-400" aria-hidden />
      </button>
      <Sheet open={open} onClose={() => setOpen(false)} title="Account status">
        <ul className="divide-y divide-line">
          {list.map((n) => (
            <li key={n.id} className="py-3">
              <p className="flex items-center gap-2 text-[15px] font-semibold"><span aria-hidden className={clsx("h-2 w-2 rounded-full", DOT[n.tone])} />{n.title}</p>
              <p className="mt-1 text-[14px] text-muted">{n.body}</p>
              <div className="mt-3">{n === top ? <LinkButton href={n.href} variant="brand" onClick={() => setOpen(false)}>{n.cta}</LinkButton>
                : <Link href={n.href} onClick={() => setOpen(false)} className="inline-flex min-h-11 items-center text-[14px] font-semibold text-ink underline underline-offset-2">{n.cta}</Link>}</div>
            </li>
          ))}
        </ul>
      </Sheet>
    </>
  );
}
