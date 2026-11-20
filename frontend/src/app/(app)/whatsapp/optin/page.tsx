"use client";
import clsx from "clsx";
import { Bell, ExternalLink, Layers, Megaphone, MessageCircle, Plus, QrCode, Trash2, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, PageHeader, Skeleton } from "@/components/ui/Card";
import { Input } from "@/components/ui/Form";
import { useToast } from "@/components/ui/Toast";
import { Bubble, IconButton, IconTile, Note, PhonePreview, Switch } from "@/components/whatsapp/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-api";
import { confirmWords, keywordProblem, OPTIN_PURPOSES, type OptinPurpose, type WaOptin, type WaOptinKeyword } from "@/lib/whatsapp";

/** What each choice is called on screen. The full wording (the `label` in OPTIN_PURPOSES) is kept as the name for screen readers and in the hint under the choice. */
const SHORT: Record<OptinPurpose, { word: string; icon: LucideIcon }> = {
  utility: { word: "Visit updates", icon: Bell },
  marketing: { word: "Offers", icon: Megaphone },
  both: { word: "Both", icon: Layers },
};

function Keyword({ k, canEdit, onChange }: { k: WaOptinKeyword; canEdit: boolean; onChange: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null);
  async function run(fn: () => Promise<unknown>, done: string) {
    setBusy(true); setErr(null);
    try { await fn(); toast(done); onChange(); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  const S = SHORT[k.purpose];
  return (
    <li className="py-3">
      <div className="flex items-center gap-3">
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-x-2.5 gap-y-1"><b className={clsx("font-mono text-[17px] tracking-wide", k.enabled ? "text-ink" : "text-ink-400")}>{k.keyword}</b><span className="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2.5 py-1 text-[13px] font-medium text-ink-700"><S.icon className="h-3.5 w-3.5" aria-hidden />{S.word}</span></p>
        </div>
        {canEdit && (
          <>
            <Switch checked={k.enabled} busy={busy} label={`${k.keyword}: ${k.enabled ? "on" : "off"}`} onChange={(v) => void run(() => api(`/whatsapp/optin/keywords/${k.id}`, { method: "PATCH", body: { enabled: v } }), v ? "Switched on." : "Switched off.")} />
            <button type="button" aria-label={`Delete ${k.keyword}`} disabled={busy} onClick={() => void run(() => api(`/whatsapp/optin/keywords/${k.id}`, { method: "DELETE" }), "Deleted.")} className="grid h-11 w-11 place-items-center rounded-full text-ink-400 hover:bg-neg-tint hover:text-neg disabled:opacity-50"><Trash2 className="h-[18px] w-[18px]" aria-hidden /></button>
          </>
        )}
      </div>
      <p className="mt-1 text-[13px] leading-5 text-muted">{k.wording}</p>
      {err && <div className="mt-2"><Alert tone="warning">{err}</Alert></div>}
    </li>
  );
}

/** Sign-ups without typing a phone number: a WhatsApp button on your QR review page, and keywords a customer can text. The customer's own message is their agreement. */
export default function Optin() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const q = useFetch<WaOptin>("/whatsapp/optin");
  const o = q.data;
  const [busy, setBusy] = useState<string | null>(null), [err, setErr] = useState<string | null>(null);
  const [word, setWord] = useState(""), [wordPurpose, setWordPurpose] = useState<OptinPurpose>("utility"), [wordErr, setWordErr] = useState<string | null>(null);
  async function save(body: Record<string, unknown>, done: string) {
    setBusy("save"); setErr(null);
    try { await api("/whatsapp/optin", { method: "PUT", body }); toast(done); void q.reload(); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(null); }
  }
  async function prepare() {
    setBusy("prepare"); setErr(null);
    try { await api("/whatsapp/setup/prepare-messages", { method: "POST", body: { include_optin: true } }); toast("Sent to WhatsApp for approval."); void q.reload(); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(null); }
  }
  async function addWord() {
    const problem = keywordProblem(word);
    if (problem) { setWordErr(problem); return; }
    setBusy("word"); setWordErr(null);
    try { await api("/whatsapp/optin/keywords", { method: "POST", body: { keyword: word.trim(), purpose: wordPurpose } }); setWord(""); toast("Keyword added."); void q.reload(); } catch (e) { setWordErr(errorMessage(e)); } finally { setBusy(null); }
  }
  const s = o?.settings ?? null;
  const purpose: OptinPurpose = s?.purpose ?? "utility";
  const needTemplate = purpose === "marketing" ? "optin_confirm_offers" : "optin_confirm";
  const confirmStatus = o ? (purpose === "both" ? o.confirm_templates.optin_confirm : o.confirm_templates[needTemplate]) : null;
  const cw = confirmWords(confirmStatus);
  const chosen = OPTIN_PURPOSES.find((p) => p.value === purpose);
  const showing = !!s?.qr_enabled;
  return (
    <>
      <PageHeader title="Sign-ups" />
      {q.error && <Alert tone="error">{q.error}</Alert>}
      {!o ? <Skeleton className="h-64" /> : (
        <div className="space-y-3 sm:space-y-4">
          {!o.connected && <Alert tone="info" title="Connect your number first"><Link href="/whatsapp/connect" className="font-semibold text-brand-700 hover:underline">Connect it</Link></Alert>}
          {err && <Alert tone="warning">{err}</Alert>}

          <section className="panel p-5 sm:p-6" aria-label="Button on your QR page">
            <div className="flex items-center gap-3">
              <IconTile icon={QrCode} tone={showing ? "pos" : "neutral"} size={44} />
              <div className="min-w-0 flex-1">
                <h2 className="text-[17px] font-semibold leading-6 text-ink">Button on your QR page</h2>
                <p className="text-[13px] leading-4 text-muted">{o.link_live ? "Customers can see it" : showing ? "Switched on, not showing yet" : "Hidden"}</p>
              </div>
              {isAdmin && <Switch checked={showing} busy={busy === "save"} label="Show the WhatsApp button on my QR page" onChange={(v) => void save({ qr_enabled: v }, v ? "Button switched on." : "Button hidden.")} />}
            </div>

            <div className="mt-5 grid gap-6 lg:grid-cols-[250px_1fr] lg:items-center">
              <PhonePreview label="What a customer sees on your QR page">
                <div className="mx-auto mt-1 h-2.5 w-24 rounded-full bg-surface-3" />
                <div className="mx-auto mt-1 grid h-16 w-16 place-items-center rounded-xl bg-surface-2 text-ink-300"><QrCode className="h-9 w-9" aria-hidden /></div>
                <div className="mx-auto h-2 w-32 rounded-full bg-surface-2" />
                <div className={clsx("mt-auto flex min-h-11 items-center justify-center gap-2 rounded-full px-3 text-[13px] font-semibold", showing ? "bg-[#1FA855] text-white" : "border border-dashed border-ink-200 text-ink-400")}>
                  <MessageCircle className="h-4 w-4" aria-hidden />{showing ? "Join on WhatsApp" : "Hidden"}
                </div>
              </PhonePreview>

              <div>
                <p className="text-[13px] font-semibold text-ink-700" id="optin-agree">What do they agree to?</p>
                <div role="radiogroup" aria-labelledby="optin-agree" className="mt-2 grid grid-cols-3 gap-2">
                  {OPTIN_PURPOSES.map((p) => {
                    const S = SHORT[p.value]; const on = purpose === p.value;
                    return (
                      <button key={p.value} type="button" role="radio" aria-checked={on} aria-label={`${p.label}. ${p.hint}`} disabled={!isAdmin || busy === "save"} onClick={() => { if (!on) void save({ purpose: p.value }, "Saved."); }}
                        className={clsx("flex min-h-[84px] flex-col items-center justify-center gap-1.5 rounded-2xl px-2 text-center transition-colors motion-reduce:transition-none disabled:cursor-not-allowed", on ? "bg-brand-50 text-brand-700 ring-2 ring-brand-600" : "bg-surface-2 text-ink-700 hover:bg-surface-3")}>
                        <S.icon className="h-6 w-6" strokeWidth={1.75} aria-hidden /><span className="text-[14px] font-semibold leading-4">{S.word}</span>
                      </button>
                    );
                  })}
                </div>
                {chosen && <p className="mt-2 text-[13px] leading-5 text-muted" aria-live="polite">{chosen.label}. {chosen.hint}</p>}

                {s && (
                  <div className="mt-4 flex flex-col rounded-2xl bg-surface-2 p-3">
                    <p className="mb-2 text-[13px] font-medium text-muted">The customer sends</p>
                    <Bubble side="out" className="max-w-full break-words">{s.prefill_text}</Bubble>
                    <Note className="mt-2.5">Only this exact message counts.</Note>
                  </div>
                )}
              </div>
            </div>

            <div className="mt-5 space-y-3 border-t border-line pt-4">
              <div className="flex items-center gap-3">
                <div className="min-w-0 flex-1"><p className="text-[15px] font-medium leading-5 text-ink">Thank-you message</p><p className="mt-1"><Badge tone={cw.tone}>{cw.label}</Badge></p></div>
                {isAdmin && <Switch checked={s?.confirm_reply ?? true} busy={busy === "save"} label="Send one short thank-you message when someone joins" onChange={(v) => void save({ confirm_reply: v }, "Saved.")} />}
              </div>
              {isAdmin && confirmStatus === null && <Button variant="secondary" className="w-full sm:w-auto" loading={busy === "prepare"} onClick={() => void prepare()}>Send for approval</Button>}
              {o.link_example && <a href={o.link_example} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center gap-1.5 text-[14px] font-semibold text-brand-700 hover:underline">Try it yourself<ExternalLink className="h-3.5 w-3.5" aria-hidden /></a>}
            </div>
            {!isAdmin && <Note className="mt-3">Only the owner or an admin can change this.</Note>}
            <Note className="mt-3">Customers can reply STOP at any time. Then only they can sign up again.</Note>
          </section>

          <section className="panel p-5 sm:p-6" aria-label="Keywords">
            <div className="flex items-center justify-between gap-3"><h2 className="text-[17px] font-semibold text-ink">Keywords</h2><span className="num rounded-full bg-surface-2 px-3 py-1 text-[13px] font-semibold text-ink-700" aria-label={`${o.keywords.length} of ${o.max_keywords} keywords`}>{o.keywords.length}/{o.max_keywords}</span></div>
            <p className="mt-1 text-[14px] leading-5 text-muted">A word on a poster, like <b className="text-ink">JOINUS</b>. A customer who sends only that word agrees to what it stands for.</p>
            {o.keywords.length === 0 ? <p className="mt-4 rounded-2xl bg-surface-2 px-4 py-5 text-center text-[14px] text-muted">No keywords yet</p> : <ul className="mt-2 divide-y divide-line">{o.keywords.map((k) => <Keyword key={k.id} k={k} canEdit={isAdmin} onChange={() => void q.reload()} />)}</ul>}
            {isAdmin && o.keywords.length < o.max_keywords && (
              <div className="mt-4 space-y-3 border-t border-line pt-4">
                <Input label="New keyword" value={word} maxLength={20} error={wordErr ?? undefined} onChange={(e) => { setWord(e.target.value); setWordErr(null); }} hint="3 to 20 letters or numbers." />
                <div role="radiogroup" aria-label="They agree to" className="grid grid-cols-3 gap-2">
                  {OPTIN_PURPOSES.map((p) => { const S = SHORT[p.value]; const on = wordPurpose === p.value; return (
                    <button key={p.value} type="button" role="radio" aria-checked={on} aria-label={p.label} onClick={() => setWordPurpose(p.value)} className={clsx("inline-flex min-h-11 items-center justify-center gap-1.5 rounded-full px-2 text-[13.5px] font-medium", on ? "bg-ink-solid text-ink-on" : "bg-surface-2 text-ink-700 hover:bg-surface-3")}><S.icon className="h-4 w-4" aria-hidden />{S.word}</button>
                  ); })}
                </div>
                <Button variant="brand" size="lg" className="w-full" icon={<Plus className="h-4 w-4" />} loading={busy === "word"} onClick={() => void addWord()}>Add keyword</Button>
              </div>
            )}
            {o.keywords.length >= o.max_keywords && <Note className="mt-3">That is the most you can have. Delete one to add another.</Note>}
          </section>

          <Note className="px-1">Everyone who joins shows on <Link href="/whatsapp/contacts" className="font-semibold text-brand-700 hover:underline">Customers</Link>.</Note>
        </div>
      )}
    </>
  );
}
