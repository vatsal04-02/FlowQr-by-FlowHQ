"use client";
import { Check, Link2, RefreshCw, Unplug, X } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Skeleton } from "@/components/ui/Card";
import { Panel, Status } from "@/components/ui/kit";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api, ApiError, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { timeAgo } from "@/lib/format";
import type { GoogleConnection, GoogleLocation, Location } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

interface GStatus { configured: boolean; configuration_note: string | null; connections: GoogleConnection[] }
const ERRORS: Record<string, string> = {
  access_denied: "You declined access, so nothing was connected.", invalid_state: "That sign-in link expired or didn't match your browser. Please try again.",
  session_mismatch: "Please log in as the same user who started the connection.", forbidden: "Only owners and admins can connect Google.",
  exchange_failed: "Google didn't accept the sign-in. Please try again.", no_refresh_token: "Google didn't grant offline access. Remove FlowQR from your Google account's connected apps, then try again.",
  not_configured: "Google sign-in isn't configured on this server yet.",
  scope_missing: "Google connected, but the Business Profile permission was not granted, so nothing was saved. Connect again and leave the box for managing your business listings ticked.",
};

// What works in each mode, stated plainly.
const MODES: [string, boolean, boolean][] = [
  ["QR/NFC cards and review links", true, true], ["AI writing assistant for customers", true, true], ["Scan, visit and click analytics", true, true],
  ["Automatic review sync", false, true], ["AI reply drafts you approve, then publish", false, true], ["Business profile tools (hours, posts, photos)", false, true],
];

/** The Google connection, as the top section of GBP Manager › Locations & Google (PRD §6.2). Reads ?connected / ?error from the OAuth return. */
export function GoogleConnectionSection() { return <Suspense><Inner /></Suspense>; }

function Inner() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const sp = useSearchParams();
  const { data, loading, reload } = useFetch<GStatus>("/google/status");
  const [connecting, setConnecting] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [connectError, setConnectError] = useState<string | null>(null); // persistent: a 6s toast made a blocked click look like a dead button
  const [disconnectId, setDisconnectId] = useState<string | null>(null);
  const err = sp.get("error");

  useEffect(() => { if (sp.get("connected")) toast("Google account connected. Choose which locations to sync."); }, [sp, toast]);

  async function connect() {
    setConnecting(true); setPending(null); setConnectError(null);
    try { const { auth_url } = await api<{ auth_url: string }>("/google/connect", { method: "POST" }); window.location.href = auth_url; }
    catch (e) { if (e instanceof ApiError && e.code === "google_config_pending") setPending(e.message); else setConnectError(errorMessage(e)); setConnecting(false); }
  }
  async function disconnect() {
    if (!disconnectId) return;
    try { await api(`/google/connections/${disconnectId}`, { method: "DELETE" }); toast("Google disconnected. Synced reviews are kept."); setDisconnectId(null); void reload(); }
    catch (e) { toast(errorMessage(e), "error"); }
  }

  const conns = data?.connections ?? [];
  const live = conns.find((c) => c.status === "active");
  const mode = live ? "connected" : "manual";
  const liveLocs = useFetch<GoogleLocation[]>(live ? `/google/connections/${live.id}/locations` : null);
  const syncing = liveLocs.data?.filter((g) => g.selected) ?? [];
  const lastSync = syncing.map((g) => g.last_synced_at).filter(Boolean).sort().pop();
  const failing = syncing.filter((g) => g.last_sync_status && g.last_sync_status !== "ok").length;
  return (
    <section aria-label="Google connection">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div><h2 className="text-lg font-semibold leading-6">Google connection</h2><p className="mt-0.5 text-sm text-muted">Connect your own Google Business Profile to sync reviews and publish approved replies.</p></div>
        {isAdmin && data?.configured !== false ? <Button size="sm" icon={<Link2 className="h-4 w-4" />} loading={connecting} onClick={() => void connect()}>{conns.length ? "Connect another account" : "Connect Google"}</Button> : null}
      </div>
      {err && <div className="mb-4"><Alert tone="error" title="Couldn't connect Google">{ERRORS[err] ?? "Something went wrong."}</Alert></div>}
      {data && !data.configured && <div className="mb-4"><Alert tone="warning" title="Configuration pending">{data.configuration_note} Your QR/NFC cards, review links and AI writing assistant work without it.</Alert></div>}
      {pending && <div className="mb-4"><Alert tone="warning" title="Configuration pending">{pending}</Alert></div>}
      {connectError && <div className="mb-4"><Alert tone="error" title="Couldn't start the Google connection">{connectError}</Alert></div>}

      <div className="grid gap-4 lg:grid-cols-[1fr_1.15fr]">
        <Panel title="Current mode">
          {loading && !data ? <Skeleton className="h-20" /> : (
            <>
              <p className="flex items-center gap-2 text-[17px] font-semibold"><span aria-hidden className={`h-2.5 w-2.5 rounded-full ${live ? "bg-ok" : "bg-ink-300"}`} />{live ? "Connected to Google" : "Manual review-link mode"}</p>
              <p className="mt-1.5 text-sm text-ink-500">{live ? `${live.google_email ?? "Google account"} · connected ${timeAgo(live.connected_at)}.` : "Customers go to your Google review link from the card. Reviews are not synced, and replies are written on Google."}</p>
              {!live && <p className="mt-3 text-[13px] text-ink-500">Automatic sync needs Google to approve Business Profile API access for FlowQR&rsquo;s project. Until then, manual mode is fully supported.</p>}
              {live && liveLocs.data && (
                <dl className="mt-4 divide-y divide-ink-100 border-t border-ink-100 text-sm">
                  {[["Locations syncing", `${syncing.length} of ${liveLocs.data.length}`], ["Last successful sync", lastSync ? timeAgo(lastSync) : "Waiting for first sync"], ["Sync problems", failing ? <Status key="p" tone="bad">{failing} {failing === 1 ? "location" : "locations"}</Status> : <Status key="p" tone="ok">None</Status>]].map(([k, v]) => (
                    <div key={k as string} className="flex items-baseline justify-between gap-4 py-2"><dt className="text-ink-500">{k}</dt><dd className="font-medium">{v}</dd></div>))}
                </dl>
              )}
            </>
          )}
        </Panel>
        <Panel title="What works in each mode" flush>
          <table className="dt" aria-label="Feature availability by mode">
            <thead><tr><th>Feature</th><th className={`!text-center ${mode === "manual" ? "!text-ink" : ""}`}>Manual link</th><th className={`!text-center ${mode === "connected" ? "!text-ink" : ""}`}>Connected</th></tr></thead>
            <tbody>{MODES.map(([f, a, b]) => (
              <tr key={f}><td>{f}</td>
                <td className="text-center">{a ? <Check className="mx-auto h-4 w-4 text-ok" aria-label="Included" /> : <X className="mx-auto h-4 w-4 text-ink-300" aria-label="Not included" />}</td>
                <td className="text-center">{b ? <Check className="mx-auto h-4 w-4 text-ok" aria-label="Included" /> : <X className="mx-auto h-4 w-4 text-ink-300" aria-label="Not included" />}</td></tr>))}</tbody>
          </table>
        </Panel>
      </div>

      <div className="mt-4 space-y-4">
        {conns.map((c) => <ConnectionPanel key={c.id} conn={c} canEdit={isAdmin} onChanged={reload} onDisconnect={() => setDisconnectId(c.id)} onReconnect={() => void connect()} />)}
      </div>

      <details className="panel mt-4 p-4 text-sm">
        <summary className="cursor-pointer text-[13px] font-semibold">What FlowQR accesses</summary>
        <ul className="mt-3 space-y-1.5 text-[13px] text-ink-700">
          <li>Your Business Profile locations and reviews (one permission: <code className="rounded bg-ink-50 px-1 font-mono text-xs">business.manage</code>).</li>
          <li>We reply only after <b>you</b> approve each reply, and show &ldquo;published&rdquo; only after Google confirms.</li>
          <li>Tokens are encrypted and never sent to your browser. You can disconnect at any time.</li>
        </ul>
      </details>

      <Modal open={!!disconnectId} onClose={() => setDisconnectId(null)} title="Disconnect Google?" footer={<><Button variant="secondary" onClick={() => setDisconnectId(null)}>Cancel</Button><Button variant="danger" onClick={() => void disconnect()}>Disconnect</Button></>}>
        <p className="text-ink-700">We&rsquo;ll revoke FlowQR&rsquo;s access and delete the stored tokens. Reviews already synced stay in your inbox. Your cards keep working with the manual review link.</p>
      </Modal>
    </section>
  );
}

const CONN_TONE: Record<string, "ok" | "info" | "bad" | "idle"> = { active: "ok", pending_selection: "info", revoked: "bad", error: "bad", disconnected: "idle" };

function ConnectionPanel({ conn, canEdit, onChanged, onDisconnect, onReconnect }: { conn: GoogleConnection; canEdit: boolean; onChanged: () => void; onDisconnect: () => void; onReconnect: () => void }) {
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
  // Lost authorization outranks everything else: until the owner reconnects, nothing about the project's API access can be checked.
  const lost = conn.status === "revoked";
  return (
    <Panel title={conn.google_email ?? "Google account"} meta={conn.connected_at ? `connected ${timeAgo(conn.connected_at)}` : undefined} flush
      action={<div className="flex items-center gap-2"><Status tone={CONN_TONE[conn.status] ?? "idle"}>{conn.status.replace("_", " ")}</Status>{canEdit && <Button variant="danger" size="sm" icon={<Unplug className="h-3.5 w-3.5" />} onClick={onDisconnect}>Disconnect</Button>}</div>}>
      {!lost && conn.no_locations && <div className="p-4 pb-0"><Alert tone="warning" title="This Google account manages no locations" action={canEdit ? <Button size="sm" onClick={onReconnect}>Connect another account</Button> : undefined}>Signing in worked and Google answered, but it lists no Business Profile location on <b>{conn.google_email ?? "this account"}</b>, so there is nothing to sync or manage. This is not a working business connection. Connect the Google account that owns or manages your listing, or refresh the list if you were just added as a manager.</Alert></div>}
      {!lost && conn.api_access === "awaiting_approval" && <div className="p-4 pb-0"><Alert tone="warning" title="Awaiting Google approval"
        action={canEdit ? <Button size="sm" variant="secondary" icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={async () => { try { await api(`/google/connections/${conn.id}/refresh-locations`, { method: "POST" }); toast("Google access confirmed."); onChanged(); void gl.reload(); } catch (e) { toast(errorMessage(e), "error"); } }}>Re-check</Button> : undefined}>
        {conn.last_error ? `${conn.last_error} ` : "Your Google sign-in worked, but Google hasn\u2019t approved FlowQR for Business Profile API access yet (quota 0). "} Reviews, replies, posts and insights stay unavailable &mdash; nothing is simulated &mdash; until approval. We re-check automatically.</Alert></div>}
      {!lost && conn.api_access === "api_disabled" && <div className="p-4 pb-0"><Alert tone="warning" title="A Google API is switched off for FlowQR"
        action={canEdit ? <Button size="sm" variant="secondary" icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={async () => { try { await api(`/google/connections/${conn.id}/refresh-locations`, { method: "POST" }); toast("Google access confirmed."); onChanged(); void gl.reload(); } catch (e) { toast(errorMessage(e), "error"); } }}>Re-check</Button> : undefined}>
        {conn.last_error ?? "A required Google Business Profile API is not enabled on FlowQR's Google project."} This is fixed on FlowQR&rsquo;s side, not yours; contact FlowQR support. Nothing is simulated in the meantime.</Alert></div>}
      {conn.last_error && (lost || (conn.api_access !== "awaiting_approval" && conn.api_access !== "api_disabled")) && <div className="p-4 pb-0"><Alert tone="error" title="Needs attention" action={canEdit ? <Button size="sm" variant="secondary" onClick={onReconnect}>Reconnect</Button> : undefined}>{conn.last_error}</Alert></div>}
      {!revoked && (gl.loading && !gl.data ? <Skeleton className="m-4 h-24" /> : (gl.data?.length ?? 0) === 0 ? <p className="p-4 text-sm text-ink-500">No Business Profile locations were found on this account.</p> : (
        <>
          <p className="px-4 pt-3 text-[13px] text-ink-500">Pick the locations to sync and match each to a FlowQR location.</p>
          <div className="overflow-x-auto"><table className="dt mt-2 min-w-[640px]">
            <thead><tr><th className="w-10">Sync</th><th>Google location</th><th>FlowQR location</th><th>Status</th></tr></thead>
            <tbody>{gl.data?.map((g) => (
              <tr key={g.id}>
                <td className="!p-0"><label className="grid h-11 w-11 cursor-pointer place-items-center sm:h-9 sm:w-9"><input type="checkbox" aria-label={`Sync ${g.title}`} disabled={!canEdit} checked={sel[g.id]?.on ?? false} onChange={(e) => setSel({ ...sel, [g.id]: { ...(sel[g.id] ?? { map: "" }), on: e.target.checked } })} className="h-[18px] w-[18px]" /></label></td>
                <td><p className="font-medium">{g.title}</p><p className="max-w-[260px] truncate text-xs text-ink-500">{g.address}</p></td>
                <td><select aria-label={`FlowQR location for ${g.title}`} disabled={!canEdit || !sel[g.id]?.on} value={sel[g.id]?.map ?? ""} onChange={(e) => setSel({ ...sel, [g.id]: { ...(sel[g.id] ?? { on: true }), map: e.target.value } })} className="min-h-9 rounded-lg border border-ink-300 bg-white px-2 text-sm disabled:bg-ink-50 disabled:text-ink-400">
                  <option value="">Match to location…</option>{locs.data?.filter((l) => l.is_active).map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}<option value="__new">+ Create from Google details</option></select></td>
                <td>{g.selected ? (
                  g.last_sync_status === "ok" ? <Status tone="ok">Synced · {timeAgo(g.last_synced_at)}</Status>
                    : g.last_sync_status ? <div><Status tone={g.last_sync_status === "rate_limited" || g.last_sync_status === "awaiting_approval" ? "warn" : "bad"}>{g.last_sync_status.replace("_", " ")}</Status>{g.last_sync_error && <p className="max-w-[220px] text-xs text-red-700">{g.last_sync_error}</p>}</div>
                    : <Status tone="idle">Waiting for first sync</Status>
                ) : <span className="text-ink-400">Not syncing</span>}</td>
              </tr>))}</tbody>
          </table></div>
          {canEdit && <div className="flex flex-wrap gap-2 border-t border-ink-100 p-4"><Button size="sm" loading={saving} onClick={() => void save()}>Save &amp; sync</Button>
            <Button size="sm" variant="secondary" icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={async () => { try { await api(`/google/connections/${conn.id}/refresh-locations`, { method: "POST" }); void gl.reload(); toast("Locations refreshed."); } catch (e) { toast(errorMessage(e), "error"); } }}>Refresh list</Button></div>}
        </>
      ))}
    </Panel>
  );
}
