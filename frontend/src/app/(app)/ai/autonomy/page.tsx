"use client";
import { AutoReplies } from "@/components/autonomy/AutoReplies";
import { ControlCentre } from "@/components/autonomy/ControlCentre";
import { PageHeader } from "@/components/ui/Card";

/** AI › Autonomy: the owner's control centre for what FlowQR may do on its own. */
export default function AutonomyPage() {
  return (
    <>
      <PageHeader eyebrow="AI Growth Agent" title="Autonomy" subtitle="What FlowQR may do on its own, what needs you, and a verified record of everything it has done." />
      <ControlCentre />
      <div className="mt-5"><AutoReplies /></div>
    </>
  );
}
