"use client";
import { CheckCircle2, ChevronDown, Clock, KeyRound, MessageSquareText, RefreshCw, Smartphone } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, PageHeader, Skeleton } from "@/components/ui/Card";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { IconTile, Note, StateDot } from "@/components/whatsapp/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-api";
import { connectWhatsApp } from "@/lib/whatsapp-connect";
import { type WaStatus } from "@/lib/whatsapp";
import { connectionHealth } from "@/lib/whatsapp-ui";

/** Your number: Meta's own sign-up window opens, you choose your number, FlowQR keeps the connection safe on its server. No password or key is ever typed or shown here. */
export default function ConnectWhatsApp() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const st = useFetch<WaStatus>("/whatsapp/status");
  const [busy, setBusy] = useState<null | "connect" | "check" | "disconnect">(null);
  const [err, setErr] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const s = st.data;
  const c = s?.connection ?? null;
  const live = !!c && c.status !== "disconnected" && c.status !== "pending";
  const health = connectionHealth(c);
  const main = health[0];

  async function connect() {
    setBusy("connect"); setErr(null);
    try {
      await connectWhatsApp();
      toast("WhatsApp is connected.");
    } catch (e) { setErr(errorMessage(e)); }
    finally { setBusy(null); void st.reload(); }
  }
  async function check() {
    setBusy("check"); setErr(null);
    try { await api("/whatsapp/connection/check", { method: "POST" }); toast("Connection checked."); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(null); void st.reload(); }
  }
  async function disconnect() {
    setBusy("disconnect"); setErr(null);
    try { await api("/whatsapp/connection/disconnect", { method: "POST" }); setConfirm(false); toast("WhatsApp is disconnected. Your customers and their agreements are kept."); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(null); void st.reload(); }
  }
  const canTry = !!s && (s.can_connect || c?.status === "needs_attention");
  const why = !s ? "" : s.addon_required && !s.addon ? "FlowQR switches on the WhatsApp add-on first." : !s.signup_available ? "Connecting opens soon." : "You cannot connect right now.";

  return (
    <>
      <PageHeader title="Connect" />
      {st.error && <Alert tone="error">{st.error}</Alert>}
      {err && <div className="mb-3"><Alert tone="error">{err}</Alert></div>}
      {!s ? <Skeleton className="h-64" /> : (
        <div className="grid gap-3 sm:gap-4 lg:grid-cols-[1.4fr_1fr]">
          <section className="panel p-5 sm:p-6" aria-label="Connection">
            <div className="flex items-center gap-4">
              <IconTile icon={Smartphone} tone={main.state === "ok" ? "pos" : main.state === "bad" ? "neg" : main.state === "warn" ? "warn" : "neutral"} size={56} />
              <div className="min-w-0 flex-1">
                <p className={live ? "num whitespace-nowrap text-[24px] font-semibold leading-8 tracking-[-.02em] text-ink" : "text-[22px] font-semibold leading-8 text-ink-500"}>{live ? c?.display_phone_number ?? "—" : "Not connected"}</p>
                <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[14px] text-muted">
                  <span className="inline-flex items-center gap-1.5"><StateDot state={main.state} />{main.value}</span>
                  {live && c?.is_test_number && <Badge tone="amber">Test number</Badge>}
                </p>
              </div>
            </div>
            {live && c?.verified_name && <p className="mt-4 rounded-2xl bg-surface-2 px-4 py-3 text-[14px] text-ink-700"><span className="text-muted">Customers see </span><span className="font-semibold text-ink">{c.verified_name}</span></p>}

            {live && (
              <ul className="mt-4 grid grid-cols-3 gap-2" aria-label="Connection health">
                {health.map((h) => (
                  <li key={h.key} className="rounded-2xl bg-surface-2 px-2.5 py-3">
                    <p className="text-[13px] leading-4 text-muted">{h.label}</p>
                    <p className="mt-1 flex items-center gap-1.5 text-[13.5px] font-semibold leading-5 text-ink"><StateDot state={h.state} />{h.value}</p>
                  </li>
                ))}
              </ul>
            )}
            {c?.attention_reason && <div className="mt-4"><Alert tone={c.status === "needs_attention" ? "warning" : "info"}>{c.attention_reason}</Alert></div>}

            {isAdmin ? (
              <div className="mt-5 flex flex-wrap gap-2.5">
                {(!live || c?.status === "needs_attention") && <Button variant="brand" size="lg" className="w-full sm:w-auto" loading={busy === "connect"} disabled={!canTry} onClick={() => void connect()} icon={<CheckCircle2 className="h-4 w-4" />}>{live ? "Connect again" : "Connect WhatsApp"}</Button>}
                {live && <Button variant="secondary" loading={busy === "check"} onClick={() => void check()} icon={<RefreshCw className="h-4 w-4" />}>Check connection</Button>}
                {live && <Button variant="ghost" onClick={() => setConfirm(true)}>Disconnect</Button>}
              </div>
            ) : <Note className="mt-4">Only the owner or an admin can change this.</Note>}
            {isAdmin && !live && !canTry && <Note className="mt-3">{why}</Note>}
          </section>

          <div className="space-y-3 sm:space-y-4">
            <section className="panel p-5" aria-label="Before you start">
              <p className="text-[15px] font-semibold text-ink">Before you start</p>
              <ul className="mt-3 grid grid-cols-3 gap-2 text-center">
                {([[MessageSquareText, "Code by SMS or call"], [KeyRound, "Facebook login"], [Clock, "About 10 minutes"]] as const).map(([Icon, text]) => (
                  <li key={text} className="flex flex-col items-center gap-2 rounded-2xl bg-surface-2 px-1.5 py-3.5"><IconTile icon={Icon} tone="neutral" size={36} className="bg-white" /><span className="text-[13px] font-medium leading-4 text-ink-700">{text}</span></li>
                ))}
              </ul>
              <Note className="mt-3">Number already in a WhatsApp app? Tell the FlowQR team first.</Note>
            </section>
            <details className="panel group p-5">
              <summary className="flex min-h-6 cursor-pointer list-none items-center justify-between text-[15px] font-semibold text-ink [&::-webkit-details-marker]:hidden">Good to know<ChevronDown aria-hidden className="h-4 w-4 text-ink-400 transition-transform group-open:rotate-180" /></summary>
              <ul className="mt-3 list-disc space-y-1.5 pl-5 text-[14px] text-ink-700">
                <li>FlowQR never sees your WhatsApp password and never messages anyone without your say-so.</li>
                <li>WhatsApp charges for each message, apart from FlowQR. You see an estimate before any offer is sent.</li>
                <li>You can disconnect any time. Your customers and what they agreed to stay in FlowQR.</li>
              </ul>
            </details>
          </div>
        </div>
      )}
      <Modal open={confirm} onClose={() => setConfirm(false)} title="Disconnect WhatsApp?" footer={<><Button variant="secondary" onClick={() => setConfirm(false)}>Keep it connected</Button><Button variant="danger" loading={busy === "disconnect"} onClick={() => void disconnect()}>Disconnect</Button></>}>
        <p className="text-sm text-ink-700">FlowQR will stop using this number and WhatsApp will stop sending us updates. Your customers and what they agreed to are kept. You can connect again later.</p>
      </Modal>
    </>
  );
}
