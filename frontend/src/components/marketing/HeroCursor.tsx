"use client";
import { MousePointer2 } from "lucide-react";
import { MouseTrackerProvider as CursorProvider, Pointer as Cursor, PointerFollower as CursorFollow } from "@/components/ui/cursor";

/**
 * The home hero's custom pointer: an orange arrow with a small "FlowQR" label that trails it. It is drawn only for a real mouse (not touch, not reduced motion) and steps aside over links
 * and buttons, where the normal cursor returns. See components/ui/cursor.tsx.
 */
export function HeroCursor() {
  return (
    <CursorProvider>
      <Cursor>
        <MousePointer2 className="h-[26px] w-[26px] fill-m-accent stroke-white drop-shadow-[0_2px_4px_rgba(11,15,46,.25)]" strokeWidth={1.5} />
      </Cursor>
      <CursorFollow align="bottom-right" gap={14}>
        <span className="block rounded-full bg-m-navy px-3 py-1 text-[12px] tracking-[-.01em] text-white shadow-[0_8px_20px_-8px_rgba(11,15,46,.5)]">FlowQR</span>
      </CursorFollow>
    </CursorProvider>
  );
}
