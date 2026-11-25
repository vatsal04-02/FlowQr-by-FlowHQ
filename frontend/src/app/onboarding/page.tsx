"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { BusinessStep } from "@/components/onboarding/BusinessStep";
import { LaunchStep } from "@/components/onboarding/LaunchStep";
import { PlanStep } from "@/components/onboarding/PlanStep";
import { ReviewsStep } from "@/components/onboarding/ReviewsStep";
import { WizardShell } from "@/components/onboarding/Shell";
import { Spinner } from "@/components/ui/Card";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { loadMemory, saveMemory, type PlaceDetails, type WizardMemory } from "@/lib/places";
import type { Location, SubscriptionInfo } from "@/lib/types";

/**
 * First-run set-up, four steps: business (with its first location), how reviews are collected, plan and payment, launch.
 * Nothing opens the app until the last step: where payment authorisation is required, the server refuses to finish onboarding until Cashfree has confirmed it (POST /tenant/complete-onboarding answers 402).
 * Progress is the server's: a person who left (or came back from Cashfree) lands on the step the server's records say they are on.
 * The business picked from Google in step 1 is kept in sessionStorage so step 2 can pre-fill itself, and it survives a page refresh.
 */
export default function Onboarding() {
  const { me, tenant, loading, refresh, logout } = useAuth();
  const router = useRouter();
  const [step, setStep] = useState<number | null>(null);
  const [mem, setMem] = useState<WizardMemory>({ place: null, method: "link" });
  const [ready, setReady] = useState(false);
  const [reason, setReason] = useState<string | null>(null);  // why the server sent the customer back to the payment step

  useEffect(() => { setMem(loadMemory()); setReady(true); }, []);
  const update = (patch: Partial<WizardMemory>) => setMem((m) => { const n = { ...m, ...patch }; saveMemory(n); return n; });

  useEffect(() => {
    if (loading) return;
    if (!me) { router.replace("/login"); return; }
    if (tenant?.onboarding_completed) { router.replace("/overview"); return; }
    if (step !== null) return;
    if (!tenant) { setStep(0); return; }
    if (typeof window !== "undefined" && window.location.search.includes("step=launch")) { setStep(3); return; }  // back from the website stage; the launch step still asks the server what is allowed
    api<Location[]>("/locations").then(async (l) => {
      if (!l.length) { setStep(0); return; }
      // an authorisation already started (or finished) with Cashfree, or a return from its checkout: the plan step, which asks the server what happened
      const back = typeof window !== "undefined" && window.location.search.includes("checkout=");
      const sub = await api<SubscriptionInfo>("/billing/subscription").catch(() => null);
      setStep(back || sub?.has_cashfree_subscription ? 2 : 1);
    }).catch(() => setStep(0));
  }, [loading, me, tenant, router, step]);

  if (step === null || !ready) return <div className="grid min-h-dvh place-items-center bg-[#F7F5F2]"><Spinner /></div>;

  /** A business with no website sees it being built before the launch step, when website building is switched on. */
  async function afterPlan() {
    const w = await api<{ enabled: boolean; interest?: string | null }>("/website").catch(() => null);
    if (w?.enabled && w.interest === "wants_site") router.push("/onboarding/website");
    else setStep(3);
  }
  async function signOut() { await logout(); router.replace("/login"); }
  const place: PlaceDetails | null = mem.place;

  return (
    <WizardShell step={step} email={me?.user.email} onSignOut={() => void signOut()} onGo={(i) => i < step && setStep(i)}>
      {step === 0 && <BusinessStep tenant={tenant} place={place} onPlace={(p) => update({ place: p })} onDone={async () => { await refresh(); setStep(1); }} />}
      {step === 1 && <ReviewsStep method={mem.method} onMethod={(m) => update({ method: m })} onBack={() => setStep(0)} onNext={() => setStep(2)} />}
      {step === 2 && <PlanStep onBack={() => setStep(1)} onDone={() => { setReason(null); void afterPlan(); }} reason={reason} />}
      {step === 3 && <LaunchStep method={mem.method} businessName={tenant?.name ?? place?.name ?? ""} onBack={() => setStep(2)} onNeedAuthorization={(why) => { setReason(why); setStep(2); }} />}
    </WizardShell>
  );
}
