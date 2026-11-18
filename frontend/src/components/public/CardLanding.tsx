"use client";
import { API_V1 } from "@/lib/config";
import { Check, Copy, ExternalLink, Info, Loader2, QrCode, PenLine } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { LogoMark } from "@/components/ui/Brand";
import { publicButtonClass } from "@/components/ui/Button";
import { AiNotice } from "@/components/public/AiNotice";
import ReviewLanding from "@/components/public/ReviewLanding";
import { api, ApiError, errorMessage } from "@/lib/api";

export type Channel = "qr" | "nfc" | null;

interface Landing {
  state: "ok" | "unassigned" | "inactive" | "not_found" | "redirect";
  url?: string;
  message?: string;
  reason?: "paused";
  campaign?: { id: string } | null;
  business?: { name: string; logo_url: string | null; category: string | null; language: string };
  location?: { name: string; city: string | null; address: string | null };
  review_url?: string | null;
  ai_available?: boolean;
  ai_disclaimer?: string;
}

const COPY = {
  en: { h: "Share your experience", sub: "Tell us how your visit went, in your own words.", label: "Your experience", ph: "e.g. The doctor listened carefully and my pain is much better…" },
  hi: { h: "अपना अनुभव साझा करें", sub: "अपने शब्दों में बताइए कि आपका अनुभव कैसा रहा।", label: "आपका अनुभव", ph: "जैसे: डॉक्टर ने ध्यान से सुना और दर्द में बहुत आराम मिला…" },
  hinglish: { h: "Apna experience share karein", sub: "Apne shabdon mein batayein ki visit kaisi rahi.", label: "Aapka experience", ph: "e.g. Doctor ne dhyan se suna aur dard mein bahut aaram mila…" },
} as const;

async function track(token: string, type: "landing_view" | "copy" | "google_click", channel: Channel) {
  try { await fetch(`${API_V1}/public/c/${token}/event`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ type, channel }), keepalive: true }); } catch { /* analytics must never block the customer */ }
}

/**
 * What opens when a physical card is scanned (printed QR: /q/<id>, or the older /c/<id>) or tapped (NFC: /n/<id>). Both doors are the same
 * card; `channel` only says which one was used. A card bound to a live review campaign shows that campaign's page (the AI review assistant);
 * otherwise the plain card page below.
 */
export default function CardLanding({ token, channel }: { token: string; channel: Channel }) {
  const [data, setData] = useState<Landing | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [lang, setLang] = useState<"auto" | "en" | "hi" | "hinglish">("auto");
  const [suggestion, setSuggestion] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const viewed = useRef(false);

  useEffect(() => {
    // The referring HOST only (never the path or query): it says which app or site the visitor came from, nothing about who they are.
    let ref: string | undefined;
    try { ref = document.referrer ? new URL(document.referrer).hostname || undefined : undefined; } catch { ref = undefined; }
    api<Landing>(`/public/c/${token}`, { params: { ...(channel ? { channel } : {}), ...(ref ? { ref } : {}) } })
      .then((d) => {
        setData(d);
        if (d.state === "redirect") {
          // The address was chosen by FlowQR staff and stored on the server. Defence in depth: only ever follow a secure https address.
          try { const u = new URL(d.url ?? ""); if (u.protocol === "https:") window.location.replace(u.toString()); } catch { /* shown below as a plain link */ }
          return;
        }
        if (d.state === "ok" && !d.campaign && !viewed.current) { viewed.current = true; void track(token, "landing_view", channel); }
      })
      .catch((e) => {
        if (e instanceof ApiError && e.status === 404) setData({ state: "not_found", message: "We couldn't find this card." });
        else setLoadError(errorMessage(e));
      });
  }, [token, channel]);

  const biz = data?.business;
  const t = COPY[(biz?.language as keyof typeof COPY) ?? "en"] ?? COPY.en;
  const final = (suggestion ?? text).trim();

  async function improve() {
    setBusy(true); setAiError(null);
    try {
      const r = await api<{ suggestion: string }>(`/public/c/${token}/assist`, { method: "POST", body: { text, language: lang } });
      setSuggestion(r.suggestion);
    } catch (e) { setAiError(errorMessage(e)); } finally { setBusy(false); }
  }

  async function copy() {
    try { await navigator.clipboard.writeText(final); }
    catch {
      const ta = document.createElement("textarea");
      ta.value = final; ta.style.position = "fixed"; ta.style.opacity = "0"; document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); } finally { document.body.removeChild(ta); }
    }
    setCopied(true); setTimeout(() => setCopied(false), 2500); void track(token, "copy", channel);
  }

  if (loadError) return <Shell><Fallback title="Something went wrong" body={loadError} /></Shell>;
  if (!data) return <Shell><div className="space-y-4" aria-busy="true" aria-label="Loading"><div className="fq-skeleton h-14 w-3/4" /><div className="fq-skeleton h-8 w-1/2" /><div className="fq-skeleton h-40 w-full" /></div></Shell>;
  if (data.state === "redirect") {
    let safe: string | null = null;
    try { const u = new URL(data.url ?? ""); if (u.protocol === "https:") safe = u.toString(); } catch { safe = null; }
    return <Shell><div className="flex items-center gap-3 text-sm text-ink-700" role="status"><Loader2 className="h-4 w-4 animate-spin" aria-hidden />Taking you there&hellip;</div>
      {safe && <p className="mt-3 text-sm text-ink-500">Not moving? <a href={safe} rel="noopener noreferrer" className="font-medium text-ink underline underline-offset-2">Continue</a></p>}</Shell>;
  }
  if (data.state !== "ok") {
    const title = data.state === "unassigned" ? "This card isn't set up yet" : data.reason === "paused" ? "This card is switched off for now" : data.state === "inactive" ? "This card is no longer active" : "Card not found";
    return <Shell><Fallback title={title} body={(data.message ?? "") + " If you're the business owner, log in to FlowQR to manage your cards."} /></Shell>;
  }
  if (data.campaign) return <ReviewLanding campaignId={data.campaign.id} via={{ token, channel }} />;

  return (
    <Shell>
      <header className="flex items-center gap-3">
        {biz?.logo_url ? /* eslint-disable-next-line @next/next/no-img-element */ <img src={biz.logo_url} alt="" className="h-14 w-14 rounded-xl border border-ink-100 object-cover" /> :
          <span className="grid h-14 w-14 shrink-0 place-items-center rounded-xl bg-ink text-2xl font-semibold text-white" aria-hidden>{biz?.name.charAt(0).toUpperCase()}</span>}
        <div className="min-w-0">
          <h1 className="truncate text-xl font-semibold leading-tight">{biz?.name}</h1>
          <p className="truncate text-sm text-ink-500">{[data.location?.name, data.location?.city].filter(Boolean).join(" · ")}</p>
        </div>
      </header>

      <section className="mt-7">
        <h2 className="text-2xl font-semibold tracking-tight">{t.h}</h2>
        <p className="mt-1 text-ink-500">{t.sub}</p>

        <label htmlFor="exp" className="mt-5 block text-sm font-semibold text-ink-700">{t.label}</label>
        <textarea id="exp" value={text} onChange={(e) => { setText(e.target.value); setSuggestion(null); }} rows={5} maxLength={1200} placeholder={t.ph}
          className="mt-1.5 w-full resize-y rounded-lg border border-ink-300 bg-white p-3.5 text-[16px] leading-relaxed placeholder:text-ink-400 hover:border-ink-500 focus-visible:border-brand-600" />
        <div className="mt-1 flex justify-between text-xs text-ink-500"><span>Be honest. Your words, your review.</span><span>{text.length}/1200</span></div>

        {data.ai_available ? (<>
          <div className="mt-4"><AiNotice lang={lang === "auto" ? (biz?.language ?? "en") : lang} /></div>{/* before the button that sends the text for AI help; Hindi when Hindi is chosen */}
          <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="sm:w-44">
              <label htmlFor="lang" className="mb-1 block text-xs font-semibold text-ink-500">Language</label>
              <select id="lang" value={lang} onChange={(e) => setLang(e.target.value as typeof lang)} className="min-h-12 w-full rounded-lg border border-ink-300 bg-white px-3 text-[16px]">
                <option value="auto">Same as I wrote</option><option value="en">English</option><option value="hi">हिन्दी</option><option value="hinglish">Hinglish</option>
              </select>
            </div>
            <button onClick={() => void improve()} disabled={busy || text.trim().length < 8}
              className={publicButtonClass("primary", "flex-1")}>
              {busy ? <Loader2 className="h-5 w-5 fq-spin" aria-hidden /> : <PenLine className="h-5 w-5" aria-hidden />}{busy ? "Improving…" : "Improve my wording"}
            </button>
          </div>
        </>) : (
          <p className="mt-4 flex gap-2 rounded-lg bg-white p-3 text-sm text-ink-700"><Info className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />Writing help isn't available right now. You can still copy your own words and post them on Google.</p>
        )}
        {aiError && <p role="alert" className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{aiError}</p>}

        {suggestion !== null && (
          <div className="fq-enter mt-5 rounded-lg border border-ink-200 bg-white p-4">
            <p className="flex items-center gap-1.5 text-sm font-semibold text-ink-700"><PenLine className="h-4 w-4 text-ink-500" aria-hidden />AI-assisted suggestion · edit freely</p>
            <label htmlFor="sugg" className="sr-only">Suggested review (editable)</label>
            <textarea id="sugg" value={suggestion} onChange={(e) => setSuggestion(e.target.value)} rows={5} maxLength={4000}
              className="mt-2 w-full resize-y rounded-xl border border-ink-300 bg-white p-3 text-[16px] leading-relaxed focus-visible:border-brand-600" />
            <p className="mt-1.5 text-xs text-ink-500">{data.ai_disclaimer}</p>
            <button onClick={() => setSuggestion(null)} className="mt-1 inline-flex min-h-11 items-center text-sm font-semibold text-brand-700 hover:underline">Use my original words instead</button>
          </div>
        )}
      </section>

      <section className="mt-6 space-y-3" aria-label="Next steps">
        <button onClick={() => void copy()} disabled={!final}
          className={publicButtonClass("secondary", "w-full")}>
          {copied ? <Check className="h-5 w-5 text-ok" aria-hidden /> : <Copy className="h-5 w-5" aria-hidden />}{copied ? "Copied!" : "Copy review"}
        </button>
        {data.review_url ? (
          <a href={data.review_url} target="_blank" rel="noopener noreferrer" onClick={() => void track(token, "google_click", channel)}
            className={publicButtonClass("ink", "w-full")}>
            Continue to Google <ExternalLink className="h-4 w-4" aria-hidden />
          </a>
        ) : <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">This business hasn't added its Google review link yet. Please try again later.</p>}
        <p className="text-center text-xs text-ink-500">On Google, paste your text and choose your own star rating. You post it yourself. We never post for you.</p>
      </section>

      <footer className="mt-10 flex items-center justify-center gap-2 border-t border-ink-100 pt-5 text-xs text-ink-500"><LogoMark size={18} />Powered by FlowQR · no incentives, no filtering of reviews</footer>
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return <div className="min-h-dvh bg-ink-50"><main className="mx-auto w-full max-w-md px-5 pb-10 pt-[max(1.5rem,env(safe-area-inset-top))]">{children}</main></div>;
}

function Fallback({ title, body }: { title: string; body: string }) {
  return (
    <div className="grid place-items-center pt-24 text-center">
      <span className="grid h-16 w-16 place-items-center rounded-2xl border border-ink-200 bg-white text-ink-500"><QrCode className="h-8 w-8" aria-hidden /></span>
      <h1 className="mt-5 font-display text-xl font-semibold">{title}</h1><p className="mt-2 max-w-xs text-ink-500">{body}</p>
    </div>
  );
}
