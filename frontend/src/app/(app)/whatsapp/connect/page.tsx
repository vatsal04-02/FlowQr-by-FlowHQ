"use client";
import { CheckCircle2, Phone, RefreshCw } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, CardHeader, PageHeader, Skeleton } from "@/components/ui/Card";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-api";
import { connectionWords, launchEmbeddedSignup, type SignupStart, type WaConnection, type WaStatus } from "@/lib/whatsapp";

/** Connect your WhatsApp: Meta's own sign-up window opens, you choose your number, FlowQR keeps the connection safe on its server. No password or key is ever typed here or shown here. */
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
  const words = connectionWords(c);

  async function connect() {
    setBusy("connect"); setErr(null);
    try {
      const start = await api<SignupStart>("/whatsapp/connect/start", { method: "POST" });
      const got = await launchEmbeddedSignup(start);
      await api<WaConnection>("/whatsapp/connect/complete", { method: "POST", body: { state: start.state, code: got.code, waba_id: got.waba_id, phone_number_id: got.phone_number_id } });
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

  return (
    <>
      <PageHeader title="Connect your WhatsApp" subtitle="Use your own business number. Customers will see messages from your number, not FlowQR's." />
      {st.error && <Alert tone="error">{st.error}</Alert>}
      {err && <div className="mb-4"><Alert tone="error">{err}</Alert></div>}
      {!s ? <Skeleton className="h-64" /> : (
        <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
          <div className="space-y-4">
            <Card>
              <CardHeader title="Connection status" action={<Badge tone={words.tone}>{words.label}</Badge>} />
              {live ? (
                <dl className="grid gap-3 text-sm sm:grid-cols-2">
                  <div><dt className="text-ink-500">Number</dt><dd className="mt-0.5 flex items-center gap-2 font-semibold tabular-nums"><Phone className="h-4 w-4 text-ink-400" aria-hidden />{c?.display_phone_number ?? "—"}{c?.is_test_number && <Badge tone="amber">Test number</Badge>}</dd></div>
                  <div><dt className="text-ink-500">Name customers see</dt><dd className="mt-0.5 font-semibold">{c?.verified_name ?? "—"}</dd></div>
                  <div><dt className="text-ink-500">Delivery updates</dt><dd className="mt-0.5 font-semibold">{c?.webhook_status === "subscribed" ? "On" : "Not working yet"}</dd></div>
                  <div><dt className="text-ink-500">Number quality</dt><dd className="mt-0.5 font-semibold">{c?.quality_rating === "GREEN" ? "Good" : c?.quality_rating === "YELLOW" ? "Medium" : c?.quality_rating === "RED" ? "Low" : "Not shown yet"}</dd></div>
                </dl>
              ) : <p className="text-sm text-ink-700">{words.hint}</p>}
              {c?.attention_reason && <div className="mt-3"><Alert tone={c.status === "needs_attention" ? "warning" : "info"}>{c.attention_reason}</Alert></div>}
              {!isAdmin && <p className="mt-3 text-[13px] text-ink-500">Only the owner or an admin of the business can change the connection.</p>}
              {isAdmin && (
                <div className="mt-4 flex flex-wrap gap-2">
                  {(!live || c?.status === "needs_attention") && <Button variant="brand" loading={busy === "connect"} disabled={!s.can_connect && c?.status !== "needs_attention"} onClick={() => void connect()} icon={<CheckCircle2 className="h-4 w-4" />}>{live ? "Connect again" : "Connect WhatsApp"}</Button>}
                  {live && <Button variant="secondary" loading={busy === "check"} onClick={() => void check()} icon={<RefreshCw className="h-4 w-4" />}>Check connection</Button>}
                  {live && <Button variant="ghost" onClick={() => setConfirm(true)}>Disconnect</Button>}
                </div>
              )}
              {isAdmin && !live && !s.can_connect && (
                <div className="mt-3"><Alert tone="info">{s.addon_required && !s.addon ? "WhatsApp automation is an add-on. Ask the FlowQR team to switch it on for your business, then come back here." : !s.signup_available ? "Connecting is not available yet. FlowQR is still completing its set-up with Meta." : "You cannot connect right now."}</Alert></div>
              )}
            </Card>
          </div>
          <div className="space-y-4">
            <Card>
              <CardHeader title="Before you start" />
              <ul className="list-disc space-y-1.5 pl-5 text-sm text-ink-700">
                <li>A phone number that can receive a code by SMS or call.</li>
                <li>A Facebook login. WhatsApp uses it to confirm you run this business.</li>
                <li>About ten minutes.</li>
              </ul>
              <p className="mt-3 text-[13px] text-ink-500">If this number is already used in a WhatsApp app on your phone, tell the FlowQR team first. It may need a different number or extra steps.</p>
            </Card>
            <Card>
              <CardHeader title="Good to know" />
              <ul className="list-disc space-y-1.5 pl-5 text-sm text-ink-700">
                <li>FlowQR never sees your WhatsApp password and never messages anyone without your say-so.</li>
                <li>WhatsApp charges for each message. That is separate from FlowQR and you will see an estimate before any offer is sent.</li>
                <li>You can disconnect at any time. Your customers and what they agreed to stay in FlowQR.</li>
              </ul>
            </Card>
          </div>
        </div>
      )}
      <Modal open={confirm} onClose={() => setConfirm(false)} title="Disconnect WhatsApp?" footer={<><Button variant="secondary" onClick={() => setConfirm(false)}>Keep it connected</Button><Button variant="danger" loading={busy === "disconnect"} onClick={() => void disconnect()}>Disconnect</Button></>}>
        <p className="text-sm text-ink-700">FlowQR will stop using this number and WhatsApp will stop sending us updates. Your customers and what they agreed to are kept. You can connect again later.</p>
      </Modal>
    </>
  );
}
