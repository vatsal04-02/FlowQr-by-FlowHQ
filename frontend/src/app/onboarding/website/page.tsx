"use client";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { Logo } from "@/components/ui/Brand";
import { Spinner } from "@/components/ui/Card";
import { WebsiteStudio } from "@/components/website/WebsiteStudio";
import { useAuth } from "@/lib/auth";

/** The website stage of set-up, after the plan and before the launch. A person who already finished set-up uses the same screen at /website. */
export default function OnboardingWebsite() {
  const { me, tenant, loading } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (loading) return;
    if (!me) router.replace("/login");
    else if (!tenant) router.replace("/onboarding");
    else if (tenant.onboarding_completed) router.replace("/website" + window.location.search);
  }, [loading, me, tenant, router]);
  if (loading || !me || !tenant || tenant.onboarding_completed) return <div className="grid min-h-dvh place-items-center bg-[#F7F5F2]"><Spinner /></div>;
  return (
    <main className="mkt min-h-dvh overflow-x-clip bg-m-bg">
      <div className="mx-auto max-w-[1320px] space-y-4 px-3 py-4 sm:px-5 sm:py-6">
        <Logo href="/onboarding" />
        <WebsiteStudio onContinue={() => router.push("/onboarding?step=launch")} />
      </div>
    </main>
  );
}
