"use client";
import { Check } from "lucide-react";
import { useEffect, useState } from "react";
import { AddBusinessForm, type CreatedBusiness } from "@/components/admin/AddBusinessForm";
import { Select } from "@/components/ui/Form";
import { Segmented } from "@/components/ui/kit";
import { useFetch } from "@/lib/use-api";

interface Opt { id: string; name: string; city?: string | null; location_id?: string | null; status?: string; is_active?: boolean }
interface Row { id: string; name: string; city?: string | null; phone?: string | null; origin?: string }

/**
 * Choose where a card goes, without leaving the inventory screen: an EXISTING business (searchable) or a NEW one created on the spot.
 * Creating a business here saves it and its first location, then selects both so the assignment can continue. No login is created for the shopkeeper.
 */
export interface PickedNames { business?: string; location?: string; campaign?: string }

export function BusinessPicker({ tenant, loc, campaign, onTenant, onLoc, onCampaign, onNames }: { tenant: string; loc: string; campaign: string; onTenant: (id: string) => void; onLoc: (id: string) => void; onCampaign: (id: string) => void; onNames?: (n: PickedNames) => void }) {
  const [tab, setTab] = useState<"existing" | "new">("existing");
  const [q, setQ] = useState(""), [search, setSearch] = useState("");
  const [created, setCreated] = useState<string | null>(null);
  useEffect(() => { const t = setTimeout(() => setSearch(q), 250); return () => clearTimeout(t); }, [q]);
  const list = useFetch<{ items: Row[] }>("/admin/tenants", { search, limit: 50 });
  const locs = useFetch<Opt[]>(tenant ? `/admin/tenants/${tenant}/locations` : null);
  const camps = useFetch<Opt[]>(tenant ? `/admin/tenants/${tenant}/campaigns` : null);
  const items = list.data?.items ?? [];
  const known = items.some((t) => t.id === tenant);
  const campaigns = (camps.data ?? []).filter((c) => c.status !== "archived" && (!c.location_id || c.location_id === loc));
  const [business, location, campName] = [items.find((t) => t.id === tenant)?.name ?? (tenant ? created ?? undefined : undefined), (locs.data ?? []).find((l) => l.id === loc)?.name, campaigns.find((c) => c.id === campaign)?.name];
  useEffect(() => { onNames?.({ business, location, campaign: campName }); }, [business, location, campName]); // eslint-disable-line react-hooks/exhaustive-deps

  function done(b: CreatedBusiness) {
    setCreated(b.name); setTab("existing"); setQ(""); setSearch(""); void list.reload();
    onTenant(b.id); onLoc(b.location.id); onCampaign("");
  }

  return (
    <div className="space-y-4">
      <Segmented<"existing" | "new"> label="Business" value={tab} onChange={(v) => { setTab(v); setCreated(null); }} options={[["existing", "Existing business"], ["new", "New business"]]} className="w-full [&>button]:flex-1" />
      {tab === "new" ? (
        <AddBusinessForm compact onCreated={done} onCancel={() => setTab("existing")} />
      ) : (
        <>
          {created && <p className="flex items-center gap-2 rounded-xl bg-pos-tint px-3 py-2 text-sm text-pos"><Check className="h-4 w-4 shrink-0" aria-hidden />{created} was created and selected. Continue below.</p>}
          <label className="block"><span className="mb-1.5 block text-sm font-medium text-ink">Find a business</span>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, city or phone" className="min-h-11 w-full rounded-full border border-transparent bg-surface-2 px-4 text-base outline-none placeholder:text-muted-soft hover:border-ink-200 focus-visible:border-accent sm:text-sm" /></label>
          <Select label="Business" value={tenant} onChange={(e) => { onTenant(e.target.value); onLoc(""); onCampaign(""); setCreated(null); }}>
            <option value="">Choose a business…</option>
            {!known && tenant && <option value={tenant}>{created ?? "Selected business"}</option>}
            {items.map((t) => <option key={t.id} value={t.id}>{t.name}{t.city ? ` · ${t.city}` : ""}{t.origin === "admin" ? " (no login)" : ""}</option>)}
          </Select>
          <Select label="Location" value={loc} disabled={!tenant} onChange={(e) => { onLoc(e.target.value); onCampaign(""); }}>
            <option value="">Choose a location…</option>{(locs.data ?? []).filter((l) => l.is_active !== false).map((l) => <option key={l.id} value={l.id}>{l.name}{l.city ? ` · ${l.city}` : ""}</option>)}
          </Select>
          <Select label="Review campaign" value={campaign} disabled={!loc} onChange={(e) => onCampaign(e.target.value)}>
            <option value="">Plain review page</option>{campaigns.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </Select>
        </>
      )}
    </div>
  );
}
