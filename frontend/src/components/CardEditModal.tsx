"use client";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Card";
import { Input, Select } from "@/components/ui/Form";
import { Modal } from "@/components/ui/Modal";
import { api, errorMessage } from "@/lib/api";
import { isLive } from "@/lib/card-ui";
import type { Card as CardT, Location } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

interface Camp { id: string; name: string; location_id: string | null; status: string }

/**
 * Label a card, and change where it points: location and review campaign. History is kept and the printed QR and NFC tag never change,
 * but a card that is in use starts sending customers somewhere new the moment this is saved, so that needs an explicit tick.
 */
export function CardEditModal({ card, locations, onClose, onSaved }: { card: CardT; locations: Location[]; onClose: () => void; onSaved: () => void }) {
  const [label, setLabel] = useState(card.label ?? "");
  const [loc, setLoc] = useState(card.location_id ?? "");
  const [campaign, setCampaign] = useState(card.campaign_id ?? "");
  const [ack, setAck] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const camps = useFetch<Camp[]>("/review-growth/campaigns");
  const options = useMemo(() => (camps.data ?? []).filter((c) => c.status !== "archived" && (!c.location_id || c.location_id === loc)), [camps.data, loc]);

  const placedNow = !!card.location_id;
  const campaignChanged = (card.campaign_id ?? "") !== campaign;
  const moving = placedNow && (loc !== card.location_id || campaignChanged);
  const needsAck = moving && (isLive(card.status) || card.status === "paused");

  async function save() {
    setBusy(true); setErr(null);
    try {
      if (!placedNow) {
        // a reserved card getting its first place: the "assign" endpoint also switches it on
        await api(`/cards/${card.id}/assign`, { method: "POST", body: { location_id: loc, campaign_id: campaign || null, label: label.trim() || null, activate: true, confirm: ack } });
      } else {
        const body: Record<string, unknown> = { label: label.trim() || null, confirm: ack };
        if (loc !== card.location_id) body.location_id = loc;
        if (campaignChanged || loc !== card.location_id) { if (campaign && options.some((c) => c.id === campaign)) body.campaign_id = campaign; else if (card.campaign_id) body.clear_campaign = true; }
        await api(`/cards/${card.id}`, { method: "PATCH", body });
      }
      onSaved();
    } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <Modal open onClose={onClose} title={`${card.location_id ? "Change" : "Assign"} ${card.card_code}`} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={busy} disabled={!loc || (needsAck && !ack)} onClick={() => void save()}>Save</Button></>}>
      <div className="space-y-4">
        {err && <Alert tone="error">{err}</Alert>}
        <Input label="Label" placeholder="e.g. Reception desk" value={label} onChange={(e) => setLabel(e.target.value)} hint="Shown only to your team, so you can tell cards apart." />
        <Select label="Location" hint="Scan history is kept. The printed link, QR and NFC tag don't change." value={loc} onChange={(e) => { setLoc(e.target.value); setCampaign(""); setAck(false); }}>
          <option value="">Choose a location…</option>{locations.map((l) => <option key={l.id} value={l.id}>{l.name}{l.city ? `, ${l.city}` : ""}</option>)}
        </Select>
        <Select label="Review page" hint="What customers see when they scan or tap this card." value={campaign} disabled={!loc} onChange={(e) => { setCampaign(e.target.value); setAck(false); }}>
          <option value="">Plain review page</option>{options.map((c) => <option key={c.id} value={c.id}>Campaign: {c.name}{c.status === "paused" ? " (paused)" : ""}</option>)}
        </Select>
        {needsAck && (
          <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
            <p>This card is in use. As soon as you save, everyone who scans or taps it goes to the new destination. Past scans stay with the old one.</p>
            <label className="mt-2 flex min-h-11 items-center gap-2 font-medium"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} className="h-5 w-5" />I understand, change this card</label>
          </div>
        )}
      </div>
    </Modal>
  );
}
