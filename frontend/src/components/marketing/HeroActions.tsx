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
      <div className="flex items-center justify-center gap-2.5 md:gap-3">
        <Link href="/register" onClick={(e) => { track("signup_cta_click"); if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey) { e.preventDefault(); setOpen(true); } }}
          className="group inline-flex min-h-11 items-center justify-center gap-1.5 rounded-full bg-m-accent px-5 text-[15px] font-medium tracking-[-.01em] text-m-ink transition-colors duration-200 hover:bg-[#F06000] md:min-h-[52px] md:gap-2 md:px-7 md:text-[16px]">
          Start free trial<ArrowRight aria-hidden className="h-4 w-4 transition-transform duration-300 group-hover:translate-x-[3px]" strokeWidth={1.75} />
        </Link>
        <Link href="/login" className="inline-flex min-h-11 items-center justify-center rounded-full border border-m-ink/70 px-5 text-[15px] font-medium tracking-[-.01em] text-m-ink transition-colors duration-200 hover:bg-m-ink/[.04] md:min-h-[52px] md:px-7 md:text-[16px]">Log in</Link>
      </div>
      <TrialNote className="mt-3 text-[13px] text-m-muted md:mt-4 md:text-[14px]" />
      <SignupDialog open={open} onClose={() => setOpen(false)} />
    </div>
  );
}
