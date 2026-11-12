"use client";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Card";
import { Input, Select } from "@/components/ui/Form";
import { Modal } from "@/components/ui/Modal";
import { api, errorMessage } from "@/lib/api";
import type { Card as CardT, Location } from "@/lib/types";

/** Label a card and move it between the business's own locations. History is kept; the printed link never changes. */
export function CardEditModal({ card, locations, onClose, onSaved }: { card: CardT; locations: Location[]; onClose: () => void; onSaved: () => void }) {
  const [label, setLabel] = useState(card.label ?? "");
  const [loc, setLoc] = useState(card.location_id ?? "");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function save() {
    setBusy(true); setErr(null);
    try { await api(`/cards/${card.id}`, { method: "PATCH", body: { label: label.trim() || null, location_id: loc || null } }); onSaved(); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  const moving = !!card.location_id && loc !== card.location_id;
  return (
    <Modal open onClose={onClose} title={`${card.location_id ? "Reassign" : "Assign"} ${card.card_code}`} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={busy} disabled={!loc} onClick={() => void save()}>Save</Button></>}>
      <div className="space-y-4">
        {err && <Alert tone="error">{err}</Alert>}
        <Input label="Label" placeholder="e.g. Reception desk" value={label} onChange={(e) => setLabel(e.target.value)} hint="Shown only to your team, so you can tell cards apart." />
        <Select label="Location" hint="Scan history is kept. The printed link and QR don't change." value={loc} onChange={(e) => setLoc(e.target.value)}>
          <option value="">Choose a location…</option>{locations.map((l) => <option key={l.id} value={l.id}>{l.name}{l.city ? `, ${l.city}` : ""}</option>)}
        </Select>
        {moving && <Alert tone="warning">Future scans from this card will count for the new location. Past scans stay with the old one.</Alert>}
      </div>
    </Modal>
  );
}
