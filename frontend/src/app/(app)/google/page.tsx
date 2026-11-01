"use client";
import { CheckCircle2, Link2, PlugZap, RefreshCw, Unplug } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, CardHeader, PageHeader, Skeleton } from "@/components/ui/Card";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api, ApiError, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { timeAgo } from "@/lib/format";
import type { GoogleConnection, GoogleLocation, Location } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

interface Status { configured: boolean; configuration_note: string | null; connections: GoogleConnection[] }
const ERRORS: Record<string, string> = {
  access_denied: "You declined access, so nothing was connected.", invalid_state: "That sign-in link expired or didn't match your browser. Please try again.",
  session_mismatch: "Please log in as the same user who started the connection.", forbidden: "Only owners and admins can connect Google.",
  exchange_failed: "Google didn't accept the sign-in. Please try again.", no_refresh_token: "Google didn't grant offline access. Remove FlowQR from your Google account's connected apps, then try again.",
  not_configured: "Google sign-in isn't configured on this server yet.",
};

export default function GooglePage() { return <Suspense><Inner /></Suspense>; }

function Inner() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const sp = useSearchParams();
  const { data, loading, reload } = useFetch<Status>("/google/status");
  const [connecting, setConnecting] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [disconnectId, setDisconnectId] = useState<string | null>(null);
  const err = sp.get("error");

  useEffect(() => { if (sp.get("connected")) toast("Google account connected. Choose which locations to sync."); }, [sp, toast]);

  async function connect() {
    setConnecting(true); setPending(null);
    try { const { auth_url } = await api<{ auth_url: string }>("/google/connect", { method: "POST" }); window.location.href = auth_url; }
    catch (e) { if (e instanceof ApiError && e.code === "google_config_pending") setPending(e.message); else toast(errorMessage(e), "error"); setConnecting(false); }
  }
  async function disconnect() {
    if (!disconnectId) return;
    try { await api(`/google/connections/${disconnectId}`, { method: "DELETE" }); toast("Google disconnected. Synced reviews are kept."); setDisconnectId(null); void reload(); }
    catch (e) { toast(errorMessage(e), "error"); }
  }

  const active = data?.connections ?? [];
  return (
    <>
      <PageHeader title="Google connection" subtitle="Connect your own Google Business Profile to sync reviews and publish approved replies."
        actions={isAdmin && data?.configured !== false ? <Button icon={<Link2 className="h-4 w-4" />} loading={connecting} onClick={() => void connect()}>{active.length ? "Connect another account" : "Connect Google"}</Button> : undefined} />
      {err && <div className="mb-4"><Alert tone="error" title="Couldn't connect Google">{ERRORS[err] ?? "Something went wrong."}</Alert></div>}

      {data && !data.configured && (
        <div className="mb-5"><Alert tone="warning" title="Configuration pending">{data.configuration_note} Your QR/NFC cards, review links and AI writing assistant work without it.</Alert></div>
      )}
      {pending && <div className="mb-5"><Alert tone="warning" title="Configuration pending">{pending}</Alert></div>}

      <Card className="mb-5"><CardHeader title="What FlowQR will access" />
        <ul className="space-y-1.5 text-sm text-ink-700">
          <li>• Your Business Profile locations and reviews (one permission: <code className="rounded bg-ink-50 px-1">business.manage</code>).</li>
          <li>• We reply only after <b>you</b> approve each reply, and only show &ldquo;published&rdquo; after Google confirms.</li>
          <li>• Tokens are encrypted and never sent to your browser. Disconnect any time.</li>
        </ul>
        <p className="mt-3 text-xs text-ink-500">Business Profile API access must be approved by Google for FlowQR&rsquo;s project. Until then, use manual review links.</p>
      </Card>

      {loading && !data ? <Skeleton className="h-40" /> : active.length === 0 ? (
        <Card><div className="flex items-center gap-3 text-ink-500"><PlugZap className="h-5 w-5" aria-hidden />No Google account connected yet.</div></Card>
      ) : active.map((c) => <ConnectionCard key={c.id} conn={c} canEdit={isAdmin} onChanged={reload} onDisconnect={() => setDisconnectId(c.id)} onReconnect={() => void connect()} />)}

      <Modal open={!!disconnectId} onClose={() => setDisconnectId(null)} title="Disconnect Google?" footer={<><Button variant="secondary" onClick={() => setDisconnectId(null)}>Cancel</Button><Button variant="danger" onClick={() => void disconnect()}>Disconnect</Button></>}>
        <p className="text-ink-700">We'll revoke FlowQR's access and delete the stored tokens. Reviews already synced stay in your inbox. Your cards keep working with the manual review link.</p>
      </Modal>
    </>
  );
}

const STATUS_TONE: Record<string, "green" | "amber" | "red" | "gray" | "blue"> = { active: "green", pending_selection: "blue", revoked: "red", error: "red", disconnected: "gray" };

function ConnectionCard({ conn, canEdit, onChanged, onDisconnect, onReconnect }: { conn: GoogleConnection; canEdit: boolean; onChanged: () => void; onDisconnect: () => void; onReconnect: () => void }) {
  const toast = useToast();
  const gl = useFetch<GoogleLocation[]>(`/google/connections/${conn.id}/locations`);
  const locs = useFetch<Location[]>("/locations");
  const [sel, setSel] = useState<Record<string, { on: boolean; map: string }>>({});
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (gl.data) setSel(Object.fromEntries(gl.data.map((g) => [g.id, { on: g.selected, map: g.location_id ?? "" }])));
  }, [gl.data]);

  async function save() {
    setSaving(true);
    try {
      const selections = (gl.data ?? []).map((g) => ({ google_location_id: g.id, selected: sel[g.id]?.on ?? false, location_id: sel[g.id]?.map && sel[g.id].map !== "__new" ? sel[g.id].map : null, create_location: sel[g.id]?.map === "__new" }));
      await api(`/google/connections/${conn.id}/selection`, { method: "PUT", body: { selections } });
      toast("Locations saved. Syncing reviews…"); void gl.reload(); onChanged();
    } catch (e) { toast(errorMessage(e), "error"); } finally { setSaving(false); }
  }
  const revoked = conn.status === "revoked" || conn.status === "error";
  return (
    <Card className="mb-5">
      <CardHeader title={conn.google_email ?? "Google account"} subtitle={conn.connected_at ? `Connected ${timeAgo(conn.connected_at)}` : undefined}
        action={<div className="flex items-center gap-2"><Badge tone={STATUS_TONE[conn.status] ?? "gray"}>{conn.status.replace("_", " ")}</Badge>{canEdit && <Button variant="danger" size="sm" icon={<Unplug className="h-4 w-4" />} onClick={onDisconnect}>Disconnect</Button>}</div>} />
      {conn.last_error && <div className="mb-4"><Alert tone="error" title="Needs attention" action={canEdit ? <Button size="sm" variant="secondary" onClick={onReconnect}>Reconnect</Button> : undefined}>{conn.last_error}</Alert></div>}
      {!revoked && (gl.loading && !gl.data ? <Skeleton className="h-24" /> : (gl.data?.length ?? 0) === 0 ? <p className="text-sm text-ink-500">No Business Profile locations were found on this account.</p> : (
        <>
          <p className="mb-3 text-sm text-ink-500">Pick the locations to sync and match each to a FlowQR location.</p>
          <ul className="divide-y divide-ink-100">
            {gl.data?.map((g) => (
              <li key={g.id} className="grid gap-3 py-3 sm:grid-cols-[auto_1fr_1fr] sm:items-center">
                <input type="checkbox" aria-label={`Sync ${g.title}`} disabled={!canEdit} checked={sel[g.id]?.on ?? false} onChange={(e) => setSel({ ...sel, [g.id]: { ...(sel[g.id] ?? { map: "" }), on: e.target.checked } })} className="h-5 w-5 accent-brand-600" />
                <div className="min-w-0"><p className="font-semibold">{g.title}</p><p className="truncate text-sm text-ink-500">{g.address}</p>
                  {g.selected && <p className="mt-1 flex items-center gap-1.5 text-xs text-ink-500">{g.last_sync_status === "ok" && <CheckCircle2 className="h-3.5 w-3.5 text-g-green" aria-hidden />}{g.last_sync_status ? `${g.last_sync_status} · ${timeAgo(g.last_synced_at)}` : "waiting for first sync"}{g.last_sync_error && <span className="text-red-700"> · {g.last_sync_error}</span>}</p>}</div>
                <select aria-label={`FlowQR location for ${g.title}`} disabled={!canEdit || !sel[g.id]?.on} value={sel[g.id]?.map ?? ""} onChange={(e) => setSel({ ...sel, [g.id]: { ...(sel[g.id] ?? { on: true }), map: e.target.value } })} className="min-h-11 rounded-xl border border-ink-200 bg-white px-3 text-sm disabled:bg-ink-50">
                  <option value="">Match to location…</option>{locs.data?.filter((l) => l.is_active).map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}<option value="__new">+ Create from Google details</option>
                </select>
              </li>
            ))}
          </ul>
          {canEdit && <div className="mt-4 flex flex-wrap gap-2"><Button loading={saving} onClick={() => void save()}>Save &amp; sync</Button>
            <Button variant="secondary" icon={<RefreshCw className="h-4 w-4" />} onClick={async () => { try { await api(`/google/connections/${conn.id}/refresh-locations`, { method: "POST" }); void gl.reload(); toast("Locations refreshed."); } catch (e) { toast(errorMessage(e), "error"); } }}>Refresh list</Button></div>}
        </>
      ))}
    </Card>
  );
}
