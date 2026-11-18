"use client";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input, Select, Textarea } from "@/components/ui/Form";
import { API_V1 } from "@/lib/config";
import { blankItem, charsLeft, moveItem, type FieldSpec, type SiteAssetInfo } from "@/lib/sites";

export interface EditorCtx { siteId: string; assets: SiteAssetInfo[]; errors: Record<string, string> }

const KIND_HINT: Record<string, string> = { phone: "A 10-digit mobile number, e.g. 98765 43210", url: "Starts with https://", email: "name@example.com" };

/** The thumbnail of an uploaded image (served to signed-in administrators only). */
export function Thumb({ siteId, asset, size = 56 }: { siteId: string; asset: SiteAssetInfo; size?: number }) {
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={`${API_V1}/admin/sites/${siteId}/assets/${asset.id}/file`} alt={asset.alt_text || "Uploaded image without a description"} width={size} height={size} className="rounded-lg object-cover" style={{ width: size, height: size }} />;
}

function AssetPick({ spec, value, onChange, ctx, error }: { spec: FieldSpec; value: string | null; onChange: (v: string | null) => void; ctx: EditorCtx; error?: string }) {
  const cur = ctx.assets.find((a) => a.id === value);
  return (
    <div className="flex items-end gap-3">
      <Select className="flex-1" wrapperClassName="flex-1" label={spec.label} hint={ctx.assets.length ? spec.hint ?? undefined : "Upload an image in the Images tab first."} error={error} value={value ?? ""} onChange={(e) => onChange(e.target.value || null)}>
        <option value="">None</option>
        {ctx.assets.map((a, i) => <option key={a.id} value={a.id}>{`Image ${i + 1}${a.kind === "logo" ? " (logo)" : ""}: ${a.alt_text || "no description yet"}`.slice(0, 80)}</option>)}
      </Select>
      {cur && <Thumb siteId={ctx.siteId} asset={cur} />}
    </div>
  );
}

/** One field of a section, business block or list item, drawn from its spec. `path` is the field's address in the content, used to show the server's error next to it. */
export function FieldEditor({ spec, value, onChange, ctx, path }: { spec: FieldSpec; value: unknown; onChange: (v: unknown) => void; ctx: EditorCtx; path: string }) {
  const error = ctx.errors[path];
  const label = spec.required ? `${spec.label}` : spec.label;
  const counter = spec.max && (spec.kind === "text" || spec.kind === "textarea") ? `${charsLeft(value as string, spec.max)} characters left` : undefined;
  switch (spec.kind) {
    case "text": case "phone": case "email": case "url":
      return <Input label={label} required={spec.required} value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)} error={error} hint={[spec.hint, KIND_HINT[spec.kind], counter].filter(Boolean)[0] ?? undefined}
                    inputMode={spec.kind === "phone" ? "tel" : undefined} autoComplete="off" />;
    case "textarea":
      return <Textarea label={label} required={spec.required} rows={4} value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)} error={error} hint={spec.hint ?? counter} />;
    case "bool":
      return (
        <label className="flex min-h-11 items-center gap-3 text-sm font-medium"><input type="checkbox" className="h-5 w-5" checked={!!value} onChange={(e) => onChange(e.target.checked)} />{spec.label}</label>
      );
    case "select":
      return <Select label={label} value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)} error={error}>{spec.options!.map((o) => <option key={o} value={o}>{o === "" ? "None" : o === "veg" ? "Vegetarian" : o === "nonveg" ? "Non-vegetarian" : o === "egg" ? "Contains egg" : o}</option>)}</Select>;
    case "asset":
      return <AssetPick spec={spec} value={(value as string | null) ?? null} onChange={onChange} ctx={ctx} error={error} />;
    case "strings":
      return (
        <Textarea label={spec.label} rows={4} hint={`One per line. Up to ${spec.max_items} entries of ${spec.max ?? 60} characters.`} error={error}
                  value={((value as string[]) ?? []).join("\n")} onChange={(e) => onChange(e.target.value.split("\n").slice(0, spec.max_items))} />
      );
    case "list": {
      const items = (value as Record<string, unknown>[]) ?? [];
      const set = (next: Record<string, unknown>[]) => onChange(next);
      return (
        <fieldset className="space-y-3">
          <legend className="mb-1 text-sm font-semibold">{spec.label} <span className="font-normal text-muted">({items.length} of {spec.max_items})</span></legend>
          {spec.hint && <p className="text-sm text-muted">{spec.hint}</p>}
          {error && <p role="alert" className="text-sm text-neg">{error}</p>}
          {items.map((item, i) => (
            <div key={i} className="rounded-2xl border border-line p-4" data-testid="list-item">
              <div className="mb-3 flex items-center justify-between gap-2">
                <span className="text-xs font-semibold uppercase tracking-wide text-muted">{spec.label.replace(/s$/, "")} {i + 1}</span>
                <span className="flex gap-1">
                  <Button size="sm" variant="secondary" aria-label="Move up" disabled={i === 0} icon={<ArrowUp className="h-3.5 w-3.5" />} onClick={() => set(moveItem(items, i, i - 1))} />
                  <Button size="sm" variant="secondary" aria-label="Move down" disabled={i === items.length - 1} icon={<ArrowDown className="h-3.5 w-3.5" />} onClick={() => set(moveItem(items, i, i + 1))} />
                  <Button size="sm" variant="secondary" aria-label="Remove" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => set(items.filter((_, j) => j !== i))} />
                </span>
              </div>
              <div className="space-y-3">
                {spec.fields!.map((f) => <FieldEditor key={f.key} spec={f} value={item[f.key]} ctx={ctx} path={`${path}[${i}].${f.key}`} onChange={(v) => set(items.map((x, j) => (j === i ? { ...x, [f.key]: v } : x)))} />)}
              </div>
            </div>
          ))}
          <Button size="sm" variant="secondary" icon={<Plus className="h-3.5 w-3.5" />} disabled={items.length >= (spec.max_items ?? 0)} onClick={() => set([...items, blankItem(spec.fields!)])}>Add {spec.label.toLowerCase().replace(/s$/, "")}</Button>
        </fieldset>
      );
    }
    default:
      return null;
  }
}
