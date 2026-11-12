"use client";
import { GbpFrame } from "@/components/gbp/GbpFrame";
import { MediaTab } from "@/components/gbp/tools";
import { PageHeader } from "@/components/ui/Card";

export default function MediaPage() {
  return (
    <>
      <PageHeader eyebrow="Google Business" title="Photos & media" subtitle="Add photos to your Google profile by public link, see what Google lists, and remove photos. Google processes each photo after it is added." />
      <GbpFrame>{(gid) => <MediaTab key={gid} gid={gid} />}</GbpFrame>
    </>
  );
}
