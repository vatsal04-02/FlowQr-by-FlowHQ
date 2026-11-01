"use client";
import { Ban, Copy, Download, Nfc, Pencil, QrCode, Zap } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { Input, Select } from "@/components/ui/Form";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate } from "@/lib/format";
import { copyText, STATUS_TONE } from "@/lib/card-ui";
import type { Card as CardT, Location } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

export default function CardsPage() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const { data, error, loading, reload } = useFetch<CardT[]>("/cards");
  const locs = useFetch<Location[]>("/locations");
  const [edit, setEdit] = useState<CardT | null>(null);
  const [view, setView] = useState<CardT | null>(null);

  async function act(c: CardT, path: string, msg: string) {
    try { await api(`/cards/${c.id}/${path}`, { method: "POST" }); toast(msg); void reload(); } catch (e) { toast(errorMessage(e), "error"); }
  }

  return (
    <>
      <PageHeader title="QR/NFC cards" subtitle="Each card has its own permanent link. Change your Google review link any time without replacing a card." />
      <div className="mb-5"><Alert tone="info" title="Cards are issued by FlowQR">Your physical cards are assigned to your locations by the FlowQR team. You can then rename them, move them between your own locations, or deactivate them.</Alert></div>
      {error && <Alert tone="error">{error}</Alert>}
      {loading && !data ? <Skeleton className="h-48" /> : data && data.length === 0 ? (
        <EmptyState icon={<QrCode className="h-6 w-6" />} title="No cards assigned yet">When your cards are assigned to a location they'll appear here with their scan stats.</EmptyState>
      ) : (
        <ul className="grid gap-4 md:grid-cols-2">
          {data?.map((c) => (
            <li key={c.id}><Card>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0"><p className="font-display text-xl font-semibold tracking-wide">{c.card_code}</p><p className="truncate text-sm text-ink-500">{c.label ? `${c.label} · ` : ""}{c.location_name ?? "No location"}</p></div>
                <Badge tone={STATUS_TONE[c.status]}>{c.status}</Badge>
              </div>
              <dl className="mt-4 grid grid-cols-4 gap-2 text-center">
                {[["Scans", c.stats.scan], ["Visits", c.stats.landing_view], ["Google clicks", c.stats.google_click], ["AI uses", c.stats.ai_assist]].map(([k, v]) => (
                  <div key={k as string} className="rounded-xl bg-ink-50 p-2"><dd className="font-display text-lg font-semibold tabular-nums">{(v as number) ?? 0}</dd><dt className="text-[11px] leading-tight text-ink-500">{k}</dt></div>
                ))}
              </dl>
              <p className="mt-3 text-xs text-ink-500">Assigned {fmtDate(c.assigned_at)}</p>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button size="sm" variant="secondary" icon={<QrCode className="h-4 w-4" />} onClick={() => setView(c)}>QR &amp; NFC</Button>
                {isAdmin && <>
                  <Button size="sm" variant="secondary" icon={<Pencil className="h-4 w-4" />} onClick={() => setEdit(c)}>Edit</Button>
                  {(c.status === "deactivated") && <Button size="sm" variant="secondary" icon={<Zap className="h-4 w-4" />} onClick={() => void act(c, "activate", "Card activated.")}>Reactivate</Button>}
                  {(c.status === "assigned" || c.status === "active") && <Button size="sm" variant="danger" icon={<Ban className="h-4 w-4" />} onClick={() => void act(c, "deactivate", "Card deactivated. Scans now show a notice.")}>Deactivate</Button>}
                  {c.status !== "lost" && <Button size="sm" variant="ghost" onClick={() => void act(c, "report-lost", "Marked as lost.")}>Report lost</Button>}
                </>}
              </div>
            </Card></li>
          ))}
        </ul>
      )}
      {edit && <EditModal card={edit} locations={(locs.data ?? []).filter((l) => l.is_active)} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); toast("Card updated."); void reload(); }} />}
      {view && (
        <Modal open onClose={() => setView(null)} title={`${view.card_code} · QR & NFC`} footer={<Button variant="secondary" onClick={() => setView(null)}>Done</Button>}>
          <div className="grid place-items-center">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={`/api/v1/cards/${view.id}/qr.svg`} alt={`QR code for card ${view.card_code}`} className="h-56 w-56 rounded-xl border border-ink-100 p-2" />
          </div>
          <div className="mt-4 flex flex-wrap justify-center gap-2">
            {isAdmin && <><a className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-ink-200 px-4 text-sm font-semibold hover:bg-ink-50" href={`/api/v1/cards/${view.id}/qr.png`}><Download className="h-4 w-4" aria-hidden />PNG</a>
              <a className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-ink-200 px-4 text-sm font-semibold hover:bg-ink-50" href={`/api/v1/cards/${view.id}/qr.svg`}><Download className="h-4 w-4" aria-hidden />SVG</a></>}
          </div>
          <div className="mt-5 rounded-xl bg-ink-50 p-3">
            <p className="flex items-center gap-2 text-sm font-semibold"><Nfc className="h-4 w-4 text-flow-600" aria-hidden />Card link (QR and NFC use the same link)</p>
            <p className="mt-1 break-all font-mono text-xs text-ink-700">{view.url}</p>
            <Button size="sm" variant="secondary" className="mt-2" icon={<Copy className="h-4 w-4" />} onClick={async () => { await copyText(view.url); toast("Link copied."); }}>Copy link</Button>
            <p className="mt-2 text-xs text-ink-500">To program an NFC tag (NTAG213/215/216), write this link as a URL/NDEF record with any free NFC writer app.</p>
          </div>
        </Modal>
      )}
    </>
  );
}

function EditModal({ card, locations, onClose, onSaved }: { card: CardT; locations: Location[]; onClose: () => void; onSaved: () => void }) {
  const [label, setLabel] = useState(card.label ?? "");
  const [loc, setLoc] = useState(card.location_id ?? "");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function save() {
    setBusy(true); setErr(null);
    try { await api(`/cards/${card.id}`, { method: "PATCH", body: { label: label.trim() || null, location_id: loc || null } }); onSaved(); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <Modal open onClose={onClose} title={`Edit ${card.card_code}`} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={busy} onClick={() => void save()}>Save</Button></>}>
      <div className="space-y-4">
        {err && <Alert tone="error">{err}</Alert>}
        <Input label="Label" placeholder="e.g. Reception desk" value={label} onChange={(e) => setLabel(e.target.value)} />
        <Select label="Location" hint="Moving a card keeps its scan history. The printed link doesn't change." value={loc} onChange={(e) => setLoc(e.target.value)}>
          {locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
        </Select>
      </div>
    </Modal>
  );
}
