"use client";
import { useState } from "react";
import { Alert, Badge, Card, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Form";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { useFetch } from "@/lib/use-api";

interface Stop { on: boolean; source?: "environment" | "admin"; reason?: string; since?: string | null }

/**
 * The platform-wide emergency stop for everything FlowQR does on customers' Google profiles (approved and autonomous changes, scheduled posts and photos, reply retries).
 * Held work waits and nothing is lost; resuming releases it. A reason is required and recorded. A stop set in the server environment cannot be lifted from here.
 */
export function PlatformStop() {
  const toast = useToast();
  const { data, error, reload } = useFetch<{ stop: Stop | null }>("/admin/autonomy/emergency-stop");
  const [reason, setReason] = useState(""), [busy, setBusy] = useState(false);
  const stop = data?.stop?.on ? data.stop : null;

  async function set(on: boolean) {
    setBusy(true);
    try {
      await api("/admin/autonomy/emergency-stop", { method: "PUT", body: { on, reason: reason.trim() || undefined } });
      setReason(""); await reload();
      toast(on ? "Everything is stopped." : "Execution resumed.");
    } catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(false); }
  }

  return (
    <Card className="mt-5">
      <CardHeader title="Emergency stop" subtitle="Stops every change FlowQR makes on customers' Google profiles, platform-wide: approved and automatic changes, scheduled posts and photos, reply retries. Work that is held waits; nothing is deleted." action={<Badge tone={stop ? "red" : "green"}>{stop ? "STOPPED" : "running"}</Badge>} />
      {error && <Alert tone="error">{error}</Alert>}
      {stop ? (
        <div className="space-y-3">
          <Alert tone="warning" title={stop.source === "environment" ? "Stopped by the server's settings" : "Stopped by a platform administrator"}>{stop.reason}{stop.since ? ` Since ${fmtDate(stop.since)}.` : ""}</Alert>
          {stop.source === "environment" ? <p className="text-sm text-muted">This stop comes from <code>AUTONOMY_EMERGENCY_STOP</code> in the server environment. Remove it there and restart to resume.</p>
            : <div className="flex flex-wrap items-end gap-3"><div className="min-w-[220px] flex-1"><Input label="Note for the record (optional)" value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)} /></div><Button loading={busy} onClick={() => void set(false)}>Resume execution</Button></div>}
        </div>
      ) : (
        <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); if (reason.trim().length >= 3) void set(true); }}>
          <div className="min-w-[220px] flex-1"><Input label="Why are you stopping everything? (required, recorded)" value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)} /></div>
          <Button type="submit" variant="danger" loading={busy} disabled={reason.trim().length < 3}>Stop everything</Button>
        </form>
      )}
    </Card>
  );
}
