"use client";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Card";
import { Select } from "@/components/ui/Form";
import { Modal } from "@/components/ui/Modal";
import { api, ApiError, errorMessage } from "@/lib/api";
import type { Card as CardT } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

interface Opt { id: string; name: string; city?: string | null; location_id?: string | null; status?: string }

/** Assign the selected cards to ONE business, location and (optionally) campaign, all together or not at all. A card that already belongs to a business is never moved without an explicit
 *  confirmation that names what changes; every assignment and move is recorded in the audit log and the card's own history. */
export function BulkAssignModal({ cards, onClose, onDone }: { cards: CardT[]; onClose: () => void; onDone: (n: number) => void }) {
  const tenants = useFetch<{ items: Opt[] }>("/admin/tenants");
  const [tenant, setTenant] = useState("");
  const locs = useFetch<(Opt & { is_active?: boolean })[]>(tenant ? `/admin/tenants/${tenant}/locations` : null);
  const camps = useFetch<Opt[]>(tenant ? `/admin/tenants/${tenant}/campaigns` : null);
  const [loc, setLoc] = useState("");
  const [campaign, setCampaign] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [ask, setAsk] = useState<string | null>(null);
  const inUse = cards.filter((c) => c.tenant_id);
  const campaigns = (camps.data ?? []).filter((c) => c.status !== "archived" && (!c.location_id || c.location_id === loc));

  async function run(confirm: boolean) {
    setBusy(true); setErr(null);
    try {
      const r = await api<{ assigned: number }>("/admin/cards/bulk-assign", { method: "POST", body: { card_ids: cards.map((c) => c.id), tenant_id: tenant, location_id: loc, campaign_id: campaign || null, confirm, activate: true } });
      onDone(r.assigned ?? cards.length);
    } catch (e) {
      if (e instanceof ApiError && e.code === "confirmation_required") setAsk(e.message);
      else setErr(errorMessage(e));
    } finally { setBusy(false); }
  }

  return (
    <Modal open onClose={onClose} title={`Assign ${cards.length} card${cards.length === 1 ? "" : "s"}`}
      footer={<><Button variant="secondary" className="!rounded-full" onClick={onClose} disabled={busy}>Cancel</Button>
        <Button className="!rounded-full" loading={busy} disabled={!tenant || !loc} onClick={() => void run(!!ask)}>{ask ? "Yes, move them" : "Assign and activate"}</Button></>}>
      <p className="text-sm text-muted">{cards.slice(0, 6).map((c) => c.card_code).join(", ")}{cards.length > 6 ? ` and ${cards.length - 6} more` : ""}. All are assigned together, or none are.</p>
      <div className="mt-4 space-y-3">
        <Select label="Business" value={tenant} onChange={(e) => { setTenant(e.target.value); setLoc(""); setCampaign(""); setAsk(null); }}>
          <option value="">Choose a business</option>{(tenants.data?.items ?? []).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</Select>
        <Select label="Location" value={loc} disabled={!tenant} onChange={(e) => { setLoc(e.target.value); setCampaign(""); setAsk(null); }}>
          <option value="">Choose a location</option>{(locs.data ?? []).filter((l) => l.is_active !== false).map((l) => <option key={l.id} value={l.id}>{l.name}{l.city ? ` · ${l.city}` : ""}</option>)}</Select>
        <Select label="Campaign (optional)" value={campaign} disabled={!loc} onChange={(e) => setCampaign(e.target.value)}>
          <option value="">Plain review page</option>{campaigns.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select>
      </div>
      {inUse.length > 0 && !ask && <div className="mt-4"><Alert tone="warning" title={`${inUse.length} of these cards already belong to a business`}>Press the button after choosing the target: if any would move, you will see exactly what changes and must confirm.</Alert></div>}
      {ask && <div className="mt-4"><Alert tone="warning" title="Please confirm">{ask} The old and new assignment are both kept in the history.</Alert></div>}
      {err && <div className="mt-4"><Alert tone="error">{err}</Alert></div>}
    </Modal>
  );
}
