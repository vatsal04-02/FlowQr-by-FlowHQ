"use client";
import { Lock } from "lucide-react";
import type { ReactNode } from "react";
import { ConnectGoogleEmptyState } from "@/components/settings/parts";
import { Alert, EmptyState, Skeleton } from "@/components/ui/Card";
import { LinkButton } from "@/components/ui/Button";
import { Select } from "@/components/ui/Form";
import { useGbp } from "@/lib/use-gbp";

/** Wraps a Google Business page: loading, not connected, awaiting approval, no locations, then the content for the chosen location. */
export function GbpFrame({ children, picker = true }: { children: (gid: string) => ReactNode; picker?: boolean }) {
  const g = useGbp();
  if (g.loading || g.locsLoading) return <Skeleton className="h-40" />;
  if (g.status.error) return <Alert tone="error" title="Couldn't check your Google connection">{g.status.error}</Alert>;
  const c = g.anyConn;
  if (!c) return <ConnectGoogleEmptyState what="This page works on your real Google Business Profile, so it needs a connected account and at least one selected location." />;
  if (c.status === "revoked") return <Alert tone="error" title="Google access was lost" action={<LinkButton href="/settings/connections/google" size="sm" variant="secondary">Reconnect</LinkButton>}>Reconnect your Google account to continue.</Alert>;
  if (c.api_access === "api_disabled" || c.api_access === "awaiting_approval") {
    return <Alert tone="warning" title={c.api_access === "api_disabled" ? "A Google API is switched off for FlowQR" : "Awaiting Google approval"} action={<LinkButton href="/settings/connections/google" size="sm" variant="secondary">Details</LinkButton>}>{c.last_error ?? "Google has not yet enabled Business Profile access for FlowQR. Nothing is simulated in the meantime."}</Alert>;
  }
  if (c.no_locations) return <Alert tone="warning" title="This Google account manages no locations" action={<LinkButton href="/settings/connections/google" size="sm">Connect another account</LinkButton>}>You signed in successfully, but Google lists no Business Profile location on this account, so there is nothing to manage. This is not a working business connection. Connect the Google account that owns or manages your listing.</Alert>;
  if (!g.conn || g.selected.length === 0) return <EmptyState icon={<Lock className="h-6 w-6" />} title="Choose a location to manage" action={<LinkButton href="/settings/connections/google">Choose locations</LinkButton>}>Your Google account is connected, but no location is selected.</EmptyState>;
  return (
    <>
      {picker && g.selected.length > 1 && <div className="mb-5 max-w-xs"><Select label="Location" value={g.gid} onChange={(e) => g.setPicked(e.target.value)}>{g.selected.map((l) => <option key={l.id} value={l.id}>{l.title}</option>)}</Select></div>}
      {g.gid ? children(g.gid) : null}
    </>
  );
}
