"use client";
import clsx from "clsx";
import { Palette, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { LandingFrame, PreviewForm } from "@/components/review-growth/LandingFrame";
import { useSelectedCampaign } from "@/components/review-growth/shared";
import { Button, LinkButton } from "@/components/ui/Button";
import { Alert, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { FilterSelect, Input, Textarea } from "@/components/ui/Form";
import { Panel, Segmented } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { BACKGROUNDS, BRAND_PRESETS, DEFAULT_CUSTOMIZATION, onBrand, type Campaign, type Customization } from "@/lib/review-growth";

const HEX = /^#[0-9a-fA-F]{6}$/;

export default function CustomizePage() {
  const { isAdmin, tenant } = useAuth();
  const toast = useToast();
  const { campaigns, selected, loading, choose, reload } = useSelectedCampaign();
  const [cz, setCz] = useState<Customization>(DEFAULT_CUSTOMIZATION);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { if (selected) { setCz(selected.customization); setError(null); } }, [selected?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const set = <K extends keyof Customization>(k: K, v: Customization[K]) => setCz((p) => ({ ...p, [k]: v }));
  const colorOk = HEX.test(cz.brand_color);
  const dirty = !!selected && JSON.stringify(cz) !== JSON.stringify(selected.customization);
  const text = (v: string) => v.trim() || null;

  async function save() {
    if (!selected || !colorOk) return;
    setBusy(true); setError(null);
    try {
      await api<Campaign>(`/review-growth/campaigns/${selected.id}`, { method: "PATCH", body: { customization: { ...cz, display_name: text(cz.display_name ?? ""), logo_url: text(cz.logo_url ?? ""), welcome_message: text(cz.welcome_message ?? ""), footer_message: text(cz.footer_message ?? "") } } });
      toast("Landing page saved."); await reload();
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }

  return (
    <>
      <PageHeader title="Page design" subtitle="Make the page customers see match your brand. Changes show in the preview straight away."
        actions={campaigns.length > 0 && selected ? <FilterSelect label="Campaign" value={selected.id} onChange={(e) => choose(e.target.value)}>{campaigns.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</FilterSelect> : undefined} />
      {loading && !campaigns.length ? <Skeleton className="h-96" /> : !selected ? (
        <EmptyState icon={<Palette className="h-5 w-5" />} title="Create a campaign to customize its page"
          action={<LinkButton href="/gbp/campaigns?new=1" size="sm" icon={<Plus className="h-4 w-4" />}>New campaign</LinkButton>}>Each campaign has its own look, so you can brand each place differently.</EmptyState>
      ) : (
        <div className="grid gap-5 lg:grid-cols-[1fr_340px]">
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); void save(); }} noValidate>
            {!isAdmin && <Alert tone="info">Only owners and admins can change the landing page.</Alert>}
            {error && <Alert tone="error" title="Couldn't save">{error}</Alert>}
            <fieldset disabled={!isAdmin || busy} className="space-y-4">
              <Panel title="Identity" meta="shown at the top of the page">
                <div className="space-y-4">
                  <Input label="Business name shown to customers" placeholder="Defaults to your business name" maxLength={120} value={cz.display_name ?? ""} onChange={(e) => set("display_name", e.target.value)} />
                  <Input label="Logo link" inputMode="url" placeholder="https://…/logo.png" maxLength={500} value={cz.logo_url ?? ""} onChange={(e) => set("logo_url", e.target.value)}
                    hint="An https link to an image you own. Leave empty to show your business initial." error={cz.logo_url && !cz.logo_url.startsWith("https://") ? "Logo link must start with https://" : undefined} />
                </div>
              </Panel>
              <Panel title="Brand colour" meta="buttons and accents; text colour adjusts automatically">
                <div className="flex flex-wrap items-center gap-2" role="radiogroup" aria-label="Brand colour presets">
                  {BRAND_PRESETS.map((c) => (
                    <button key={c} type="button" role="radio" aria-checked={cz.brand_color.toUpperCase() === c} aria-label={`Use ${c}`} onClick={() => set("brand_color", c)}
                      className={clsx("grid h-11 w-11 place-items-center rounded-full ring-offset-2 transition sm:h-9 sm:w-9", cz.brand_color.toUpperCase() === c ? "ring-2 ring-ink" : "ring-1 ring-ink-200 hover:ring-ink-400")} style={{ background: c }}>
                      {cz.brand_color.toUpperCase() === c && <span className="h-2 w-2 rounded-full" style={{ background: onBrand(c) }} />}</button>))}
                  <label className="ml-1 flex items-center gap-2 text-[13px] font-medium text-ink-700">Custom
                    <input type="color" value={colorOk ? cz.brand_color : "#1B46B8"} onChange={(e) => set("brand_color", e.target.value.toUpperCase())} aria-label="Pick a custom colour" className="h-11 w-11 cursor-pointer rounded-lg border border-ink-300 bg-white p-1 sm:h-9 sm:w-9" /></label>
                  <Input label="Hex" wrapperClassName="w-28" maxLength={7} value={cz.brand_color} onChange={(e) => set("brand_color", e.target.value)} error={colorOk ? undefined : "Use #RRGGBB"} />
                </div>
              </Panel>
              <Panel title="Messages">
                <div className="space-y-4">
                  <Textarea label="Welcome message" rows={2} maxLength={200} placeholder="e.g. Thanks for visiting us today!" value={cz.welcome_message ?? ""} onChange={(e) => set("welcome_message", e.target.value)} hint={`${(cz.welcome_message ?? "").length}/200. Don't offer rewards or discounts for reviews.`} className="min-h-[72px]" />
                  <Textarea label="Footer message" rows={2} maxLength={200} placeholder="e.g. Open Mon–Sat, 9am–7pm" value={cz.footer_message ?? ""} onChange={(e) => set("footer_message", e.target.value)} hint={`${(cz.footer_message ?? "").length}/200`} className="min-h-[72px]" />
                </div>
              </Panel>
              <Panel title="Background">
                <Segmented label="Background style" value={cz.background} onChange={(v) => set("background", v)} options={BACKGROUNDS} />
              </Panel>
            </fieldset>
            {isAdmin && <div className="flex items-center justify-end gap-3">
              {dirty && <span className="text-sm text-ink-500">Unsaved changes</span>}
              <Button type="button" variant="secondary" disabled={!dirty || busy} onClick={() => setCz(selected.customization)}>Reset</Button>
              <Button type="submit" loading={busy} disabled={!dirty || !colorOk}>Save landing page</Button>
            </div>}
          </form>

          <aside aria-label="Live preview" className="lg:sticky lg:top-6 lg:self-start">
            <p className="mb-2 text-[13px] font-medium text-ink-500">Live preview</p>
            <div className="mx-auto h-[560px] w-[300px] overflow-y-auto overflow-x-hidden rounded-[30px] border-[7px] border-ink bg-white shadow-float">
              <LandingFrame preview business={{ name: cz.display_name || tenant?.name || "Your business", logo_url: cz.logo_url?.startsWith("https://") ? cz.logo_url : tenant?.logo_url ?? null, location: selected.location_name }}
                branding={{ brand_color: colorOk ? cz.brand_color : "#1B46B8", background: cz.background, welcome_message: cz.welcome_message, footer_message: cz.footer_message }}>
                <PreviewForm />
              </LandingFrame>
            </div>
          </aside>
        </div>
      )}
    </>
  );
}
