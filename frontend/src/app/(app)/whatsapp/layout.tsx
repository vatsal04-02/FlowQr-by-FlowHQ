"use client";
import type { ReactNode } from "react";
import { EmptyState, Skeleton } from "@/components/ui/Card";
import { useAuth } from "@/lib/auth";

/** The WhatsApp area exists only while the server has WhatsApp automation switched on (me.integrations.whatsapp_enabled). Until then there is no menu entry, and a typed address explains itself. */
export default function WhatsAppLayout({ children }: { children: ReactNode }) {
  const { me, loading } = useAuth();
  if (loading) return <Skeleton className="h-64" />;
  if (!me?.integrations.whatsapp_enabled) return <EmptyState title="WhatsApp is not available yet">We are still getting WhatsApp ready for businesses. Nothing has changed for you, and your review cards work as before.</EmptyState>;
  return <>{children}</>;
}
