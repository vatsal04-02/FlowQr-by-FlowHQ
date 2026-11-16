"use client";
import { GbpFrame } from "@/components/gbp/GbpFrame";
import { PhotoScheduler } from "@/components/gbp/PhotoScheduler";
import { MediaTab } from "@/components/gbp/tools";
import { PageHeader } from "@/components/ui/Card";

/** GBP Manager › Photos: what Google shows, what's missing, and photos on their way (uploaded, approved, scheduled, confirmed by Google). */
export default function MediaPage() {
  return (
    <>
      <PageHeader title="Photos" subtitle="Add photos, approve them, and choose when they go to Google. Only what Google confirms is shown as live." />
      <GbpFrame>{(gid) => (
        <div className="space-y-6">
          <PhotoScheduler key={gid} gid={gid} />
          <section aria-labelledby="ongoogle-h" className="panel p-5 sm:p-6">
            <h2 id="ongoogle-h" className="mb-4 text-lg font-semibold">On Google now</h2>
            <MediaTab key={`m-${gid}`} gid={gid} canAdd={false} />
          </section>
        </div>
      )}</GbpFrame>
    </>
  );
}
