"use client";
import { GbpFrame } from "@/components/gbp/GbpFrame";
import { GeoGrid } from "@/components/gbp/GeoGrid";
import { LocalRank } from "@/components/gbp/LocalRank";
import { PageHeader } from "@/components/ui/Card";

/** GBP Manager › Local ranking: measured positions for the search terms a business tracks (Google Places API). */
export default function RankPage() {
  return (
    <>
      <PageHeader title="Search words you track" subtitle="Add the words your customers search. FlowQR checks where your business appears on Google Maps and keeps the history. Nothing is estimated." />
      <GbpFrame>{(gid) => <div className="space-y-6"><LocalRank key={gid} gid={gid} /><GeoGrid key={`map-${gid}`} gid={gid} /></div>}</GbpFrame>
    </>
  );
}
