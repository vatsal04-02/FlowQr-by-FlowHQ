"use client";
import { PageHeader } from "@/components/ui/Card";
import { SetupRequired } from "@/components/SetupRequired";

export default function StudioAssetsPage() {
  return (
    <>
      <PageHeader eyebrow="Content Studio" title="Asset library" subtitle="Images and files you reuse in posts." />
      <SetupRequired integration="meta" what="Asset library" plans={["Store and reuse photos for posts.", "File storage is not built yet. Photos for Google can already be added by public link in Photos & Media."]} />
    </>
  );
}
