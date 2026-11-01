"use client";
import { MailPlus, Trash2, UserX } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, CardHeader, PageHeader, Skeleton } from "@/components/ui/Card";
import { ErrorSummary, Input, Select } from "@/components/ui/Form";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate } from "@/lib/format";
import { emailRule, useForm } from "@/lib/form";
import type { Role } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

interface Staff { members: { user_id: string; email: string; full_name: string; role: Role }[]; invitations: { id: string; email: string; role: Role; expires_at: string }[] }
const ROLE_HELP: Record<Role, string> = { owner: "Full control incl. billing & roles", admin: "Manage locations, cards, approve & publish replies", staff: "View reviews, draft replies" };

export default function StaffPage() {
  const { me, role, isAdmin } = useAuth();
  const toast = useToast();
  const { data, error, loading, reload } = useFetch<Staff>("/staff");
  const [busy, setBusy] = useState(false);
  const f = useForm({ email: "", role: "staff" }, { email: emailRule });

  async function invite(e: React.FormEvent) {
    e.preventDefault(); f.setServerError(null);
    if (!f.validateAll()) return;
    setBusy(true);
    try { await api("/staff/invitations", { method: "POST", body: { email: f.values.email.trim(), role: f.values.role } }); f.setValues({ email: "", role: "staff" }); toast("Invitation sent."); void reload(); }
    catch (err) { f.fail(errorMessage(err)); } finally { setBusy(false); }
  }
  const run = async (fn: () => Promise<unknown>, msg: string) => { try { await fn(); toast(msg); void reload(); } catch (e) { toast(errorMessage(e), "error"); } };

  return (
    <>
      <PageHeader title="Staff" subtitle="Invite teammates and control what they can do." />
      {error && <Alert tone="error">{error}</Alert>}
      {isAdmin && (
        <Card className="mb-5"><CardHeader title="Invite a teammate" subtitle="They'll get an email link valid for 72 hours." />
          <form onSubmit={invite} noValidate className="space-y-4">
            <ErrorSummary errors={f.errors} serverError={f.serverError} summaryRef={f.summaryRef} />
            <div className="grid gap-4 sm:grid-cols-[1fr_220px_auto] sm:items-end">
              <Input label="Email" type="email" inputMode="email" {...f.bind("email")} />
              <Select label="Role" {...f.bind("role")}><option value="staff">Staff</option>{role === "owner" && <option value="admin">Admin</option>}</Select>
              <Button type="submit" loading={busy} icon={<MailPlus className="h-4 w-4" />}>Send invite</Button>
            </div>
            <p className="text-sm text-ink-500">{ROLE_HELP[f.values.role as Role]}</p>
          </form>
        </Card>
      )}
      <Card pad={false}>
        <div className="p-5 sm:p-6"><CardHeader title="Team" /></div>
        {loading && !data ? <Skeleton className="m-5 h-24" /> : (
          <ul className="divide-y divide-ink-100 border-t border-ink-100">
            {data?.members.map((m) => (
              <li key={m.user_id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3.5 sm:px-6">
                <div className="min-w-0"><p className="truncate font-semibold">{m.full_name}{m.user_id === me?.user.id && <span className="ml-2 text-xs font-normal text-ink-500">(you)</span>}</p><p className="truncate text-sm text-ink-500">{m.email}</p></div>
                <div className="flex items-center gap-2">
                  {role === "owner" && m.user_id !== me?.user.id ? (
                    <select aria-label={`Role for ${m.full_name}`} value={m.role} onChange={(e) => void run(() => api(`/staff/${m.user_id}`, { method: "PATCH", body: { role: e.target.value } }), "Role updated.")} className="min-h-11 rounded-xl border border-ink-200 bg-white px-3 text-sm sm:min-h-9">
                      <option value="owner">Owner</option><option value="admin">Admin</option><option value="staff">Staff</option>
                    </select>
                  ) : <Badge tone={m.role === "owner" ? "orange" : m.role === "admin" ? "blue" : "gray"}>{m.role}</Badge>}
                  {isAdmin && m.user_id !== me?.user.id && m.role !== "owner" && (
                    <Button variant="ghost" size="sm" aria-label={`Remove ${m.full_name}`} icon={<UserX className="h-4 w-4 text-red-600" />} onClick={() => { if (confirm(`Remove ${m.full_name} from this business?`)) void run(() => api(`/staff/${m.user_id}`, { method: "DELETE" }), "Member removed."); }} />
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
      {data && data.invitations.length > 0 && (
        <Card className="mt-5" pad={false}><div className="p-5 sm:p-6"><CardHeader title="Pending invitations" /></div>
          <ul className="divide-y divide-ink-100 border-t border-ink-100">{data.invitations.map((i) => (
            <li key={i.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3.5 sm:px-6"><div><p className="font-semibold">{i.email}</p><p className="text-sm text-ink-500">{i.role} · expires {fmtDate(i.expires_at)}</p></div>
              {isAdmin && <Button variant="ghost" size="sm" icon={<Trash2 className="h-4 w-4" />} onClick={() => void run(() => api(`/staff/invitations/${i.id}`, { method: "DELETE" }), "Invitation revoked.")}>Revoke</Button>}</li>))}</ul></Card>
      )}
    </>
  );
}
