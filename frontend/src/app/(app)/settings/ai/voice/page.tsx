"use client";
import { PenLine } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, PageHeader } from "@/components/ui/Card";
import { ErrorSummary, Input, Textarea } from "@/components/ui/Form";
import { Panel } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useForm } from "@/lib/form";

interface Preview { body: string; language: string; flags: string[] }

/**
 * AI › Brand voice (PRD §6.3): the tone and instructions every AI-drafted reply follows (moved from Settings). The sample reply is written
 * on request, from the unsaved text, for a made-up review; it counts as one AI use and is never posted anywhere.
 */
export default function BrandVoicePage() {
  const { tenant, isAdmin, refresh } = useAuth();
  const toast = useToast();
  const f = useForm({ brand_tone: tenant?.brand_tone ?? "", ai_instructions: tenant?.ai_instructions ?? "" }, {});
  const [busy, setBusy] = useState(false);
  const [rating, setRating] = useState(5);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [pBusy, setPBusy] = useState(false);
  const [pErr, setPErr] = useState<string | null>(null);

  async function save(e: React.FormEvent) {
    e.preventDefault(); f.setServerError(null); setBusy(true);
    try {
      await api("/tenant", { method: "PATCH", body: { brand_tone: f.values.brand_tone.trim() || null, ai_instructions: f.values.ai_instructions.trim() || null } });
      await refresh(); toast("Brand voice saved.");
    } catch (err) { f.fail(errorMessage(err)); } finally { setBusy(false); }
  }
  async function sample() {
    setPBusy(true); setPErr(null);
    try { setPreview(await api<Preview>("/tenant/voice-preview", { method: "POST", body: { rating, brand_tone: f.values.brand_tone.trim() || null, ai_instructions: f.values.ai_instructions.trim() || null } })); }
    catch (err) { setPErr(errorMessage(err)); } finally { setPBusy(false); }
  }

  return (
    <>
      <PageHeader title="Brand voice" subtitle="How AI-drafted replies sound. Every reply still waits for a person to approve it." />
      {!isAdmin && <div className="mb-4"><Alert tone="info">Only owners and admins can change the brand voice.</Alert></div>}
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <form onSubmit={save} noValidate className="space-y-4">
          <ErrorSummary errors={f.errors} serverError={f.serverError} summaryRef={f.summaryRef} />
          <Panel title="Tone and instructions">
            <fieldset disabled={!isAdmin} className="space-y-4">
              <Input label="Brand tone" placeholder="e.g. warm, professional, reassuring" {...f.bind("brand_tone")} />
              <Textarea label="Instructions for replies" rows={6} placeholder="e.g. Sign off as 'Team Demo Clinic'. For complaints, invite them to call the front desk. Never mention prices." hint="Don't include patient details or passwords." {...f.bind("ai_instructions")} />
            </fieldset>
            {isAdmin && <div className="mt-5 flex justify-end"><Button type="submit" loading={busy}>Save brand voice</Button></div>}
          </Panel>
        </form>
        <Panel title="Sample reply" meta="for a made-up review, never posted">
          <div role="radiogroup" aria-label="Sample review rating" className="mb-4 inline-flex rounded-full bg-surface-2 p-1">
            {[5, 3, 1].map((r) => <button key={r} type="button" role="radio" aria-checked={rating === r} onClick={() => setRating(r)}
              className={`min-h-9 rounded-full px-4 text-sm font-medium ${rating === r ? "bg-surface text-ink shadow-pill" : "text-muted"}`}>{r}★ review</button>)}
          </div>
          <div className="rounded-tile bg-surface-2 p-4 text-sm leading-relaxed">
            {preview ? <><p className="whitespace-pre-wrap">{preview.body}</p>{preview.flags.length > 0 && <p className="mt-2 text-xs text-warn">Would be flagged for a person: {preview.flags.join(", ")}</p>}</>
              : <p className="text-muted">Write a sample to hear how your replies will sound with the text on the left (saved or not).</p>}
          </div>
          {pErr && <div className="mt-3"><Alert tone="error">{pErr}</Alert></div>}
          <Button className="mt-4" variant="secondary" icon={<PenLine className="h-4 w-4" />} loading={pBusy} disabled={!isAdmin} onClick={() => void sample()}>{preview ? "Write another" : "Write a sample"}</Button>
          <p className="mt-2 text-xs text-muted">Uses one AI generation from this month&rsquo;s allowance.</p>
        </Panel>
      </div>
    </>
  );
}
