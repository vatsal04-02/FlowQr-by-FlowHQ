"use client";
import { AgencyJourneyScreen } from "@/components/gbp/AgencyJourney";
import { PageHeader } from "@/components/ui/Card";

export default function ConnectGooglePage() {
  return (
    <>
      <PageHeader title="Connect Google" subtitle="Sign in once, choose your business location and approve FlowQR as your Manager. We then do the rest and show you every step." />
      <AgencyJourneyScreen />
    </>
  );
}
