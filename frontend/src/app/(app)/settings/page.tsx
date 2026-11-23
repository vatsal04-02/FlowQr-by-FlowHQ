"use client";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

/** On a phone the hub (drawn by the layout) is this page. From 768px up there is no hub, so go straight to the first page. */
export default function SettingsIndex() {
  const router = useRouter();
  useEffect(() => { if (window.matchMedia("(min-width: 768px)").matches) router.replace("/settings/business"); }, [router]);
  return null;
}
