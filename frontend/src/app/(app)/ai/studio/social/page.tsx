"use client";
import { PageHeader } from "@/components/ui/Card";
import { SetupRequired } from "@/components/SetupRequired";

export default function StudioSocialPage() {
  return (
    <>
      <PageHeader eyebrow="Content Studio" title="Social publishing" subtitle="Facebook and Instagram." />
      <SetupRequired integration="meta" what="Facebook & Instagram publishing" plans={["Connect a Facebook Page and linked Instagram account through Meta's official login.", "Publish only what you approved, with Meta's own confirmation before anything is marked published.", "Manual download is the fallback when no connection exists."]} />
    </>
  );
}
