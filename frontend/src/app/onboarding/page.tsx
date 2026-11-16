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
import type { Location } from "@/lib/types";

/**
 * First-run set-up, four steps: business (with its first location), how reviews are collected, plan and card, launch.
 * Nothing opens the app until the last step: the server refuses to finish onboarding while a card is still due (POST /tenant/complete-onboarding answers 402).
 * The business picked from Google in step 1 is kept in sessionStorage so step 2 can pre-fill itself, and it survives a page refresh.
 */
export default function Onboarding() {
  const { me, tenant, loading, refresh, logout } = useAuth();
  const router = useRouter();
  const [step, setStep] = useState<number | null>(null);
  const [mem, setMem] = useState<WizardMemory>({ place: null, method: "link" });
  const [ready, setReady] = useState(false);

  useEffect(() => { setMem(loadMemory()); setReady(true); }, []);
  const update = (patch: Partial<WizardMemory>) => setMem((m) => { const n = { ...m, ...patch }; saveMemory(n); return n; });

  useEffect(() => {
    if (loading) return;
    if (!me) { router.replace("/login"); return; }
    if (tenant?.onboarding_completed) { router.replace("/overview"); return; }
    if (step !== null) return;
    if (!tenant) { setStep(0); return; }
    api<Location[]>("/locations").then((l) => setStep(l.length ? 1 : 0)).catch(() => setStep(0));
  }, [loading, me, tenant, router, step]);

  if (step === null || !ready) return <div className="grid min-h-dvh place-items-center bg-[#F7F5F2]"><Spinner /></div>;

  async function signOut() { await logout(); router.replace("/login"); }
  const place: PlaceDetails | null = mem.place;

  return (
    <WizardShell step={step} email={me?.user.email} onSignOut={() => void signOut()} onGo={(i) => i < step && setStep(i)}>
      {step === 0 && <BusinessStep tenant={tenant} place={place} onPlace={(p) => update({ place: p })} onDone={async () => { await refresh(); setStep(1); }} />}
      {step === 1 && <ReviewsStep method={mem.method} onMethod={(m) => update({ method: m })} onBack={() => setStep(0)} onNext={() => setStep(2)} />}
      {step === 2 && <PlanStep onBack={() => setStep(1)} onDone={() => setStep(3)} />}
      {step === 3 && <LaunchStep method={mem.method} businessName={tenant?.name ?? place?.name ?? ""} onBack={() => setStep(2)} onNeedCard={() => setStep(2)} />}
    </WizardShell>
  );
}
