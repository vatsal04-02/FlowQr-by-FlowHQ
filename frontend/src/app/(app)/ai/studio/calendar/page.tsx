"use client";
import { PageHeader } from "@/components/ui/Card";
import { SetupRequired } from "@/components/SetupRequired";

export default function StudioCalendarPage() {
  return (
    <>
      <PageHeader eyebrow="Content Studio" title="Content calendar" subtitle="One calendar for everything you plan to publish." />
      <SetupRequired integration="meta" what="Cross-channel calendar" plans={["Google posts you scheduled already appear in Google Business \u2192 Posts \u2192 Calendar.", "Facebook and Instagram posts will join them once a Meta connection exists."]} />
    </>
  );
}
