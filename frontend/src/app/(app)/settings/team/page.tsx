"use client";
import { MailPlus, MapPin, Trash2, UserX } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, PageHeader, Skeleton } from "@/components/ui/Card";
import { ErrorSummary, Input, Select } from "@/components/ui/Form";
import { Panel } from "@/components/ui/kit";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api, ApiError, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate } from "@/lib/format";
import { emailRule, useForm } from "@/lib/form";
import type { Location, Role, StaffInvitation, StaffMember } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

interface Staff { members: StaffMember[]; invitations: StaffInvitation[] }
const ROLES: [Role, string, string][] = [["owner", "Owner", "Full control, including billing and roles. Sees every location."], ["admin", "Admin", "Manage locations and cards; approve and publish replies. Sees every location."], ["staff", "Staff", "View reviews and draft replies. Can be limited to specific locations."]];

/** What a failed access change means, in plain terms. */
function accessError(e: unknown): string {
  if (!(e instanceof ApiError)) return "Something went wrong. Please try again.";
  if (e.status === 404) return "One of those locations, or this team member, no longer exists. Refresh the page and try again.";
  if (e.status === 400) return "Owners and admins always have every location. Change their role to Staff first.";
  if (e.status === 403) return "Only owners and admins can change location access.";
  return e.message;
}

function LocationPicker({ locations, all, picked, onAll, onToggle, idPrefix }: { locations: Location[]; all: boolean; picked: Set<string>; onAll: (v: boolean) => void; onToggle: (id: string) => void; idPrefix: string }) {
  return (
    <fieldset className="space-y-2">
      <legend className="mb-1 text-[13px] font-medium text-ink-700">Location access</legend>
      <label className="flex min-h-11 items-center gap-2 text-sm sm:min-h-0"><input type="radio" name={`${idPrefix}-scope`} className="h-[18px] w-[18px]" checked={all} onChange={() => onAll(true)} />Every location, including ones added later</label>
      <label className="flex min-h-11 items-center gap-2 text-sm sm:min-h-0"><input type="radio" name={`${idPrefix}-scope`} className="h-[18px] w-[18px]" checked={!all} onChange={() => onAll(false)} />Only the locations ticked below</label>
      {!all && (
        <ul className="max-h-56 divide-y divide-ink-100 overflow-y-auto rounded-lg border border-ink-100">
          {locations.length === 0 && <li className="p-3 text-sm text-ink-500">No locations yet.</li>}
          {locations.map((l) => (
            <li key={l.id}><label className="flex min-h-11 cursor-pointer items-center gap-3 px-3 py-1.5 hover:bg-ink-50">
              <input type="checkbox" className="h-[18px] w-[18px] shrink-0" checked={picked.has(l.id)} onChange={() => onToggle(l.id)} />
              <span className="min-w-0 flex-1 truncate text-sm">{l.name}{!l.is_active && <span className="ml-2 text-xs text-ink-500">deactivated</span>}</span>
            </label></li>))}
        </ul>)}
      {!all && picked.size === 0 && <p className="text-xs text-amber-800">With nothing ticked, this person will see no reviews, cards, campaigns or analytics at all.</p>}
    </fieldset>
  );
}

export default function StaffPage() {
  const { me, role, isAdmin } = useAuth();
  const toast = useToast();
  const { data, error, loading, reload } = useFetch<Staff>("/staff");
  const locs = useFetch<Location[]>(isAdmin ? "/locations" : null);
  const [busy, setBusy] = useState(false);
  const f = useForm({ email: "", role: "staff" }, { email: emailRule });
  const [inviteAll, setInviteAll] = useState(true);
  const [invitePicked, setInvitePicked] = useState<Set<string>>(new Set());
  const [edit, setEdit] = useState<StaffMember | null>(null);
  const [editAll, setEditAll] = useState(true);
  const [editPicked, setEditPicked] = useState<Set<string>>(new Set());
  const [editError, setEditError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const locations = locs.data ?? [];
  const nameOf = (id: string) => locations.find((l) => l.id === id)?.name ?? "a removed location";
  const flip = (set: Set<string>, apply: (s: Set<string>) => void, id: string) => { const n = new Set(set); if (n.has(id)) n.delete(id); else n.add(id); apply(n); };

  async function invite(e: React.FormEvent) {
    e.preventDefault(); f.setServerError(null);
    if (!f.validateAll()) return;
    const limited = f.values.role === "staff" && !inviteAll;
    setBusy(true);
    try {
      const inv = await api<{ email_sent: boolean | null }>("/staff/invitations", { method: "POST", body: { email: f.values.email.trim(), role: f.values.role, ...(limited ? { location_ids: [...invitePicked] } : {}) } });
      f.setValues({ email: "", role: "staff" }); setInviteAll(true); setInvitePicked(new Set());
      if (inv.email_sent === false) toast("Invitation created, but the email could not be delivered. Check the email settings or ask your FlowQR admin.", "error"); else toast("Invitation sent.");
      void reload();
    } catch (err) {
      f.fail(err instanceof ApiError && err.status === 404 ? "One of the selected locations no longer exists. Refresh the page and choose again." : err instanceof ApiError && err.code === "plan_limit" ? err.message : errorMessage(err));
    } finally { setBusy(false); }
  }
  const run = async (fn: () => Promise<unknown>, msg: string) => { try { await fn(); toast(msg); void reload(); } catch (e) { toast(errorMessage(e), "error"); } };

  function openAccess(m: StaffMember) { setEdit(m); setEditAll(m.all_locations); setEditPicked(new Set(m.location_ids)); setEditError(null); }
  async function saveAccess() {
    if (!edit) return;
    setSaving(true); setEditError(null);
    try {
      await api(`/staff/${edit.user_id}/locations`, { method: "PUT", body: { all_locations: editAll, location_ids: editAll ? [] : [...editPicked] } });
      toast(editAll ? `${edit.full_name} can now see every location.` : `${edit.full_name} is now limited to ${editPicked.size} location${editPicked.size === 1 ? "" : "s"}.`);
      setEdit(null); void reload();
    } catch (e) { setEditError(accessError(e)); } finally { setSaving(false); }
  }

  const access = (m: StaffMember) => m.role !== "staff" ? "Every location" : m.all_locations ? "Every location" : m.location_ids.length === 0 ? "No locations" : m.location_ids.length <= 2 ? m.location_ids.map(nameOf).join(", ") : `${m.location_ids.length} locations`;

  return (
    <>
      <PageHeader eyebrow="Business" title="Staff" subtitle={data ? `${data.members.length} ${data.members.length === 1 ? "person" : "people"}${data.invitations.length ? ` · ${data.invitations.length} invited` : ""}` : "Invite teammates and control what they can do."} />
      {error && <Alert tone="error">{error}</Alert>}
      {locs.error && <div className="mb-3"><Alert tone="error" title="Couldn't load locations">{locs.error} Location access can&rsquo;t be edited until this loads.</Alert></div>}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <div className="min-w-0 space-y-4">
          <Panel title="Team" flush>
            {loading && !data ? <Skeleton className="m-4 h-24" /> : (
              <div className="overflow-x-auto"><table className="dt min-w-[620px]">
                <thead><tr><th>Member</th><th>Role</th><th>Location access</th><th className="w-12" /></tr></thead>
                <tbody>{data?.members.map((m) => (
                  <tr key={m.user_id}>
                    <td><p className="font-medium">{m.full_name}{m.user_id === me?.user.id && <span className="ml-2 text-xs font-normal text-ink-500">you</span>}</p><p className="text-[13px] text-ink-500">{m.email}</p></td>
                    <td>{role === "owner" && m.user_id !== me?.user.id ? (
                      <select aria-label={`Role for ${m.full_name}`} value={m.role} onChange={(e) => { const next = e.target.value; if (m.role === "staff" && !m.all_locations && next !== "staff" && !confirm(`${m.full_name} is limited to specific locations. As ${next === "owner" ? "an owner" : "an admin"} they will see every location, and the limit is removed. Continue?`)) return; void run(() => api(`/staff/${m.user_id}`, { method: "PATCH", body: { role: next } }), "Role updated."); }} className="min-h-9 rounded-lg border border-ink-300 bg-white px-2 text-sm">
                        <option value="owner">Owner</option><option value="admin">Admin</option><option value="staff">Staff</option></select>
                    ) : <Badge tone={m.role === "owner" ? "blue" : "gray"}>{m.role}</Badge>}</td>
                    <td>
                      <span className={m.role === "staff" && !m.all_locations && m.location_ids.length === 0 ? "text-amber-800" : ""}>{access(m)}</span>
                      {isAdmin && m.role === "staff" && m.user_id !== me?.user.id && <Button variant="ghost" size="sm" className="ml-1" icon={<MapPin className="h-3.5 w-3.5" />} aria-label={`Change location access for ${m.full_name}`} disabled={!locs.data} onClick={() => openAccess(m)}>Change</Button>}
                    </td>
                    <td className="text-right">{isAdmin && m.user_id !== me?.user.id && m.role !== "owner" && (
                      <Button variant="ghost" size="sm" aria-label={`Remove ${m.full_name}`} icon={<UserX className="h-4 w-4 text-red-600" />} onClick={() => { if (confirm(`Remove ${m.full_name} from this business?`)) void run(() => api(`/staff/${m.user_id}`, { method: "DELETE" }), "Member removed."); }} />)}</td>
                  </tr>))}</tbody>
              </table></div>
            )}
          </Panel>
          {data && data.invitations.length > 0 && (
            <Panel title="Pending invitations" flush>
              <div className="overflow-x-auto"><table className="dt min-w-[520px]"><thead><tr><th>Email</th><th>Role</th><th>Location access</th><th>Expires</th><th className="w-12" /></tr></thead>
                <tbody>{data.invitations.map((i) => (
                  <tr key={i.id}><td className="font-medium">{i.email}</td><td><Badge>{i.role}</Badge></td>
                    <td className="text-ink-500">{i.location_ids == null ? "Every location" : i.location_ids.length === 0 ? "No locations" : `${i.location_ids.length} location${i.location_ids.length === 1 ? "" : "s"}`}</td>
                    <td className="whitespace-nowrap text-ink-500">{fmtDate(i.expires_at)}</td>
                    <td className="text-right">{isAdmin && <Button variant="ghost" size="sm" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => void run(() => api(`/staff/invitations/${i.id}`, { method: "DELETE" }), "Invitation revoked.")}>Revoke</Button>}</td></tr>))}</tbody></table></div>
            </Panel>
          )}
        </div>

        <div className="min-w-0 space-y-4">
          {isAdmin && (
            <Panel title="Invite a teammate" meta="link valid 72 hours">
              <form onSubmit={invite} noValidate className="space-y-3">
                <ErrorSummary errors={f.errors} serverError={f.serverError} summaryRef={f.summaryRef} />
                <Input label="Email" type="email" inputMode="email" {...f.bind("email")} />
                <Select label="Role" {...f.bind("role")}><option value="staff">Staff</option>{role === "owner" && <option value="admin">Admin</option>}</Select>
                {f.values.role === "staff" && locations.length > 0 && <LocationPicker idPrefix="invite" locations={locations.filter((l) => l.is_active)} all={inviteAll} picked={invitePicked} onAll={setInviteAll} onToggle={(id) => flip(invitePicked, setInvitePicked, id)} />}
                <Button type="submit" loading={busy} icon={<MailPlus className="h-4 w-4" />}>Send invite</Button>
              </form>
            </Panel>
          )}
          <Panel title="What each role can do" flush>
            <dl className="divide-y divide-ink-100 text-sm">{ROLES.map(([k, l, d]) => <div key={k} className="px-4 py-2.5"><dt className="font-semibold">{l}</dt><dd className="mt-0.5 text-[13px] text-ink-500">{d}</dd></div>)}</dl>
          </Panel>
        </div>
      </div>

      <Modal open={edit !== null} onClose={() => setEdit(null)} title={edit ? `Location access for ${edit.full_name}` : "Location access"}
        footer={<><Button variant="secondary" onClick={() => setEdit(null)}>Cancel</Button><Button loading={saving} onClick={() => void saveAccess()}>Save access</Button></>}>
        <div className="space-y-3">
          {editError && <Alert tone="error" title="Access not changed">{editError}</Alert>}
          <LocationPicker idPrefix="edit" locations={locations} all={editAll} picked={editPicked} onAll={setEditAll} onToggle={(id) => flip(editPicked, setEditPicked, id)} />
          <p className="text-xs text-ink-500">A limited staff member sees only the reviews, cards, QR campaigns, Google profile tools and analytics of their locations. The change applies immediately.</p>
        </div>
      </Modal>
    </>
  );
}
