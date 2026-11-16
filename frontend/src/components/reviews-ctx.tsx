"use client";
import { createContext, useContext } from "react";
import type { Review } from "@/lib/types";

export const REPLY_STATE: Record<Review["reply_state"], { tone: "ok" | "warn" | "bad" | "info" | "idle"; label: string; bar: string }> = {
  none: { tone: "warn", label: "Needs reply", bar: "bg-amber-500" },
  draft: { tone: "info", label: "Draft ready", bar: "bg-brand-600" },
  approved: { tone: "info", label: "Approved, not published", bar: "bg-brand-600" },
  publishing: { tone: "info", label: "Sending to Google", bar: "bg-brand-600" },
  published: { tone: "ok", label: "Replied", bar: "bg-transparent" },
  failed: { tone: "bad", label: "Publish failed", bar: "bg-red-600" },
};

/** The list pane owns the review list; the detail pane tells it to refresh after approve / publish / discard. */
export const ReviewsCtx = createContext<{ refresh: () => void } | null>(null);
export const useReviewsList = () => { const c = useContext(ReviewsCtx); return c ?? { refresh: () => {} }; };
