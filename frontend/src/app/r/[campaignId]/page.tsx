"use client";
import { useParams } from "next/navigation";
import ReviewLanding from "@/components/public/ReviewLanding";

// A review campaign's permanent link (what a campaign QR code encodes). The page itself is shared with cards bound to a campaign.
export default function Page() {
  const { campaignId } = useParams<{ campaignId: string }>();
  return <ReviewLanding campaignId={campaignId} />;
}
