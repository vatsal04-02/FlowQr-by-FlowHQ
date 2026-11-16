"use client";
import clsx from "clsx";
import { ArrowLeft, ArrowRight, Check, Plus, Store, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Violations } from "@/components/agent/TaskCard";
import { Button } from "@/components/ui/Button";
import { Alert, PageHeader, Skeleton } from "@/components/ui/Card";
import { Input, Textarea } from "@/components/ui/Form";
import { useToast } from "@/components/ui/Toast";
import type { Knowledge, Offer, Violation } from "@/lib/agent";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-api";
import { useGbp } from "@/lib/use-gbp";

const lines = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);
type Form = { description: string; services: string; hours: string; brand_voice: string; audience: string; approved: string; prohibited: string; offers: Offer[]; faqs: { q: string; a: string }[] };
const fromData = (d: Knowledge): Form => ({ description: d.description, services: d.services.join("\n"), hours: d.hours, brand_voice: d.brand_voice, audience: d.audience ?? "", approved: d.approved_claims.join("\n"), prohibited: d.prohibited_claims.join("\n"), offers: d.offers, faqs: d.faqs });

const STEPS = [
  { id: "about", title: "About you", help: "What you do and where. The AI only talks about what you write here." },
  { id: "prices", title: "Prices & offers", help: "Only the prices you list here can ever be mentioned." },
  { id: "faq", title: "Customer questions", help: "Questions customers ask you, with your answers." },
  { id: "rules", title: "Rules", help: "Words the AI must never use, and claims you are allowed to make." },
  { id: "check", title: "Check", help: "Test some text against your rules, then save." },
] as const;

const SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const ORDER = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"];
const t12 = (t: string) => { const [h, m] = t.split(":").map(Number); return `${((h + 11) % 12) + 1}${m ? `:${String(m).padStart(2, "0")}` : ""} ${h < 12 ? "am" : "pm"}`; };
/** "Mon–Fri 9 am–1 pm, 4 pm–8 pm; Sat 9 am–1 pm; Sun closed", built only from the hours Google reports. */
function hoursText(hours: { day: string; open: string; close: string }[]) {
  const per = ORDER.map((d) => { const p = hours.filter((h) => h.day === d).map((h) => `${t12(h.open)}–${t12(h.close)}`); return p.length ? p.join(", ") : "closed"; });
  const out: string[] = [];
  for (let i = 0; i < 7;) { let j = i; while (j + 1 < 7 && per[j + 1] === per[i]) j++; out.push(`${i === j ? SHORT[i] : `${SHORT[i]}–${SHORT[j]}`} ${per[i]}`); i = j + 1; }
  return out.join("; ");
}

export default function KnowledgePage() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const gbp = useGbp();
  const { data, error, setData } = useFetch<Knowledge>("/agent/knowledge");
  const [f, setF] = useState<Form | null>(null);
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const [filling, setFilling] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);
  const [probe, setProbe] = useState("");
  const [found, setFound] = useState<Violation[] | null>(null);
  useEffect(() => { if (data && !f) setF(fromData(data)); }, [data, f]);
  const dirty = !!(data && f && JSON.stringify(f) !== JSON.stringify(fromData(data)));

  async function save() {
    if (!f) return;
    setBusy(true); setSaveErr(null);
    try {
      const d = await api<Knowledge>("/agent/knowledge", { method: "PUT", body: { description: f.description, services: lines(f.services), hours: f.hours, brand_voice: f.brand_voice, audience: f.audience, approved_claims: lines(f.approved), prohibited_claims: lines(f.prohibited),
        offers: f.offers.filter((o) => o.name.trim()).map((o) => ({ name: o.name.trim(), price_inr: o.price_inr === null || (o.price_inr as unknown) === "" ? null : Number(o.price_inr), details: o.details || null, valid_until: o.valid_until || null })), faqs: f.faqs.filter((x) => x.q.trim() && x.a.trim()) } });
      setData(d); setF(null); toast("Business Brain saved.");
    } catch (e) { setSaveErr(errorMessage(e)); } finally { setBusy(false); }
  }
  /** A suggestion from the connected Google profile. Only fills empty fields; nothing is saved until the owner checks it and saves. */
  async function fillFromGoogle() {
    const gid = gbp.selected[0]?.id;
    if (!gid || !f) return;
    setFilling(true);
    try {
      const info = await api<{ description: string | null; hours: { day: string; open: string; close: string }[] }>(`/gbp/${gid}/info`);
      const next = { ...f }; const filled: string[] = [];
      if (!f.description.trim() && info.description) { next.description = info.description.slice(0, 600); filled.push("description"); }
      if (!f.hours.trim() && info.hours.length) { next.hours = hoursText(info.hours); filled.push("opening hours"); }
      setF(next);
      toast(filled.length ? `Filled in your ${filled.join(" and ")} from Google. Check it, then save.` : "Nothing new to fill in: those fields already have text, or Google has none.");
    } catch (e) { toast(errorMessage(e), "error"); } finally { setFilling(false); }
  }
  const set = (patch: Partial<Form>) => f && setF({ ...f, ...patch });
  if (error) return <Alert tone="error">{error}</Alert>;
  if (!data || !f) return <Skeleton className="h-96" />;
  const ro = !isAdmin;

  const done = [
    !!(f.description.trim() && f.services.trim() && f.brand_voice.trim()),
    f.offers.some((o) => o.name.trim()), f.faqs.some((q) => q.q.trim() && q.a.trim()), !!f.prohibited.trim(), false,
  ];
  const cur = STEPS[step];

  return (
    <>
      <PageHeader title="Business Brain" subtitle="What your AI assistant knows about you. It never says anything that isn't here." />
      {ro && <div className="mb-4"><Alert tone="info">Only owners and admins can edit this.</Alert></div>}
      {saveErr && <div className="mb-4"><Alert tone="error" title="Not saved">{saveErr}</Alert></div>}

      <nav aria-label="Setup steps" className="mb-5">
        <ol className="grid grid-cols-5 gap-1.5">
          {STEPS.map((s, i) => (
            <li key={s.id}><button type="button" aria-current={i === step ? "step" : undefined} onClick={() => setStep(i)} className="group w-full text-left">
              <span className={clsx("block h-1.5 rounded-full transition-colors", i === step ? "bg-fq" : done[i] ? "bg-green-600" : "bg-ink-200")} />
              <span className={clsx("mt-1.5 flex items-center gap-1 text-[13px] font-semibold leading-tight", i === step ? "text-navy" : "text-ink-500 group-hover:text-navy")}>
                {done[i] && i !== step && <Check className="h-3.5 w-3.5 shrink-0 text-green-700" strokeWidth={3} aria-hidden />}<span className="hidden sm:inline">{s.title}</span><span className="sm:hidden">{i + 1}</span>{done[i] && <span className="sr-only"> (done)</span>}</span>
            </button></li>))}
        </ol>
      </nav>

      <section aria-labelledby="step-h" className="rounded-2xl border border-ink-100 bg-white p-4 sm:p-6">
        <p className="text-[13px] font-semibold text-brand-700">Step {step + 1} of {STEPS.length}</p>
        <h2 id="step-h" className="text-xl font-bold text-navy">{cur.title}</h2>
        <p className="mt-0.5 text-sm text-ink-700">{cur.help}</p>

        <div className="mt-5 space-y-4">
          {step === 0 && (
            <>
              {isAdmin && gbp.selected.length > 0 && (
                <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-brand-50 p-3.5">
                  <p className="flex items-center gap-2 text-sm text-navy"><Store className="h-4 w-4 text-brand-700" aria-hidden />Save time: fill the empty boxes from your Google profile.</p>
                  <Button size="sm" variant="secondary" loading={filling} onClick={() => void fillFromGoogle()}>Fill from Google</Button>
                </div>)}
              <Textarea label="What do you do, and where?" rows={3} maxLength={600} disabled={ro} hint="Example: Physiotherapy clinic in Vijay Nagar, Indore. Pain relief and rehab for adults. No claims, prices or links." value={f.description} onChange={(e) => set({ description: e.target.value })} />
              <Textarea label="Services (one per line)" rows={4} disabled={ro} hint="Example: Back pain treatment, Sports injury rehab, Post-surgery rehab" value={f.services} onChange={(e) => set({ services: e.target.value })} />
              <Textarea label="Opening hours" rows={2} disabled={ro} placeholder="Mon–Sat 9 am–7 pm, Sun closed" value={f.hours} onChange={(e) => set({ hours: e.target.value })} />
              <Input label="How should replies sound?" disabled={ro} placeholder="warm, calm, professional" value={f.brand_voice} onChange={(e) => set({ brand_voice: e.target.value })} />
              <Input label="Who are your best customers?" disabled={ro} maxLength={300} hint="Example: office workers nearby, parents of school children. It decides which tips and examples your posts use." placeholder="office workers within 3 km" value={f.audience} onChange={(e) => set({ audience: e.target.value })} />
            </>)}

          {step === 1 && (
            <div className="space-y-3">
              {f.offers.map((o, i) => (
                <div key={i} className="grid gap-2 rounded-xl bg-ink-50 p-3 sm:grid-cols-[1fr_120px_auto]">
                  <Input label="Name" disabled={ro} placeholder="First consultation" value={o.name} onChange={(e) => set({ offers: f.offers.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)) })} />
                  <Input label="Price (₹)" type="number" min={0} disabled={ro} value={o.price_inr ?? ""} onChange={(e) => set({ offers: f.offers.map((x, j) => (j === i ? { ...x, price_inr: e.target.value === "" ? null : Number(e.target.value) } : x)) })} />
                  {!ro && <Button variant="ghost" size="sm" className="self-end" aria-label="Remove offer" icon={<Trash2 className="h-4 w-4 text-red-600" />} onClick={() => set({ offers: f.offers.filter((_, j) => j !== i) })} />}
                  <div className="sm:col-span-3"><Input label="Details (optional)" disabled={ro} value={o.details ?? ""} onChange={(e) => set({ offers: f.offers.map((x, j) => (j === i ? { ...x, details: e.target.value } : x)) })} /></div>
                </div>))}
              {!ro && <Button size="sm" variant="secondary" icon={<Plus className="h-4 w-4" />} onClick={() => set({ offers: [...f.offers, { name: "", price_inr: null, details: null, valid_until: null }] })}>Add a price or offer</Button>}
              {f.offers.length === 0 && <p className="rounded-xl bg-brand-50 p-3 text-sm text-ink-700">No prices listed. The AI will not mention any price, discount or free service. That is a safe choice; add some if you want them in replies and posts.</p>}
            </div>)}

          {step === 2 && (
            <div className="space-y-3">
              {f.faqs.map((q, i) => (
                <div key={i} className="space-y-2 rounded-xl bg-ink-50 p-3"><Input label="Question" disabled={ro} placeholder="Do I need an appointment?" value={q.q} onChange={(e) => set({ faqs: f.faqs.map((x, j) => (j === i ? { ...x, q: e.target.value } : x)) })} />
                  <Textarea label="Answer" rows={2} disabled={ro} value={q.a} onChange={(e) => set({ faqs: f.faqs.map((x, j) => (j === i ? { ...x, a: e.target.value } : x)) })} />
                  {!ro && <Button variant="ghost" size="sm" icon={<Trash2 className="h-4 w-4 text-red-600" />} onClick={() => set({ faqs: f.faqs.filter((_, j) => j !== i) })}>Remove</Button>}</div>))}
              {!ro && <Button size="sm" variant="secondary" icon={<Plus className="h-4 w-4" />} onClick={() => set({ faqs: [...f.faqs, { q: "", a: "" }] })}>Add a question</Button>}
              {f.faqs.length === 0 && <p className="rounded-xl bg-brand-50 p-3 text-sm text-ink-700">Optional. Good answers here help the AI reply to customers who ask the same thing in reviews.</p>}
            </div>)}

          {step === 3 && (
            <>
              {data.safety_profile === "health" && <p className="rounded-xl bg-brand-50 p-3.5 text-sm text-navy"><b>Health business rules are on.</b> Replies and posts may never confirm someone is a patient, mention treatment or conditions, or promise outcomes. The list below is pre-filled; edit it as needed.</p>}
              <Textarea label="Never say (one phrase per line)" rows={8} disabled={ro} hint="A draft containing any of these is rejected." value={f.prohibited} onChange={(e) => set({ prohibited: e.target.value })} />
              <Textarea label="Claims you approve (one per line)" rows={3} disabled={ro} hint="Wording you explicitly allow, such as an accreditation you hold. It overrides the rules above for that exact wording." value={f.approved} onChange={(e) => set({ approved: e.target.value })} />
            </>)}

          {step === 4 && (
            <>
              {!data.completeness.complete && <p className="rounded-xl bg-brand-50 p-3.5 text-sm text-navy">Still missing: <b>{data.completeness.missing.join(", ")}</b>. Drafts are weaker without them.</p>}
              <Textarea label="Try a reply, post or description" rows={3} value={probe} onChange={(e) => { setProbe(e.target.value); setFound(null); }} />
              <div className="flex flex-wrap items-center gap-2">
                <Button size="sm" variant="secondary" disabled={!probe.trim()} onClick={async () => { try { setFound((await api<{ violations: Violation[] }>("/agent/knowledge/check", { method: "POST", body: { text: probe, kind: "post" } })).violations); } catch (e) { toast(errorMessage(e), "error"); } }}>Check it against my rules</Button>
                {found && found.length === 0 && <span className="inline-flex items-center gap-1 text-sm font-semibold text-green-800"><Check className="h-4 w-4" strokeWidth={3} aria-hidden />Passes your rules</span>}
              </div>
              {found && found.length > 0 && <Violations items={found} />}
              <details className="rounded-xl bg-ink-50 p-3"><summary className="flex min-h-11 cursor-pointer items-center text-sm font-semibold text-navy sm:min-h-8">See exactly what the AI is given</summary><pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap text-xs text-ink-700">{data.grounding_preview}</pre></details>
            </>)}
        </div>

        <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-ink-100 pt-4">
          <Button variant="ghost" icon={<ArrowLeft className="h-4 w-4" />} disabled={step === 0} onClick={() => setStep(step - 1)}>Back</Button>
          <div className="flex flex-wrap items-center gap-2">
            {isAdmin && <Button variant={step === STEPS.length - 1 ? "primary" : "secondary"} loading={busy} disabled={!dirty} onClick={() => void save()}>{dirty ? "Save Business Brain" : "Saved"}</Button>}
            {step < STEPS.length - 1 && <Button variant="primary" onClick={() => setStep(step + 1)}>Next<ArrowRight className="h-4 w-4" aria-hidden /></Button>}
          </div>
        </div>
      </section>
    </>
  );
}
