"use client";
import { Download, Trash2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Card";
import { Input } from "@/components/ui/Form";
import { Panel } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import { api, ApiError, apiFile, errorMessage, saveBlob } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate } from "@/lib/format";
import { useFetch } from "@/lib/use-api";

interface Deletion { requested: boolean; scheduled_for: string | null; grace_days: number }

/** Export and deletion for the business owner. Deletion is scheduled with a grace period and can be cancelled. */
export function YourDataPanel() {
  const { tenant, me, role } = useAuth();
  const toast = useToast();
  const del = useFetch<Deletion>("/account/deletion");
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const owner = role === "owner";
  const needsPassword = !!me?.user.has_local_login;

  async function exportData() {
    setExporting(true); setExportError(null);
    try { const { blob } = await apiFile("/account/export"); saveBlob(blob, `flowqr-export-${tenant?.slug ?? "business"}.zip`); toast("Your data was downloaded."); }
    catch (e) { setExportError(e instanceof ApiError && e.status === 429 ? "You can export 3 times an hour. Try again later." : errorMessage(e)); }
    finally { setExporting(false); }
  }
  async function schedule() {
    setBusy(true); setError(null);
    try { del.setData(await api<Deletion>("/account/deletion", { method: "POST", body: { confirm_name: name, password: needsPassword ? password : undefined } })); setOpen(false); setName(""); setPassword(""); toast("Deletion scheduled. You can cancel it until the date shown."); }
    catch (e) { setError(e instanceof ApiError && e.code === "cancel_subscription_first" ? e.message : e instanceof ApiError && e.status === 422 ? "That doesn\u2019t match the business name exactly." : e instanceof ApiError && e.status === 403 ? "That password is not correct." : errorMessage(e)); }
    finally { setBusy(false); }
  }
  async function cancel() {
    setBusy(true);
    try { del.setData(await api<Deletion>("/account/deletion", { method: "DELETE" })); toast("Deletion cancelled. Nothing was changed."); }
    catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(false); }
  }

  return (
    <Panel title="Your data" meta="export or delete everything FlowQR holds for this business">
      {!owner && <Alert tone="info">Only the business owner can export or delete the business&rsquo;s data.</Alert>}
      {owner && (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="min-w-0 flex-1 text-sm text-ink-700"><b>Download your data.</b> A ZIP of JSON files: locations, reviews and replies, QR campaigns and cards, scans, team, billing and audit records. Google tokens and password hashes are never included.</p>
            <Button variant="secondary" icon={<Download className="h-4 w-4" />} loading={exporting} onClick={() => void exportData()}>Download</Button>
          </div>
          {exportError && <Alert tone="error" title="Export failed">{exportError}</Alert>}
          <div className="border-t border-ink-100 pt-4">
            {del.data?.requested ? (
              <Alert tone="warning" title={`This business will be deleted on ${del.data.scheduled_for ? fmtDate(del.data.scheduled_for) : "the scheduled date"}`}
                action={<Button size="sm" variant="secondary" loading={busy} onClick={() => void cancel()}>Cancel deletion</Button>}>
                Until then everything works as normal. After that date the business and all its data are permanently deleted and cannot be recovered.</Alert>
            ) : (
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="min-w-0 flex-1 text-sm text-ink-700"><b>Delete this business.</b> Removes the business and all its data after a {del.data?.grace_days ?? 14}-day grace period you can cancel. Printed cards stop opening your page. <a className="text-brand-700 underline" href="/data-deletion">What is deleted</a></p>
                <Button variant="danger" icon={<Trash2 className="h-4 w-4" />} onClick={() => { setError(null); setOpen(true); }}>Delete business…</Button>
              </div>)}
            {del.error && <p className="mt-2 text-xs text-red-700">{del.error}</p>}
          </div>
          {open && (
            <div role="group" aria-label="Confirm deletion" className="space-y-3 rounded-lg border border-red-200 bg-red-50/60 p-4">
              <p className="text-sm text-red-900">Download your data first if you want a copy. If you have a paid plan, cancel it on the Subscription page before this step.</p>
              {error && <Alert tone="error" title="Not scheduled">{error}</Alert>}
              <Input label={`Type the business name (${tenant?.name ?? ""}) to confirm`} value={name} onChange={(e) => setName(e.target.value)} autoComplete="off" />
              {needsPassword && <Input label="Your password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />}
              <div className="flex gap-2"><Button variant="danger" loading={busy} disabled={name !== tenant?.name || (needsPassword && !password)} onClick={() => void schedule()}>Schedule deletion</Button><Button variant="secondary" onClick={() => setOpen(false)}>Keep my business</Button></div>
            </div>)}
        </div>)}
    </Panel>
  );
}
