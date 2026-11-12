"use client";
import { PageHeader } from "@/components/ui/Card";
import { SetupRequired } from "@/components/SetupRequired";

export default function LocalVisibility() {
  return (
    <>
      <PageHeader eyebrow="Google Business" title="Local visibility" subtitle="Where your business appears in local search for the terms customers use." />
      <SetupRequired integration="rank_provider" what="Local rank tracking" plans={[
        "Track your position for chosen search terms around each location, through a rank-tracking provider's official API.",
        "Show real positions with the date and place they were measured, and how they changed.",
        "Never scrape Google Maps or Search, and never show a rank that was not measured."]} />
    </>
  );
}
