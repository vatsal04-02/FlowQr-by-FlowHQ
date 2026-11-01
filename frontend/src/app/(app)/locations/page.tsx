"use client";
import { ExternalLink, MapPin, Pencil, Plus } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { ErrorSummary, Input } from "@/components/ui/Form";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { googleUrlRule, phoneRule, required, useForm } from "@/lib/form";
import type { Location } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

export default function LocationsPage() {
  const { isAdmin, role } = useAuth();
  const toast = useToast();
  const { data, error, loading, reload } = useFetch<Location[]>("/locations");
  const [editing, setEditing] = useState<Location | "new" | null>(null);

  return (
    <>
      <PageHeader title="Locations" subtitle="Each branch has its own cards, review link and stats." actions={isAdmin ? <Button icon={<Plus className="h-4 w-4" />} onClick={() => setEditing("new")}>Add location</Button> : undefined} />
      {error && <Alert tone="error">{error}</Alert>}
      {loading && !data ? <Skeleton className="h-40" /> : data && data.length === 0 ? (
        <EmptyState icon={<MapPin className="h-6 w-6" />} title="No locations yet" action={isAdmin ? <Button onClick={() => setEditing("new")}>Add your first location</Button> : undefined}>Add a branch to start assigning cards.</EmptyState>
      ) : (
        <ul className="grid gap-4 md:grid-cols-2">
          {data?.map((l) => (
            <li key={l.id}><Card className={l.is_active ? "" : "opacity-60"}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0"><h2 className="truncate text-lg font-semibold">{l.name}</h2>
                  <p className="text-sm text-ink-500">{[l.address_line, l.city, l.state, l.postal_code].filter(Boolean).join(", ") || "No address"}</p></div>
                {isAdmin && <Button variant="ghost" size="sm" aria-label={`Edit ${l.name}`} onClick={() => setEditing(l)} icon={<Pencil className="h-4 w-4" />} />}
              </div>
              <div className="mt-4 rounded-xl bg-ink-50 p-3 text-sm">
                <p className="mb-1 flex items-center gap-2 font-semibold text-ink-700">Google review link {l.review_url ? <Badge tone="green">{l.review_url_source === "google" ? "From Google" : "Set"}</Badge> : <Badge tone="amber">Missing</Badge>}</p>
                {l.review_url ? <a href={l.review_url} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-8 items-center gap-1 break-all text-brand-700 hover:underline">{l.review_url}<ExternalLink className="h-3.5 w-3.5 shrink-0" aria-hidden /></a> : <p className="text-ink-500">Customers can't continue to Google until you add it.</p>}
              </div>
              {!l.is_active && <p className="mt-3 text-sm text-ink-500">This location is deactivated.</p>}
            </Card></li>
          ))}
        </ul>
      )}
      {editing && <LocationModal loc={editing === "new" ? null : editing} canDeactivate={role === "owner"} onClose={() => setEditing(null)} onSaved={(m) => { setEditing(null); toast(m); void reload(); }} />}
    </>
  );
}

function LocationModal({ loc, onClose, onSaved, canDeactivate }: { loc: Location | null; onClose: () => void; onSaved: (msg: string) => void; canDeactivate: boolean }) {
  const [busy, setBusy] = useState(false);
  const f = useForm({
    name: loc?.name ?? "", address_line: loc?.address_line ?? "", city: loc?.city ?? "", state: loc?.state ?? "", postal_code: loc?.postal_code ?? "", phone: loc?.phone ?? "", review_url: loc?.review_url ?? "",
  }, { name: required("Location name"), phone: phoneRule, review_url: googleUrlRule });

  async function save(e: React.FormEvent) {
    e.preventDefault(); f.setServerError(null);
    if (!f.validateAll()) return;
    setBusy(true);
    try {
      const body = Object.fromEntries(Object.entries(f.values).map(([k, v]) => [k, String(v).trim() || null]));
      if (loc) await api(`/locations/${loc.id}`, { method: "PATCH", body }); else await api("/locations", { method: "POST", body });
      onSaved(loc ? "Location updated." : "Location added.");
    } catch (err) { f.fail(errorMessage(err)); } finally { setBusy(false); }
  }
  async function deactivate() {
    if (!loc) return;
    setBusy(true);
    try { await api(`/locations/${loc.id}`, { method: "DELETE" }); onSaved("Location deactivated."); } catch (err) { f.fail(errorMessage(err)); } finally { setBusy(false); }
  }
  return (
    <Modal open onClose={onClose} title={loc ? "Edit location" : "Add location"} footer={<>
      {loc && canDeactivate && loc.is_active && <Button variant="danger" className="mr-auto" onClick={() => void deactivate()} disabled={busy}>Deactivate</Button>}
      <Button variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" form="loc-form" loading={busy}>Save</Button></>}>
      <form id="loc-form" onSubmit={save} noValidate className="space-y-4">
        <ErrorSummary errors={f.errors} serverError={f.serverError} summaryRef={f.summaryRef} />
        <Input label="Location name" required {...f.bind("name")} />
        <Input label="Street address" {...f.bind("address_line")} />
        <div className="grid gap-4 sm:grid-cols-2"><Input label="City" {...f.bind("city")} /><Input label="State" {...f.bind("state")} /><Input label="PIN code" inputMode="numeric" {...f.bind("postal_code")} /><Input label="Phone" type="tel" inputMode="tel" {...f.bind("phone")} /></div>
        <Input label="Google review link" inputMode="url" placeholder="https://g.page/r/…/review" hint="You can change this any time. Your printed QR/NFC cards keep working." {...f.bind("review_url")} />
      </form>
    </Modal>
  );
}
