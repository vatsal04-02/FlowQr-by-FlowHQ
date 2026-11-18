"use client";
import { Trash2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Card";
import { Input } from "@/components/ui/Form";
import { Panel } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import { api, ApiError, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate } from "@/lib/format";
import { useFetch } from "@/lib/use-api";

interface MyDeletion {
  state: "none" | "awaiting_confirmation" | "scheduled";
  scheduled_for: string | null;
  confirm_link_expires_at: string | null;
  grace_days: number;
  blocked_by: string[];
  is_platform_admin: boolean;
}

/** Settings › Account: delete MY OWN account (not the business). Three visible states: nothing asked, link emailed (waiting for the click), scheduled (with the date, cancellable). */
export function DeleteMyAccountPanel() {
  const { me } = useAuth();
  const toast = useToast();
  const st = useFetch<MyDeletion>("/account/me/deletion");
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const needsPassword = !!me?.user.has_local_login;
  const d = st.data;

  async function request() {
    setBusy(true); setError(null);
    try {
      st.setData(await api<MyDeletion>("/account/me/deletion", { method: "POST", body: { confirm_email: email, password: needsPassword ? password : undefined } }));
      setOpen(false); setEmail(""); setPassword(""); toast("Check your email for the confirmation link.");
    } catch (e) {
      setError(e instanceof ApiError && e.status === 422 ? "That is not your email address. Type it exactly as shown."
        : e instanceof ApiError && e.status === 403 ? (needsPassword ? "That password is not correct." : "For your security, sign in again and then try straight away.") : errorMessage(e));
    } finally { setBusy(false); }
  }
  async function cancel() {
    setBusy(true);
    try { st.setData(await api<MyDeletion>("/account/me/deletion", { method: "DELETE" })); toast("Cancelled. Your account was not changed."); }
    catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(false); }
  }

  return (
    <Panel title="Delete my account" meta="remove me from FlowQR; this does not delete any business">
      {st.loading && !d ? <p className="text-sm text-ink-500">Loading…</p> : d?.state === "scheduled" ? (
        <Alert tone="warning" title={`Your account will be deleted on ${d.scheduled_for ? fmtDate(d.scheduled_for) : "the scheduled date"}`}
          action={<Button size="sm" variant="secondary" loading={busy} onClick={() => void cancel()}>Cancel deletion</Button>}>
          You have been signed out everywhere else. You can still sign in here until then, and cancel. After that date your name, email, phone and sign-in are removed and you lose access to every business you belong to.</Alert>
      ) : d?.state === "awaiting_confirmation" ? (
        <Alert tone="info" title="Check your email"
          action={<Button size="sm" variant="secondary" loading={busy} onClick={() => void cancel()}>Cancel request</Button>}>
          We sent a confirmation link to {me?.user.email}. It works once{d.confirm_link_expires_at ? ` and expires ${fmtDate(d.confirm_link_expires_at)}` : ""}. Nothing is deleted until you open it.</Alert>
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-ink-700">Deleting your account removes your sign-in, name, email address and phone number, and your access to every business you belong to. <b>It does not delete any business</b>; the people you work with keep working. Google connections that you made for a business are disconnected. You get {d?.grace_days ?? 14} days to change your mind.</p>
          {d?.is_platform_admin && <Alert tone="info">Platform administrator accounts are removed by FlowQR operations, not from here.</Alert>}
          {!!d?.blocked_by.length && <Alert tone="warning" title="You are the only owner of a business">{d.blocked_by.join(", ")}. A business must always have an owner: make someone else an owner (Settings, Team) or delete the business (Settings, Your data), then come back here.</Alert>}
          {!open ? (
            <Button variant="danger" icon={<Trash2 className="h-4 w-4" />} disabled={!!d?.blocked_by.length || !!d?.is_platform_admin} onClick={() => { setError(null); setOpen(true); }}>Delete my account…</Button>
          ) : (
            <div role="group" aria-label="Confirm deleting my account" className="space-y-3 rounded-lg border border-red-200 bg-red-50/60 p-4">
              {error && <Alert tone="error" title="Not requested">{error}</Alert>}
              <Input label={`Type your email address (${me?.user.email ?? ""}) to confirm`} type="email" autoComplete="off" value={email} onChange={(e) => setEmail(e.target.value)} />
              {needsPassword && <Input label="Your password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />}
              <div className="flex gap-2">
                <Button variant="danger" loading={busy} disabled={email.trim().toLowerCase() !== (me?.user.email ?? "").toLowerCase() || (needsPassword && !password)} onClick={() => void request()}>Email me the confirmation link</Button>
                <Button variant="secondary" onClick={() => setOpen(false)}>Not now</Button>
              </div>
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}
