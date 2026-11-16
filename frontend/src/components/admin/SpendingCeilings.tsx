"use client";
import { useState } from "react";
import { Alert, Card, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Form";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useFetch } from "@/lib/use-api";

interface Budgets { ai_monthly_budget_usd: number | null; ai_spent_usd: number | null; ai_priced: boolean; places_monthly_cap: number | null; places_used_this_month: number }

/** One business's own spending ceilings. Leaving a box empty clears that ceiling (the business then follows the platform default). Every change is audited with the note. */
export function SpendingCeilings({ tenantId }: { tenantId: string }) {
  const toast = useToast();
  const { data: b, error, reload } = useFetch<Budgets>(`/admin/tenants/${tenantId}/budgets`);
  const [edit, setEdit] = useState(false), [ai, setAi] = useState(""), [places, setPlaces] = useState(""), [note, setNote] = useState(""), [busy, setBusy] = useState(false);

  function open() { setAi(b?.ai_monthly_budget_usd == null ? "" : String(b.ai_monthly_budget_usd)); setPlaces(b?.places_monthly_cap == null ? "" : String(b.places_monthly_cap)); setNote(""); setEdit(true); }
  async function save(e: React.FormEvent) {
    e.preventDefault(); setBusy(true);
    try {
      await api(`/admin/tenants/${tenantId}/budgets`, { method: "PUT", body: { ai_monthly_budget_usd: ai.trim() === "" ? null : Number(ai), places_monthly_cap: places.trim() === "" ? null : Number(places), note: note.trim() } });
      await reload(); setEdit(false); toast("Ceilings saved.");
    } catch (err) { toast(errorMessage(err), "error"); } finally { setBusy(false); }
  }

  return (
    <Card>
      <CardHeader title="Spending ceilings" subtitle="What this business may spend on AI and Google searches each month." action={!edit && b && <Button size="sm" variant="secondary" onClick={open}>Change</Button>} />
      {error && <Alert tone="error">{error}</Alert>}
      {b && !edit && (
        <dl className="grid gap-3 text-sm sm:grid-cols-2">
          <div><dt className="text-muted">AI budget this month</dt><dd className="num font-semibold">{b.ai_monthly_budget_usd == null ? "No business-specific ceiling" : `$${b.ai_monthly_budget_usd.toFixed(2)}`}</dd>
            <dd className="text-xs text-muted">{b.ai_priced ? `Spent so far: $${(b.ai_spent_usd ?? 0).toFixed(2)}` : "AI prices are not configured, so spend in dollars cannot be shown and a dollar ceiling refuses AI calls."}</dd></div>
          <div><dt className="text-muted">Google searches this month</dt><dd className="num font-semibold">{b.places_monthly_cap == null ? "No business-specific ceiling" : b.places_monthly_cap}</dd><dd className="text-xs text-muted">Used so far: {b.places_used_this_month}</dd></div>
        </dl>
      )}
      {b && edit && (
        <form onSubmit={save} className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <Input label="AI budget per month (USD)" inputMode="decimal" hint="Empty = follow the platform default." value={ai} onChange={(e) => setAi(e.target.value)} />
            <Input label="Google searches per month" inputMode="numeric" hint="Empty = follow the plan and platform limits." value={places} onChange={(e) => setPlaces(e.target.value)} />
          </div>
          <Input label="Why? (required, kept in the audit log)" value={note} minLength={3} maxLength={300} required onChange={(e) => setNote(e.target.value)} />
          <div className="flex gap-2"><Button type="submit" loading={busy} disabled={note.trim().length < 3}>Save ceilings</Button><Button type="button" variant="secondary" onClick={() => setEdit(false)}>Cancel</Button></div>
        </form>
      )}
    </Card>
  );
}
