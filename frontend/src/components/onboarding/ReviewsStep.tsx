"use client";
import clsx from "clsx";
import { ArrowRight, Check, Link2, ShieldCheck, Star } from "lucide-react";
import { Button } from "@/components/ui/Button";
import type { WizardMemory } from "@/lib/places";
import type { Location } from "@/lib/types";
import { useFetch } from "@/lib/use-api";
import { StepActions, StepCard, StepHeading } from "./Shell";

/** How reviews will reach the dashboard. Nothing is connected here: Google is only connected after the plan step, because that needs an active account. */
export function ReviewsStep({ method, onMethod, onBack, onNext }: { method: WizardMemory["method"]; onMethod: (m: WizardMemory["method"]) => void; onBack: () => void; onNext: () => void }) {
  const locs = useFetch<Location[]>("/locations");
  const hasLink = !!locs.data?.[0]?.review_url;
  const opts = [
    { id: "link" as const, icon: Star, title: "Use my Google review link", badge: "Fastest",
      body: "Customers who tap or scan your card land on your review page, then go to Google to post. Cards, AI writing help and scan counts work straight away.",
      status: hasLink ? "We already have your Google review link." : "You can add your review link later under Locations." },
    { id: "google" as const, icon: Link2, title: "Connect my Google Business Profile", badge: null,
      body: "Also brings your existing reviews into FlowQR and lets you approve AI-drafted replies before they go live on Google.",
      status: "Needs Google's approval for FlowQR. You will connect right after your plan is set up." },
  ];
  return (
    <StepCard>
      <StepHeading step={1} title="How do you want to collect reviews?">Your QR and NFC cards work either way. You can switch whenever you like.</StepHeading>
      <fieldset className="mt-7">
        <legend className="sr-only">How do you want to collect reviews?</legend>
        <div className="grid gap-3">
          {opts.map((o) => {
            const on = method === o.id;
            return (
              <label key={o.id} className={clsx("flex cursor-pointer gap-4 rounded-[20px] p-4 ring-1 transition-[box-shadow,background-color] duration-200 focus-within:ring-2 focus-within:ring-m-accentStrong sm:p-5",
                on ? "bg-m-tint ring-2 ring-m-accent" : "bg-white ring-m-line hover:ring-m-ink/25")}>
                <input type="radio" name="method" value={o.id} checked={on} onChange={() => onMethod(o.id)} className="sr-only" />
                <span aria-hidden className={clsx("grid h-11 w-11 shrink-0 place-items-center rounded-[14px]", on ? "bg-white text-m-accentStrong" : "bg-m-bg text-m-ink2")}><o.icon className="h-5 w-5" strokeWidth={1.75} /></span>
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-x-2.5 gap-y-1"><span className="text-[16px] font-semibold text-m-ink">{o.title}</span>{o.badge && <span className="rounded-full bg-m-accent px-2.5 py-0.5 text-[11px] font-semibold text-m-ink">{o.badge}</span>}</span>
                  <span className="mt-1 block text-[14px] leading-relaxed text-m-ink2">{o.body}</span>
                  <span className="mt-2 flex items-start gap-1.5 text-[13px] text-m-muted">{o.id === "link" && hasLink && <Check className="mt-0.5 h-4 w-4 shrink-0 text-[#157347]" aria-hidden />}{o.status}</span>
                </span>
                <span aria-hidden className={clsx("mt-1 grid h-5 w-5 shrink-0 place-items-center rounded-full ring-1", on ? "bg-m-accent text-m-ink ring-m-accent" : "bg-white ring-m-muted2")}>{on && <Check className="h-3 w-3" strokeWidth={3} />}</span>
              </label>
            );
          })}
        </div>
      </fieldset>

      <details className="mt-5 rounded-[16px] border border-m-line bg-white/60 px-4 py-3 text-[14px] text-m-ink2">
        <summary className="flex min-h-9 cursor-pointer list-none items-center gap-2 font-medium text-m-ink"><ShieldCheck className="h-4 w-4 text-[#157347]" aria-hidden />What does connecting Google allow?</summary>
        <ul className="mt-3 list-disc space-y-1.5 pl-5 leading-relaxed">
          <li>FlowQR can <b>read</b> your Business Profile and your reviews.</li>
          <li>It changes your profile, publishes a Google Post or photo, or posts a reply <b>only after you (or a teammate you chose) approve that exact change</b>, apart from the simple thank-you replies to new 4 and 5 star reviews that you can switch off.</li>
          <li>You choose which locations to connect, you can switch everything off with one button, and you can disconnect Google at any time.</li>
          <li>Signing in with Google is separate: it only proves who you are. It never gives access to a Business Profile.</li>
        </ul>
        <p className="mt-3 leading-relaxed"><b>No Google Business Profile yet?</b> Choose the first option. You can create one at business.google.com and connect it later.</p>
      </details>

      <StepActions onBack={onBack}>
        <Button variant="brand" size="lg" className="w-full sm:w-auto sm:min-w-[200px]" onClick={onNext}>Continue <ArrowRight className="h-4 w-4" aria-hidden /></Button>
      </StepActions>
    </StepCard>
  );
}
