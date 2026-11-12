"use client";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Card";
import { Select, Textarea } from "@/components/ui/Form";
import { Panel } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import type { ContextResp, Lang } from "@/lib/review-growth";

const LANGS: { v: Lang; label: string }[] = [{ v: "en", label: "English" }, { v: "hi", label: "हिन्दी (Hindi)" }];
const checkbox = "h-5 w-5 shrink-0 rounded border-ink-300";

/** Owner-configured business context: what the business offers. Never treated as evidence of what a customer experienced. */
export function BusinessContext({ canEdit }: { canEdit: boolean }) {
  const toast = useToast();
  const [ctx, setCtx] = useState<ContextResp | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [category, setCategory] = useState("");            // "" = detect from the business category
  const [description, setDescription] = useState("");
  const [services, setServices] = useState("");            // one per line
  const [languages, setLanguages] = useState<Lang[]>(["en", "hi"]);
  const [off, setOff] = useState<string[]>([]);            // disabled suggestion ids
  const [dirty, setDirty] = useState(false);
  const seq = useRef(0);

  function apply(c: ContextResp, keepEdits = false) {
    setCtx(c);
    if (keepEdits) return;
    setCategory(c.category_override ?? ""); setDescription(c.description); setServices(c.services.join("\n"));
    setLanguages(c.languages); setOff(c.suggestions.filter((s) => !s.enabled).map((s) => s.id)); setDirty(false);
  }
  useEffect(() => { api<ContextResp>("/review-growth/context").then((c) => apply(c)).catch((e) => setErr(errorMessage(e))); }, []);

  /** Changing the category previews that category's topics without saving. */
  async function pickCategory(v: string) {
    setCategory(v); setDirty(true);
    const mine = ++seq.current;
    try {
      const c = await api<ContextResp>("/review-growth/context", { params: { preview_category: v || ctx?.detected_category || "" } });
      if (mine === seq.current) { setCtx(c); setOff([]); }
    } catch { /* keep the previous list; saving still validates */ }
  }

  const list = services.split("\n").map((s) => s.trim()).filter(Boolean);
  const toggleLang = (l: Lang) => { setDirty(true); setLanguages((p) => (p.includes(l) ? p.filter((x) => x !== l) : [...p, l])); };
  const toggleTopic = (id: string) => { setDirty(true); setOff((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id])); };

  async function save() {
    setSaving(true); setErr(null);
    try {
      const c = await api<ContextResp>("/review-growth/context", { method: "PUT", body: { category_key: category || null, description: description.trim() || null, services: list, disabled_suggestions: off, languages } });
      apply(c); toast("Business context saved.");
    } catch (e) { setErr(errorMessage(e)); } finally { setSaving(false); }
  }

  if (!ctx) return <Panel title="Business context">{err ? <Alert tone="error">{err}</Alert> : <div className="fq-skeleton h-40" aria-busy="true" />}</Panel>;
  const enabledCount = ctx.suggestions.filter((s) => !off.includes(s.id)).length;

  return (
    <Panel title="Business context" meta="what customers can pick from, and what the AI knows you offer">
      <fieldset disabled={!canEdit || saving} className="space-y-5">
        <Select label="Business type" value={category} onChange={(e) => void pickCategory(e.target.value)}
          hint={`Detected from your business category${ctx.tenant_category ? ` (${ctx.tenant_category})` : ""}: ${ctx.categories.find((c) => c.key === ctx.detected_category)?.label ?? ctx.detected_category}. Pick another to choose a different set of topics.`}>
          <option value="">Detect automatically</option>
          {ctx.categories.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
        </Select>

        <div>
          <Textarea label="What you do (optional)" rows={3} maxLength={ctx.limits.description} value={description} placeholder="e.g. Exercise-based physiotherapy clinic for back and neck pain."
            onChange={(e) => { setDescription(e.target.value); setDirty(true); }} className="!min-h-[84px]" hint="Plain facts only. Claims like “best”, guarantees, cures, prices or links are not accepted." />
          <p className="mt-1 text-right text-xs text-ink-500"><span className="num">{description.length}/{ctx.limits.description}</span></p>
        </div>

        <Textarea label="Services or products (one per line, optional)" rows={4} value={services} placeholder={"Back pain rehabilitation\nSports injury rehabilitation"}
          onChange={(e) => { setServices(e.target.value); setDirty(true); }} className="!min-h-[104px]"
          hint={`${list.length}/${ctx.limits.services} listed. Tells the AI what you offer. A customer's draft only mentions one if they brought it up.`} />

        <div>
          <p id="bc-topics" className="mb-0.5 text-[13px] font-medium text-ink-700">Topics customers can choose ({enabledCount} of {ctx.suggestions.length} shown)</p>
          <p className="mb-2 text-sm text-ink-500">Customers pick what applies and say if it was good, okay or not good. Topics are never claims about your business.</p>
          <ul className="grid gap-1.5 sm:grid-cols-2">
            {ctx.suggestions.map((s) => (
              <li key={s.id}>
                <label className="flex min-h-11 cursor-pointer items-center gap-3 rounded-lg border border-ink-200 bg-white px-3 py-2 text-sm hover:bg-ink-50 sm:min-h-10">
                  <input type="checkbox" className={checkbox} checked={!off.includes(s.id)} onChange={() => toggleTopic(s.id)} />
                  <span className="flex-1">{s.en}<span lang="hi" className="ml-2 text-ink-500">{s.hi}</span></span>
                </label>
              </li>))}
          </ul>
          {enabledCount === 0 && <p className="mt-2 text-sm text-ink-500">With every topic off, customers see only the text box.</p>}
        </div>

        <div role="group" aria-labelledby="bc-langs">
          <p id="bc-langs" className="mb-1 text-[13px] font-medium text-ink-700">Languages customers can choose</p>
          <div className="flex flex-wrap gap-2">
            {LANGS.map((l) => (
              <label key={l.v} className="flex min-h-11 cursor-pointer items-center gap-2.5 rounded-lg border border-ink-200 bg-white px-3 text-sm sm:min-h-10">
                <input type="checkbox" className={checkbox} checked={languages.includes(l.v)} onChange={() => toggleLang(l.v)} />{l.label}
              </label>))}
          </div>
          {languages.length === 0 && <p role="alert" className="mt-1.5 text-sm text-red-700">Keep at least one language.</p>}
        </div>
      </fieldset>

      {err && <div className="mt-4"><Alert tone="error">{err}</Alert></div>}
      <ul className="mt-4 space-y-1 text-xs text-ink-500">{ctx.notes.map((n) => <li key={n}>{n}</li>)}</ul>
      {canEdit
        ? <div className="mt-4"><Button loading={saving} disabled={!dirty || languages.length === 0} onClick={() => void save()}>Save business context</Button></div>
        : <p className="mt-4 text-sm text-ink-500">Only an owner or admin can change this.</p>}
    </Panel>
  );
}
