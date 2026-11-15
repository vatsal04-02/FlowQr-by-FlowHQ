"use client";
import { Check, ScanLine, TriangleAlert } from "lucide-react";
import { useMemo, useState } from "react";
import { CardScanner } from "@/components/cards/CardScanner";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Card";
import { Input, Select, Textarea } from "@/components/ui/Form";
import { Panel, Status } from "@/components/ui/kit";
import { api, ApiError, errorMessage } from "@/lib/api";
import { CARD_STATUS } from "@/lib/card-ui";
import type { Card as CardT } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

interface Opt { id: string; name: string; city?: string | null; location_id?: string | null; status?: string }
type Mode = "admin" | "tenant";

/** Where a card that is about to be assigned goes. */
const where = (b: string | null | undefined, l: string | null | undefined, c: string | null | undefined) =>
  [b, l, c ? `campaign: ${c}` : "plain review page"].filter(Boolean).join(" · ");

/**
 * Assign physical cards to a business location and review campaign by scanning them.
 *
 * FlowHQ staff (mode="admin") pick any business; a business owner/admin (mode="tenant") picks among their own locations and can only
 * identify cards FlowHQ has already reserved or assigned to them: the server answers "not available" for anything else, so this screen
 * can never be used to claim stock. Nothing changes until "Assign and activate" is pressed on the confirmation, and a card already
 * in use needs an explicit tick first.
 */
export function AssignCards({ mode, onDone }: { mode: Mode; onDone?: () => void }) {
  const admin = mode === "admin";
  const tenants = useFetch<{ items: Opt[] }>(admin ? "/admin/tenants" : null);
  const [tenant, setTenant] = useState("");
  const locs = useFetch<Opt[]>(admin ? (tenant ? `/admin/tenants/${tenant}/locations` : null) : "/locations");
  const camps = useFetch<Opt[]>(admin ? (tenant ? `/admin/tenants/${tenant}/campaigns` : null) : "/review-growth/campaigns");
  const [loc, setLoc] = useState("");
  const [campaign, setCampaign] = useState("");
  const [label, setLabel] = useState("");
  const [scanning, setScanning] = useState(false);
  const [looking, setLooking] = useState(false);
  const [card, setCard] = useState<CardT | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [ack, setAck] = useState(false);
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState<CardT[]>([]);
  const [bulk, setBulk] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkAck, setBulkAck] = useState<string | null>(null);

  const locations = (locs.data ?? []).filter((l) => (l as { is_active?: boolean }).is_active !== false);
  const campaigns = useMemo(() => (camps.data ?? []).filter((c) => c.status !== "archived" && (!c.location_id || c.location_id === loc)), [camps.data, loc]);
  const tenantName = admin ? tenants.data?.items.find((t) => t.id === tenant)?.name : undefined;
  const locName = locations.find((l) => l.id === loc)?.name;
  const campName = campaigns.find((c) => c.id === campaign)?.name;
  const ready = !!loc && (!admin || !!tenant);

  const inUse = !!card && ["assigned", "active", "paused"].includes(card.status);
  const otherBusiness = !!card && admin && !!card.tenant_id && card.tenant_id !== tenant && ["reserved", "assigned", "active", "paused"].includes(card.status);
  const needsAck = inUse || otherBusiness;
  const blocked = !!card && (card.status === "retired" || card.status === "lost");

  async function identify(text: string) {
    setLooking(true); setProblem(null); setCard(null); setAck(false);
    try {
      const c = await api<CardT>(admin ? "/admin/cards/lookup" : "/cards/lookup", { method: "POST", body: { scan: text } });
      setCard(c); setScanning(false);
    } catch (e) { setProblem(errorMessage(e)); setScanning(true); } finally { setLooking(false); }
  }

  async function assign() {
    if (!card) return;
    setSaving(true); setProblem(null);
    try {
      const body = { ...(admin ? { tenant_id: tenant } : {}), location_id: loc, campaign_id: campaign || null, label: label.trim() || null, confirm: ack, activate: true };
      const c = await api<CardT>(admin ? `/admin/cards/${card.id}/assign` : `/cards/${card.id}/assign`, { method: "POST", body });
      setDone((d) => [c, ...d]); setCard(null); setAck(false); onDone?.();
    } catch (e) { setProblem(e instanceof ApiError && e.code === "confirmation_required" ? "This card is already in use. Tick the box to confirm the change." : errorMessage(e)); }
    finally { setSaving(false); }
  }

  async function assignMany(confirm: boolean) {
    const serials = bulk.split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean);
    if (!serials.length) return;
    setBulkBusy(true); setProblem(null);
    try {
      const r = await api<{ assigned: number; serials: string[] }>("/admin/cards/bulk-assign", { method: "POST", body: { serials, tenant_id: tenant, location_id: loc, campaign_id: campaign || null, confirm, activate: true } });
      setBulk(""); setBulkAck(null); setDone((d) => [...r.serials.map((s) => ({ card_code: s, id: s } as CardT)), ...d]); onDone?.();
    } catch (e) {
      if (e instanceof ApiError && e.code === "confirmation_required") setBulkAck((e.detail as { message: string }).message);
      else setProblem(errorMessage(e));
    } finally { setBulkBusy(false); }
  }

  return (
    <div className="space-y-5" data-testid="assign-cards">
      <Panel title="1. Where should the cards go?" meta="choose first, then scan each card">
        <div className="grid gap-4 sm:grid-cols-2">
          {admin && (
            <Select label="Business" value={tenant} onChange={(e) => { setTenant(e.target.value); setLoc(""); setCampaign(""); setCard(null); }}>
              <option value="">Choose a business…</option>{tenants.data?.items.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </Select>
          )}
          <Select label="Location" value={loc} disabled={admin && !tenant} onChange={(e) => { setLoc(e.target.value); setCampaign(""); setCard(null); }}>
            <option value="">Choose a location…</option>{locations.map((l) => <option key={l.id} value={l.id}>{l.name}{l.city ? ` – ${l.city}` : ""}</option>)}
          </Select>
          <Select label="Review campaign" hint="The page customers see when they scan or tap" value={campaign} disabled={!loc} onChange={(e) => { setCampaign(e.target.value); setCard(null); }}>
            <option value="">Plain review page (no campaign)</option>{campaigns.map((c) => <option key={c.id} value={c.id}>{c.name}{c.status === "paused" ? " (paused)" : ""}</option>)}
          </Select>
          <Input label="Label (optional)" placeholder="e.g. Reception desk" value={label} onChange={(e) => setLabel(e.target.value)} />
        </div>
      </Panel>

      <Panel title="2. Scan the card" meta={ready ? where(tenantName, locName, campName) : "choose the destination above"}>
        {done.length > 0 && !card && !scanning && (
          <p role="status" className="mb-3 flex items-start gap-2 rounded-lg bg-green-50 p-3 text-sm text-green-900" data-testid="assigned-ok">
            <Check className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            <span>Assigned and live: <b className="card-code">{done.slice(0, 6).map((c) => c.card_code).join(", ")}</b>{done.length > 6 ? ` and ${done.length - 6} more` : ""}. Scan the next card whenever you are ready.</span>
          </p>
        )}
        {problem && <div className="mb-3"><Alert tone="error">{problem}</Alert></div>}
        {scanning ? <CardScanner busy={looking} onResult={(t) => void identify(t)} onClose={() => setScanning(false)} />
          : card ? (
            <div className="space-y-3" data-testid="assign-confirm">
              <div className="rounded-xl border border-ink-200 bg-ink-50 p-4">
                <p className="eyebrow">Confirm this card</p>
                <p className="card-code mt-1 text-2xl font-semibold tracking-[.06em]" data-testid="confirm-serial">{card.card_code}</p>
                <p className="mt-1 flex items-center gap-2 text-sm text-ink-500">Currently <Status tone={CARD_STATUS[card.status].tone}>{CARD_STATUS[card.status].label}</Status>{card.batch_name ? ` · batch ${card.batch_name}` : ""}</p>
                <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-[110px_1fr]">
                  <dt className="text-ink-500">Business</dt><dd className="font-medium">{admin ? tenantName ?? "—" : "Your business"}</dd>
                  <dt className="text-ink-500">Location</dt><dd className="font-medium">{locName ?? "—"}</dd>
                  <dt className="text-ink-500">Campaign</dt><dd className="font-medium">{campName ?? "Plain review page"}</dd>
                </dl>
              </div>
              {blocked && <Alert tone="error">This card is {CARD_STATUS[card.status].label.toLowerCase()} and cannot be assigned.</Alert>}
              {needsAck && !blocked && (
                <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
                  <p className="flex items-start gap-2"><TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                    <span>This card is already in use{card.tenant_name ? <> by <b>{card.tenant_name}</b></> : null}{card.location_name ? <> at <b>{card.location_name}</b></> : null}{card.campaign_name ? <> (campaign <b>{card.campaign_name}</b>)</> : null}.
                      Assigning it sends everyone who scans or taps it to the new destination straight away. The printed code and NFC tag do not change.</span></p>
                  <label className="mt-2 flex min-h-11 items-center gap-2 font-medium"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} className="h-5 w-5" />I understand, move this card</label>
                </div>
              )}
              <div className="flex flex-wrap gap-2">
                <Button loading={saving} disabled={!ready || blocked || (needsAck && !ack)} onClick={() => void assign()}>Assign and activate</Button>
                <Button variant="secondary" onClick={() => { setCard(null); setProblem(null); setScanning(true); }} icon={<ScanLine className="h-4 w-4" />}>Scan a different card</Button>
              </div>
            </div>
          ) : (
            <Button disabled={!ready} icon={<ScanLine className="h-4 w-4" />} onClick={() => { setProblem(null); setScanning(true); }}>Scan card</Button>
          )}
        {!ready && !scanning && !card && <p className="mt-2 text-[13px] text-ink-500">Choose {admin ? "a business and " : ""}a location first.</p>}
      </Panel>

      {admin && (
        <Panel title="Assign many at once" meta="paste serial numbers">
          <Textarea label="Serial numbers" hint="One per line or separated by commas, e.g. FQR-0001, FQR-0002. All are assigned together or none are." rows={4} value={bulk} onChange={(e) => { setBulk(e.target.value); setBulkAck(null); }} />
          {bulkAck && (
            <div className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900" role="alert">
              <p>{bulkAck}</p>
              <Button className="mt-2" size="sm" loading={bulkBusy} onClick={() => void assignMany(true)}>Yes, move them</Button>
            </div>
          )}
          <div className="mt-3"><Button variant="secondary" loading={bulkBusy} disabled={!ready || !bulk.trim()} onClick={() => void assignMany(false)}>Assign these cards</Button></div>
        </Panel>
      )}
    </div>
  );
}
