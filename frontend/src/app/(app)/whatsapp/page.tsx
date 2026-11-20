"use client";
import { Check, Clock, MessageCircle, Smartphone, Users, Zap } from "lucide-react";
import { LinkButton } from "@/components/ui/Button";
import { Alert, Badge, PageHeader, Skeleton } from "@/components/ui/Card";
import { Figure, Meter, Note, Ring, StateDot, StepRail, TileLink } from "@/components/whatsapp/ui";
import { useFetch } from "@/lib/use-api";
import { currentStep, type WaAutomations, type WaSetup, type WaStatus, type WaUsage } from "@/lib/whatsapp";
import { connectionHealth, firstOpen, pct, STEP_ACTION, stepLine, type StepKey } from "@/lib/whatsapp-ui";

/** WhatsApp overview: one picture of where you are (a ring and a row of six steps), one button for what to do next, and four small tiles. The long explanations live on the screens behind them. */
export default function WhatsAppOverview() {
  const st = useFetch<WaStatus>("/whatsapp/status");
  const au = useFetch<WaAutomations>("/whatsapp/automations");
  const su = useFetch<WaSetup>("/whatsapp/setup");
  const us = useFetch<WaUsage>("/whatsapp/usage");
  const s = st.data, setup = su.data;
  const step = setup ? currentStep(setup) : null;
  const now = setup ? firstOpen(setup.steps) : -1;
  const [numberHealth] = connectionHealth(s?.connection ?? null);
  const live = !!s?.connection && s.connection.status !== "disconnected" && s.connection.status !== "pending";
  const t = us.data?.totals;
  const sending = !!s?.messaging.enabled && !!t && t.attempted > 0;

  return (
    <>
      <PageHeader title="WhatsApp" actions={s?.addon ? <Badge tone="green">{s.addon.label} plan</Badge> : undefined} />
      {st.error && <Alert tone="error">{st.error}</Alert>}
      {!s || !setup ? <div className="space-y-3"><Skeleton className="h-72" /><div className="grid grid-cols-2 gap-3"><Skeleton className="h-36" /><Skeleton className="h-36" /></div></div> : (
        <div className="space-y-3 sm:space-y-4">
          <section className="panel p-5 sm:p-6" aria-label="Set-up progress">
            <div className="flex flex-col items-center gap-5 text-center sm:flex-row sm:gap-7 sm:text-left">
              <Ring done={setup.done} total={setup.total} size={132} complete={setup.complete} label={`${setup.done} of ${setup.total} set-up steps done`}>
                {setup.complete
                  ? <Check className="h-12 w-12 text-pos" strokeWidth={2.5} aria-hidden />
                  : <span className="num text-[36px] font-semibold leading-none tracking-[-.03em] text-ink">{setup.done}<span className="text-[20px] font-medium text-ink-300">/{setup.total}</span></span>}
              </Ring>
              <div className="min-w-0 flex-1">
                <h2 className="text-[22px] font-semibold leading-7 tracking-[-.015em] text-ink">{setup.complete ? "You are all set" : STEP_ACTION[step!.key as StepKey]}</h2>
                <p className="mt-1 text-[15px] leading-6 text-muted">{setup.complete ? "Helpers are ready to work." : stepLine(step!)}</p>
                <LinkButton href="/whatsapp/setup" variant={setup.complete ? "secondary" : "brand"} size="lg" className="mt-4 w-full sm:w-auto">
                  {setup.complete ? "Review set-up" : step?.state === "waiting" ? "See status" : setup.done === 0 ? "Start" : "Continue"}
                </LinkButton>
              </div>
            </div>
            {!setup.complete && <div className="mt-6 border-t border-line pt-4"><StepRail steps={setup.steps.map((x) => ({ key: x.key, state: x.state }))} current={now} /></div>}
          </section>

          <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
            <TileLink href="/whatsapp/connect" icon={Smartphone} tone={numberHealth.state === "ok" ? "pos" : numberHealth.state === "bad" ? "neg" : numberHealth.state === "warn" ? "warn" : "neutral"}
              label={<><StateDot state={numberHealth.state} />{s.connection?.is_test_number && live ? "Test number" : numberHealth.value}</>}>
              <p className={live ? "num whitespace-nowrap text-[16px] font-semibold leading-6 tracking-[-.015em] text-ink" : "text-[17px] font-semibold leading-6 text-ink-500"}>{live ? s.connection?.display_phone_number : "No number yet"}</p>
            </TileLink>
            <TileLink href="/whatsapp/contacts" icon={Users} tone="brand" label="Customers">
              <Figure value={s.counts.contacts} />
            </TileLink>
            <TileLink href="/whatsapp/messages" icon={MessageCircle} tone={sending ? "pos" : "neutral"} label={sending ? "Sent this month" : <><Clock aria-hidden className="h-3.5 w-3.5" />{s.messaging.enabled ? "Nothing sent yet" : "Not sending yet"}</>}>
              {sending ? <><Figure value={t!.sent} /><div className="mt-2"><Meter value={pct(t!.read, t!.sent)} tone="pos" label="Share read" /></div></> : <p className="text-[17px] font-semibold leading-6 text-ink-500">Off</p>}
            </TileLink>
            <TileLink href="/whatsapp/automations" icon={Zap} tone={au.data && au.data.active > 0 ? "pos" : "neutral"} label="Helpers on">
              <Figure value={<>{au.data?.active ?? 0}<span className="text-[18px] font-medium text-ink-300">{au.data?.limit ? `/${au.data.limit}` : ""}</span></>} />
            </TileLink>
          </div>

          <Note className="px-1">WhatsApp charges per message, apart from FlowQR. You see an estimate before anything is sent.</Note>
        </div>
      )}
    </>
  );
}
