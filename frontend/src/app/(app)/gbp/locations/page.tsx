"use client";
import clsx from "clsx";
import { ExternalLink, MapPin, Pencil, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Button, LinkButton } from "@/components/ui/Button";
import { Alert, EmptyState, ErrorState, PageHeader, Skeleton } from "@/components/ui/Card";
import { ErrorSummary, Input } from "@/components/ui/Form";
import { Status } from "@/components/ui/kit";
import { Modal } from "@/components/ui/Modal";
import { useConfirm } from "@/components/ui/Confirm";
import { useToast } from "@/components/ui/Toast";
import { ApiError, api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { CARD_STATUS } from "@/lib/card-ui";
import { timeAgo } from "@/lib/format";
import { googleUrlRule, phoneRule, required, useForm } from "@/lib/form";
import type { Card, GoogleConnection, GoogleLocation, Location } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

const COLS = "md:grid-cols-[minmax(0,1.15fr)_minmax(0,1.2fr)_minmax(0,1.35fr)_minmax(0,1fr)_auto]";

export default function LocationsPage() {
  // Google sends people back here after sign-in (and old emails link here): the connection now lives on its own page, so carry them there with the result.
  const router = useRouter();
  const sp = useSearchParams();
  useEffect(() => { if (sp.get("connected") || sp.get("error")) router.replace(`/settings/connections/google?${sp.toString()}`); }, [sp, router]);
  const { isAdmin, role } = useAuth();
  const toast = useToast();
  const { data, error, loading, reload } = useFetch<Location[]>("/locations");
  const cards = useFetch<Card[]>("/cards");
  const google = useFetch<{ configured: boolean; connections: GoogleConnection[] }>("/google/status");
  const conn = google.data?.connections.find((c) => c.status === "active");
  const gl = useFetch<GoogleLocation[]>(conn ? `/google/connections/${conn.id}/locations` : null);
  const [editing, setEditing] = useState<Location | "new" | null>(null);

  // Everything a branch needs to be healthy, computed once per row.
  const rows = (data ?? []).map((l) => {
    const g = gl.data?.find((x) => x.location_id === l.id && x.selected);
    const mine = (cards.data ?? []).filter((c) => c.location_id === l.id);
    const sync: { tone: "ok" | "warn" | "bad" | "idle"; label: string; note?: string } =
      g ? (g.last_sync_status === "ok" ? { tone: "ok", label: "Synced", note: timeAgo(g.last_synced_at) }
        : g.last_sync_status === "rate_limited" ? { tone: "warn", label: "Rate limited", note: "Google asked us to slow down. It retries automatically." }
        : g.last_sync_status ? { tone: "bad", label: "Sync error", note: g.last_sync_error ?? undefined }
        : { tone: "idle", label: "Waiting for first sync" })
      : conn ? { tone: "warn", label: "Not matched to a Google location", note: "Choose it on the Google connection page." }
      : { tone: "idle", label: "Manual link", note: "Review sync is off" };
    const attention = !l.is_active ? false : !l.review_url || sync.tone === "bad" || sync.tone === "warn" || mine.length === 0;
    return { l, g, mine, sync, attention };
  });
  const needs = rows.filter((r) => r.attention).length;
  const connected = rows.filter((r) => r.g).length;

  return (
    <>
      <PageHeader title="Locations & Google"
        subtitle={data ? `${data.length} ${data.length === 1 ? "branch" : "branches"} · ${connected} synced with Google · ${needs ? `${needs} need${needs === 1 ? "s" : ""} attention` : "all healthy"}` : "Each branch has its own cards, review link and stats."}
        actions={isAdmin ? <Button size="sm" icon={<Plus className="h-4 w-4" />} onClick={() => setEditing("new")}>Add location</Button> : undefined} />
      <Link href="/settings/connections/google" className="panel mb-6 flex min-h-[68px] items-center justify-between gap-3 p-4 hover:bg-surface-2"><span className="min-w-0"><span className="block font-semibold">Google connection</span><span className="block text-[13px] text-muted">{conn ? "Connected. Choose locations, or stop FlowQR managing your profile." : "Not connected. Connect once to sync reviews."}</span></span><span className="shrink-0 text-[13px] font-semibold text-accent-ink">Open</span></Link>
      <h2 className="mb-3 text-lg font-semibold">Your locations</h2>
      {error && <ErrorState error={error} onRetry={() => void reload()} />}
      {loading && !data ? <Skeleton className="h-48" /> : data && data.length === 0 ? (
        <EmptyState icon={<MapPin className="h-5 w-5" />} title="No locations yet" action={isAdmin ? <Button size="sm" onClick={() => setEditing("new")}>Add your first location</Button> : undefined}>Add a branch to start assigning cards and collecting reviews.</EmptyState>
      ) : (
        <section className="panel overflow-hidden" aria-label="Locations">
          <div className={clsx("hidden gap-4 border-b border-ink-100 bg-ink-50/60 px-4 py-2 text-xs font-semibold text-ink-500 md:grid", COLS)} aria-hidden>
            <span>Location</span><span>Google</span><span>Review link</span><span>Cards</span><span className="w-8" />
          </div>
          <ul className="divide-y divide-ink-100">
            {rows.map(({ l, g, mine, sync, attention }) => (
              <li key={l.id} className={clsx("relative grid gap-x-4 gap-y-2 px-4 py-3.5", COLS, !l.is_active && "opacity-60", attention && "bg-warn-tint/40")}>
                                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold">{l.name}{!l.is_active && <span className="ml-2 text-xs font-normal text-ink-500">deactivated</span>}</p>
                  <p className="truncate text-[13px] text-ink-500">{[l.address_line, l.city, l.state, l.postal_code].filter(Boolean).join(", ") || "No address"}</p>
                </div>
                <div className="min-w-0 text-[13px]">
                  <Status tone={sync.tone}>{sync.label}{sync.tone === "ok" && sync.note ? ` · ${sync.note}` : ""}</Status>
                  {sync.note && sync.tone !== "ok" && <p className="mt-0.5 line-clamp-2 text-xs text-ink-500">{sync.note}</p>}
                  {g && <p className="mt-0.5 truncate text-xs text-ink-500">{g.title}</p>}
                </div>
                <div className="min-w-0 text-[13px]">
                  {l.review_url ? (
                    <>
                      <Status tone="ok">{l.review_url_source === "google" ? "From Google" : "Configured"}</Status>
                      <a href={l.review_url} target="_blank" rel="noopener noreferrer" className="mt-0.5 flex min-h-8 items-center gap-1 truncate font-mono text-xs text-brand-700 hover:underline"><span className="truncate">{l.review_url.replace(/^https:\/\//, "")}</span><ExternalLink className="h-3 w-3 shrink-0" aria-hidden /></a>
                    </>
                  ) : (
                    <><Status tone="warn">Missing</Status><p className="mt-0.5 text-xs text-ink-500">Customers can&rsquo;t continue to Google from this branch.</p></>
                  )}
                </div>
                <div className="min-w-0 text-[13px]">
                  {mine.length === 0 ? <span className="text-ink-500">No cards assigned</span> : (
                    <ul className="flex flex-wrap gap-x-3 gap-y-0.5">{mine.map((c) => (
                      <li key={c.id}><Link href={`/gbp/cards/${c.id}`} className="inline-flex items-center gap-1.5 hover:underline" title={`${c.card_code}: ${CARD_STATUS[c.status].label}`}>
                        <span aria-hidden className={clsx("h-1.5 w-1.5 rounded-full", c.status === "active" ? "bg-ok" : c.status === "assigned" ? "bg-brand-600" : "bg-ink-300")} /><span className="card-code text-xs">{c.card_code}</span></Link></li>))}</ul>
                  )}
                </div>
                <div className="flex items-start justify-end">{isAdmin && <Button variant="ghost" size="sm" aria-label={`Edit ${l.name}`} onClick={() => setEditing(l)} icon={<Pencil className="h-3.5 w-3.5" />} />}</div>
              </li>
            ))}
          </ul>
        </section>
      )}
      {editing && <LocationModal loc={editing === "new" ? null : editing} canDeactivate={role === "owner"} onClose={() => setEditing(null)} onSaved={(m) => { setEditing(null); toast(m); void reload(); }} />}
    </>
  );
}

function LocationModal({ loc, onClose, onSaved, canDeactivate }: { loc: Location | null; onClose: () => void; onSaved: (msg: string) => void; canDeactivate: boolean }) {
  const confirm = useConfirm();
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
  async function deactivate(confirmed = false) {
    if (!loc) return;
    setBusy(true);
    try { await api(`/locations/${loc.id}`, { method: "DELETE", params: confirmed ? { confirm: "true" } : undefined }); onSaved(confirmed ? "Location deactivated. Codes that lead to it now show an inactive page." : "Location deactivated."); }
    catch (err) {
      // The server refuses to switch off a location that live printed codes lead to unless we say we mean it.
      if (!confirmed && err instanceof ApiError && err.code === "codes_would_stop") {
        setBusy(false);
        if (await confirm({ title: "Deactivate this location anyway?", body: err.message, confirmLabel: "Deactivate anyway" })) return deactivate(true);
        return;
      }
      f.fail(errorMessage(err));
    } finally { setBusy(false); }
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
