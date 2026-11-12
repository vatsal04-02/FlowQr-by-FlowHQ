import { MarketingFooter, MarketingHeader } from "@/components/marketing/MarketingChrome";
import { LandingPlans, TrialNote } from "@/components/marketing/LandingPlans";

const NOTES = [
  ["Cards are separate", "Physical QR/NFC cards are sold separately from the software subscription and are paid per order."],
  ["Google access", "Google review sync, replies and profile tools need your own Google Business Profile account and Google's API access. Without it, FlowQR runs in manual review-link mode."],
  ["Review rules", "FlowQR never posts reviews for customers, never filters feedback by rating, and never offers incentives for reviews."],
  ["Payments", "Payments are processed securely by Razorpay (UPI, cards, netbanking). Prices are in rupees, plus GST as applicable."],
];

export default function Pricing() {
  return (
    <div className="bg-white">
      <MarketingHeader />
      <main>
        <section className="border-b border-ink-100 bg-ink-50">
          <div className="container-page py-12 sm:py-16"><p className="eyebrow">Pricing</p><h1 className="mt-2 max-w-2xl text-3xl font-bold sm:text-4xl">Simple pricing in rupees.</h1><p className="mt-3 max-w-xl text-[17px] text-ink-700"><TrialNote /></p></div>
        </section>
        <section className="container-page py-10 sm:py-14">
          <LandingPlans />
          <dl className="mt-10 grid divide-y divide-ink-200 border-y border-ink-200 text-sm sm:grid-cols-2 sm:divide-y-0 sm:gap-x-10">
            {NOTES.map(([k, v]) => <div key={k} className="grid gap-1 border-ink-200 py-3 sm:border-b sm:grid-cols-[8rem_1fr] sm:gap-4 [&:nth-last-child(-n+2)]:sm:border-b-0"><dt className="font-semibold">{k}</dt><dd className="text-ink-500">{v}</dd></div>)}
          </dl>
        </section>
      </main>
      <MarketingFooter />
    </div>
  );
}
