"use client";
import { Check, Clock, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";
import { GoogleConnectionSection } from "@/components/gbp/GoogleConnection";
import { StatusChip, type ChipKind } from "@/components/settings/parts";
import { PageHeader, Skeleton } from "@/components/ui/Card";
import { googleLine, syncChip } from "@/lib/shell-status";
import type { GoogleConnection, GoogleLocation } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

const List = ({ title, kind, items }: { title: string; kind: ChipKind; items: string[] }) => (
  <section className="rounded-[18px] border border-set-line bg-set-surface p-4" aria-label={title}>
    <StatusChip kind={kind}>{title}</StatusChip>
    <ul className="mt-3 space-y-2.5">
      {items.map((t) => <li key={t} className="flex gap-2.5 text-[14px] font-medium leading-snug text-set-soft"><Check aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-set-ok-dot" strokeWidth={2.25} />{t}</li>)}
    </ul>
  </section>
);

const Block = ({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) => (
  <section className="flex gap-3.5 rounded-[18px] border border-set-line bg-set-surface p-4" aria-label={title}>
    <span aria-hidden className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-set-t-connect text-set-i-connect">{icon}</span>
    <div className="min-w-0"><h2 className="text-[15px] font-bold text-set-ink">{title}</h2><div className="mt-1 space-y-1.5 text-[14px] font-medium leading-snug text-set-soft">{children}</div></div>
  </section>
);

/**
 * Connected accounts › Google Business Profile: the one place Google is connected, explained and diagnosed. Every other screen that needs Google links here
 * (components/settings/parts.tsx, ConnectGoogleEmptyState). The connection itself (sign-in, guided setup, choosing locations, disconnecting) is the existing, tested component.
 */
export default function GoogleSettingsPage() {
  const status = useFetch<{ configured: boolean; connections: GoogleConnection[] }>("/google/status");
  const active = status.data?.connections.find((c) => c.status === "active");
  const locs = useFetch<GoogleLocation[]>(active ? `/google/connections/${active.id}/locations` : null);
  const line = googleLine(status.data?.connections);
  const sync = syncChip(locs.data);
  const kind: ChipKind = line?.tone === "ok" ? "ok" : line ? "warn" : "neutral";
  const headline = !line ? "Checking…" : line.tone === "ok" ? "Connected" : line.label === "Google not connected" ? "Not connected" : line.label;

  return (
    <>
      <PageHeader title="Google Business Profile" subtitle="Where FlowQR reads your reviews and, once you approve each one, publishes your replies." />
      <div className="space-y-4">
        <section aria-label="Connection status" className="rounded-[18px] border border-set-line bg-set-surface p-4 sm:p-5">
          {status.loading && !status.data ? <Skeleton className="h-16" /> : (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
              <StatusChip kind={kind}>{headline}</StatusChip>
              {sync && <span className="inline-flex items-center gap-1.5 text-[13px] font-medium text-set-muted"><Clock aria-hidden className="h-3.5 w-3.5" />{sync.kind === "ok" ? "Reviews are syncing" : sync.label}</span>}
              <p className="basis-full text-[14px] font-medium text-set-soft">
                {line?.tone === "ok" ? "Your Google account is linked. Choose below which locations FlowQR looks after."
                  : "Connect once and FlowQR can bring in your reviews and prepare replies for you to approve."}
              </p>
            </div>
          )}
        </section>

        <div className="grid gap-4 md:grid-cols-2">
          <List title="Works now" kind="ok" items={["QR and NFC cards and your review links", "AI help writing review requests and replies"]} />
          <List title="After you connect" kind="info" items={["Your Google reviews come into the inbox", "Approved replies are published for you", "Profile, ranking and performance pages fill with real data"]} />
        </div>

        <Block icon={<ShieldCheck className="h-5 w-5" strokeWidth={1.75} />} title="What FlowQR accesses">
          <p>Your Business Profile locations and reviews.</p>
          <p>Replies go out only after you approve each one, and show as published only after Google confirms.</p>
          <p>Sign-in details are encrypted and never sent to your browser. You can disconnect at any time.</p>
        </Block>

        <div className="rounded-[18px] border border-set-line bg-set-surface p-4 sm:p-5"><GoogleConnectionSection /></div>
      </div>
    </>
  );
}
