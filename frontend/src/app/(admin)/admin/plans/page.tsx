"use client";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, CardHeader, PageHeader, Skeleton, ErrorState } from "@/components/ui/Card";
import { Input } from "@/components/ui/Form";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { rupees } from "@/lib/billing";
import { useFetch } from "@/lib/use-api";

interface Plan { code: string; name: string; price_paise: number; active: boolean; retired: boolean; max_locations: number; max_staff: number; review_generations: number; review_replies: number; features: string[]; limits: { geo?: { max_grids: number | null; max_points: number | null; monthly_points: number | null } }; pending_owner_configuration: string[] }
interface Plans { plans: Plan[]; assumptions: string[]; unapproved_limits: Record<string, string>; promotion: { plan: string; days: number; max_per_business: number; owner_decision_pending: string[] }; card_offers: { code: string; quantity: number; price_paise: number }[]; quota_rule: string }

function GeoForm({ plan, onSaved }: { plan: Plan; onSaved: () => void }) {
  const toast = useToast();
  const g = plan.limits.geo ?? { max_grids: null, max_points: null, monthly_points: null };
  const [v, setV] = useState({ max_grids: g.max_grids?.toString() ?? "", max_points: g.max_points?.toString() ?? "", monthly_points: g.monthly_points?.toString() ?? "" });
  const [note, setNote] = useState(""), [existing, setExisting] = useState(true), [busy, setBusy] = useState(false);
  const n = (s: string) => (s.trim() ? Number(s) : null);
  async function save() {
    setBusy(true);
    try { await api(`/admin/plans/${plan.code}/limits`, { method: "PUT", body: { geo: { max_grids: n(v.max_grids), max_points: n(v.max_points), monthly_points: n(v.monthly_points) }, apply_to_existing: existing, note } }); toast("Saved."); onSaved(); }
    catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(false); }
  }
  return (
    <form className="mt-3 space-y-3 rounded-tile border border-line p-3" onSubmit={(e) => { e.preventDefault(); void save(); }}>
      <p className="text-sm font-medium">Map allowances (all three, or leave all empty to switch maps off)</p>
      <div className="grid gap-3 sm:grid-cols-3">
        <Input label="Maps per location" inputMode="numeric" value={v.max_grids} onChange={(e) => setV({ ...v, max_grids: e.target.value })} />
        <Input label="Points per map" inputMode="numeric" value={v.max_points} onChange={(e) => setV({ ...v, max_points: e.target.value })} />
        <Input label="Searches per month" inputMode="numeric" value={v.monthly_points} onChange={(e) => setV({ ...v, monthly_points: e.target.value })} />
      </div>
      <Input label="Why (recorded in the audit log)" value={note} onChange={(e) => setNote(e.target.value)} />
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="h-4 w-4" checked={existing} onChange={(e) => setExisting(e.target.checked)} />Also apply to businesses already on this plan</label>
      <Button type="submit" size="sm" loading={busy} disabled={note.trim().length < 3}>Save</Button>
    </form>
  );
}

interface Gate { id: string; label: string; status: "passed" | "not_done"; date: string | null; evidence: string | null; blocked_by?: string }

/** Platform admin: what each plan is, which limits are still waiting for an owner decision, and where those are set. */
export default function AdminPlans() {
  const { data, error, reload } = useFetch<Plans>("/admin/plans");
  const gates = useFetch<{ overall: string; gates: Gate[] }>("/admin/release-gates");
  if (error) return <ErrorState error={error} onRetry={() => void reload()} />;
  if (!data) return <Skeleton className="h-64" />;
  const pending = data.plans.filter((p) => p.pending_owner_configuration.length > 0);
  return (
    <>
      <PageHeader title="Plans and limits" subtitle="The confirmed plans, and the limits that are not approved yet." />
      {gates.data && (
        <Card className="mb-5"><CardHeader title="Release status" subtitle={gates.data.overall} />
          <ol className="divide-y divide-line text-sm">{gates.data.gates.map((g) => <li key={g.id} className="flex flex-col gap-1 py-2.5 sm:flex-row sm:items-start sm:justify-between sm:gap-4"><div className="min-w-0"><p className="font-medium">{g.label}</p><p className="text-xs text-muted">{g.status === "passed" ? `${g.date}: ${g.evidence}` : `Blocked by: ${g.blocked_by}`}</p></div><Badge tone={g.status === "passed" ? "green" : "red"}>{g.status === "passed" ? "passed" : "not done"}</Badge></li>)}</ol>
          <p className="mt-3 text-xs text-muted">Tests with test doubles never turn the live rungs green. Edit backend/app/release_gates.json, with evidence, when a rung is really passed.</p></Card>
      )}
      {pending.length > 0 && <div className="mb-5"><Alert tone="warning" title="Waiting for an owner decision">These features stay switched off until the numbers are approved: {Array.from(new Set(pending.flatMap((p) => p.pending_owner_configuration))).map((k) => data.unapproved_limits[k] ?? k).join(", ")}. Nothing has been assumed.</Alert></div>}
      <div className="space-y-5">
        {data.plans.filter((p) => !p.retired).map((p) => (
          <Card key={p.code}>
            <CardHeader title={`${p.name} · ${rupees(p.price_paise)} / month`} subtitle={`${p.max_locations} location${p.max_locations === 1 ? "" : "s"} · ${p.max_staff} team members · ${p.review_generations} review generations and ${p.review_replies} AI replies a month (separate allowances)`} />
            <div className="flex flex-wrap gap-1.5">{p.features.map((f) => <Badge key={f}>{f.replace(/_/g, " ")}</Badge>)}</div>
            {p.features.includes("geo_ranking") ? <GeoForm plan={p} onSaved={() => void reload()} /> : <p className="mt-3 text-sm text-muted">Maps are not part of this plan.</p>}
            {p.pending_owner_configuration.length > 0 && <p className="mt-2 text-sm text-neg">Not configured: {p.pending_owner_configuration.join(", ")}</p>}
          </Card>
        ))}
      </div>
      <h2 className="mb-2 mt-8 text-[15px] font-semibold">Assumptions in this catalogue</h2>
      <ul className="panel list-disc space-y-1.5 p-4 pl-8 text-sm">{data.assumptions.map((a) => <li key={a}>{a}</li>)}<li>{data.quota_rule}</li></ul>
      <h2 className="mb-2 mt-8 text-[15px] font-semibold">Card purchase promotion</h2>
      <div className="panel space-y-1.5 p-4 text-sm">
        <p>A paid card order includes {data.promotion.days} days of {data.promotion.plan}, up to {data.promotion.max_per_business} per business. It is free access, not a subscription, and is never counted as MRR.</p>
        <p>Offers: {data.card_offers.map((o) => `${o.quantity} card${o.quantity === 1 ? "" : "s"} for ${rupees(o.price_paise)}`).join("; ")}. One-time revenue.</p>
        <p className="text-neg">Owner decisions pending: {data.promotion.owner_decision_pending.join("; ")}.</p>
      </div>
    </>
  );
}
