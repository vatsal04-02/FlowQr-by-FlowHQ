"use client";
import { Lock } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge } from "@/components/ui/Card";
import { Input } from "@/components/ui/Form";
import { Meter, Panel, Segmented } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import type { AutonomySettings, Mode, Usage } from "@/lib/autonomy";
import { fmtDate, fmtNum } from "@/lib/format";
import { LevelBadge } from "./Actions";

const MODES = [["ask", "Ask me"], ["auto", "Do it"], ["off", "Never"]] as const;

/** What FlowQR may do on its own, per kind of change. Level 3 and public content (posts, photos, replies) can never be set to "Do it": the server refuses it. */
export function Permissions({ s, isOwner, onSaved }: { s: AutonomySettings; isOwner: boolean; onSaved: () => void }) {
  const toast = useToast();
  const [edit, setEdit] = useState<Record<string, Mode>>({});
  const [limit, setLimit] = useState<string>(String(s.daily_limit));
  const [busy, setBusy] = useState(false);
  const dirty = Object.keys(edit).length > 0 || Number(limit) !== s.daily_limit;
  async function save() {
    setBusy(true);
    try { await api("/agent/autonomy-settings", { method: "PUT", body: { permissions: edit, daily_limit: Number(limit) } }); setEdit({}); toast("Permissions saved."); onSaved(); }
    catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(false); }
  }
  const groups = [1, 2, 3] as const;
  const names = { 1: "Safe to do on its own", 2: "Only if you allow that exact kind of change", 3: "Always needs the owner" } as const;
  return (
    <Panel title="What FlowQR may do" meta="per kind of change">
      {!isOwner && <div className="mb-4"><Alert tone="info">Only the business owner can change these.</Alert></div>}
      {!s.enabled && <div className="mb-4"><Alert tone="warning" title="Autonomy is switched off">These settings take effect only once the owner turns autonomy on.</Alert></div>}
      <div className="space-y-6">
        {groups.map((lv) => {
          const rows = s.permissions.filter((p) => p.level === lv);
          if (!rows.length) return null;
          return (
            <section key={lv} aria-label={names[lv]}>
              <div className="mb-2 flex items-center gap-2"><LevelBadge level={lv} /><h3 className="text-sm font-semibold">{names[lv]}</h3></div>
              <ul className="divide-y divide-line rounded-tile border border-line">
                {rows.map((p) => {
                  const mode = edit[p.type] ?? p.mode;
                  return (
                    <li key={p.type} className="flex flex-col gap-2 p-3 sm:flex-row sm:items-center sm:justify-between">
                      <span className="text-sm font-medium">{p.label}</span>
                      {p.can_be_auto || lv === 1 ? (
                        <Segmented value={mode} label={`${p.label}: what to do`} options={isOwner ? MODES : MODES.filter(([m]) => m === mode)} onChange={(m) => setEdit({ ...edit, [p.type]: m })} />
                      ) : (
                        <span className="inline-flex items-center gap-1.5 text-[13px] text-muted"><Lock className="h-3.5 w-3.5" aria-hidden />{mode === "off" ? "Never" : "Always asks a person"}</span>
                      )}
                    </li>
                  );
                })}
              </ul>
            </section>
          );
        })}
        <div className="max-w-xs"><Input label="Most changes FlowQR may make on its own in 24 hours" type="number" min={0} max={50} value={limit} onChange={(e) => setLimit(e.target.value)} disabled={!isOwner} hint="Posts, photos and replies are never counted here: a person approves each one." /></div>
        {isOwner && <Button onClick={() => void save()} loading={busy} disabled={!dirty}>Save permissions</Button>}
        {s.permissions_set_at && <p className="text-xs text-muted">Last changed {fmtDate(s.permissions_set_at)}.</p>}
      </div>
    </Panel>
  );
}

function Row({ label, used, cap, hint, tone }: { label: string; used: number; cap: number | null; hint?: string; tone?: "info" | "warn" | "bad" }) {
  return (
    <li className="space-y-1.5 py-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm"><span className="font-medium">{label}</span><span className="tabular-nums text-muted">{cap ? `${fmtNum(used)} of ${fmtNum(cap)}` : `${fmtNum(used)} used`}</span></div>
      {cap ? <Meter value={used} max={cap} tone={tone ?? (used >= cap ? "bad" : used >= cap * 0.8 ? "warn" : "info")} label={label} /> : null}
      {hint && <p className="text-xs text-muted">{hint}</p>}
    </li>
  );
}

/** This month's AI and Google usage against the limits that protect the bill. Limits are set by your plan and by FlowQR; this page only shows them. */
export function UsagePanel({ u }: { u: Usage }) {
  const usd = (n: number) => `$${n.toFixed(2)}`;
  return (
    <Panel title="Usage and limits" meta={`this month, resets ${fmtDate(u.month_resets_on, { day: "numeric", month: "short" })}`}>
      <ul className="divide-y divide-line">
        <Row label="AI review generations" used={u.ai.review_generations_used} cap={u.ai.review_generations_cap} hint="The writing help your customers see on the review page. Separate from replies." />
        <Row label="AI review replies" used={u.ai.review_replies_used} cap={u.ai.review_replies_cap} hint="Drafts of replies to your Google reviews. When used up you can still write replies yourself. Posts and profile suggestions are not counted here: they follow your plan and your AI budget." />
        {u.ai.priced && u.ai.usd_budget ? <Row label="AI spend" used={u.ai.usd_spent ?? 0} cap={u.ai.usd_budget} hint={`${usd(u.ai.usd_spent ?? 0)} of ${usd(u.ai.usd_budget)}. When the budget is reached, FlowQR stops using AI for this business.`} /> :
          <li className="py-3 text-sm text-muted">{u.ai.calls} AI calls and {fmtNum(u.ai.tokens_used)} tokens so far. {u.ai.note ?? "No spending budget is set for this business."}</li>}
        {u.ai.tokens_budget ? <Row label="AI tokens" used={u.ai.tokens_used} cap={u.ai.tokens_budget} /> : null}
        {u.places.grid_enabled ? <Row label="Map searches (Google)" used={u.places.grid_points_used} cap={u.places.grid_points_cap} hint={u.places.platform_capped ? "FlowQR's overall Google allowance for this month is used, so scans are paused for everyone." : `${u.places.grid_points_left} left. Each point on a map is one search.`} /> :
          <li className="py-3 text-sm text-muted">{u.places.grid_reason === "not_configured" ? "Map ranking is part of your plan, but its allowances have not been set yet, so it is switched off for now." : "Map ranking isn't included in your plan."}</li>}
        {u.places.business_cap !== null && <Row label="Google searches (your ceiling)" used={u.places.units_this_month} cap={u.places.business_cap} hint="A ceiling set for your business by FlowQR support." />}
        <Row label="Ranking checks (Google)" used={u.places.search_checks_used} cap={u.places.search_checks_cap} hint={u.places.priced && u.places.estimated_usd != null ? `Estimated Google cost this month: ${usd(u.places.estimated_usd)}.` : undefined} />
        <Row label="Changes made on their own, last 24 hours" used={u.autonomy.executed_last_24h} cap={u.autonomy.daily_limit || null} hint="Your daily limit protects the profile from a runaway change." />
      </ul>
      {u.ai.blocked && <div className="mt-3"><Badge tone="red">AI is paused for this business until the budget resets</Badge></div>}
    </Panel>
  );
}
