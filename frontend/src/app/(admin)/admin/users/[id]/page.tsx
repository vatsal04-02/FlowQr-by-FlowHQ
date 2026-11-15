"use client";
import clsx from "clsx";
import { ArrowLeft, CheckCircle2, LogOut, MailCheck, Send, XCircle } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { signIn, type UserDetail } from "@/components/admin/LoginCheck";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, PageHeader, Skeleton } from "@/components/ui/Card";
import { Modal } from "@/components/ui/Modal";
import { Panel } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { fmtDate, timeAgo } from "@/lib/format";
import { SUB_TONE } from "@/lib/admin-ui";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-api";

const ACTION: Record<string, string> = { "auth.login": "Logged in", "auth.login_google": "Logged in with Google", "auth.logout": "Logged out", "auth.password_reset": "Reset their password", "auth.password_change": "Changed their password" };

export default function UserPage() {
  const { id } = useParams<{ id: string }>();
  const { me } = useAuth();
  const toast = useToast();
  const { data: d, error, reload } = useFetch<UserDetail>(`/admin/users/${id}`);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<"deactivate" | "reset" | null>(null);

  async function run(key: string, fn: () => Promise<unknown>, ok: string) {
    setBusy(key);
    try { await fn(); toast(ok); setConfirm(null); await reload(); } catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(null); }
  }
  if (error) return <Alert tone="error">{error}</Alert>;
  if (!d) return <Skeleton className="h-64" />;
  const u = d.user, self = me?.user.id === u.id;
  return (
    <>
      <Link href="/admin/users" className="mb-4 inline-flex min-h-11 items-center gap-1.5 text-sm font-semibold text-muted hover:text-ink"><ArrowLeft className="h-4 w-4" aria-hidden />All users</Link>
      <PageHeader title={u.full_name || u.email} subtitle={<span className="break-all">{u.email}{u.phone ? ` · ${u.phone}` : ""}</span>}
        actions={<span className="flex flex-wrap gap-1.5">{u.is_platform_admin && <Badge tone="blue">platform admin</Badge>}{!u.is_active ? <Badge tone="red">deactivated</Badge> : <Badge tone="green">active</Badge>}{!u.email_verified && <Badge tone="amber">email not verified</Badge>}</span>} />

      <section className={clsx("mb-6 flex items-start gap-3 rounded-card p-5 sm:p-6", d.login.can_log_in ? "bg-pos-tint" : "bg-neg-tint")} role="status" aria-label="Login status">
        {d.login.can_log_in ? <CheckCircle2 className="h-6 w-6 shrink-0 text-pos" aria-hidden /> : <XCircle className="h-6 w-6 shrink-0 text-neg" aria-hidden />}
        <div className="min-w-0"><p className="text-lg font-semibold">{d.login.can_log_in ? "Can log in" : "Cannot log in"}</p>
          {d.login.reasons.map((x) => <p key={x} className="mt-1 text-sm font-medium text-neg">{x}</p>)}{d.login.notes.map((x) => <p key={x} className="mt-1 text-[13px] text-ink-700">{x}</p>)}</div>
      </section>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <div className="space-y-6">
          <Panel title="Account">
            <dl className="grid grid-cols-2 gap-x-6 gap-y-4 text-sm sm:grid-cols-3">
              {([["Sign-in", signIn(u)], ["Email verified", u.email_verified ? "Yes" : "No"], ["Live sessions", u.live_sessions], ["Last login", u.last_login_at ? timeAgo(u.last_login_at) : "Never"], ["Joined", fmtDate(u.created_at)], ["Businesses", u.businesses]] as const).map(([k, v]) => (
                <div key={k}><dt className="text-xs text-muted">{k}</dt><dd className="mt-0.5 font-semibold">{v}</dd></div>))}
            </dl>
          </Panel>
          <Panel title="Businesses" flush>
            {d.businesses.length === 0 ? <p className="p-4 text-sm text-muted">Not a member of any business.</p> : (
              <div className="overflow-x-auto"><table className="dt min-w-[480px]"><thead><tr><th>Business</th><th>Role</th><th>Plan</th></tr></thead>
                <tbody>{d.businesses.map((b) => (
                  <tr key={b.tenant_id}><td><Link href={`/admin/customers/${b.tenant_id}`} className="font-semibold text-accent-ink hover:underline">{b.name}</Link>{b.suspended && <Badge tone="red">suspended</Badge>}</td><td className="capitalize">{b.role}</td>
                    <td>{b.plan ?? "–"} {b.subscription_status && <Badge tone={SUB_TONE[b.subscription_status] ?? "gray"}>{b.subscription_status}</Badge>}</td></tr>))}</tbody></table></div>)}
          </Panel>
          <Panel title="Recent activity" meta="logins and password changes">
            {d.recent_activity.length === 0 ? <p className="text-sm text-muted">Nothing recorded yet.</p> : (
              <ul className="divide-y divide-line">{d.recent_activity.map((a, i) => <li key={i} className="flex flex-wrap justify-between gap-2 py-2.5 text-sm first:pt-0"><span className="font-medium">{ACTION[a.action] ?? a.action}</span><span className="text-muted">{timeAgo(a.at)}{a.ip ? ` · ${a.ip}` : ""}</span></li>)}</ul>)}
          </Panel>
        </div>

        <div className="space-y-6">
          <Panel title="Help this person">
            <div className="space-y-2.5">
              <Button className="w-full" variant="secondary" icon={<Send className="h-4 w-4" />} disabled={!u.is_active} onClick={() => setConfirm("reset")}>Send password reset email</Button>
              {!u.email_verified && <Button className="w-full" variant="secondary" icon={<MailCheck className="h-4 w-4" />} loading={busy === "verify"} onClick={() => void run("verify", () => api(`/admin/users/${id}/verify-email`, { method: "POST" }), "Email marked as verified.")}>Mark email as verified</Button>}
              <Button className="w-full" variant="secondary" icon={<LogOut className="h-4 w-4" />} disabled={u.live_sessions === 0} loading={busy === "revoke"}
                onClick={() => void run("revoke", () => api(`/admin/users/${id}/revoke-sessions`, { method: "POST" }), "Signed out everywhere.")}>Sign out everywhere ({u.live_sessions})</Button>
              <Button className="w-full" variant={u.is_active ? "danger" : "primary"} disabled={self} onClick={() => (u.is_active ? setConfirm("deactivate") : void run("active", () => api(`/admin/users/${id}`, { method: "PATCH", body: { is_active: true } }), "Account reactivated."))}>
                {u.is_active ? "Deactivate account" : "Reactivate account"}</Button>
              {self && <p className="text-xs text-muted">You can&rsquo;t deactivate your own account.</p>}
            </div>
            <p className="mt-4 text-xs text-muted">Passwords are never shown or set by staff: a reset email lets the person choose their own. Every action here is logged.</p>
          </Panel>
          <Panel title="Live sessions" meta="where they are logged in">
            {d.sessions.length === 0 ? <p className="text-sm text-muted">Not logged in anywhere.</p> : (
              <ul className="divide-y divide-line">{d.sessions.map((s, i) => <li key={i} className="py-2.5 text-sm first:pt-0"><p className="truncate font-medium" title={s.device}>{s.device || "Unknown device"}</p><p className="text-xs text-muted">Since {timeAgo(s.started)}{s.ip ? ` · ${s.ip}` : ""}</p></li>)}</ul>)}
          </Panel>
        </div>
      </div>

      <Modal open={confirm === "reset"} onClose={() => setConfirm(null)} title="Send a password reset email?"
        footer={<><Button variant="secondary" onClick={() => setConfirm(null)}>Cancel</Button><Button loading={busy === "reset"} onClick={() => void run("reset", () => api(`/admin/users/${id}/send-reset`, { method: "POST" }), "Reset email sent.")}>Send email</Button></>}>
        <p className="text-sm">We&rsquo;ll email <b className="break-all">{u.email}</b> a link to choose a new password. It expires soon, and nothing changes until they use it.</p>
      </Modal>
      <Modal open={confirm === "deactivate"} onClose={() => setConfirm(null)} title="Deactivate this account?"
        footer={<><Button variant="secondary" onClick={() => setConfirm(null)}>Cancel</Button><Button variant="danger" loading={busy === "active"} onClick={() => void run("active", () => api(`/admin/users/${id}`, { method: "PATCH", body: { is_active: false } }), "Account deactivated.")}>Deactivate</Button></>}>
        <p className="text-sm">{u.full_name || u.email} will be signed out everywhere and won&rsquo;t be able to log in until you reactivate the account. Their businesses and data are not touched.</p>
      </Modal>
    </>
  );
}
