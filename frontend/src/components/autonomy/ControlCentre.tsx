"use client";
import clsx from "clsx";
import { OctagonX, Power } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, EmptyState, Skeleton } from "@/components/ui/Card";
import { Modal } from "@/components/ui/Modal";
import { Panel, Segmented, Status } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import type { AutonomySettings, ControlCentre as CC } from "@/lib/autonomy";
import { useFetch } from "@/lib/use-api";
import { ActionLine, WaitingCard } from "./Actions";
import { Permissions, UsagePanel } from "./PermissionsUsage";

type Tab = "waiting" | "activity" | "problems" | "permissions" | "usage";

function state(s: AutonomySettings): { tone: "ok" | "warn" | "bad" | "idle"; label: string; detail: string } {
  if (s.platform_emergency_stop) return { tone: "bad", label: "Paused for everyone", detail: s.platform_emergency_stop_reason ?? "FlowQR has paused all automatic changes platform-wide. Nothing is lost; it resumes when the pause is lifted." };
  if (s.suspended) return { tone: "bad", label: "Stopped", detail: s.suspended_reason ?? "Autonomy is suspended. Nothing runs on its own until the owner resumes it." };
  if (s.enabled) return { tone: "ok", label: "On", detail: "FlowQR may make the safe (Level 1) changes you allowed, and the kinds you set to “Do it”. It re-checks everything just before it acts and counts a change as done only when Google shows it." };
  return { tone: "idle", label: "Off", detail: "FlowQR will suggest changes but never make one without a person approving it." };
}

/** The switch, with the owner's emergency stop beside it. Turning autonomy on explains exactly what that allows before it does anything. */
function Master({ s, isOwner, onChanged }: { s: AutonomySettings; isOwner: boolean; onChanged: () => void }) {
  const toast = useToast();
  const [confirm, setConfirm] = useState<"on" | "stop" | null>(null);
  const [busy, setBusy] = useState(false);
  const st = state(s);
  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    try { await fn(); toast(ok); setConfirm(null); onChanged(); } catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(false); }
  }
  return (
    <section className="panel p-5 sm:p-6" aria-labelledby="ac-h">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 max-w-2xl">
          <div className="flex items-center gap-3"><h2 id="ac-h" className="text-lg font-semibold">Autonomy</h2><Status tone={st.tone}>{st.label}</Status></div>
          <p className="mt-1.5 text-sm text-muted">{st.detail}</p>
          {s.failure_streak > 0 && !s.suspended && <p className="mt-1.5 text-sm text-warn">{s.failure_streak} change{s.failure_streak === 1 ? "" : "s"} in a row did not work out. After 3, autonomy stops by itself.</p>}
        </div>
        {isOwner ? (
          <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:items-center">
            {s.enabled && !s.suspended ? (
              <Button variant="secondary" icon={<Power className="h-4 w-4" aria-hidden />} onClick={() => void run(() => api("/agent/autonomy-settings", { method: "PUT", body: { enabled: false } }), "Autonomy is off.")} loading={busy}>Turn off</Button>
            ) : (
              <Button icon={<Power className="h-4 w-4" aria-hidden />} onClick={() => (s.suspended ? void run(() => api("/agent/autonomy-settings/resume", { method: "POST" }), "Resumed. Turn autonomy on when you are ready.") : setConfirm("on"))} loading={busy}>{s.suspended ? "Resume" : "Turn on"}</Button>
            )}
            <Button variant="danger" icon={<OctagonX className="h-4 w-4" aria-hidden />} onClick={() => setConfirm("stop")}>Emergency stop</Button>
          </div>
        ) : <p className="text-sm text-muted">Only the business owner can change this.</p>}
      </div>
      <Modal open={confirm === "on"} onClose={() => setConfirm(null)} title="Turn autonomy on?" footer={<><Button variant="secondary" onClick={() => setConfirm(null)}>Not now</Button><Button loading={busy} onClick={() => void run(() => api("/agent/autonomy-settings", { method: "PUT", body: { enabled: true } }), "Autonomy is on.")}>Turn on</Button></>}>
        <ul className="list-disc space-y-2 pl-5 text-sm">
          <li>FlowQR may improve your Google description from facts you have approved (Level 1), and nothing more, until you choose otherwise under Permissions.</li>
          <li>Kinds you set to &ldquo;Do it&rdquo; may run on their own. Name, main category, address and other Level 3 changes always need you.</li>
          <li>Posts, photos and review replies are never sent without a person approving each one.</li>
          <li>Every change is re-checked just before it runs, then read back from Google. You can see each step, and the Emergency stop works instantly.</li>
        </ul>
      </Modal>
      <Modal open={confirm === "stop"} onClose={() => setConfirm(null)} title="Stop everything now?" footer={<><Button variant="secondary" onClick={() => setConfirm(null)}>Cancel</Button><Button variant="danger" loading={busy} onClick={() => void run(() => api("/agent/autonomy-settings/stop", { method: "POST" }), "Stopped. Nothing will run on its own.")}>Stop autonomy</Button></>}>
        <p className="text-sm">Autonomy is switched off, anything waiting to run on its own goes back to waiting for you, and nothing runs until you resume it. Changes you approved yourself are not affected, and nothing already on Google is undone.</p>
      </Modal>
    </section>
  );
}

/**
 * Owner autonomy control centre: the switch and emergency stop, what waits for a person, what ran, what failed and why, the permission for each kind of change, and the
 * month's AI and Google usage. Everything is read from the server's records; a change counts as done only when Google's own profile showed it.
 */
export function ControlCentre() {
  const { data, error, reload } = useFetch<CC>("/agent/control-centre");
  const [tab, setTab] = useState<Tab>("waiting");
  if (error) return <Alert tone="error" title="Couldn't load the control centre">{error}</Alert>;
  if (!data) return <div className="space-y-4"><Skeleton className="h-36" /><Skeleton className="h-64" /></div>;
  const d = data;
  const tabs: [Tab, string][] = [["waiting", `Needs you${d.waiting.length ? ` (${d.waiting.length})` : ""}`], ["activity", "Activity"], ["problems", `Problems${d.problems.length ? ` (${d.problems.length})` : ""}`], ["permissions", "Permissions"], ["usage", "Usage"]];
  return (
    <div className="space-y-5">
      <Master s={d.settings} isOwner={d.is_owner} onChanged={() => void reload()} />
      <Segmented value={tab} onChange={setTab} label="Control centre sections" options={tabs} className="w-full sm:w-auto" />
      {tab === "waiting" && (
        <Panel title="Needs your decision" meta="nothing here has changed on Google yet">
          {d.waiting.length === 0 ? <EmptyState title="Nothing is waiting for you">When FlowQR suggests a change that needs a person, it appears here with what is on Google now and what it would become.</EmptyState> :
            <ul className="space-y-4">{d.waiting.map((a) => <WaitingCard key={a.id} a={a} canDecide={d.can_decide} isOwner={d.is_owner} onChanged={() => void reload()} />)}</ul>}
          {d.running.length > 0 && <div className="mt-6"><h3 className="text-sm font-semibold">Approved, about to run ({d.running.length})</h3><ul className={clsx("mt-1 divide-y divide-line")}>{d.running.map((a) => <ActionLine key={a.id} a={a} />)}</ul></div>}
        </Panel>
      )}
      {tab === "activity" && (
        <Panel title="What FlowQR has done" meta="each one confirmed by reading Google back">
          {d.recent.length === 0 ? <EmptyState title="Nothing has been applied yet">Confirmed changes show here, with every step recorded.</EmptyState> : <ul className="divide-y divide-line">{d.recent.map((a) => <ActionLine key={a.id} a={a} />)}</ul>}
        </Panel>
      )}
      {tab === "problems" && (
        <Panel title="Failed, blocked and stopped" meta="last 30 days">
          {d.problems.length === 0 ? <EmptyState title="No problems">If something is blocked for lack of evidence, fails, or is stopped because your profile changed, the reason shows here.</EmptyState> : <ul className="divide-y divide-line">{d.problems.map((a) => <ActionLine key={a.id} a={a} />)}</ul>}
        </Panel>
      )}
      {tab === "permissions" && <Permissions s={d.settings} isOwner={d.is_owner} onSaved={() => void reload()} />}
      {tab === "usage" && <UsagePanel u={d.usage} />}
    </div>
  );
}
