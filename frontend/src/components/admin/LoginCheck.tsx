"use client";
import clsx from "clsx";
import { CheckCircle2, Search, UserX, XCircle } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Card";
import { api, errorMessage } from "@/lib/api";
import { fmtDate, timeAgo } from "@/lib/format";

export interface Verdict { can_log_in: boolean; reasons: string[]; notes: string[] }
export interface UserRow {
  id: string; email: string; full_name: string; phone: string | null; is_active: boolean; is_platform_admin: boolean; email_verified: boolean; has_password: boolean;
  google_linked: boolean; last_login_at: string | null; created_at: string; businesses: number; live_sessions: number; business_names?: string[];
}
export interface UserDetail {
  user: UserRow; login: Verdict;
  businesses: { tenant_id: string; name: string; role: string; suspended: boolean; plan: string | null; subscription_status: string | null }[];
  sessions: { started: string; expires: string; ip: string | null; device: string }[];
  recent_activity: { action: string; at: string; ip: string | null }[];
}
interface Result extends Partial<UserDetail> { exists: boolean; email: string; login: Verdict; pending_invitations?: { business: string; role: string; expires_at: string }[] }

export const signIn = (u: Pick<UserRow, "has_password" | "google_linked">) => [u.has_password && "Email + password", u.google_linked && "Google"].filter(Boolean).join(" · ") || "None";

/** The login check: type an email, get a plain answer to "does this person exist, and can they log in?" with the exact reasons. */
export function LoginCheck() {
  const [email, setEmail] = useState("");
  const [r, setR] = useState<Result | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function check(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    setBusy(true); setErr(null);
    try { setR(await api<Result>("/admin/users/lookup", { method: "POST", body: { email } })); } catch (x) { setR(null); setErr(errorMessage(x)); } finally { setBusy(false); }
  }
  const ok = r?.exists && r.login.can_log_in;
  return (
    <section className="panel mb-6 p-5 sm:p-6" aria-labelledby="lc-h">
      <h2 id="lc-h" className="text-lg font-semibold">Login check</h2>
      <p className="mt-0.5 text-sm text-muted">Type an email to see whether an account exists and whether that person can log in. Each check is logged.</p>
      <form onSubmit={check} className="mt-4 flex flex-wrap gap-2" role="search">
        <label className="flex h-12 min-w-[240px] flex-1 items-center gap-2 rounded-full bg-surface-2 px-4 text-muted focus-within:ring-2 focus-within:ring-accent">
          <Search className="h-4 w-4 shrink-0" aria-hidden /><span className="sr-only">Email to check</span>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@example.com" autoComplete="off" className="focus-inner w-full bg-transparent text-sm text-ink outline-none placeholder:text-muted" />
        </label>
        <Button type="submit" loading={busy} disabled={!email.trim()}>Check</Button>
      </form>
      {err && <div className="mt-4"><Alert tone="error">{err}</Alert></div>}
      {r && (
        <div className={clsx("mt-5 rounded-tile p-4 sm:p-5", ok ? "bg-pos-tint" : "bg-neg-tint")} role="status">
          <div className="flex items-start gap-3">
            {ok ? <CheckCircle2 className="mt-0.5 h-6 w-6 shrink-0 text-pos" aria-hidden /> : r.exists ? <XCircle className="mt-0.5 h-6 w-6 shrink-0 text-neg" aria-hidden /> : <UserX className="mt-0.5 h-6 w-6 shrink-0 text-neg" aria-hidden />}
            <div className="min-w-0 flex-1">
              <p className="text-lg font-semibold">{!r.exists ? "No account with this email" : ok ? "Account exists and can log in" : "Account exists but cannot log in"}</p>
              <p className="break-all text-sm text-ink-700">{r.email}{r.user ? ` · ${r.user.full_name}` : ""}</p>
              {r.login.reasons.map((x) => <p key={x} className="mt-2 text-sm font-medium text-neg">{x}</p>)}
              {r.login.notes.map((x) => <p key={x} className="mt-1.5 text-[13px] text-ink-700">{x}</p>)}
              {!r.exists && r.pending_invitations && r.pending_invitations.length > 0 && (
                <p className="mt-2 rounded-inner bg-surface px-3 py-2 text-sm">Has a pending invitation to {r.pending_invitations.map((i) => `${i.business} (${i.role})`).join(", ")}. They need to open the invite link and set a password.</p>
              )}
              {r.user && (
                <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1.5 text-sm sm:grid-cols-4">
                  <div><dt className="text-xs text-muted">Sign-in</dt><dd className="font-medium">{signIn(r.user)}</dd></div>
                  <div><dt className="text-xs text-muted">Email verified</dt><dd className="font-medium">{r.user.email_verified ? "Yes" : "No"}</dd></div>
                  <div><dt className="text-xs text-muted">Last login</dt><dd className="font-medium">{r.user.last_login_at ? timeAgo(r.user.last_login_at) : "Never"}</dd></div>
                  <div><dt className="text-xs text-muted">Joined</dt><dd className="font-medium">{fmtDate(r.user.created_at)}</dd></div>
                </dl>
              )}
              {r.user && <Link href={`/admin/users/${r.user.id}`} className="mt-3 inline-flex min-h-11 items-center rounded-full bg-surface px-4 text-sm font-semibold hover:bg-surface-2">Open account</Link>}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
