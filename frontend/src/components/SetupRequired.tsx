"use client";
import type { ReactNode } from "react";
import { LinkButton } from "@/components/ui/Button";
import { Alert, Skeleton } from "@/components/ui/Card";
import { Panel, Status } from "@/components/ui/kit";
import type { Integration } from "@/lib/agent";
import { useFetch } from "@/lib/use-api";

const TONE = { connected: "ok", attention: "warn", not_connected: "idle", setup_required: "warn", not_available: "idle" } as const;
const WORD = { connected: "Connected", attention: "Needs attention", not_connected: "Not connected", setup_required: "Setup required", not_available: "Not available yet" } as const;

/** An honest "this isn't live yet" page. Its status comes from the server, which only says "Connected" after a real call succeeded. */
export function SetupRequired({ integration, what, plans, children }: { integration: string; what: string; plans: string[]; children?: ReactNode }) {
  const { data, loading } = useFetch<{ integrations: Integration[] }>("/workspace/integrations");
  const i = data?.integrations.find((x) => x.id === integration);
  return (
    <div className="space-y-4">
      <Panel title={what} action={i ? <Status tone={TONE[i.status]}>{WORD[i.status]}</Status> : undefined}>
        {loading && !data ? <Skeleton className="h-16" /> : (
          <div className="space-y-3 text-sm">
            <p className="text-ink-700">{i?.detail ?? "This part of FlowQR is not connected."}</p>
            {i && i.steps.length > 0 && <div><p className="mb-1 text-[13px] font-medium text-ink-500">What has to happen first</p><ol className="ml-5 list-decimal space-y-1 text-ink-700">{i.steps.map((s) => <li key={s}>{s}</li>)}</ol></div>}
            {i?.href && <LinkButton href={i.href} size="sm" variant="secondary">Open</LinkButton>}
          </div>)}
      </Panel>
      <Panel title="What this will do" meta="planned, not available yet">
        <ul className="ml-5 list-disc space-y-1 text-sm text-ink-700">{plans.map((p) => <li key={p}>{p}</li>)}</ul>
        <p className="mt-3 text-xs text-ink-500">Nothing on this page is simulated: no messages, rankings, posts or results are shown until the real service is connected and FlowQR has a working integration for it.</p>
      </Panel>
      {children}
    </div>
  );
}

export function NotLiveNote() {
  return <Alert tone="info" title="Not live yet">This area is planned. It shows exactly what is missing instead of pretending to work.</Alert>;
}
