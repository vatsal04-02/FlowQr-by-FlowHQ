"use client";
import { PageHeader } from "@/components/ui/Card";
import { SetupRequired } from "@/components/SetupRequired";

export default function StudioBrandPage() {
  return (
    <>
      <PageHeader eyebrow="Content Studio" title="Brand kit" subtitle="Your logo, colours and voice for generated content." />
      <SetupRequired integration="meta" what="Brand kit" plans={["Keep logo, colours and tone in one place for generated content.", "Brand voice already used by the AI lives in Knowledge Base; QR code colours live in QR design & export."]} />
    </>
  );
}
