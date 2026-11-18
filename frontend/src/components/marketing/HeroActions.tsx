"use client";
import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { track } from "@/lib/track";
import { SignupDialog } from "./SignupDialog";
import { TrialNote } from "./TrialNote";

/**
 * The home hero's actions: "Start free trial" (opens the sign-up form in a window over the page; it is a real link to /register, so a new tab or a browser without scripts still gets the full
 * page), "Log in", and the trial terms from the server underneath. Nothing else competes with them on the first screen.
 */
export function HeroActions() {
  const [open, setOpen] = useState(false);
  return (
    <div className="flex w-full basis-full flex-col items-center md:mt-3">
      <div className="flex w-full max-w-[420px] flex-col items-stretch gap-3 sm:w-auto sm:max-w-none sm:flex-row sm:items-center">
        <Link href="/register" onClick={(e) => { track("signup_cta_click"); if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey) { e.preventDefault(); setOpen(true); } }}
          className="group inline-flex min-h-[52px] items-center justify-center gap-2 rounded-full bg-m-accent px-7 text-[16px] font-medium tracking-[-.01em] text-m-ink transition-colors duration-200 hover:bg-[#F06000]">
          Start free trial<ArrowRight aria-hidden className="h-4 w-4 transition-transform duration-300 group-hover:translate-x-[3px]" strokeWidth={1.75} />
        </Link>
        <Link href="/login" className="inline-flex min-h-[52px] items-center justify-center rounded-full border border-m-ink/70 px-7 text-[16px] font-medium tracking-[-.01em] text-m-ink transition-colors duration-200 hover:bg-m-ink/[.04]">Log in</Link>
      </div>
      <TrialNote className="mt-4 text-[14px] text-m-muted" />
      <SignupDialog open={open} onClose={() => setOpen(false)} />
    </div>
  );
}
