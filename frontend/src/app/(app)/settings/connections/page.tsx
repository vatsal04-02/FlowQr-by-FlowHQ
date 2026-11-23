"use client";
import { Lock, MessageCircle, Share2 } from "lucide-react";
import Link from "next/link";
import { SettingsGroup, StatusChip, type ChipKind } from "@/components/settings/parts";
import { Button } from "@/components/ui/Button";
import { Alert, PageHeader, Skeleton } from "@/components/ui/Card";
import type { Integration } from "@/lib/agent";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-api";

const OWNER_WORD: Record<Integration["status"], { kind: ChipKind; label: string }> = {
  connected: { kind: "ok", label: "Connected" }, attention: { kind: "warn", label: "Needs attention" }, not_connected: { kind: "warn", label: "Not connected" },
  setup_required: { kind: "neutral", label: "Setup required" }, not_available: { kind: "neutral", label: "Not available yet" },
};
const MANAGED_WORD: Record<Integration["status"], { kind: ChipKind; label: string }> = {
  connected: { kind: "ok", label: "Working" }, attention: { kind: "warn", label: "Paused" }, not_connected: { kind: "neutral", label: "Being set up" },
  setup_required: { kind: "neutral", label: "Being set up" }, not_available: { kind: "neutral", label: "Being set up" },
};
/** Things a business connects itself, with a plain sentence of ours (the server's own text names environment variables, so owners never see it). */
const OWN: Record<string, { title: string; sub: string; href: string | null }> = {
  whatsapp: { title: "WhatsApp Business", sub: "Customer chats and messages", href: "/whatsapp/connect" },
  meta: { title: "Facebook and Instagram", sub: "Posting to your pages", href: null },
};
const MANAGED = ["ai", "razorpay", "email", "rank_provider"];

/** Connected accounts › Other connections. Google has its own page. What FlowQR runs for you (email, AI, payments) is a read-only list: instructions for it are for administrators only. */
export default function Connections() {
  const { me } = useAuth();
  const admin = !!me?.user.is_platform_admin;
  const { data, error, reload } = useFetch<{ integrations: Integration[] }>("/workspace/integrations");
  const own = (data?.integrations ?? []).filter((i) => OWN[i.id]);
  const managed = (data?.integrations ?? []).filter((i) => MANAGED.includes(i.id));
  return (
    <>
      <PageHeader title="Other connections" subtitle="Google Business Profile has its own page. Connected means the service has answered a real request for your business." />
      <div className="space-y-5">
        <Link href="/settings/connections/google" className="set-focus flex min-h-12 items-center justify-between gap-3 rounded-[14px] border border-set-line bg-set-surface px-4 text-[15px] font-bold text-set-ink">
          Google Business Profile<span className="text-[13px] font-bold text-set-action">Open</span>
        </Link>
        {error && <Alert tone="error" title="This did not load" action={<Button size="sm" variant="secondary" onClick={() => void reload()}>Try again</Button>}>{error} Nothing was changed.</Alert>}
        {!data && !error ? <Skeleton className="h-48" /> : data && (
          <>
            <SettingsGroup id="own" label="Your accounts">
              {own.map((i) => {
                const o = OWN[i.id], w = OWNER_WORD[i.status];
                const body = (
                  <div className="flex min-h-[68px] items-center gap-3.5 border-t border-set-line px-4 py-3 first:border-t-0">
                    <span aria-hidden className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-set-t-connect text-set-i-connect">{i.id === "whatsapp" ? <MessageCircle className="h-5 w-5" strokeWidth={1.75} /> : <Share2 className="h-5 w-5" strokeWidth={1.75} />}</span>
                    <span className="min-w-0 flex-1"><span className="block text-[15px] font-bold text-set-ink">{o.title}</span><span className="block text-[13px] font-medium text-set-muted">{o.sub}</span><StatusChip kind={w.kind} className="mt-1.5 sm:hidden">{w.label}</StatusChip></span>
                    <StatusChip kind={w.kind} className="hidden sm:inline-flex">{w.label}</StatusChip>
                  </div>
                );
                return o.href ? <Link key={i.id} href={o.href} className="set-focus block hover:bg-set-paper">{body}</Link> : <div key={i.id}>{body}</div>;
              })}
            </SettingsGroup>

            <SettingsGroup id="managed" label="Managed by FlowQR">
              <p className="flex items-start gap-2 px-4 pt-3 text-[13px] font-medium text-set-muted"><Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />FlowQR runs these for you. There is nothing to set up.</p>
              {managed.map((i) => {
                const w = MANAGED_WORD[i.status];
                return (
                  <div key={i.id} className="border-t border-set-line px-4 py-3 first:border-t-0">
                    <div className="flex items-center justify-between gap-3"><span className="text-[15px] font-bold text-set-ink">{i.label.replace(/ \(.*\)$/, "")}</span><StatusChip kind={w.kind}>{w.label}</StatusChip></div>
                    {admin && (
                      <div className="mt-2 rounded-xl bg-set-paper p-3 text-[13px] font-medium text-set-soft">
                        <p>{i.detail}</p>
                        {i.steps.length > 0 && <ol className="ml-5 mt-1.5 list-decimal space-y-1">{i.steps.map((s) => <li key={s}>{s}</li>)}</ol>}
                      </div>
                    )}
                  </div>
                );
              })}
            </SettingsGroup>
          </>
        )}
      </div>
    </>
  );
}
