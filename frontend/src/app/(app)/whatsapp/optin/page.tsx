"use client";
import { ExternalLink, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, PageHeader, Skeleton } from "@/components/ui/Card";
import { Input, Select } from "@/components/ui/Form";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-api";
import { confirmWords, keywordProblem, OPTIN_PURPOSES, type OptinPurpose, type WaOptin, type WaOptinKeyword } from "@/lib/whatsapp";

const purposeLabel = (p: OptinPurpose) => OPTIN_PURPOSES.find((x) => x.value === p)?.label ?? p;

function Keyword({ k, canEdit, onChange }: { k: WaOptinKeyword; canEdit: boolean; onChange: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null);
  async function run(fn: () => Promise<unknown>, done: string) {
    setBusy(true); setErr(null);
    try { await fn(); toast(done); onChange(); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <li className="py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-2"><b className="font-mono text-[15px] text-ink">{k.keyword}</b><Badge tone={k.enabled ? "green" : "gray"}>{k.enabled ? "On" : "Off"}</Badge><span className="text-[13px] text-ink-500">{purposeLabel(k.purpose)}</span></span>
        {canEdit && (
          <span className="flex gap-2">
            <Button variant="secondary" size="sm" loading={busy} onClick={() => void run(() => api(`/whatsapp/optin/keywords/${k.id}`, { method: "PATCH", body: { enabled: !k.enabled } }), k.enabled ? "Switched off." : "Switched on.")}>{k.enabled ? "Switch off" : "Switch on"}</Button>
            <Button variant="ghost" size="sm" aria-label={`Delete ${k.keyword}`} disabled={busy} onClick={() => void run(() => api(`/whatsapp/optin/keywords/${k.id}`, { method: "DELETE" }), "Deleted.")}><Trash2 className="h-4 w-4" aria-hidden /></Button>
          </span>
        )}
      </div>
      <p className="mt-1 text-[13px] text-ink-500">What it means when a customer sends it: {k.wording}</p>
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
  return (
    <>
      <PageHeader title="Sign-ups" subtitle="Let customers join by messaging you. No phone number is typed on any page, and their own message is their agreement." />
      {q.error && <Alert tone="error">{q.error}</Alert>}
      {!o ? <Skeleton className="h-64" /> : (
        <div className="space-y-4">
          {!o.connected && <Alert tone="info" title="Connect your WhatsApp number first">Sign-ups arrive on your own WhatsApp number. <Link href="/whatsapp/connect" className="font-semibold text-brand-700 hover:underline">Connect it</Link></Alert>}
          {err && <Alert tone="warning">{err}</Alert>}

          <Card>
            <div className="flex items-start justify-between gap-3"><h2 className="text-lg font-semibold text-ink">A WhatsApp button on your QR page</h2><Badge tone={o.link_live ? "green" : "gray"}>{o.link_live ? "Showing" : "Not showing"}</Badge></div>
            <p className="mt-1 text-sm text-ink-700">Customers see an optional button. It opens WhatsApp with a message already written. They agree only by sending it, and only to what the message says.</p>
            <fieldset className="mt-4" disabled={!isAdmin}>
              <legend className="text-[13px] font-semibold text-ink-700">What do they agree to?</legend>
              <div className="mt-2 space-y-2">{OPTIN_PURPOSES.map((p) => (
                <label key={p.value} className="flex cursor-pointer items-start gap-2 text-sm text-ink-700"><input type="radio" name="purpose" className="mt-1 accent-[#BD3E1B]" checked={purpose === p.value} onChange={() => void save({ purpose: p.value }, "Saved.")} /><span><b className="text-ink">{p.label}</b><br /><span className="text-[13px] text-ink-500">{p.hint}</span></span></label>
              ))}</div>
            </fieldset>
            {s && (
              <div className="mt-4 rounded-xl bg-ink-50 p-3 text-[13px] text-ink-700">
                <p className="font-semibold text-ink">The message the customer sends</p>
                <p className="mt-1 break-words">{s.prefill_text}</p>
                <p className="mt-2 text-ink-500">Only this exact message counts. If a customer changes the words, they are not signed up.</p>
              </div>
            )}
            <label className="mt-4 flex items-start gap-2 text-sm text-ink-700"><input type="checkbox" className="mt-1 h-4 w-4 accent-[#BD3E1B]" disabled={!isAdmin} checked={s?.confirm_reply ?? true} onChange={(e) => void save({ confirm_reply: e.target.checked }, "Saved.")} />Send one short thank-you message when someone joins</label>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-[13px] text-ink-500"><span>Thank-you message:</span><Badge tone={cw.tone}>{cw.label}</Badge>{isAdmin && confirmStatus === null && <Button variant="secondary" size="sm" loading={busy === "prepare"} onClick={() => void prepare()}>Send for approval</Button>}</div>
            {isAdmin ? (
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <Button variant="brand" loading={busy === "save"} onClick={() => void save({ qr_enabled: !(s?.qr_enabled ?? false) }, s?.qr_enabled ? "Button hidden." : "Button switched on.")}>{s?.qr_enabled ? "Hide the button" : "Show the button on my QR page"}</Button>
                {o.link_example && <a href={o.link_example} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-[13px] font-semibold text-brand-700 hover:underline">Try it yourself<ExternalLink className="h-3.5 w-3.5" aria-hidden /></a>}
              </div>
            ) : <p className="mt-3 text-[13px] text-ink-500">Only the owner or an admin can change this.</p>}
            <p className="mt-3 text-[12px] text-ink-500">Customers can reply STOP at any time. If they do, only they can sign up again.</p>
          </Card>

          <Card>
            <h2 className="text-lg font-semibold text-ink">Keywords</h2>
            <p className="mt-1 text-sm text-ink-700">A word on a poster or counter card, like <b>JOINUS</b>. A customer who sends only that word, to your number, agrees to what it stands for. You can have up to {o.max_keywords}.</p>
            {o.keywords.length === 0 ? <p className="mt-3 text-[13px] text-ink-500">No keywords yet.</p> : <ul className="mt-2 divide-y divide-ink-100">{o.keywords.map((k) => <Keyword key={k.id} k={k} canEdit={isAdmin} onChange={() => void q.reload()} />)}</ul>}
            {isAdmin && o.keywords.length < o.max_keywords && (
              <div className="mt-4 grid items-start gap-3 sm:grid-cols-[1fr_1fr_auto]">
                <Input label="New keyword" value={word} maxLength={20} error={wordErr ?? undefined} onChange={(e) => { setWord(e.target.value); setWordErr(null); }} hint="3 to 20 letters or numbers." />
                <Select label="They agree to" value={wordPurpose} onChange={(e) => setWordPurpose(e.target.value as OptinPurpose)}>{OPTIN_PURPOSES.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}</Select>
                <Button variant="secondary" className="sm:mt-6" loading={busy === "word"} onClick={() => void addWord()}>Add keyword</Button>
              </div>
            )}
            {o.keywords.length >= o.max_keywords && <p className="mt-3 text-[13px] text-ink-500">You have the most keywords you can have. Delete one to add another.</p>}
          </Card>

          <p className="text-[13px] text-ink-500">Each customer who joins this way shows on <Link href="/whatsapp/contacts" className="font-semibold text-brand-700 hover:underline">Customers</Link> with how they joined, and in your customer export.</p>
        </div>
      )}
    </>
  );
}
