"use client";
import { Check, ChevronDown, ChevronRight, Lock, MapPin } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { GoogleConnectionSection } from "@/components/gbp/GoogleConnection";
import { StatusChip, StickyActionBar, type ChipKind } from "@/components/settings/parts";
import { Button } from "@/components/ui/Button";
import { Alert, PageHeader, Skeleton } from "@/components/ui/Card";
import { ApiError, api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { googleLine, syncChip } from "@/lib/shell-status";
import type { GoogleConnection, GoogleLocation, Location } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

/** A titled list of 52px rows with a tick (or a lock) each, and a chip saying what the list means. */
function Features({ title, chip, kind, items, lock }: { title: string; chip: string; kind: ChipKind; items: string[]; lock?: boolean }) {
  return (
    <section aria-label={title} className="space-y-2">
      <div className="flex items-center justify-between px-1"><h2 className="text-sm font-extrabold text-set-soft">{title}</h2><StatusChip kind={kind}>{chip}</StatusChip></div>
      <ul className="overflow-hidden rounded-[18px] border border-set-line bg-set-surface">
        {items.map((t) => (
          <li key={t} className="flex min-h-[52px] items-center gap-3 border-t border-set-line px-4 py-2 first:border-t-0">
            {lock ? <Lock aria-hidden className="h-5 w-5 shrink-0 text-set-info-dot" strokeWidth={2} /> : <Check aria-hidden className="h-5 w-5 shrink-0 text-set-ok-dot" strokeWidth={2.2} />}
            <span className="text-[14px] font-semibold leading-snug text-set-ink">{t}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * Connected accounts › Google Business Profile: the one place Google is connected, explained and diagnosed. Every other screen that needs Google links here (ConnectGoogleEmptyState).
 * Layout follows the design board: a status card (warm when not connected), what works now, what connecting unlocks, locations, what FlowQR accesses, and a pinned Connect button.
 * The connection itself (guided setup, choosing locations, disconnecting) is the existing, tested component, below.
 */
export default function GoogleSettingsPage() {
  const { isAdmin } = useAuth();
  const status = useFetch<{ configured: boolean; connections: GoogleConnection[]; configuration_note?: string }>("/google/status");
  const active = status.data?.connections.find((c) => c.status === "active");
  const gl = useFetch<GoogleLocation[]>(active ? `/google/connections/${active.id}/locations` : null);
  const locs = useFetch<Location[]>("/locations");
  const line = googleLine(status.data?.connections);
  const sync = syncChip(gl.data);
  const connected = line?.tone === "ok";
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function connect() {
    setBusy(true); setProblem(null);
    try { const { auth_url } = await api<{ auth_url: string }>("/google/connect", { method: "POST" }); window.location.href = auth_url; }
    catch (e) { setProblem(e instanceof ApiError && e.code === "google_config_pending" ? e.message : errorMessage(e)); setBusy(false); }
  }

  const branches = (locs.data ?? []).filter((l) => l.is_active);
  const synced = (gl.data ?? []).filter((x) => x.selected).length;
  const canConnect = isAdmin && !connected && status.data?.configured !== false;

  return (
    <>
      <PageHeader title="Google Business Profile" subtitle="Where FlowQR reads your reviews and, once you approve each one, publishes your replies." />
      <div className="space-y-4">
        {status.loading && !status.data ? <Skeleton className="h-28" /> : (
          <section aria-label="Connection status" className={connected ? "space-y-2.5 rounded-[18px] border border-set-line bg-set-surface p-4" : "space-y-2.5 rounded-[18px] border border-set-attn-line bg-set-attn-bg p-4"}>
            <StatusChip kind={connected ? "ok" : "warn"}>{connected ? "Connected" : line && line.label !== "Google not connected" ? line.label : "Not connected"}</StatusChip>
            <h2 className={connected ? "text-[17px] font-extrabold leading-snug text-set-ink" : "text-[17px] font-extrabold leading-snug text-set-attn-title"}>
              {connected ? "Google is connected" : "You're using manual review-link mode"}
            </h2>
            <p className={connected ? "text-[14px] font-medium leading-relaxed text-set-soft" : "text-[14px] font-medium leading-relaxed text-set-attn-body"}>
              {connected ? `Reviews are syncing${sync && sync.kind !== "ok" ? `: ${sync.label.toLowerCase()}` : ""}. Choose below which locations FlowQR looks after.`
                : "Customers reach your Google review link from the card. Reviews aren't synced and replies are written on Google."}
            </p>
          </section>
        )}
        {problem && <Alert tone="warning" title="Couldn't start the Google connection">{problem}</Alert>}

        <Features title="Works now" chip="Included" kind="ok" items={["QR/NFC cards and review links", "AI writing assistant for customers", "Scan, visit and click analytics"]} />
        <Features title={connected ? "Now on" : "After you connect"} chip={connected ? "On" : "Unlocks"} kind={connected ? "ok" : "info"} lock={!connected}
          items={["Automatic review sync", "AI reply drafts you approve, then publish", "Business profile tools: hours, posts, photos"]} />

        <section aria-label="Locations" className="space-y-2">
          <h2 className="px-1 text-sm font-extrabold text-set-soft">Locations</h2>
          <div className="overflow-hidden rounded-[18px] border border-set-line bg-set-surface">
            <Link href="/gbp/locations" className="set-focus flex min-h-[68px] items-center gap-3.5 px-4 py-3">
              <span aria-hidden className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-set-t-connect text-set-i-connect"><MapPin className="h-5 w-5" strokeWidth={1.75} /></span>
              <span className="min-w-0 flex-1"><span className="block text-[15px] font-bold text-set-ink">{locs.data ? `${branches.length} ${branches.length === 1 ? "branch" : "branches"}` : "Your branches"}</span>
                <span className="block text-[13px] font-medium text-set-muted">{locs.data ? `${synced} synced with Google` : "Review links and cards"}</span></span>
              <ChevronRight aria-hidden className="h-[18px] w-[18px] shrink-0 text-set-switch-off" />
            </Link>
            <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)} className="set-focus flex min-h-14 w-full items-center justify-between gap-3 border-t border-set-line px-4 text-left">
              <span className="text-sm font-bold text-set-ink">What FlowQR accesses</span><ChevronDown aria-hidden className={open ? "h-[18px] w-[18px] rotate-180 text-set-switch-off" : "h-[18px] w-[18px] text-set-switch-off"} />
            </button>
            {open && (
              <ul className="space-y-2 border-t border-set-line bg-set-paper px-4 py-3 text-[13px] font-medium leading-snug text-set-soft">
                <li>Your Business Profile locations and reviews.</li>
                <li>Replies go out only after you approve each one, and show as published only after Google confirms.</li>
                <li>Sign-in details are encrypted and never sent to your browser. You can disconnect at any time.</li>
              </ul>
            )}
          </div>
        </section>

        <div className="rounded-[18px] border border-set-line bg-set-surface p-4 sm:p-5"><GoogleConnectionSection /></div>

        {canConnect && (
          <StickyActionBar note="Nothing is posted until a person approves it.">
            <Button variant="brand" loading={busy} onClick={() => void connect()} className="w-full md:w-auto">Connect Google</Button>
          </StickyActionBar>
        )}
      </div>
    </>
  );
}
