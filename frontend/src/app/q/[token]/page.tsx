"use client";
import { useParams } from "next/navigation";
import CardLanding from "@/components/public/CardLanding";

// The address a card's printed QR code encodes.
export default function Page() {
  const { token } = useParams<{ token: string }>();
  return <CardLanding token={token} channel={"qr"} />;
}
