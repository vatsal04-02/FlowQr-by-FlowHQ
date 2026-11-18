"use client";
import { MessageCircle, ShieldCheck, Users } from "lucide-react";
import Link from "next/link";
import { LinkButton } from "@/components/ui/Button";
import { Alert, Badge, Card, CardHeader, PageHeader, Skeleton, Stat } from "@/components/ui/Card";
import { connectionWords, nextStep, type WaAutomations, type WaStatus } from "@/lib/whatsapp";
import { useFetch } from "@/lib/use-api";

/** WhatsApp overview. Everything here is in plain words: where the set-up stands, what to do next, who has agreed to hear from you. Nothing has been sent from here yet. */
export default function WhatsAppOverview() {
  const st = useFetch<WaStatus>("/whatsapp/status");
  const au = useFetch<WaAutomations>("/whatsapp/automations");
  const s = st.data;
  const conn = connectionWords(s?.connection ?? null);
  const step = s ? nextStep(s) : null;
  return (
    <>
      <PageHeader title="WhatsApp" subtitle="Remind customers, ask for reviews and send offers, only to people who agreed to hear from you." />
      {st.error && <Alert tone="error">{st.error}</Alert>}
      {!s ? <Skeleton className="h-72" /> : (
        <div className="space-y-4">
          {step && (
            <Card>
              <p className="text-[13px] font-semibold uppercase tracking-wide text-ink-500">Your next step</p>
              <h2 className="mt-1 text-xl font-semibold text-ink">{step.title}</h2>
              <p className="mt-1 max-w-2xl text-sm text-ink-700">{step.body}</p>
              <div className="mt-4"><LinkButton href={step.href} variant="brand">{step.cta}</LinkButton></div>
            </Card>
          )}
          <div className="grid gap-4 lg:grid-cols-3">
            <Card>
              <CardHeader title="Your WhatsApp number" action={<Badge tone={conn.tone}>{conn.label}</Badge>} />
              {s.connection && s.connection.status !== "disconnected" && s.connection.display_phone_number ? (
                <p className="text-lg font-semibold tabular-nums text-ink">{s.connection.display_phone_number}{s.connection.is_test_number && <span className="ml-2 align-middle"><Badge tone="amber">Test number</Badge></span>}</p>
              ) : null}
              <p className="mt-1 text-sm text-ink-700">{conn.hint}</p>
              <p className="mt-3"><Link href="/whatsapp/connect" className="text-[13px] font-semibold text-brand-700 hover:underline">{s.connection ? "Manage connection" : "Connect"}</Link></p>
            </Card>
            <Card>
              <CardHeader title="Customers who agreed" action={<Users className="h-5 w-5 text-ink-400" aria-hidden />} />
              <div className="grid grid-cols-2 gap-3">
                <Stat label="To offers" value={s.counts.marketing} />
                <Stat label="To visit updates" value={s.counts.utility} />
              </div>
              <p className="mt-3 text-[13px] text-ink-500">{s.counts.opted_out > 0 ? `${s.counts.opted_out} asked to stop offers. We never message them with offers again. ` : ""}<Link href="/whatsapp/contacts" className="font-semibold text-brand-700 hover:underline">See your customers</Link></p>
            </Card>
            <Card>
              <CardHeader title="Messages" action={<MessageCircle className="h-5 w-5 text-ink-400" aria-hidden />} />
              <p className="text-sm text-ink-700">{s.messaging.enabled ? "Messages can be sent." : "Sending is not switched on yet. When it is, you will see here how many were sent and delivered."}</p>
              <p className="mt-3 text-[13px] text-ink-500">WhatsApp (Meta) charges for each message separately from FlowQR. You will always see the estimate before anything is sent.</p>
            </Card>
          </div>
          <Card>
            <CardHeader title="Your plan" action={<ShieldCheck className="h-5 w-5 text-ink-400" aria-hidden />} />
            {s.addon ? <p className="text-sm text-ink-700"><span className="font-semibold text-ink">{s.addon.label}.</span> {s.addon.summary}</p>
              : <p className="text-sm text-ink-700">WhatsApp automation is an add-on to your FlowQR plan. Ask the FlowQR team to switch it on for your business.</p>}
            {s.addon && au.data && <p className="mt-1 text-[13px] text-ink-500">Up to {au.data.limit} automations at a time.</p>}
          </Card>
          <Card>
            <CardHeader title="What you will be able to do" action={<Link href="/whatsapp/automations" className="text-[13px] font-semibold text-brand-700 hover:underline">See all</Link>} />
            <ul className="grid gap-3 sm:grid-cols-3">
              {(au.data?.items ?? []).filter((a) => ["review_followup", "enquiry_followup", "offers"].includes(a.key)).map((a) => (
                <li key={a.key} className="rounded-2xl bg-surface-2 p-4"><p className="font-semibold text-ink">{a.title}</p><p className="mt-1 text-[13px] text-ink-700">{a.description}</p></li>
              ))}
            </ul>
          </Card>
        </div>
      )}
    </>
  );
}
