"use client";
import { Check, Copy, ExternalLink, Info, Loader2, QrCode, Sparkles } from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { LogoMark } from "@/components/ui/Brand";
import { api, ApiError, errorMessage } from "@/lib/api";

interface Landing {
  state: "ok" | "unassigned" | "inactive" | "not_found";
  message?: string;
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

async function track(token: string, type: "landing_view" | "copy" | "google_click") {
  try { await fetch(`/api/v1/public/c/${token}/event`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ type }), keepalive: true }); } catch { /* analytics must never block the customer */ }
}

export default function CardLanding() {
  const { token } = useParams<{ token: string }>();
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
    api<Landing>(`/public/c/${token}`)
      .then((d) => {
        setData(d);
        if (d.state === "ok" && !viewed.current) { viewed.current = true; void track(token, "landing_view"); }
      })
      .catch((e) => {
        if (e instanceof ApiError && e.status === 404) setData({ state: "not_found", message: "We couldn't find this card." });
        else setLoadError(errorMessage(e));
      });
  }, [token]);

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
    setCopied(true); setTimeout(() => setCopied(false), 2500); void track(token, "copy");
  }

  if (loadError) return <Shell><Fallback title="Something went wrong" body={loadError} /></Shell>;
  if (!data) return <Shell><div className="space-y-4" aria-busy="true" aria-label="Loading"><div className="fq-skeleton h-14 w-3/4" /><div className="fq-skeleton h-8 w-1/2" /><div className="fq-skeleton h-40 w-full" /></div></Shell>;
  if (data.state !== "ok") {
    const title = data.state === "unassigned" ? "This card isn't set up yet" : data.state === "inactive" ? "This card is no longer active" : "Card not found";
    return <Shell><Fallback title={title} body={(data.message ?? "") + " If you're the business owner, log in to FlowQR to manage your cards."} /></Shell>;
  }

  return (
    <Shell>
      <header className="flex items-center gap-3">
        {biz?.logo_url ? /* eslint-disable-next-line @next/next/no-img-element */ <img src={biz.logo_url} alt="" className="h-14 w-14 rounded-2xl border border-ink-100 object-cover" /> :
          <span className="grid h-14 w-14 shrink-0 place-items-center rounded-2xl bg-brand-600 font-display text-2xl font-semibold text-white" aria-hidden>{biz?.name.charAt(0).toUpperCase()}</span>}
        <div className="min-w-0">
          <h1 className="truncate font-display text-xl font-semibold leading-tight">{biz?.name}</h1>
          <p className="truncate text-sm text-ink-500">{[data.location?.name, data.location?.city].filter(Boolean).join(" · ")}</p>
        </div>
      </header>

      <section className="mt-7">
        <h2 className="font-display text-2xl font-semibold">{t.h}</h2>
        <p className="mt-1 text-ink-500">{t.sub}</p>

        <label htmlFor="exp" className="mt-5 block text-sm font-semibold text-ink-700">{t.label}</label>
        <textarea id="exp" value={text} onChange={(e) => { setText(e.target.value); setSuggestion(null); }} rows={5} maxLength={1200} placeholder={t.ph}
          className="mt-1.5 w-full resize-y rounded-2xl border border-ink-200 bg-white p-4 text-[16px] leading-relaxed placeholder:text-ink-400 focus-visible:border-brand-500" />
        <div className="mt-1 flex justify-between text-xs text-ink-500"><span>Be honest. Your words, your review.</span><span>{text.length}/1200</span></div>

        {data.ai_available ? (
          <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="sm:w-44">
              <label htmlFor="lang" className="mb-1 block text-xs font-semibold text-ink-500">Language</label>
              <select id="lang" value={lang} onChange={(e) => setLang(e.target.value as typeof lang)} className="min-h-12 w-full rounded-xl border border-ink-200 bg-white px-3 text-[16px]">
                <option value="auto">Same as I wrote</option><option value="en">English</option><option value="hi">हिन्दी</option><option value="hinglish">Hinglish</option>
              </select>
            </div>
            <button onClick={() => void improve()} disabled={busy || text.trim().length < 8}
              className="inline-flex min-h-12 flex-1 items-center justify-center gap-2 rounded-xl bg-brand-600 px-5 font-semibold text-white transition-colors hover:bg-brand-700 disabled:opacity-50">
              {busy ? <Loader2 className="h-5 w-5 fq-spin" aria-hidden /> : <Sparkles className="h-5 w-5" aria-hidden />}{busy ? "Improving…" : "Improve my wording"}
            </button>
          </div>
        ) : (
          <p className="mt-4 flex gap-2 rounded-xl bg-ink-50 p-3 text-sm text-ink-700"><Info className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />Writing help isn't available right now. You can still copy your own words and post them on Google.</p>
        )}
        {aiError && <p role="alert" className="mt-3 rounded-xl bg-amber-50 p-3 text-sm text-amber-900">{aiError}</p>}

        {suggestion !== null && (
          <div className="fq-enter mt-5 rounded-2xl border border-brand-200 bg-brand-50/50 p-4">
            <p className="flex items-center gap-1.5 text-sm font-semibold text-brand-800"><Sparkles className="h-4 w-4" aria-hidden />AI-assisted suggestion · edit freely</p>
            <label htmlFor="sugg" className="sr-only">Suggested review (editable)</label>
            <textarea id="sugg" value={suggestion} onChange={(e) => setSuggestion(e.target.value)} rows={5} maxLength={4000}
              className="mt-2 w-full resize-y rounded-xl border border-brand-200 bg-white p-3 text-[16px] leading-relaxed focus-visible:border-brand-500" />
            <p className="mt-1.5 text-xs text-ink-500">{data.ai_disclaimer}</p>
            <button onClick={() => setSuggestion(null)} className="mt-1 inline-flex min-h-11 items-center text-sm font-semibold text-brand-700 hover:underline">Use my original words instead</button>
          </div>
        )}
      </section>

      <section className="mt-6 space-y-3" aria-label="Next steps">
        <button onClick={() => void copy()} disabled={!final}
          className="inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-xl border border-ink-200 bg-white px-5 font-semibold transition-colors hover:bg-ink-50 disabled:opacity-50">
          {copied ? <Check className="h-5 w-5 text-g-green" aria-hidden /> : <Copy className="h-5 w-5" aria-hidden />}{copied ? "Copied!" : "Copy review"}
        </button>
        {data.review_url ? (
          <a href={data.review_url} target="_blank" rel="noopener noreferrer" onClick={() => void track(token, "google_click")}
            className="inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-xl bg-ink px-5 font-semibold text-white transition-colors hover:bg-ink-700">
            Continue to Google <ExternalLink className="h-4 w-4" aria-hidden />
          </a>
        ) : <p className="rounded-xl bg-amber-50 p-3 text-sm text-amber-900">This business hasn't added its Google review link yet. Please try again later.</p>}
        <p className="text-center text-xs text-ink-500">On Google, paste your text and choose your own star rating. You post it yourself. We never post for you.</p>
      </section>

      <footer className="mt-10 flex items-center justify-center gap-2 border-t border-ink-100 pt-5 text-xs text-ink-500"><LogoMark size={18} />Powered by FlowQR · no incentives, no filtering of reviews</footer>
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return <div className="min-h-dvh bg-gradient-to-b from-brand-50/60 to-white"><main className="mx-auto w-full max-w-md px-5 pb-10 pt-[max(1.5rem,env(safe-area-inset-top))]">{children}</main></div>;
}

function Fallback({ title, body }: { title: string; body: string }) {
  return (
    <div className="grid place-items-center pt-24 text-center">
      <span className="grid h-16 w-16 place-items-center rounded-2xl bg-white text-ink-400 shadow-card"><QrCode className="h-8 w-8" aria-hidden /></span>
      <h1 className="mt-5 font-display text-xl font-semibold">{title}</h1><p className="mt-2 max-w-xs text-ink-500">{body}</p>
    </div>
  );
}
