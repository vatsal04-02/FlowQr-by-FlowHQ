"use client";
import Link from "next/link";
import { Alert, PageHeader, Skeleton } from "@/components/ui/Card";
import { Panel, Status } from "@/components/ui/kit";
import type { Integration } from "@/lib/agent";
import { useFetch } from "@/lib/use-api";

const TONE = { connected: "ok", attention: "warn", not_connected: "idle", setup_required: "warn", not_available: "idle" } as const;
const WORD = { connected: "Connected", attention: "Needs attention", not_connected: "Not connected", setup_required: "Setup required", not_available: "Not available yet" } as const;

export default function Connections() {
  const { data, error } = useFetch<{ integrations: Integration[] }>("/workspace/integrations");
  return (
    <>
      <PageHeader eyebrow="Settings" title="Connections" subtitle={'"Connected" appears only after the service has actually answered a real request for your business.'} />
      {error && <Alert tone="error">{error}</Alert>}
      {!data ? <Skeleton className="h-64" /> : (
        <div className="grid gap-4 lg:grid-cols-2">{data.integrations.map((i) => (
          <Panel key={i.id} title={i.label} action={<Status tone={TONE[i.status]}>{WORD[i.status]}</Status>}>
            <p className="text-sm text-ink-700">{i.detail}</p>
            {i.steps.length > 0 && <ol className="ml-5 mt-2 list-decimal space-y-1 text-[13px] text-ink-500">{i.steps.map((s) => <li key={s}>{s}</li>)}</ol>}
            {i.href && <p className="mt-3"><Link className="text-[13px] font-medium text-brand-700 hover:underline" href={i.href}>Open</Link></p>}
          </Panel>))}</div>)}
    </>
  );
}
