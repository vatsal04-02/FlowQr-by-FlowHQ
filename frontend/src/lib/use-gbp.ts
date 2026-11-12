"use client";
import { useEffect, useMemo, useState } from "react";
import { useLocationScope } from "@/lib/location-scope";
import type { GoogleConnection, GoogleLocation } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

/** The Google Business locations the signed-in person can manage, and which one is selected (follows the global location picker). */
export function useGbp() {
  const status = useFetch<{ configured: boolean; connections: GoogleConnection[] }>("/google/status");
  const conn = status.data?.connections.find((c) => c.status === "active");
  const locs = useFetch<GoogleLocation[]>(conn ? `/google/connections/${conn.id}/locations` : null);
  const { locationId } = useLocationScope();
  const selected = useMemo(() => locs.data?.filter((l) => l.selected) ?? [], [locs.data]);
  const [picked, setPicked] = useState("");
  // the global location picker wins when it points at one of these; otherwise the person's own choice; otherwise the first
  const fromScope = locationId ? selected.find((l) => l.location_id === locationId)?.id : undefined;
  useEffect(() => { if (!picked && selected[0]) setPicked(selected[0].id); }, [selected, picked]);
  const gid = fromScope ?? (selected.some((l) => l.id === picked) ? picked : selected[0]?.id ?? "");
  const anyConn = status.data?.connections.find((c) => c.status !== "disconnected");
  return { status, conn, anyConn, selected, gid, setPicked, loading: status.loading && !status.data, locsLoading: !!conn && locs.loading && !locs.data };
}
