"use client";
import { Check, Circle } from "lucide-react";
import Link from "next/link";
import { Alert, Badge, Card, PageHeader, Skeleton } from "@/components/ui/Card";
import { automationStatus, type WaAutomation, type WaAutomations } from "@/lib/whatsapp";
import { useFetch } from "@/lib/use-api";

function Need({ done, children }: { done: boolean; children: React.ReactNode }) {
  return <li className="flex items-start gap-2 text-[13px] text-ink-700">{done ? <Check className="mt-0.5 h-4 w-4 shrink-0 text-pos" aria-label="Done" /> : <Circle className="mt-0.5 h-4 w-4 shrink-0 text-ink-300" aria-label="Not yet" />}<span>{children}</span></li>;
}

function Card1({ a }: { a: WaAutomation }) {
  return (
    <Card>
      <div className="flex items-start justify-between gap-3"><h2 className="text-lg font-semibold text-ink">{a.title}</h2><Badge tone="gray">{automationStatus(a)}</Badge></div>
      <p className="mt-1 text-sm text-ink-700">{a.description}</p>
      <p className="mt-3 text-[13px] font-semibold text-ink-500">What it needs</p>
      <ul className="mt-1 space-y-1">
        <Need done={a.ready.connection}>Your WhatsApp number is connected</Need>
        <Need done={a.ready.customers}>{a.purpose === "marketing" ? "Customers who agreed to receive offers" : "Customers who agreed to updates about their visit or enquiry"}</Need>
        {a.purpose === "marketing" && <li className="text-[13px] text-ink-500">An approved message, and your OK before anything is sent.</li>}
      </ul>
    </Card>
  );
}

/** The ready-made outcomes. In this first release they are shown, not switched on: nothing is sent yet. */
export default function Automations() {
  const { data, error } = useFetch<WaAutomations>("/whatsapp/automations");
  return (
    <>
      <PageHeader title="Automations" subtitle="Ready-made helpers. You pick one, check a few details and switch it on." />
      {error && <Alert tone="error">{error}</Alert>}
      {!data ? <Skeleton className="h-64" /> : (
        <div className="space-y-4">
          <Alert tone="info" title="Coming soon">These helpers are being finished. When they are ready you will switch them on here. Meanwhile, connect your number and add the customers who agreed to hear from you.</Alert>
          {data.limit !== null && <p className="text-sm text-ink-700">Your plan allows up to <b>{data.limit}</b> automations at a time.</p>}
          <div className="grid gap-4 lg:grid-cols-2">{data.items.map((a) => <Card1 key={a.key} a={a} />)}</div>
          <p className="text-[13px] text-ink-500">WhatsApp charges for each message, separately from FlowQR. <Link href="/whatsapp/contacts" className="font-semibold text-brand-700 hover:underline">Customers who agreed</Link> are the only ones who will ever be messaged.</p>
        </div>
      )}
    </>
  );
}
