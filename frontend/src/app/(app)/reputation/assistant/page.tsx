"use client";
import { ExternalLink, Plus, ShieldCheck, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { useSelectedCampaign } from "@/components/review-growth/shared";
import { Button, LinkButton } from "@/components/ui/Button";
import { Alert, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { FilterSelect, Select, Textarea } from "@/components/ui/Form";
import { Meter, Panel, Status } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtNum } from "@/lib/format";
import { DEFAULT_CUSTOMIZATION, STYLES, type AITestResult, type Campaign, type Customization, type Lang, type RGSettings, type Style } from "@/lib/review-growth";
import { useFetch } from "@/lib/use-api";

const PROTECTIONS = [
  ["Built from the customer's own words", "They type a few words (or a whole review). The model may only reorganise what they wrote. It is told never to add services, feelings, results, names, prices or promises."],
  ["Checked after it is written", "Drafts that add numbers, names, ratings, feelings, results, praise or a service the customer didn't mention are discarded. So are drafts that are more positive than the customer's words. A second AI pass fact-checks what's left."],
  ["Asks instead of guessing", "If the words are too vague to write something truthful (just “good”), the customer is asked for a little more detail. Nothing is invented."],
  ["The customer decides", "They edit the text, confirm it reflects their real experience, then post it on Google themselves. Nothing is ever submitted for them."],
  ["Same flow for everyone", "A complaint and a compliment get exactly the same experience. Nothing is filtered, gated or routed by sentiment."],
  ["Never a dead end", "If AI is unavailable, over its limit or fails the checks, the customer is told kindly and simply writes their own words."],
] as const;

const ERROR_HELP: Record<string, string> = {
  not_configured: "No API key or model is set on the server.",
  auth: "The provider rejected the API key. Check OPENROUTER_API_KEY.",
  forbidden: "The provider refused this model for your account or app (some free models are restricted). Pick another model.",
  credits: "The provider account has no credits for this model.",
  quota_exhausted: "The provider's daily request limit is reached (free accounts get a small daily quota). Add credits or choose another model.",
  rate_limited: "The provider is rate limiting requests. Try again shortly.",
  timeout: "The model took too long. Try again or raise AI_TIMEOUT_SECONDS.",
  tls: "The server can't verify the provider's HTTPS certificate. A proxy or antivirus may be re-signing traffic (see AI_EXTRA_CA_BUNDLE).",
  provider_error: "The provider returned an error or couldn't be reached.",
  bad_response: "The model returned an unusable reply.",
  needs_more: "The sample words were too vague to write a truthful review. This is the check working; try something more specific.",
  rejected: "The model wrote a draft, but it failed our faithfulness checks (shown below).",
};

/** Admin diagnostic: one real generation through the configured provider and the same checks customers get. */
function ModelTest({ model, onDone }: { model: string | null | undefined; onDone: () => void }) {
  const { isAdmin } = useAuth();
  const [words, setWords] = useState("back pain, friendly staff, explained exercises clearly");
  const [lang, setLang] = useState<Lang>("en");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<AITestResult | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function run() {
    setBusy(true); setErr(null); setRes(null);
    try { setRes(await api<AITestResult>("/review-growth/ai/test", { method: "POST", body: { text: words, language: lang } })); onDone(); }
    catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  if (!isAdmin) return null;
  return (
    <Panel title="Test the AI model" meta={model ?? undefined}>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); void run(); }}>
        <Textarea label="Sample customer words" rows={2} value={words} maxLength={1200} onChange={(e) => setWords(e.target.value)} className="min-h-[72px]" hint="Try keywords, a sentence, Hindi, or something negative." />
        <Select label="Language" value={lang} onChange={(e) => setLang(e.target.value as Lang)}><option value="en">English</option><option value="hi">हिन्दी</option></Select>
        <Button type="submit" loading={busy} icon={<Sparkles className="h-4 w-4" />}>Run a real test</Button>
        <p className="text-xs text-ink-500">Makes real calls to the provider (a draft plus its fact-check) and counts toward your monthly AI usage. A successful test also lifts any “AI paused” state. Customers never see this.</p>
      </form>
      {err && <div className="mt-3"><Alert tone="error">{err}</Alert></div>}
      {res && (
        <div className="mt-4 space-y-3 border-t border-ink-100 pt-4 text-sm" aria-live="polite">
          <p className="flex items-center justify-between"><span className="text-ink-500">Result</span><Status tone={res.ok ? "ok" : res.error?.code === "needs_more" ? "warn" : "bad"}>{res.ok ? "Passed the checks" : res.error?.code === "needs_more" ? "Asked for more detail" : "Did not pass"}</Status></p>
          {res.error && <Alert tone={res.error.code === "rejected" || res.error.code === "needs_more" ? "warning" : "error"} title={res.error.code}>{ERROR_HELP[res.error.code] ?? res.error.message}{res.checks?.reason ? ` (${res.checks.reason})` : ""}{res.checks?.unsupported && <span className="mt-1 block text-[13px]">Not supported by the words: {res.checks.unsupported}</span>}</Alert>}
          {(res.draft ?? res.rejected_text) && <blockquote className={`whitespace-pre-wrap rounded-lg border p-3 ${res.draft ? "border-ink-200 bg-white" : "border-amber-200 bg-amber-50"}`}>{res.draft ?? res.rejected_text}</blockquote>}
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-[13px]">
            <dt className="text-ink-500">Model</dt><dd className="truncate text-right font-mono">{res.model_served ?? res.model ?? "–"}</dd>
            <dt className="text-ink-500">Latency</dt><dd className="num text-right">{res.latency_ms !== null ? `${fmtNum(res.latency_ms)} ms` : "–"}</dd>
            <dt className="text-ink-500">Tokens (in / out)</dt><dd className="num text-right">{res.tokens ? `${fmtNum(res.tokens.prompt)} / ${fmtNum(res.tokens.completion)}` : "–"}</dd>
          </dl>
        </div>
      )}
    </Panel>
  );
}

export default function GeneratorPage() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const { campaigns, selected, loading, choose, reload } = useSelectedCampaign();
  const settings = useFetch<RGSettings>("/review-growth/settings");
  const [cz, setCz] = useState<Customization>(DEFAULT_CUSTOMIZATION);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { if (selected) { setCz(selected.customization); setError(null); } }, [selected?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const dirty = !!selected && JSON.stringify(cz) !== JSON.stringify(selected.customization);

  async function save() {
    if (!selected) return;
    setBusy(true); setError(null);
    try {
      // customers no longer choose a style, so the allowed list is just the default
      await api<Campaign>(`/review-growth/campaigns/${selected.id}`, { method: "PATCH", body: { customization: { ...cz, allowed_styles: [cz.default_style] } } });
      toast("Generator settings saved."); await reload();
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  const ai = settings.data?.ai;

  return (
    <>
      <PageHeader eyebrow="Review Growth" title="AI review generator" subtitle="Customers type a few words; AI turns them into a review they edit, confirm and post themselves."
        actions={campaigns.length > 0 && selected ? <FilterSelect label="Campaign" value={selected.id} onChange={(e) => choose(e.target.value)}>{campaigns.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</FilterSelect> : undefined} />

      {ai && !ai.configured && <div className="mb-4"><Alert tone="warning" title="AI drafting isn't configured on this server">Set the AI provider key on the server to enable it. Until then customers write their own review and still continue to Google.</Alert></div>}
      {ai?.degraded && (
        <div className="mb-4"><Alert tone="warning" title="AI writing help is paused" action={isAdmin ? <span className="text-xs">Run a test to re-check</span> : undefined}>
          {ai.degraded.message} Customers are not blocked: they see the plain “write your review” screen until this clears (automatically, or after a successful test below).</Alert></div>
      )}

      <div className="grid gap-5 lg:grid-cols-[1fr_360px]">
        <div className="space-y-4">
          {loading && !campaigns.length ? <Skeleton className="h-72" /> : !selected ? (
            <EmptyState icon={<Sparkles className="h-5 w-5" />} title="Create a campaign to configure its generator"
              action={<LinkButton href="/gbp/campaigns?new=1" size="sm" icon={<Plus className="h-4 w-4" />}>New campaign</LinkButton>}>Defaults are set per campaign.</EmptyState>
          ) : (
            <form onSubmit={(e) => { e.preventDefault(); void save(); }} className="space-y-4" noValidate>
              {!isAdmin && <Alert tone="info">Only owners and admins can change these settings.</Alert>}
              {error && <Alert tone="error" title="Couldn't save">{error}</Alert>}
              <fieldset disabled={!isAdmin || busy} className="space-y-4">
                <Panel title="Defaults" meta={selected.name}>
                  <div className="grid gap-4 sm:grid-cols-2">
                    <Select label="Starting language" value={cz.default_language} onChange={(e) => setCz({ ...cz, default_language: e.target.value as Lang })} hint="Customers can switch between English and Hindi on the page.">
                      <option value="en">English</option><option value="hi">हिन्दी (Hindi)</option></Select>
                    <Select label="Writing style" value={cz.default_style} onChange={(e) => setCz({ ...cz, default_style: e.target.value as Style })} hint="Customers aren't asked to choose a style.">
                      {STYLES.map((s) => <option key={s.v} value={s.v}>{s.label}: {s.hint}</option>)}</Select>
                  </div>
                </Panel>
              </fieldset>
              {isAdmin && <div className="flex items-center justify-end gap-3">
                {dirty && <span className="text-sm text-ink-500">Unsaved changes</span>}
                <Button type="button" variant="secondary" disabled={!dirty || busy} onClick={() => setCz(selected.customization)}>Reset</Button>
                <Button type="submit" loading={busy} disabled={!dirty}>Save settings</Button>
              </div>}
              <a href={selected.url} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center gap-1.5 text-sm font-medium text-brand-700 hover:underline"><ExternalLink className="h-4 w-4" aria-hidden />Try the customer experience (opens the live page)</a>
            </form>
          )}
          <Panel title="How drafts are protected" action={<ShieldCheck className="h-4 w-4 text-ok" aria-hidden />}>
            <ul className="grid gap-x-6 gap-y-4 sm:grid-cols-2">{PROTECTIONS.map(([t, b]) => <li key={t}><p className="text-sm font-semibold">{t}</p><p className="mt-0.5 text-[13px] text-ink-500">{b}</p></li>)}</ul>
          </Panel>
        </div>

        <div className="space-y-4">
          <Panel title="AI status">
            {!settings.data ? <Skeleton className="h-24" /> : (
              <div className="space-y-3 text-sm">
                <p className="flex items-center justify-between"><span className="text-ink-500">Drafting</span><Status tone={ai?.degraded ? "warn" : ai?.configured ? "ok" : "warn"}>{ai?.degraded ? "Paused" : ai?.configured ? `On (${ai.provider})` : "Not configured"}</Status></p>
                {ai?.model && <p className="flex items-center justify-between gap-3"><span className="text-ink-500">Model</span><span className="truncate font-mono text-[13px]">{ai.model}</span></p>}
                <div><p className="mb-1.5 flex justify-between"><span className="text-ink-500">AI calls this month</span><b className="num">{fmtNum(ai?.used_this_month)} / {fmtNum(ai?.monthly_limit)}</b></p>
                  <Meter value={ai?.used_this_month ?? 0} max={ai?.monthly_limit ?? 1} tone={(ai?.used_this_month ?? 0) >= (ai?.monthly_limit ?? 1) ? "bad" : "info"} label="AI calls used this month" /></div>
                <p className="text-xs text-ink-500">Each draft, fact-check and rewrite counts. Each customer can request up to {settings.data.limits.max_drafts_per_customer} drafts. When the plan limit is reached, customers write their own words.</p>
              </div>)}
          </Panel>
          <ModelTest model={ai?.model} onDone={() => void settings.reload()} />
        </div>
      </div>
    </>
  );
}
