"use client";
import { Lock, MapPin, MessageCircle, Share2 } from "lucide-react";
import type { ReactNode } from "react";
import { SettingsGroup, StatusChip, type ChipKind } from "@/components/settings/parts";
import { MANAGED_WORD, OWNER_WORD } from "@/components/settings/status";
import { LinkButton } from "@/components/ui/Button";
import { ErrorState, PageHeader, Skeleton } from "@/components/ui/Card";
import type { Integration } from "@/lib/agent";
import { useAuth } from "@/lib/auth";
import { googleLine } from "@/lib/shell-status";
import type { GoogleConnection } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

const MANAGED = ["email", "ai", "razorpay", "rank_provider"];
const MANAGED_LABEL: Record<string, string> = { email: "Email", ai: "AI provider", razorpay: "Payments", rank_provider: "Local rank tracking" };

/** One connectable service: a 44px tinted icon, its name and status chip, one plain sentence, and (when there is something to press) one button. */
function ServiceCard({ icon, title, chip, text, action }: { icon: ReactNode; title: string; chip: { kind: ChipKind; label: string } | null; text: string; action?: ReactNode }) {
  return (
    <section aria-label={title} className="flex flex-col gap-3.5 rounded-[18px] border border-set-line bg-set-surface p-4">
      <div className="flex items-center gap-3.5">
        <span aria-hidden className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-set-t-connect text-set-i-connect">{icon}</span>
        <div className="min-w-0 flex-1"><h2 className="text-base font-extrabold leading-tight text-set-ink">{title}</h2>{chip && <StatusChip kind={chip.kind} className="mt-1.5">{chip.label}</StatusChip>}</div>
      </div>
      <p className="text-[14px] font-medium leading-relaxed text-set-soft">{text}</p>
      {action}
    </section>
  );
}

/**
 * Connected accounts: Google, WhatsApp and Facebook & Instagram as one card each, then what FlowQR runs for you (read-only, nothing to set up). Google is connected on its own page.
 * The server's own sentences name environment variables, so owners never see them; platform administrators see them under the managed list.
 */
export default function Connections() {
  const { me } = useAuth();
  const admin = !!me?.user.is_platform_admin;
  const waOn = !!me?.integrations.whatsapp_enabled;
  const { data, error, reload } = useFetch<{ integrations: Integration[] }>("/workspace/integrations");
  const google = useFetch<{ configured: boolean; connections: GoogleConnection[] }>("/google/status");
  const g = googleLine(google.data?.connections);
  const gChip = g ? (g.tone === "ok" ? { kind: "ok" as const, label: "Connected" } : { kind: "warn" as const, label: g.tone === "idle" ? "Not connected" : g.label }) : null;
  const by = (id: string) => data?.integrations.find((i) => i.id === id);
  const wa = by("whatsapp"), meta = by("meta");
  const managed = (data?.integrations ?? []).filter((i) => MANAGED.includes(i.id));
  const small = "w-full";
  return (
    <>
      <PageHeader title="Connected accounts" subtitle="Connected appears only after the service has answered a real request for your business." />
      <div className="space-y-4">
        {error && <ErrorState error={error} onRetry={() => void reload()} />}
        {!data && !error ? <Skeleton className="h-72" /> : (
          <>
            <ServiceCard icon={<MapPin className="h-[22px] w-[22px]" strokeWidth={1.8} />} title="Google Business Profile" chip={gChip}
              text="Sync reviews, publish approved replies and manage your profile hours, posts and photos."
              action={g?.tone === "ok"
                ? <LinkButton href="/settings/connections/google" variant="secondary" className={small}>Manage Google</LinkButton>
                : <LinkButton href="/settings/connections/google" variant="brand" className={small}>Connect Google</LinkButton>} />
            <ServiceCard icon={<MessageCircle className="h-[22px] w-[22px]" strokeWidth={1.8} />} title="WhatsApp Business" chip={wa ? OWNER_WORD[wa.status] : null}
              text={wa?.status === "connected" ? "Customer chats, auto-replies and bookings." : "Customer chats, auto-replies and bookings. Messaging isn't set up yet."}
              action={waOn ? <LinkButton href="/whatsapp/connect" variant="secondary" className={small}>Open WhatsApp setup</LinkButton> : undefined} />
            <ServiceCard icon={<Share2 className="h-[22px] w-[22px]" strokeWidth={1.8} />} title="Facebook & Instagram" chip={meta ? OWNER_WORD[meta.status] : null}
              text="Publish approved posts to your pages. Publishing isn't available yet." />

            <SettingsGroup id="managed" label="Managed by FlowQR">
              {managed.map((i) => {
                const w = MANAGED_WORD[i.status];
                return (
                  <div key={i.id} className="border-t border-set-line px-4 py-3 first:border-t-0">
                    <div className="flex min-h-9 items-center justify-between gap-3"><span className="text-[14px] font-bold text-set-ink">{MANAGED_LABEL[i.id] ?? i.label}</span><StatusChip kind={w.kind}>{w.label}</StatusChip></div>
                    {admin && (
                      <div className="mt-2 rounded-xl bg-set-paper p-3 text-[13px] font-medium text-set-soft">
                        <p>{i.detail}</p>
                        {i.steps.length > 0 && <ol className="ml-5 mt-1.5 list-decimal space-y-1">{i.steps.map((s) => <li key={s}>{s}</li>)}</ol>}
                      </div>
                    )}
                  </div>
                );
              })}
              <p className="flex items-start gap-2 border-t border-set-line px-4 py-3 text-[13px] font-medium leading-snug text-set-muted"><Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />These are set up by your FlowQR administrator. Nothing for you to enter here.</p>
            </SettingsGroup>
          </>
        )}
      </div>
    </>
  );
}
