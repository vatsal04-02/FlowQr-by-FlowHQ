"use client";
import type { Plan, PlansResponse } from "./types";
import { useFetch } from "./use-api";

/** Shown until /billing/plans answers (and if it never does), so public pages are never empty. Mirrors the server defaults. */
export const FALLBACK_PLANS: Plan[] = [
  { code: "essential", name: "Essential", price_paise: 39900, currency: "INR", interval: "monthly", max_locations: 1, monthly_ai_generations: 300, max_staff: 3, features: ["review_sync", "ai_replies", "gbp_info"] },
  { code: "growth", name: "Growth", price_paise: 79900, currency: "INR", interval: "monthly", max_locations: 3, monthly_ai_generations: 1000, max_staff: 10, features: ["review_sync", "ai_replies", "gbp_info", "gbp_posts", "gbp_media", "gbp_performance", "insights"] },
  { code: "multi", name: "Multi-location", price_paise: 149900, currency: "INR", interval: "monthly", max_locations: 10, monthly_ai_generations: 5000, max_staff: 50, features: ["review_sync", "ai_replies", "gbp_info", "gbp_posts", "gbp_media", "gbp_performance", "insights"] },
];

export function usePlans() {
  const { data } = useFetch<PlansResponse>("/billing/plans");
  return { plans: data?.plans ?? FALLBACK_PLANS, trialDays: data?.trial_days ?? 14 };
}
