"use client";
import { ArrowDown, ArrowUp, ChevronDown, ChevronRight, ImagePlus, Plus, Trash2 } from "lucide-react";
import { useRef, useState } from "react";
import { FieldEditor, Thumb, type EditorCtx } from "@/components/admin/site/FieldEditor";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, CardHeader } from "@/components/ui/Card";
import { controlClass, Input, invalidClass, Select, Textarea } from "@/components/ui/Form";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { addableSections, blankItem, CTA_LABEL, charsLeft, hasErrorUnder, moveItem, newSectionId, setPath, type Catalogue, type Cta, type SiteContent, type SiteInfo } from "@/lib/sites";

interface PanelProps { cat: Catalogue; draft: SiteContent; set: (next: SiteContent) => void; ctx: EditorCtx }

// ---------------------------------------------------------------------------------------------------------------- business details, hours and buttons
export function DetailsPanel({ cat, draft, set, ctx }: PanelProps) {
  const upd = (key: string) => (v: unknown) => set(setPath(draft, `business.${key}`, v));
  const cta = (which: "primary" | "secondary", next: Cta | null) => set({ ...draft, cta: { ...draft.cta, [which]: next } });
  return (
    <div className="space-y-5">
      <Card><CardHeader title="Business details" />
        <p className="mb-4 text-sm text-muted">These come from the business record and fill the website. Changing them here changes the website only, not the business record.</p>
        <div className="space-y-4">
          {cat.business_fields.map((f) => <FieldEditor key={f.key} spec={f} value={draft.business[f.key]} onChange={upd(f.key)} ctx={ctx} path={`business.${f.key}`} />)}
        </div>
      </Card>
      <Card><CardHeader title="Opening hours" />
        <p className="mb-3 text-sm text-muted">Use the 24-hour format, for example 09:00 and 18:00. Leave both empty to hide a day.</p>
        <div className="space-y-2">
          {draft.business.hours.map((h, i) => (
            <div key={h.day} className="grid grid-cols-[6.5rem_1fr_1fr_auto] items-center gap-2">
              <span className="text-sm font-medium">{h.day}</span>
              <input aria-label={`${h.day} opens`} aria-invalid={!!ctx.errors[`business.hours[${i}].open`]} inputMode="numeric" placeholder="09:00" maxLength={5} value={h.open} disabled={h.closed} className={`${controlClass} ${ctx.errors[`business.hours[${i}].open`] ? invalidClass : ""}`}
                     onChange={(e) => set(setPath(draft, `business.hours[${i}].open`, e.target.value))} />
              <input aria-label={`${h.day} closes`} aria-invalid={!!ctx.errors[`business.hours[${i}].close`]} inputMode="numeric" placeholder="18:00" maxLength={5} value={h.close} disabled={h.closed} className={`${controlClass} ${ctx.errors[`business.hours[${i}].close`] ? invalidClass : ""}`}
                     onChange={(e) => set(setPath(draft, `business.hours[${i}].close`, e.target.value))} />
              <label className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" className="h-5 w-5" checked={h.closed} onChange={(e) => set(setPath(draft, `business.hours[${i}].closed`, e.target.checked))} />Closed</label>
            </div>
          ))}
        </div>
      </Card>
      <Card><CardHeader title="Buttons" />
        <p className="mb-4 text-sm text-muted">The main button appears in the header, the first screen and a bar at the bottom on phones.</p>
        {(["primary", "secondary"] as const).map((w) => {
          const c = draft.cta[w];
          return (
            <div key={w} className="mb-4 grid gap-3 sm:grid-cols-2">
              <Select label={w === "primary" ? "Main button does" : "Second button does"} value={c?.kind ?? ""} onChange={(e) => cta(w, e.target.value ? { kind: e.target.value, label: c?.label ?? "" } : null)}>
                {w === "secondary" && <option value="">No second button</option>}
                {cat.cta_kinds.map((k) => <option key={k} value={k}>{CTA_LABEL[k] ?? k}</option>)}
              </Select>
              {c && <Input label="Button text" value={c.label} onChange={(e) => cta(w, { ...c, label: e.target.value })} hint={`${charsLeft(c.label, 30)} characters left`} error={ctx.errors[`cta.${w}.label`]} />}
            </div>
          );
        })}
        <Select label="Accent colour" value={draft.theme.accent} onChange={(e) => set({ ...draft, theme: { accent: e.target.value } })} hint="Every colour is chosen to be readable with white text.">
          {Object.keys(cat.accents).map((k) => <option key={k} value={k}>{k[0].toUpperCase() + k.slice(1)}</option>)}
        </Select>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------------- sections
export function SectionsPanel({ cat, draft, set, ctx, template }: PanelProps & { template: string }) {
  const [open, setOpen] = useState<string | null>(null);
  const [adding, setAdding] = useState("");
  const tpl = cat.templates.find((t) => t.key === template)!;
  const secs = draft.sections;
  const canAdd = addableSections(tpl.allowed_sections, secs, cat.max_sections);
  const put = (next: typeof secs) => set({ ...draft, sections: next });
  return (
    <div className="space-y-3">
      <Alert tone="info">Sections appear on the page in this order. Turn a section off to hide it without losing what you wrote. Every section that is on needs content before the site can be published.</Alert>
      <ul className="space-y-2">
        {secs.map((s, i) => {
          const spec = cat.section_types[s.type];
          const isOpen = open === s.id;
          const bad = hasErrorUnder(ctx.errors, `sections[${i}]`);
          return (
            <li key={s.id} className="rounded-2xl border border-line bg-surface" data-testid="section-row">
              <div className="flex flex-wrap items-center gap-2 p-3">
                <button type="button" className="flex min-h-11 flex-1 items-center gap-2 text-left font-semibold" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : s.id)}>
                  {isOpen ? <ChevronDown className="h-4 w-4" aria-hidden /> : <ChevronRight className="h-4 w-4" aria-hidden />}{spec.label}
                  {!s.enabled && <Badge tone="gray">off</Badge>}{bad && <Badge tone="red">needs attention</Badge>}
                </button>
                <label className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" className="h-5 w-5" checked={s.enabled} onChange={(e) => put(secs.map((x, j) => (j === i ? { ...x, enabled: e.target.checked } : x)))} />Show</label>
                <Button size="sm" variant="secondary" aria-label={`Move ${spec.label} up`} disabled={i === 0} icon={<ArrowUp className="h-3.5 w-3.5" />} onClick={() => put(moveItem(secs, i, i - 1))} />
                <Button size="sm" variant="secondary" aria-label={`Move ${spec.label} down`} disabled={i === secs.length - 1} icon={<ArrowDown className="h-3.5 w-3.5" />} onClick={() => put(moveItem(secs, i, i + 1))} />
                <Button size="sm" variant="secondary" aria-label={`Remove ${spec.label}`} icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => { if (confirm(`Remove the ${spec.label} section and everything in it?`)) put(secs.filter((_, j) => j !== i)); }} />
              </div>
              {isOpen && (
                <div className="space-y-4 border-t border-line p-4">
                  {spec.fields.map((f) => <FieldEditor key={f.key} spec={f} value={s.data[f.key]} ctx={ctx} path={`sections[${i}].data.${f.key}`}
                                                       onChange={(v) => put(secs.map((x, j) => (j === i ? { ...x, data: { ...x.data, [f.key]: v } } : x)))} />)}
                </div>
              )}
            </li>
          );
        })}
      </ul>
      <div className="flex flex-wrap items-end gap-3">
        <Select label="Add a section" wrapperClassName="min-w-[14rem]" value={adding} onChange={(e) => setAdding(e.target.value)} disabled={!canAdd.length}>
          <option value="">{canAdd.length ? "Choose…" : "Nothing more to add"}</option>
          {canAdd.map((t) => <option key={t} value={t}>{cat.section_types[t].label}</option>)}
        </Select>
        <Button variant="secondary" icon={<Plus className="h-4 w-4" />} disabled={!adding} onClick={() => {
          const id = newSectionId(secs.map((s) => s.id));
          put([...secs, { id, type: adding, enabled: true, data: blankItem(cat.section_types[adding].fields) }]);
          setOpen(id); setAdding("");
        }}>Add section</Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------------- images
export function ImagesPanel({ site, reload, readOnly }: { site: SiteInfo; reload: () => Promise<unknown> | void; readOnly: boolean }) {
  const toast = useToast();
  const file = useRef<HTMLInputElement>(null);
  const [alt, setAlt] = useState(""), [kind, setKind] = useState<"photo" | "logo">("photo"), [busy, setBusy] = useState(false);
  async function upload(f: File) {
    setBusy(true);
    try {
      const r = await api<{ created: boolean }>(`/admin/sites/${site.id}/assets`, { method: "POST", raw: f, params: { kind, alt_text: alt || undefined } });
      toast(r.created ? "Image added." : "That image was already in the library."); setAlt(""); await reload();
    } catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(false); if (file.current) file.current.value = ""; }
  }
  const patch = async (id: string, body: Record<string, unknown>, msg: string) => { try { await api(`/admin/sites/${site.id}/assets/${id}`, { method: "PATCH", body }); toast(msg); await reload(); } catch (e) { toast(errorMessage(e), "error"); } };
  return (
    <div className="space-y-5">
      <Card><CardHeader title="Add an image" />
        <p className="mb-4 text-sm text-muted">JPEG, PNG or WebP, up to 8 MB. Each image is resized and cleaned of location and camera details before it is used. SVG and other types are not accepted.</p>
        <div className="grid gap-3 sm:grid-cols-[1fr_10rem]">
          <Input label="Description for people who cannot see it (alt text)" value={alt} onChange={(e) => setAlt(e.target.value)} hint="For example: The reception desk with two chairs. Required before publishing." />
          <Select label="Use as" value={kind} onChange={(e) => setKind(e.target.value as "photo" | "logo")}><option value="photo">Photo</option><option value="logo">Logo</option></Select>
        </div>
        <input ref={file} type="file" accept="image/jpeg,image/png,image/webp" className="sr-only" aria-label="Choose an image" disabled={readOnly || busy} onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); }} />
        <Button className="mt-4" icon={<ImagePlus className="h-4 w-4" />} loading={busy} disabled={readOnly} onClick={() => file.current?.click()}>Choose an image</Button>
        <p className="mt-2 text-xs text-muted">{site.assets.length} of 24 images used.</p>
      </Card>
      {site.assets.length === 0 ? <Alert tone="info">No images yet. A website works without them, but photos make it far more convincing.</Alert> : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {site.assets.map((a, i) => (
            <li key={a.id} className="rounded-2xl border border-line p-3" data-testid="asset-row">
              <div className="flex gap-3"><Thumb siteId={site.id} asset={a} size={72} />
                <div className="min-w-0 flex-1 text-sm"><p className="font-semibold">Image {i + 1} {a.kind === "logo" && <Badge tone="blue">logo</Badge>}</p><p className="text-muted">{a.width} × {a.height} · {Math.round(a.size_bytes / 1024)} KB</p></div></div>
              <Textarea label="Alt text" rows={2} defaultValue={a.alt_text} onBlur={(e) => { if (e.target.value !== a.alt_text) void patch(a.id, { alt_text: e.target.value }, "Alt text saved."); }} error={!a.alt_text ? "Needed before publishing" : undefined} />
              <Button className="mt-2" size="sm" variant="danger" icon={<Trash2 className="h-3.5 w-3.5" />} disabled={readOnly} onClick={async () => {
                if (!confirm("Delete this image? It is removed from the draft. A website that is already live keeps showing it until you publish again.")) return;
                try { await api(`/admin/sites/${site.id}/assets/${a.id}`, { method: "DELETE" }); toast("Image deleted. Save is not needed; reload to see the draft."); await reload(); } catch (e) { toast(errorMessage(e), "error"); }
              }}>Delete</Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------------- search settings
export function SeoPanel({ draft, set, ctx, host }: { draft: SiteContent; set: (next: SiteContent) => void; ctx: EditorCtx; host: string }) {
  const seo = draft.seo;
  const upd = (k: string, v: unknown) => set({ ...draft, seo: { ...seo, [k]: v } });
  return (
    <Card><CardHeader title="Search and sharing" />
      <div className="space-y-4">
        <Input label="Page title" value={seo.title} onChange={(e) => upd("title", e.target.value)} error={ctx.errors["seo.title"]} hint={`${charsLeft(seo.title, 70)} characters left. Shown in search results and browser tabs.`} />
        <Textarea label="Description" rows={3} value={seo.description} onChange={(e) => upd("description", e.target.value)} error={ctx.errors["seo.description"]} hint={`${charsLeft(seo.description, 160)} characters left. Shown under the title in search results.`} />
        <FieldEditor spec={{ key: "og_image", label: "Image for sharing links (optional)", kind: "asset", hint: "Shown when the link is shared on WhatsApp or social media." }} value={seo.og_image} onChange={(v) => upd("og_image", v)} ctx={ctx} path="seo.og_image" />
      </div>
      <div className="mt-5 rounded-2xl bg-surface-2 p-4 text-sm" aria-label="How it may look in search results">
        <p className="text-xs text-muted">https://{host}/</p>
        <p className="mt-1 text-base font-semibold text-accent">{seo.title || "Page title"}</p>
        <p className="mt-1 text-muted">{seo.description || "Description"}</p>
      </div>
      <p className="mt-4 text-xs text-muted">Good titles and descriptions help people understand the website. They do not guarantee any position in Google search, and FlowQR does not promise one.</p>
    </Card>
  );
}
