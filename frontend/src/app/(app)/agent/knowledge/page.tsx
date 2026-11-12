"use client";
import { Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, PageHeader, Skeleton } from "@/components/ui/Card";
import { Input, Textarea } from "@/components/ui/Form";
import { Panel } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import { Violations } from "@/components/agent/TaskCard";
import type { Knowledge, Offer, Violation } from "@/lib/agent";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-api";

const lines = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);

export default function KnowledgePage() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const { data, error, setData } = useFetch<Knowledge>("/agent/knowledge");
  const [f, setF] = useState<{ description: string; services: string; hours: string; brand_voice: string; approved: string; prohibited: string; offers: Offer[]; faqs: { q: string; a: string }[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);
  const [probe, setProbe] = useState("");
  const [found, setFound] = useState<Violation[] | null>(null);
  useEffect(() => { if (data && !f) setF({ description: data.description, services: data.services.join("\n"), hours: data.hours, brand_voice: data.brand_voice, approved: data.approved_claims.join("\n"), prohibited: data.prohibited_claims.join("\n"), offers: data.offers, faqs: data.faqs }); }, [data, f]);
  const dirty = !!(data && f && JSON.stringify(f) !== JSON.stringify({ description: data.description, services: data.services.join("\n"), hours: data.hours, brand_voice: data.brand_voice, approved: data.approved_claims.join("\n"), prohibited: data.prohibited_claims.join("\n"), offers: data.offers, faqs: data.faqs }));

  async function save() {
    if (!f) return;
    setBusy(true); setSaveErr(null);
    try {
      const d = await api<Knowledge>("/agent/knowledge", { method: "PUT", body: { description: f.description, services: lines(f.services), hours: f.hours, brand_voice: f.brand_voice, approved_claims: lines(f.approved), prohibited_claims: lines(f.prohibited),
        offers: f.offers.filter((o) => o.name.trim()).map((o) => ({ name: o.name.trim(), price_inr: o.price_inr === null || (o.price_inr as unknown) === "" ? null : Number(o.price_inr), details: o.details || null, valid_until: o.valid_until || null })), faqs: f.faqs.filter((x) => x.q.trim() && x.a.trim()) } });
      setData(d); setF(null); toast("Knowledge base saved.");
    } catch (e) { setSaveErr(errorMessage(e)); } finally { setBusy(false); }
  }
  const set = (patch: Partial<NonNullable<typeof f>>) => f && setF({ ...f, ...patch });
  if (error) return <Alert tone="error">{error}</Alert>;
  if (!data || !f) return <Skeleton className="h-96" />;
  const ro = !isAdmin;
  return (
    <>
      <PageHeader eyebrow="AI Growth Agent" title="Knowledge Base" subtitle="The only facts the AI may state about your business. Anything not here, it is told not to say, and every draft is checked against these rules."
        actions={isAdmin ? <Button loading={busy} disabled={!dirty} onClick={() => void save()}>Save knowledge base</Button> : undefined} />
      {ro && <div className="mb-4"><Alert tone="info">Only owners and admins can edit this.</Alert></div>}
      {saveErr && <div className="mb-4"><Alert tone="error" title="Not saved">{saveErr}</Alert></div>}
      {!data.completeness.complete && <div className="mb-4"><Alert tone="warning" title="Not complete yet">Missing: {data.completeness.missing.join(", ")}. Drafts are weaker without them.</Alert></div>}
      {data.safety_profile === "health" && <div className="mb-4"><Alert tone="info" title="Health business safety rules are on">Replies and posts may never confirm someone is a patient, mention treatment or conditions, or promise outcomes. The &ldquo;not allowed&rdquo; list below was pre-filled for you; edit it as needed.</Alert></div>}
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-4">
          <Panel title="About your business">
            <div className="space-y-3"><Textarea label="Description" rows={3} maxLength={600} disabled={ro} hint="Plain, factual: what you do and where. No claims, prices or links." value={f.description} onChange={(e) => set({ description: e.target.value })} />
              <Textarea label="Services (one per line)" rows={4} disabled={ro} value={f.services} onChange={(e) => set({ services: e.target.value })} />
              <Textarea label="Opening hours" rows={2} disabled={ro} placeholder="Mon-Sat 9am-7pm, closed Sunday" value={f.hours} onChange={(e) => set({ hours: e.target.value })} />
              <Input label="Brand voice" disabled={ro} placeholder="warm, calm, professional" value={f.brand_voice} onChange={(e) => set({ brand_voice: e.target.value })} /></div>
          </Panel>
          <Panel title="Verified prices and offers" meta="the only prices the AI may mention">
            <div className="space-y-3">{f.offers.map((o, i) => (
              <div key={i} className="grid gap-2 rounded-lg border border-ink-100 p-3 sm:grid-cols-[1fr_110px_auto]">
                <Input label="Name" disabled={ro} value={o.name} onChange={(e) => set({ offers: f.offers.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)) })} />
                <Input label="Price (₹)" type="number" min={0} disabled={ro} value={o.price_inr ?? ""} onChange={(e) => set({ offers: f.offers.map((x, j) => (j === i ? { ...x, price_inr: e.target.value === "" ? null : Number(e.target.value) } : x)) })} />
                {!ro && <Button variant="ghost" size="sm" className="self-end" aria-label="Remove offer" icon={<Trash2 className="h-4 w-4 text-red-600" />} onClick={() => set({ offers: f.offers.filter((_, j) => j !== i) })} />}
                <div className="sm:col-span-3"><Input label="Details (optional)" disabled={ro} value={o.details ?? ""} onChange={(e) => set({ offers: f.offers.map((x, j) => (j === i ? { ...x, details: e.target.value } : x)) })} /></div>
              </div>))}
              {!ro && <Button size="sm" variant="secondary" icon={<Plus className="h-4 w-4" />} onClick={() => set({ offers: [...f.offers, { name: "", price_inr: null, details: null, valid_until: null }] })}>Add a price or offer</Button>}
              {f.offers.length === 0 && <p className="text-[13px] text-ink-500">None verified: the AI is told not to mention any price, discount or free service.</p>}
            </div>
          </Panel>
          <Panel title="Frequently asked questions"><div className="space-y-3">{f.faqs.map((q, i) => (
            <div key={i} className="space-y-2 rounded-lg border border-ink-100 p-3"><Input label="Question" disabled={ro} value={q.q} onChange={(e) => set({ faqs: f.faqs.map((x, j) => (j === i ? { ...x, q: e.target.value } : x)) })} /><Textarea label="Answer" rows={2} disabled={ro} value={q.a} onChange={(e) => set({ faqs: f.faqs.map((x, j) => (j === i ? { ...x, a: e.target.value } : x)) })} />
              {!ro && <Button variant="ghost" size="sm" icon={<Trash2 className="h-4 w-4 text-red-600" />} onClick={() => set({ faqs: f.faqs.filter((_, j) => j !== i) })}>Remove</Button>}</div>))}
            {!ro && <Button size="sm" variant="secondary" icon={<Plus className="h-4 w-4" />} onClick={() => set({ faqs: [...f.faqs, { q: "", a: "" }] })}>Add a question</Button>}</div></Panel>
        </div>
        <div className="space-y-4">
          <Panel title="Claims you approve"><Textarea label="One per line" rows={3} disabled={ro} hint="Wording you explicitly allow, for example an accreditation you hold. It overrides the health rules for that exact wording." value={f.approved} onChange={(e) => set({ approved: e.target.value })} /></Panel>
          <Panel title="Never say" meta="drafts containing these are rejected"><Textarea label="One phrase per line" rows={10} disabled={ro} value={f.prohibited} onChange={(e) => set({ prohibited: e.target.value })} /></Panel>
          <Panel title="Check a piece of text" meta="uses your saved rules">
            <Textarea label="Paste any reply, post or description" rows={3} value={probe} onChange={(e) => { setProbe(e.target.value); setFound(null); }} />
            <div className="mt-2 flex items-center gap-2"><Button size="sm" variant="secondary" disabled={!probe.trim()} onClick={async () => { try { setFound((await api<{ violations: Violation[] }>("/agent/knowledge/check", { method: "POST", body: { text: probe, kind: "post" } })).violations); } catch (e) { toast(errorMessage(e), "error"); } }}>Check</Button>{found && found.length === 0 && <span className="text-sm text-green-700">No rule broken.</span>}</div>
            {found && found.length > 0 && <div className="mt-2"><Violations items={found} /></div>}
          </Panel>
          <Panel title="What the AI is given"><details><summary className="cursor-pointer text-sm font-medium text-brand-700">Show the exact facts block</summary><pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap rounded-lg bg-ink-50 p-3 text-xs text-ink-700">{data.grounding_preview}</pre></details></Panel>
        </div>
      </div>
    </>
  );
}
