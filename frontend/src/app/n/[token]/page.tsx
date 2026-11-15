"use client";
import { useParams } from "next/navigation";
import CardLanding from "@/components/public/CardLanding";

// The address written onto a card's NFC tag (an NDEF URL record). Same card as the QR, counted as an NFC tap.
export default function Page() {
  const { token } = useParams<{ token: string }>();
  return <CardLanding token={token} channel={"nfc"} />;
}
