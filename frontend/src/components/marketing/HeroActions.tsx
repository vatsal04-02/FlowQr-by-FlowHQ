"use client";
import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { track } from "@/lib/track";
import { TrialNote } from "./TrialNote";

/**
 * The home hero's actions: "Start free trial" (a plain link to the Sign up page, /register), "Log in", and the trial terms from the server underneath. Nothing else competes with them on the first screen.
 */
export function HeroActions() {
  return (
    <div className="flex w-full flex-col items-start">
      <div className="flex flex-wrap items-center gap-3">
        <Link href="/register" onClick={() => track("signup_cta_click")}
          className="group inline-flex min-h-11 items-center justify-center gap-1.5 rounded-full bg-[#C2410C] px-6 text-[16px] font-semibold text-white shadow-[0_10px_24px_-10px_rgba(194,65,12,.6)] transition-colors duration-200 hover:bg-[#A8380A] md:min-h-[52px] md:gap-2 md:px-7 md:text-[17px]">
          Start free trial<ArrowRight aria-hidden className="h-4 w-4 transition-transform duration-300 group-hover:translate-x-[3px]" strokeWidth={1.75} />
        </Link>
        <Link href="/login" className="inline-flex min-h-11 items-center justify-center rounded-full border-[1.5px] border-[#0D1230] px-6 text-[16px] font-semibold text-[#0D1230] transition-colors duration-200 hover:bg-[#0D1230]/[.05] md:min-h-[52px] md:px-7 md:text-[17px]">Log in</Link>
      </div>
      <TrialNote className="mt-4 text-[14px] text-[#4A4F6E]" />
    </div>
  );
}
