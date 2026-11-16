"use client";
import type { Plan, PlansResponse } from "./types";
import { useFetch } from "./use-api";

/** Shown until /billing/plans answers (and if it never does), so public pages are never empty. Mirrors the confirmed commercial plans (backend/app/services/plans.py); the server's answer replaces it as soon as it arrives. */
export const FALLBACK_PLANS: Plan[] = [
  { code: "starter", name: "Launch", price_paise: 49900, currency: "INR", interval: "monthly", max_locations: 1, monthly_ai_generations: 400, review_generations: 200, review_replies: 200, max_staff: 3, features: ["review_sync", "ai_replies", "review_generation", "qr_campaigns", "review_analytics", "gbp_connection", "gbp_info"] },
  { code: "growth", name: "Growth", price_paise: 79900, currency: "INR", interval: "monthly", max_locations: 1, monthly_ai_generations: 800, review_generations: 400, review_replies: 400, max_staff: 10, features: [...["review_sync", "ai_replies", "review_generation", "qr_campaigns", "review_analytics", "gbp_connection", "gbp_info"], ...["gbp_posts", "gbp_media", "gbp_performance", "insights", "local_seo", "keyword_tracking", "geo_ranking", "autonomy", "ai_posts", "profile_optimizer", "growth_agent"]] },
  { code: "pro", name: "Scale", price_paise: 149900, currency: "INR", interval: "monthly", max_locations: 10, monthly_ai_generations: 1600, review_generations: 800, review_replies: 800, max_staff: 50, features: [...["review_sync", "ai_replies", "review_generation", "qr_campaigns", "review_analytics", "gbp_connection", "gbp_info"], ...["gbp_posts", "gbp_media", "gbp_performance", "insights", "local_seo", "keyword_tracking", "geo_ranking", "autonomy", "ai_posts", "profile_optimizer", "growth_agent"], "multi_location"] },
];

export function usePlans() {
  const { data } = useFetch<PlansResponse>("/billing/plans");
  // null until the server has answered: the site then says nothing about payment rather than say something that may be wrong
  return { plans: data?.plans ?? FALLBACK_PLANS, trialDays: data?.trial_days ?? 7, mandateRequired: data ? !!data.billing?.mandate_required : null };
}

/** What the site says about payment next to "N-day free trial", read from the server like the length. Where Cashfree billing is on, a payment method (UPI AutoPay or card) is authorised
 *  before the trial starts and the first payment is after it; where it is off, no card is needed. */
export const trialTerms = (mandateRequired: boolean | null) => (mandateRequired === null ? "" : mandateRequired ? "Authorise UPI AutoPay or a card to start. Your first payment is after the trial." : "No card needed.");
