"use client";
import clsx from "clsx";
import { useCallback, useRef, useState } from "react";
import { Card, Dashes, Title } from "@/components/seo/visuals";
import { SourceTag } from "@/components/seo/parts";
import { Button, LinkButton } from "@/components/ui/Button";
import { api, errorMessage } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import type { GoogleMetrics } from "@/lib/seo";

type Phase = "idle" | "syncing" | "failed" | "done";

/**
 * "Check Google now": the existing authorised refresh (POST /agent/google/refresh, owner or admin, at most 6 an hour per business). One request at a time: a second tap while the
 * first is running is ignored (a ref, not only the disabled button, so a double-tap in the same frame cannot start two). The server answers per location, so a partial failure is
 * reported with the location's own message; whatever Google did return is already stored, and `onSynced` reloads the page's numbers either way.
 */
export function useGoogleSync(onSynced: () => Promise<unknown> | void) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const lock = useRef(false);
  const run = useCallback(async () => {
    if (lock.current) return;
    lock.current = true; setPhase("syncing"); setError(null);
    try {
      const r = await api<{ locations: { title: string; ok: boolean; error: string | null }[] }>("/agent/google/refresh", { method: "POST" });
      await onSynced();
      const bad = r.locations.filter((l) => !l.ok);
      if (bad.length) { setError(bad.map((b) => `${b.title}: ${b.error ?? "Google did not answer."}`).join(" ")); setPhase("failed"); } else setPhase("done");
    } catch (e) { setError(errorMessage(e)); setPhase("failed"); }
    finally { lock.current = false; }
  }, [onSynced]);
  return { phase, error, run, busy: phase === "syncing" };
}
export type GoogleSync = ReturnType<typeof useGoogleSync>;

/** The one card shown while there are no numbers to draw. Exactly one state at a time, in this order: syncing, failed, couldn't load, then what the server says about the connection. */
export function EmptyGoogle({ d, loadError, reload, isAdmin, sync, rangeEmpty }: { d: GoogleMetrics | null; loadError: string | null; reload: () => void; isAdmin: boolean; sync: GoogleSync; rangeEmpty: boolean }) {
  const st = d?.availability.state;
  let text = "No daily numbers saved yet.";
  let tone: "muted" | "bad" = "muted";
  let action: React.ReactNode = null;

  if (sync.phase === "syncing") {
    text = "Syncing with Google…";
  } else if (sync.phase === "failed") {
    text = sync.error ?? "Google didn't answer."; tone = "bad";
    action = st === "not_connected" ? <LinkButton href="/gbp/locations" size="sm">Reconnect Google</LinkButton> : isAdmin ? <Button size="sm" onClick={() => void sync.run()}>Try again</Button> : null;
  } else if (loadError && !d) {
    text = "Couldn't load these numbers."; tone = "bad";
    action = <Button size="sm" variant="secondary" onClick={reload}>Try again</Button>;
  } else if (rangeEmpty) {
    text = `No days in this range. Last synced ${timeAgo(d?.availability.last_fetched_at)}. Try a longer range.`;
  } else if (st === "not_connected") {
    text = "Google isn't connected.";
    action = <LinkButton href="/gbp/locations" size="sm">Reconnect Google</LinkButton>;
  } else if (st === "no_location") {
    text = "No Google location chosen.";
    action = <LinkButton href="/gbp/locations" size="sm" variant="secondary">Choose a location</LinkButton>;
  } else if (st === "api_disabled" || st === "awaiting_approval") {
    text = st === "api_disabled" ? "Google access isn't switched on yet." : "Waiting for Google's approval.";
    action = <LinkButton href="/gbp/locations" size="sm" variant="secondary">Details</LinkButton>;
  } else if (sync.phase === "done") {
    text = "Google answered with no daily numbers yet. It reports a few days late.";
    action = isAdmin ? <Button size="sm" variant="secondary" onClick={() => void sync.run()}>Check Google now</Button> : null;
  } else {
    text = isAdmin ? "Connected. No daily numbers saved yet." : "Connected. An owner or admin can fetch the numbers.";
    action = isAdmin ? <Button size="sm" onClick={() => void sync.run()}>Check Google now</Button> : null;
  }

  return (
    <Card label="Google performance">
      <Title right={<SourceTag source="google" />}>From Google</Title>
      <div className="mt-4 grid grid-cols-2 gap-4 md:grid-cols-4" aria-hidden>{["Calls", "Directions", "Website clicks", "Profile views"].map((l) => <div key={l}><p className="text-[13px] text-muted">{l}</p><p className="text-[20px] font-semibold">–</p><Dashes className={clsx("mt-1", sync.busy && "animate-pulse")} /></div>)}</div>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <p role={tone === "bad" ? "alert" : "status"} className={clsx("min-w-0 text-[14px]", tone === "bad" ? "text-neg" : "text-muted")}>{text}</p>
        {sync.busy ? <Button size="sm" variant="secondary" loading disabled>Syncing</Button> : action}
      </div>
    </Card>
  );
}

/** Data is showing: when it was last stored from Google, and (owner or admin) a way to fetch again. */
export function SyncedLine({ at, isAdmin, sync }: { at: string | null; isAdmin: boolean; sync: GoogleSync }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 text-[13px] text-muted">
      <p role="status">{sync.busy ? "Syncing with Google…" : sync.phase === "failed" ? <span className="text-neg" role="alert">{sync.error}</span> : `Last synced ${timeAgo(at)}`}</p>
      {isAdmin && <Button size="sm" variant="ghost" loading={sync.busy} disabled={sync.busy} onClick={() => void sync.run()}>{sync.phase === "failed" ? "Try again" : "Check Google now"}</Button>}
    </div>
  );
}
