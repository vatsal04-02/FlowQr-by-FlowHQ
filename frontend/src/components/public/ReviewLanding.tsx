"use client";
import { API_V1 } from "@/lib/config";
import clsx from "clsx";
import { Check, Clock, Copy, ExternalLink, Loader2, Pencil, QrCode, ShieldCheck, PenLine, Star, TriangleAlert, UserCheck } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { AiNotice } from "@/components/public/AiNotice";
import { LandingFrame } from "@/components/review-growth/LandingFrame";
import { api, ApiError } from "@/lib/api";
import { COPY, type Background, type Lang, type Rating, type Topic } from "@/lib/review-growth";

interface Landing {
  state: "ok";
  business: { name: string; category: string | null; logo_url: string | null };
  location: { name: string; city: string | null; address: string | null };
  branding: { brand_color: string; background: Background; welcome_message: string | null; footer_message: string | null };
  generator: { default_language: Lang; languages: Lang[]; max_input_chars: number };
  suggestions: Topic[];
  ai_available: boolean; google_ready: boolean; review_url: string | null; review_url_kind: string;
  submission?: { mode: "handoff" | "direct" }; // "handoff" today: Google offers no public way to submit a review for a customer
}
interface DraftResp {
  session_id: string | null; draft: string | null; ai_status: "ok" | "manual" | "needs_more" | "rejected" | "unavailable"; ask?: "detail";
  retryable: boolean; generation_count: number; remaining_drafts: number; follow_up?: string | null;
}
/** Where the text in the box came from: a neutral AI opener, a rewrite from the customer's stars/topics, or the customer's own typing. */
type Origin = "none" | "refined";
type Notice = { tone: "info" | "error"; text: string; retry?: () => void } | null;
type Handoff = { copied: boolean | null; returned?: boolean } | null;

const RATINGS: Rating[] = [1, 2, 3, 4, 5];
const MIN_CHARS = 10;
const btn = "inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-xl px-5 text-[16px] font-semibold transition active:translate-y-px";
// NB: Tailwind can't tell whether `x-[var(--brand)]` is a colour or a length, so the `color:` hint is required for accent/border/ring.
const ring = "focus-visible:ring-[color:var(--brand)]";
const primary = `${btn} ${ring} bg-[var(--brand)] text-[var(--on-brand)] shadow-panel hover:brightness-95`;
const secondary = `${btn} ${ring} border border-ink-300 bg-white text-ink hover:bg-ink-50`;
const headingCls = "text-[1.55rem] font-semibold sm:text-[1.7rem] leading-tight tracking-tight outline-none focus-visible:ring-0 focus-visible:ring-offset-0";
const STORE = (id: string) => `fq-review-${id}`;

const post = <T,>(id: string, path: string, body: unknown) => api<T>(`/public/reviews/${id}${path}`, { method: "POST", body });

/** Copy synchronously inside the tap (clipboard permission and iOS both require the user gesture), with two independent mechanisms. */
function legacyCopy(value: string): boolean {
  try {
    const ta = document.createElement("textarea");
    ta.value = value; ta.setAttribute("readonly", ""); ta.setAttribute("aria-hidden", "true");
    ta.style.cssText = "position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;font-size:16px"; // 16px: iOS zooms smaller fields
    document.body.appendChild(ta); ta.focus(); ta.select(); ta.setSelectionRange(0, value.length);
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch { return false; }
}
function copyToClipboard(value: string): Promise<boolean> {
  const sync = legacyCopy(value);
  const modern = typeof navigator !== "undefined" && navigator.clipboard?.writeText ? navigator.clipboard.writeText(value).then(() => true, () => false) : Promise.resolve(false);
  return modern.then((ok) => ok || sync);
}

/** Set when the visitor came through a physical card (printed QR or NFC tap): their milestones are also counted on that card, with the way they got in. */
export type CardVia = { token: string; channel: "qr" | "nfc" | null };

export default function ReviewLanding({ campaignId, via }: { campaignId: string; via?: CardVia }) {
  const viaRef = useRef(via);
  viaRef.current = via;
  const sent = useRef<Set<string>>(new Set());
  /** Count a milestone on the card. Fire and forget: analytics must never slow down or change what the customer sees. */
  const trackCard = useCallback((type: "landing_view" | "ai_assist" | "copy" | "google_click", once = true) => {
    const v = viaRef.current;
    if (!v || (once && sent.current.has(type))) return;
    sent.current.add(type);
    try { void fetch(`${API_V1}/public/c/${v.token}/event`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ type, channel: v.channel }), keepalive: true }).catch(() => undefined); } catch { /* ignore */ }
  }, []);
  const [page, setPage] = useState<Landing | null>(null);
  const [fail, setFail] = useState<{ title: string; body: string; retry?: boolean } | null>(null);
  const [lang, setLang] = useState<Lang>("en");
  const [rating, setRating] = useState<Rating | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [text, setText] = useState("");
  const [aiText, setAiText] = useState("");          // the last text the AI wrote into the box: anything else in there is the customer's own
  const [origin, setOrigin] = useState<Origin>("none");
  const [loading, setLoading] = useState<null | "refine">(null);
  const [notice, setNotice] = useState<Notice>(null);
  const [ask, setAsk] = useState(false);              // permission prompt: replace the customer's edited text with a rewrite?
  const [undo, setUndo] = useState<string | null>(null);
  const [followUp, setFollowUp] = useState<string | null>(null);
  const [session, setSession] = useState<string | null>(null);
  const [handoff, setHandoff] = useState<Handoff>(null);
  const [copiedFlash, setCopiedFlash] = useState(false);
  const [needStars, setNeedStars] = useState(false);
  const [short, setShort] = useState(false);
  const [ready, setReady] = useState(false);
  const [consent, setConsent] = useState(false);       // direct submission only: explicit consent to submit exactly this text
  const [submitState, setSubmitState] = useState<null | "sending" | "done" | "failed">(null);

  const textRef = useRef(text); textRef.current = text;
  const aiRef = useRef(aiText); aiRef.current = aiText;
  const sessionRef = useRef(session); sessionRef.current = session;
  const originRef = useRef(origin); originRef.current = origin;
  const ratingRef = useRef(rating); ratingRef.current = rating;
  const pickedRef = useRef(picked); pickedRef.current = picked;
  const langRef = useRef(lang); langRef.current = lang;
  const handoffRef = useRef(handoff); handoffRef.current = handoff;
  const req = useRef(0);
  const lastKey = useRef("");
  const dismissed = useRef("");
  const starsRef = useRef<HTMLDivElement>(null);
  const boxRef = useRef<HTMLTextAreaElement>(null);
  const t = COPY[lang];

  const edited = () => textRef.current.trim() !== "" && textRef.current.trim() !== aiRef.current.trim();
  const label = (s: Topic) => (lang === "hi" ? s.hi : s.en);

  // ---------------------------------------------------------------- load the page and restore a review in progress. The box starts EMPTY: nothing is pre-written for the customer.
  const load = useCallback(() => {
    setFail(null);
    api<Landing>(`/public/reviews/${campaignId}`)
      .then((d) => {
        setPage(d);
        trackCard("landing_view");
        let startLang = d.generator.default_language;
        let restored = false;
        try {
          const raw = window.localStorage.getItem(STORE(campaignId));
          const s = raw ? JSON.parse(raw) : null;
          if (s && Date.now() - s.ts < 24 * 3600 * 1000 && typeof s.text === "string" && s.text.trim()) { // coming back (from Google, or after a refresh): the review is exactly as they left it
            restored = true;
            if (d.generator.languages.includes(s.lang)) startLang = s.lang;
            setText(s.text); setAiText(s.aiText ?? ""); setOrigin(s.origin ?? "none"); setRating(s.rating ?? null); setPicked(Array.isArray(s.picked) ? s.picked : []);
            if (s.handoff) setHandoff({ copied: s.copied ?? null, returned: true });
          }
        } catch { /* private mode or blocked storage: start fresh */ }
        setLang(startLang);
        setReady(true);
      })
      .catch((e) => {
        if (e instanceof ApiError && e.status === 404) setFail({ title: "Page not found", body: "We couldn't find this review page. If you scanned a QR code, ask the business for a new one." });
        else if (e instanceof ApiError && e.status === 410 && (e.detail as { state?: string } | undefined)?.state === "deactivated") setFail({ title: "This QR code was switched off", body: "The business switched this QR code off. Please ask them for a new one." });
        else if (e instanceof ApiError && e.status === 410) setFail({ title: "This page is no longer active", body: "The business has paused or retired this review page." });
        else if (e instanceof ApiError && e.status === 429) setFail({ title: "Too many attempts", body: "Please wait a few minutes and scan the code again.", retry: true });
        else setFail({ title: "Something went wrong", body: "Please check your connection and try again.", retry: true });
      });
  }, [campaignId, trackCard]);
  useEffect(load, [load]);

  // keep the review safe: survive a refresh, or a return from Google in the same tab. Saved shortly after every change, immediately at the tap,
  // and whenever the page is hidden (the tap sends them to another tab).
  const persist = useCallback((o: { handoff?: boolean; copied?: boolean | null } = {}) => {
    try {
      window.localStorage.setItem(STORE(campaignId), JSON.stringify({
        text: textRef.current, aiText: aiRef.current, origin: originRef.current, rating: ratingRef.current, picked: pickedRef.current, lang: langRef.current,
        handoff: o.handoff ?? !!handoffRef.current, copied: o.copied !== undefined ? o.copied : handoffRef.current?.copied ?? null, ts: Date.now(),
      }));
    } catch { /* storage unavailable */ }
  }, [campaignId]);
  useEffect(() => {
    if (!ready) return;
    const id = setTimeout(() => persist(), 400);
    return () => clearTimeout(id);
  }, [ready, persist, text, aiText, origin, rating, picked, lang, handoff]);
  useEffect(() => {
    if (!ready) return;
    const flush = () => { if (document.visibilityState === "hidden") persist(); };
    document.addEventListener("visibilitychange", flush); window.addEventListener("pagehide", flush as () => void);
    return () => { document.removeEventListener("visibilitychange", flush); window.removeEventListener("pagehide", flush as () => void); };
  }, [ready, persist]);

  // ---------------------------------------------------------------- automatic drafting
  /** Rewrite from the customer's stars + topics. Their own words (anything in the box the AI did not write) go in as their words; text the AI wrote never does. */
  const refine = useCallback(async (replaceEdits: boolean) => {
    if (rating === null || picked.length === 0) return;
    const mine = edited() ? textRef.current.trim().slice(0, 1200) : "";
    const before = textRef.current;
    const id = ++req.current;
    setLoading("refine"); setNotice(null); setAsk(false);
    try {
      let r: DraftResp | null = null;
      if (sessionRef.current) {
        try { r = await post<DraftResp>(campaignId, "/refine", { session_id: sessionRef.current, rating, suggestions: picked, text: mine, language: lang }); }
        catch (e) { if (!(e instanceof ApiError && (e.status === 404 || e.status === 410))) throw e; setSession(null); sessionRef.current = null; }
      }
      if (!r) r = await post<DraftResp>(campaignId, "/generate", { mode: "ai", rating, suggestions: picked, text: mine, language: lang });
      if (id !== req.current) return; // a newer change superseded this one
      if (r.session_id) { setSession(r.session_id); sessionRef.current = r.session_id; }
      if (r.ai_status === "ok" && r.draft) {
        if (!replaceEdits && textRef.current !== before) { setAsk(true); return; } // they typed while we were writing: never overwrite
        if (mine) setUndo(before); else setUndo(null);
        setText(r.draft); setAiText(r.draft); setOrigin("refined"); setFollowUp(r.follow_up ?? null); setHandoff(null); trackCard("ai_assist");
      } else if (r.ai_status === "needs_more") setNotice({ tone: "info", text: t.askMore });
      else if (r.ai_status === "rejected") setNotice({ tone: "error", text: t.rejected, retry: () => void refine(false) });
      else if (r.retryable) setNotice({ tone: "error", text: t.retryMsg, retry: () => void refine(false) });
      else setNotice({ tone: "info", text: t.aiDown });
    } catch (e) {
      if (id !== req.current) return;
      const s = e instanceof ApiError ? e.status : 0;
      if (s === 429 || s === 403) setNotice({ tone: "info", text: t.aiBusy });
      else setNotice({ tone: "error", text: t.retryMsg, retry: () => void refine(false) });
    } finally { if (id === req.current) setLoading(null); }
  }, [rating, picked, lang, campaignId, t]); // eslint-disable-line react-hooks/exhaustive-deps

  // when the stars, topics or language change: refine in place (debounced). A customer's own edits are never replaced without asking.
  const selKey = `${rating ?? ""}|${[...picked].sort().join(",")}|${lang}`;
  useEffect(() => {
    if (!ready) return;
    if (!lastKey.current) { lastKey.current = selKey; return; }
    if (selKey === lastKey.current) return;
    const id = setTimeout(() => {
      lastKey.current = selKey;
      if (rating !== null && picked.length > 0) {
        if (edited()) { if (dismissed.current !== selKey) setAsk(true); } else void refine(false);
      }
    }, 700);
    return () => clearTimeout(id);
  }, [selKey, ready]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---------------------------------------------------------------- the one tap
  function onCopyContinue(e: React.MouseEvent<HTMLAnchorElement>) {
    const value = textRef.current.trim();
    if (value.length < MIN_CHARS) { e.preventDefault(); setShort(true); boxRef.current?.focus(); return; }
    // No preventDefault: the browser follows the link natively (a real link click is never popup-blocked), while the copy starts in the same gesture.
    const pending = copyToClipboard(value);
    setShort(false); setHandoff({ copied: null }); setAsk(false);
    persist({ handoff: true, copied: null });
    void pending.then((ok) => { setHandoff({ copied: ok }); persist({ handoff: true, copied: ok }); void track(value, ok); });
  }
  async function track(value: string, copied: boolean) {
    trackCard("google_click"); if (copied) trackCard("copy");
    try { // one request, sent with keepalive so it completes even if the page is backgrounded: tracking can never block, delay or change what the customer sees
      const r = await api<{ session_id: string }>(`/public/reviews/${campaignId}/handoff`, {
        method: "POST", keepalive: true,
        body: { session_id: sessionRef.current, final_text: value.slice(0, 2000), copied, rating: ratingRef.current, suggestions: pickedRef.current, language: langRef.current },
      });
      if (r?.session_id) { setSession(r.session_id); sessionRef.current = r.session_id; }
    } catch (e) { if (e instanceof ApiError && (e.status === 404 || e.status === 410)) { sessionRef.current = null; setSession(null); } /* otherwise ignore */ }
  }  async function copyOnly() {
    const value = textRef.current.trim();
    if (value.length < MIN_CHARS) { setShort(true); boxRef.current?.focus(); return; }
    setShort(false);
    const ok = await copyToClipboard(value);
    if (ok) trackCard("copy");
    setHandoff((h) => ({ ...(h ?? {}), copied: ok }));
    if (ok) { setCopiedFlash(true); setTimeout(() => setCopiedFlash(false), 2500); }
    else { boxRef.current?.focus(); boxRef.current?.select(); } // last resort: select the text so they can copy it by hand
  }

  /** Direct submission to Google. Only reachable when the server says an approved provider is enabled (never today). Success is shown ONLY when
   *  the server reports Google confirmed it; every other outcome falls back to the copy-and-open-Google route with the review kept. */
  async function submitReview() {
    const value = textRef.current.trim();
    if (value.length < MIN_CHARS) { setShort(true); boxRef.current?.focus(); return; }
    if (ratingRef.current === null) { setNeedStars(true); starsRef.current?.querySelector<HTMLElement>("[tabindex='0']")?.focus(); return; }
    if (!consent) return;
    setSubmitState("sending"); setAsk(false);
    try {
      const r = await api<{ published: boolean; session_id?: string }>(`/public/reviews/${campaignId}/submit`, {
        method: "POST", keepalive: true,
        body: { session_id: sessionRef.current, final_text: value.slice(0, 2000), rating: ratingRef.current, consent: true, suggestions: pickedRef.current, language: langRef.current },
      });
      if (r?.session_id) { setSession(r.session_id); sessionRef.current = r.session_id; }
      setSubmitState(r?.published === true ? "done" : "failed");
    } catch { setSubmitState("failed"); }
  }
  const pickRating = (n: Rating) => { setRating(n); setNeedStars(false); };
  const toggle = (id: string) => { setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id])); if (rating === null) setNeedStars(true); };
  function onStarKey(e: React.KeyboardEvent) {
    const move = e.key === "ArrowRight" || e.key === "ArrowUp" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowDown" ? -1 : 0;
    if (!move) return;
    e.preventDefault();
    const n = Math.min(5, Math.max(1, (rating ?? (move > 0 ? 0 : 6)) + move)) as Rating;
    pickRating(n);
    requestAnimationFrame(() => starsRef.current?.querySelectorAll<HTMLElement>("[role=radio]")[n - 1]?.focus());
  }
  async function another() { // a different wording of the same thing, only offered while the box holds untouched AI text
    if (!sessionRef.current) return;
    setLoading("refine"); setNotice(null);
    try {
      const r = await post<DraftResp>(campaignId, "/regenerate", { session_id: sessionRef.current, language: lang });
      if (r.ai_status === "ok" && r.draft) { setText(r.draft); setAiText(r.draft); setFollowUp(r.follow_up ?? null); }
      else setNotice({ tone: "info", text: t.noOther });
    } catch (e) { setNotice({ tone: "info", text: e instanceof ApiError && e.status === 429 ? t.noMoreRewrites : t.retryMsg }); } finally { setLoading(null); }
  }

  if (fail) {
    return (
      <div className="grid min-h-dvh place-items-center bg-ink-50 px-6 text-center">
        <div className="max-w-xs">
          <span className="mx-auto grid h-16 w-16 place-items-center rounded-2xl border border-ink-200 bg-white text-ink-500"><QrCode className="h-8 w-8" aria-hidden /></span>
          <h1 className="mt-5 text-xl font-semibold">{fail.title}</h1><p className="mt-2 text-ink-500">{fail.body}</p>
          {fail.retry && <button onClick={load} className="mt-5 inline-flex min-h-11 items-center rounded-xl border border-ink-300 bg-white px-5 font-semibold">Try again</button>}
        </div>
      </div>
    );
  }
  if (!page) {
    return (
      <div className="min-h-dvh bg-ink-50"><div className="mx-auto max-w-md space-y-4 px-5 pt-8" aria-busy="true" aria-label="Loading">
        <div className="fq-skeleton h-14 w-3/4" /><div className="fq-skeleton h-8 w-1/2" /><div className="fq-skeleton h-44 w-full" /></div></div>
    );
  }

  const place = [page.location.name, page.location.city].filter(Boolean).join(" · ");
  const max = Math.min(page.generator.max_input_chars, 2000);
  const chips = page.suggestions;
  const reviewUrl = page.review_url;
  const isEdited = text.trim() !== "" && text.trim() !== aiText.trim();
  const badge = handoff?.copied ? { icon: Check, text: t.badgeCopied } : isEdited || (origin === "none" && text.trim()) ? { icon: Pencil, text: t.badgeEdited }
    : origin === "refined" ? { icon: PenLine, text: t.badgeRefined } : null;
  const ready2go = text.trim().length >= MIN_CHARS;
  const busy = loading !== null;

  const LangToggle = page.generator.languages.length > 1 ? (
    <div role="radiogroup" aria-label={t.language} className="inline-grid grid-cols-2 rounded-xl bg-black/5 p-0.5">
      {([["en", "English"], ["hi", "हिन्दी"]] as const).filter(([v]) => page.generator.languages.includes(v)).map(([v, l]) => (
        <button key={v} type="button" role="radio" aria-checked={lang === v} onClick={() => setLang(v)}
          className={clsx("min-h-9 rounded-[10px] px-3.5 text-[13px] font-semibold transition", ring, lang === v ? "bg-white text-ink shadow-panel" : "text-ink-500")}>{l}</button>))}
    </div>
  ) : null;

  const isDirect = page.submission?.mode === "direct" && submitState !== "failed"; // never true today; a failed direct submit drops back to the supported route
  const sending = submitState === "sending";
  const ctaStyle = { background: "linear-gradient(135deg, var(--brand), color-mix(in srgb, var(--brand) 80%, #000))", boxShadow: "0 14px 28px -12px color-mix(in srgb, var(--brand) 75%, transparent)" } as const;
  const ctaCls = clsx(btn, ring, "group !min-h-[3.4rem] !px-4 !text-[16px] text-[var(--on-brand)] hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-55", !ready2go && "opacity-60");

  return (
    <LandingFrame business={{ name: page.business.name, logo_url: page.business.logo_url, location: place }} branding={page.branding}>
      <section lang={lang} className="space-y-4">
        <div className="fq-rise">
          <h2 className={headingCls}>{t.h}</h2>
          <p className="mt-1 text-[15px] leading-relaxed text-ink-500 [@media(max-height:620px)]:hidden">{t.sub}</p>
          <ul className="mt-2.5 flex flex-wrap [@media(max-height:620px)]:hidden gap-x-4 gap-y-1 text-[12px] font-medium text-ink-500">
            {([[Clock, t.trust[0]], [ShieldCheck, t.trust[1]], [UserCheck, t.trust[2]]] as const).map(([Icon, label2]) => (
              <li key={label2} className="inline-flex items-center gap-1"><Icon className="h-3.5 w-3.5 text-[var(--brand-ink)]" aria-hidden />{label2}</li>))}
          </ul>
          {LangToggle && <div className="mt-3">{LangToggle}</div>}
          {page.ai_available && <div className="mt-3"><AiNotice lang={lang} /></div>}{/* shown before anything can be sent for AI help, in the language the customer picked */}
        </div>

        {submitState === "done" && (
          <div role="status" className="fq-enter rounded-3xl bg-white p-5 text-center shadow-panel ring-1 ring-black/5">
            <span className="mx-auto grid h-12 w-12 place-items-center rounded-full bg-[var(--brand-tint)] text-[var(--brand-ink)]"><Check className="h-6 w-6" aria-hidden /></span>
            <p className="mt-3 text-lg font-semibold text-ink">{t.submittedH}</p>
            <p className="mt-1 text-sm text-ink-500">{t.submittedSub}</p>
          </div>
        )}
        {submitState === "failed" && (
          <div role="alert" className="fq-enter rounded-2xl bg-amber-50 p-4 ring-1 ring-amber-300">
            <p className="flex items-start gap-2 text-[15px] font-semibold text-ink"><TriangleAlert className="mt-0.5 h-5 w-5 shrink-0 text-amber-700" aria-hidden />{t.submitFailedH}</p>
            <p className="mt-1 text-sm leading-relaxed text-ink-700">{t.submitFailedSub}</p>
          </div>
        )}
        {handoff && (
          <div role="status" className={clsx("fq-enter rounded-2xl p-4 ring-1", handoff.copied === false ? "bg-amber-50 ring-amber-300" : "bg-white ring-black/10 shadow-panel")}>
            {handoff.returned && handoff.copied !== false && <p className="mb-1 text-sm text-ink-500">{t.welcomeBack}</p>}
            <p className="flex items-start gap-2 text-[15px] font-semibold text-ink">
              {handoff.copied === false ? <TriangleAlert className="mt-0.5 h-5 w-5 shrink-0 text-amber-700" aria-hidden /> : <Check className="mt-0.5 h-5 w-5 shrink-0 text-ok" aria-hidden />}
              {handoff.copied === false ? t.copyFailedH : t.copiedH}
            </p>
            <p className="mt-1 text-sm leading-relaxed text-ink-700">{handoff.copied === false ? t.copyFailedSub : t.copiedSub}</p>
            <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1">
              <button type="button" onClick={() => void copyOnly()} className="min-h-10 text-sm font-semibold text-[var(--brand-ink)] hover:underline">{copiedFlash ? t.copied : t.copyAgain}</button>
              {reviewUrl && <a href={reviewUrl} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-10 items-center gap-1 text-sm font-semibold text-[var(--brand-ink)] hover:underline">{t.openAgain}<ExternalLink className="h-3.5 w-3.5" aria-hidden /></a>}
            </div>
          </div>
        )}

        {submitState !== "done" && (
          <div className="fq-rise rounded-[28px] bg-white/95 p-4 shadow-[0_22px_44px_-22px_rgba(20,24,28,.35)] ring-1 ring-black/5 sm:p-5" style={{ ["--d" as string]: "70ms" }}>
            {/* ---------------------------------------------- stars */}
            <div>
              <p id="rate-l" className="text-sm font-semibold text-ink-700">{t.rateLabel}</p>
              <div ref={starsRef} role="radiogroup" aria-labelledby="rate-l" aria-describedby="rate-h" onKeyDown={onStarKey} className="mt-0.5 flex flex-wrap items-center gap-x-0.5">
                {RATINGS.map((n) => {
                  const on = rating !== null && n <= rating;
                  return (
                    <button key={n} type="button" role="radio" aria-checked={rating === n} aria-label={`${n} ${n === 1 ? t.star : t.stars}, ${t.rateWords[n - 1]}`}
                      tabIndex={rating === n || (rating === null && n === 1) ? 0 : -1} onClick={() => pickRating(n)}
                      className={clsx("grid h-14 w-12 place-items-center rounded-xl transition active:scale-90", ring)}>
                      <Star key={rating === n ? `p${n}` : n} className={clsx("h-9 w-9 transition-colors duration-200", on ? "" : "text-ink-300", rating === n && "fq-pop")}
                        style={on ? { fill: "var(--brand)", color: "var(--brand)", filter: "drop-shadow(0 3px 5px color-mix(in srgb, var(--brand) 40%, transparent))" } : undefined} strokeWidth={1.75} aria-hidden />
                    </button>
                  );
                })}
                <span className="ml-2 min-w-20 text-[16px] font-semibold text-[var(--brand-ink)]" aria-live="polite">{rating ? t.rateWords[rating - 1] : ""}</span>
              </div>
              <p id="rate-h" role={needStars ? "alert" : undefined} className={clsx("text-sm", needStars ? "font-medium text-amber-800" : rating !== null && picked.length === 0 && chips.length > 0 ? "text-ink-500" : "sr-only")}>{needStars ? t.needStars : rating !== null && picked.length === 0 && chips.length > 0 ? t.needTopics : t.rateHint}</p>
            </div>

            {/* ---------------------------------------------- the review box: the suggestion is here before they do anything */}
            <div className="mt-3 border-t border-black/5 pt-3">
              <div className="mb-1.5 flex min-h-6 items-center justify-between gap-3">
                <label htmlFor="review" className="text-sm font-semibold text-ink-700">{t.editorLabel}</label>
                {badge && (
                  <span className={clsx("inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-semibold", handoff?.copied ? "bg-emerald-50 text-ok" : "bg-[var(--brand-tint)] text-[var(--brand-ink)]")} data-testid="origin-badge">
                    <badge.icon className="h-3 w-3" aria-hidden />{badge.text}
                  </span>
                )}
              </div>
              <div className="relative">
                <textarea id="review" ref={boxRef} rows={5} value={text} maxLength={max} readOnly={busy || sending} aria-busy={busy || undefined} aria-describedby="review-hint" placeholder={t.editorPh}
                  onChange={(e) => { setText(e.target.value); setShort(false); setUndo(null); if (handoff?.copied === false) setHandoff(null); }}
                  className={clsx("w-full resize-y rounded-2xl border px-4 py-3.5 text-[16px] leading-relaxed text-ink placeholder:text-ink-400 transition-colors hover:border-ink-500 focus-visible:border-[color:var(--brand)] focus-visible:bg-white", ring,
                    busy ? "border-ink-200 text-transparent" : "border-ink-200", short && "border-amber-500", !isEdited && origin !== "none" && !busy ? "bg-[var(--brand-tint)]" : "bg-white")} />
                {busy && (
                  <div className="pointer-events-none absolute inset-0 rounded-2xl px-4 py-4" aria-hidden>
                    <div className="fq-skeleton mb-2.5 h-4 w-11/12" /><div className="fq-skeleton mb-2.5 h-4 w-full" /><div className="fq-skeleton mb-2.5 h-4 w-10/12" /><div className="fq-skeleton h-4 w-7/12" />
                  </div>
                )}
                {busy && <span className="sr-only" role="status">{t.tailoring}</span>}
              </div>
              <div id="review-hint" className="mt-1 flex min-h-5 items-start justify-between gap-3 text-xs text-ink-500">
                <span role={short ? "alert" : undefined} className={clsx(short && "font-medium text-amber-800")}>{short || (!busy && text.trim().length > 0 && text.trim().length < MIN_CHARS) ? t.tooShort : busy ? t.tailoring : ""}</span>
                <span className="shrink-0 tabular-nums">{text.length}/{max}</span>
              </div>
              <div className="mt-0.5 flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-sm">
                <div className="flex flex-wrap gap-x-4">
                  {!busy && undo && <button type="button" onClick={() => { setText(undo); setUndo(null); setOrigin("none"); }} className="min-h-9 font-semibold text-[var(--brand-ink)] hover:underline">{t.undo}</button>}
                  {!busy && origin !== "none" && !isEdited && <button type="button" onClick={() => void another()} className="min-h-9 font-semibold text-[var(--brand-ink)] hover:underline">{t.another}</button>}
                </div>
                {reviewUrl && (
                  <button type="button" onClick={() => void copyOnly()} data-testid="copy-only" className={clsx("inline-flex min-h-9 items-center gap-1.5 rounded-lg px-2 font-semibold text-[var(--brand-ink)] hover:underline", ring)}>
                    {copiedFlash ? <Check className="h-4 w-4 text-ok" aria-hidden /> : <Copy className="h-4 w-4" aria-hidden />}{copiedFlash ? t.copied : t.copyBtn}
                  </button>
                )}
              </div>

              {ask && (
                <div role="alertdialog" aria-labelledby="refine-q" className="fq-enter mt-3 rounded-xl bg-white p-3.5 ring-1 ring-black/10">
                  <p id="refine-q" className="text-sm font-medium">{t.refineQ}</p>
                  <div className="mt-3 grid grid-cols-2 gap-2">
                    <button type="button" onClick={() => { dismissed.current = selKey; setAsk(false); }} className={clsx(secondary, "!min-h-11 !px-3 !text-sm")}>{t.refineNo}</button>
                    <button type="button" onClick={() => void refine(true)} className={clsx(primary, "!min-h-11 !px-3 !text-sm")}>{t.refineYes}</button>
                  </div>
                </div>
              )}
              {notice && (
                <div role={notice.tone === "error" ? "alert" : "status"} className={clsx("mt-3 rounded-xl p-3.5 text-sm", notice.tone === "error" ? "bg-amber-50 text-amber-950" : "bg-black/[.03] text-ink-700")}>
                  <p>{notice.text}</p>
                  {notice.retry && <button type="button" onClick={notice.retry} className="mt-1 min-h-9 font-semibold text-[var(--brand-ink)] hover:underline">{t.tryAgain}</button>}
                </div>
              )}
              {followUp && origin === "refined" && !isEdited && (
                <p className="mt-3 rounded-xl bg-black/[.03] p-3.5 text-sm"><span className="font-semibold">{t.followUp}</span> {followUp}{" "}
                  <button type="button" onClick={() => boxRef.current?.focus()} className="font-semibold text-[var(--brand-ink)] hover:underline">{t.followUpBtn}</button></p>
              )}
            </div>

            {/* ---------------------------------------------- topics: they tailor the draft above */}
            {chips.length > 0 && (
              <div className="mt-3 border-t border-black/5 pt-3">
                <p id="chips-l" className="text-sm font-semibold text-ink-700">{t.topicsLabel}</p>
                <p className="text-xs text-ink-500">{t.topicsHint}</p>
                <div role="group" aria-labelledby="chips-l" className="mt-2 flex flex-wrap gap-2">
                  {chips.map((s) => {
                    const on = picked.includes(s.id);
                    return (
                      <button key={s.id} type="button" aria-pressed={on} onClick={() => toggle(s.id)}
                        className={clsx("inline-flex min-h-11 items-center gap-1.5 rounded-full px-4 text-[15px] font-medium transition active:scale-[.97]", ring,
                          on ? "bg-[var(--brand)] text-[var(--on-brand)] shadow-[0_6px_14px_-8px_var(--brand)]" : "bg-white text-ink-700 ring-1 ring-ink-300 hover:bg-ink-50")}>
                        {on && <Check className="h-4 w-4" aria-hidden />}{label(s)}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        )}
        <p className="text-center text-xs text-ink-500">{t.privacy}</p>

        {/* ------------------------------------------------ the one tap: a compact bar that stays in reach on phones */}
        {submitState !== "done" && (
          <div className="sticky bottom-0 z-10 -mx-5 bg-white/95 px-5 pb-[max(0.5rem,env(safe-area-inset-bottom))] pt-2.5 shadow-[0_-10px_24px_-14px_rgba(0,0,0,0.3)] backdrop-blur" data-testid="cta-bar">
            {isDirect ? (
              <>
                <label className="mb-2 flex cursor-pointer items-start gap-2.5 text-[12px] leading-snug text-ink-700">
                  <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} data-testid="consent" className="mt-0.5 h-5 w-5 shrink-0 !accent-[color:var(--brand)]" />
                  <span>{t.consentLabel}</span>
                </label>
                <button type="button" onClick={() => void submitReview()} disabled={!consent || sending || !ready2go} data-testid="submit-review" className={ctaCls} style={ctaStyle}>
                  {sending ? <Loader2 className="h-5 w-5 fq-spin" aria-hidden /> : <PenLine className="h-5 w-5" aria-hidden />}{sending ? t.submitting : t.submit}
                </button>
                <p id="cta-hint" className="mt-1.5 text-center text-[12px] leading-snug text-ink-700">{t.submitHint}</p>
                {reviewUrl && <a href={reviewUrl} target="_blank" rel="noopener noreferrer" onClick={onCopyContinue} data-testid="copy-continue" className="mt-0.5 flex min-h-10 items-center justify-center gap-1 text-[13px] font-semibold text-[var(--brand-ink)] hover:underline">{t.orHandoff}<ExternalLink className="h-3.5 w-3.5" aria-hidden /></a>}
              </>
            ) : reviewUrl ? (
              <a href={reviewUrl} target="_blank" rel="noopener noreferrer" onClick={onCopyContinue} aria-describedby="cta-hint" aria-disabled={!ready2go || undefined} data-testid="copy-continue" className={ctaCls} style={ctaStyle}>
                {t.cta}<ExternalLink className="h-[18px] w-[18px] shrink-0 transition-transform group-hover:translate-x-0.5" aria-hidden />
              </a>
            ) : (
              <button type="button" onClick={() => void copyOnly()} aria-describedby="cta-hint" className={ctaCls} style={ctaStyle}>
                {copiedFlash ? <Check className="h-5 w-5" aria-hidden /> : <Copy className="h-5 w-5" aria-hidden />}{copiedFlash ? t.copied : t.ctaCopyOnly}
              </button>
            )}
            {!isDirect && <p id="cta-hint" className="mt-1.5 text-center text-[12px] leading-snug text-ink-700">{reviewUrl ? t.ctaHint : t.noLink} <span className="text-ink-500">{t.confirmNote}</span></p>}
          </div>
        )}
      </section>
    </LandingFrame>
  );
}