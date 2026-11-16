"use client";
import { useParams } from "next/navigation";
import CardLanding from "@/components/public/CardLanding";

// The address printed on cards made before inventory batches. The way in is not known here (an older NFC tag may have been written with it), so no channel is recorded.
export default function Page() {
  const { token } = useParams<{ token: string }>();
  return <CardLanding token={token} channel={null} />;
}
