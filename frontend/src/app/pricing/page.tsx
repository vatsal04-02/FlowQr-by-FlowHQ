"use client";
import { MarketingFooter, MarketingHeader } from "@/components/MarketingChrome";
import { LinkButton } from "@/components/ui/Button";
import { PlanCards } from "@/components/PlanCards";
import type { Plan, PlansResponse } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

const FALLBACK: Plan[] = [
  { code: "essential", name: "Essential", price_paise: 39900, currency: "INR", interval: "monthly", max_locations: 1, monthly_ai_generations: 300, max_staff: 3, features: ["review_sync", "ai_replies", "gbp_info"] },
  { code: "growth", name: "Growth", price_paise: 79900, currency: "INR", interval: "monthly", max_locations: 3, monthly_ai_generations: 1000, max_staff: 10, features: ["review_sync", "ai_replies", "gbp_info", "gbp_posts", "gbp_media", "gbp_performance", "insights"] },
  { code: "multi", name: "Multi-location", price_paise: 149900, currency: "INR", interval: "monthly", max_locations: 10, monthly_ai_generations: 5000, max_staff: 50, features: ["review_sync", "ai_replies", "gbp_info", "gbp_posts", "gbp_media", "gbp_performance", "insights"] },
];

export default function Pricing() {
  const { data } = useFetch<PlansResponse>("/billing/plans");
  const plans = data?.plans ?? FALLBACK;
  return (
    <div className="bg-white">
      <MarketingHeader />
      <main className="container-page py-14">
        <h1 className="text-center text-4xl font-semibold">Simple pricing in rupees</h1>
        <p className="mx-auto mt-3 max-w-xl text-center text-lg text-ink-500">Start with a {data?.trial_days ?? 14}-day free trial with Growth features. No card needed. Cancel any time.</p>
        <div className="mt-10"><PlanCards plans={plans} action={(p) => <LinkButton href="/register" variant={p.code === "growth" ? "primary" : "secondary"} className="w-full">Start free trial</LinkButton>} /></div>
        <section className="mx-auto mt-14 max-w-3xl rounded-2xl bg-ink-50 p-6 text-sm text-ink-700">
          <h2 className="text-lg font-semibold">Good to know</h2>
          <ul className="mt-3 list-disc space-y-1.5 pl-5">
            <li>Physical QR/NFC cards are sold separately from the software subscription and are paid per order.</li>
            <li>Google review sync, replies and profile tools need your own Google Business Profile account and Google&rsquo;s API access.</li>
            <li>FlowQR never posts reviews for customers, never filters feedback by rating, and never offers incentives for reviews.</li>
            <li>Payments are processed securely by Razorpay (UPI, cards, netbanking).</li>
          </ul>
        </section>
      </main>
      <MarketingFooter />
    </div>
  );
}
