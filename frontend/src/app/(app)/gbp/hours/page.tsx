"use client";
import { GbpFrame } from "@/components/gbp/GbpFrame";
import { InfoTab } from "@/components/gbp/tools";
import { PageHeader } from "@/components/ui/Card";

/** GBP Manager › Opening hours (PRD §5.2): the hours half of the profile editor, same data and same save call as Business info. */
export default function HoursPage() {
  return (
    <>
      <PageHeader title="Opening hours" subtitle="Your regular weekly hours on Google. Saved changes go straight to Google." />
      <GbpFrame>{(gid) => <InfoTab key={gid} gid={gid} part="hours" />}</GbpFrame>
    </>
  );
}
