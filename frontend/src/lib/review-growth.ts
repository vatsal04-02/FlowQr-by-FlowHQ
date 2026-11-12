import type { QRStyle } from "./types";
import type { CSSProperties } from "react";

export type Style = "natural" | "short" | "detailed" | "professional" | "warm";
export type Background = "plain" | "soft" | "gradient" | "dots";
export type Lang = "en" | "hi";

export const STYLES: readonly { v: Style; label: string; hint: string }[] = [
  { v: "natural", label: "Natural", hint: "Conversational, like telling a friend" },
  { v: "short", label: "Short", hint: "One or two simple sentences" },
  { v: "detailed", label: "Detailed", hint: "Expands only on what the customer shared" },
  { v: "professional", label: "Professional", hint: "Polished and measured" },
  { v: "warm", label: "Warm", hint: "Personal and grateful" },
];
export const BACKGROUNDS: readonly [Background, string][] = [["plain", "Plain"], ["soft", "Soft tint"], ["gradient", "Gradient"], ["dots", "Dotted"]];
export const BRAND_PRESETS = ["#1B46B8", "#0A7D6B", "#D9560B", "#7A2E8E", "#B3261E", "#171719"] as const;

// Customer-facing copy. The page language follows the language the customer picks for their review.
export interface Copy {
  h: string; sub: string; language: string; privacy: string;
  rateLabel: string; rateHint: string; rateWords: [string, string, string, string, string]; star: string; stars: string; needStars: string; needTopics: string;
  topicsLabel: string; topicsHint: string;
  editorLabel: string; editorPh: string; tooShort: string; askMore: string;
  badgeStarter: string; badgeRefined: string; badgeEdited: string; badgeCopied: string; loadingStarter: string; tailoring: string; blank: string; another: string; undo: string;
  cta: string; ctaCopyOnly: string; ctaHint: string; confirmNote: string;
  copiedH: string; copiedSub: string; copyFailedH: string; copyFailedSub: string; copyAgain: string; openAgain: string; copyBtn: string; copied: string; welcomeBack: string;
  refineQ: string; refineYes: string; refineNo: string; followUp: string; followUpBtn: string;
  trust: [string, string, string]; submit: string; submitting: string; submitHint: string; consentLabel: string; submittedH: string; submittedSub: string; submitFailedH: string; submitFailedSub: string; orHandoff: string;
  retryMsg: string; rejected: string; tryAgain: string; aiDown: string; aiBusy: string; noOther: string; noMoreRewrites: string; noLink: string;
}
export const COPY: Record<Lang, Copy> = {
  en: {
    h: "Share your experience", sub: "Tap your stars. Edit the suggested review, then copy it to Google.",
    language: "Language", privacy: "We don't ask for your name, phone or email.",
    rateLabel: "How would you rate your visit?", rateHint: "This sets the tone of your review.",
    rateWords: ["Poor", "Not good", "Okay", "Good", "Very good"], star: "star", stars: "stars",
    needStars: "Choose your stars so the review reflects how your visit was.", needTopics: "Pick what applies to tailor your review.",
    topicsLabel: "What stood out? (optional)", topicsHint: "Pick only what truly applies. We tailor the review to it.",
    editorLabel: "Your review", editorPh: "Write your review here…", tooShort: "Write at least a short sentence to continue.",
    askMore: "Could you add a little more? For example, what you came in for, or one thing you remember about the visit.",
    badgeStarter: "AI suggestion · edit freely", badgeRefined: "Written from your answers · edit freely", badgeEdited: "Your review · edited by you", badgeCopied: "Copied · ready to paste",
    loadingStarter: "Preparing a suggestion…", tailoring: "Tailoring your review…", blank: "Start blank", another: "Try another wording", undo: "Undo",
    cta: "Copy & Continue to Google", ctaCopyOnly: "Copy review", ctaHint: "Your review will be copied. Paste it into Google's review box.",
    confirmNote: "Continuing confirms it is your own experience. You post it yourself.",
    copiedH: "Your review is copied.", copiedSub: "Paste it into Google's review box, then choose your own star rating and post it yourself.",
    copyFailedH: "We couldn't copy it automatically.", copyFailedSub: "Tap Copy review below, then paste it into Google's review box.",
    copyAgain: "Copy again", openAgain: "Open Google again", copyBtn: "Copy review", copied: "Copied", welcomeBack: "Welcome back. Your review is still here.",
    refineQ: "Update your review with your latest stars and topics?", refineYes: "Update my review", refineNo: "Keep my text",
    followUp: "Optional:", followUpBtn: "Add a few words",
    trust: ["Takes under a minute", "No sign-up or personal details", "You stay in control"], submit: "Submit review", submitting: "Submitting…", submitHint: "Your review is sent to Google as you see it above.",
    consentLabel: "I confirm this reflects my own experience, and I agree to submit exactly this review to Google.", submittedH: "Your review was submitted to Google.", submittedSub: "Thank you. Google may take a little while to show it.",
    submitFailedH: "We couldn't submit it from here.", submitFailedSub: "Your review is safe below. Copy it and post it on Google yourself.", orHandoff: "Prefer to post it yourself? Copy & open Google",
    retryMsg: "We couldn't write that just now. Please try again, or write it yourself.", tryAgain: "Try again",
    rejected: "We couldn't put that into words without adding things you didn't say. Please try again, or write it yourself.",
    aiDown: "Our writing helper isn't available right now, so please write your review in your own words below.",
    aiBusy: "Writing help is busy right now, so please write your review in your own words below.",
    noOther: "That's about the best wording for what you picked. Add a few words of your own for a different version, or edit it yourself.",
    noMoreRewrites: "You've used all the rewrites. You can still edit the text yourself.",
    noLink: "This business hasn't added its Google review link yet. You can still copy your review and post it later.",
  },
  hi: {
    h: "अपना अनुभव साझा करें", sub: "स्टार चुनें। सुझाए गए रिव्यू को बदलें, फिर उसे Google पर कॉपी करें।",
    language: "भाषा", privacy: "हम आपका नाम, फ़ोन या ईमेल नहीं माँगते।",
    rateLabel: "आप अपनी विज़िट को कितने स्टार देंगे?", rateHint: "इससे आपके रिव्यू का लहजा तय होता है।",
    rateWords: ["खराब", "अच्छा नहीं", "ठीक-ठाक", "अच्छा", "बहुत अच्छा"], star: "स्टार", stars: "स्टार",
    needStars: "पहले स्टार चुनें ताकि रिव्यू आपकी विज़िट के अनुभव को दर्शाए।", needTopics: "रिव्यू को अपने अनुभव के अनुसार ढालने के लिए जो लागू हो वह चुनें।",
    topicsLabel: "क्या खास लगा? (वैकल्पिक)", topicsHint: "केवल वही चुनें जो सच में लागू हो। हम रिव्यू को उसी के अनुसार ढालेंगे।",
    editorLabel: "आपका रिव्यू", editorPh: "अपना रिव्यू यहाँ लिखें…", tooShort: "आगे बढ़ने के लिए कम से कम एक छोटा वाक्य लिखें।",
    askMore: "क्या आप थोड़ा और बता सकेंगे? जैसे आप किस काम से आए थे, या इस विज़िट की कोई एक बात जो आपको याद रही।",
    badgeStarter: "AI का सुझाव · बेझिझक बदलें", badgeRefined: "आपके जवाबों से लिखा गया · बेझिझक बदलें", badgeEdited: "आपका रिव्यू · आपने बदला", badgeCopied: "कॉपी हो गया · पेस्ट करने के लिए तैयार",
    loadingStarter: "सुझाव तैयार हो रहा है…", tailoring: "आपके जवाबों के अनुसार रिव्यू ढाला जा रहा है…", blank: "खाली से शुरू करें", another: "दूसरा रूप दिखाएँ", undo: "वापस लाएँ",
    cta: "कॉपी करें और Google पर जाएँ", ctaCopyOnly: "रिव्यू कॉपी करें", ctaHint: "आपका रिव्यू कॉपी हो जाएगा। उसे Google के रिव्यू बॉक्स में पेस्ट करें।",
    confirmNote: "आगे बढ़ना मानना है कि यह आपका अपना अनुभव है। पोस्ट आप खुद करते हैं।",
    copiedH: "आपका रिव्यू कॉपी हो गया है।", copiedSub: "Google के रिव्यू बॉक्स में पेस्ट करें, फिर अपनी स्टार रेटिंग खुद चुनकर पोस्ट करें।",
    copyFailedH: "अपने-आप कॉपी नहीं हो सका।", copyFailedSub: "नीचे “रिव्यू कॉपी करें” दबाएँ, फिर Google के रिव्यू बॉक्स में पेस्ट करें।",
    copyAgain: "फिर से कॉपी करें", openAgain: "Google फिर से खोलें", copyBtn: "रिव्यू कॉपी करें", copied: "कॉपी हो गया", welcomeBack: "वापस स्वागत है। आपका रिव्यू यहीं सुरक्षित है।",
    refineQ: "अपने नए स्टार और विषयों के अनुसार रिव्यू बदलें?", refineYes: "मेरा रिव्यू बदलें", refineNo: "मेरा लिखा रखें",
    followUp: "वैकल्पिक:", followUpBtn: "कुछ शब्द जोड़ें",
    trust: ["एक मिनट से भी कम", "साइन-अप या निजी जानकारी नहीं", "नियंत्रण आपके हाथ में"], submit: "रिव्यू सबमिट करें", submitting: "सबमिट हो रहा है…", submitHint: "आपका रिव्यू वैसा ही Google को भेजा जाएगा जैसा ऊपर दिख रहा है।",
    consentLabel: "मैं पुष्टि करता/करती हूँ कि यह मेरे अपने अनुभव को दर्शाता है, और यही रिव्यू Google को सबमिट करने के लिए सहमत हूँ।", submittedH: "आपका रिव्यू Google को सबमिट हो गया।", submittedSub: "धन्यवाद। Google को इसे दिखाने में थोड़ा समय लग सकता है।",
    submitFailedH: "यहाँ से सबमिट नहीं हो सका।", submitFailedSub: "आपका रिव्यू नीचे सुरक्षित है। उसे कॉपी करके Google पर खुद पोस्ट करें।", orHandoff: "खुद पोस्ट करना चाहते हैं? कॉपी करें और Google खोलें",
    retryMsg: "अभी यह नहीं लिखा जा सका। कृपया दोबारा कोशिश करें, या खुद लिखें।", tryAgain: "दोबारा कोशिश करें",
    rejected: "आपके कहे से हटकर कुछ जोड़े बिना इसे नहीं लिखा जा सका। कृपया दोबारा कोशिश करें, या खुद लिखें।",
    aiDown: "लिखने वाला सहायक अभी उपलब्ध नहीं है, इसलिए कृपया नीचे अपने शब्दों में अपना रिव्यू लिखें।",
    aiBusy: "लिखने वाला सहायक अभी व्यस्त है, इसलिए कृपया नीचे अपने शब्दों में अपना रिव्यू लिखें।",
    noOther: "आपके चुने के हिसाब से यही सबसे अच्छा रूप है। अलग संस्करण के लिए अपने कुछ शब्द जोड़ें, या खुद बदलाव करें।",
    noMoreRewrites: "फिर से लिखने के सभी मौके पूरे हो गए। आप अब भी खुद बदलाव कर सकते हैं।",
    noLink: "इस बिज़नेस ने अभी अपना Google रिव्यू लिंक नहीं जोड़ा है। आप अपना रिव्यू कॉपी करके बाद में पोस्ट कर सकते हैं।",
  },
};
export interface Customization {
  brand_color: string; display_name: string | null; logo_url: string | null; welcome_message: string | null; footer_message: string | null;
  background: Background; show_rating: boolean; default_style: Style; default_language: Lang; allowed_styles: Style[];
}
export const DEFAULT_CUSTOMIZATION: Customization = {
  brand_color: "#1B46B8", display_name: null, logo_url: null, welcome_message: null, footer_message: null, background: "soft",
  show_rating: true, default_style: "natural", default_language: "en", allowed_styles: STYLES.map((s) => s.v),
};

export interface CampaignStats { scans: number; unique_scans: number; feedback_submitted: number; ai_requested: number; manual_selected: number; drafts_generated: number; drafts_approved: number; google_redirects: number }
export interface Campaign {
  id: string; name: string; status: "active" | "paused" | "archived"; location_id: string | null; location_name: string | null; public_id: string; url: string;
  customization: Customization; review_url_ready: boolean; review_url_source: string | null; stats: CampaignStats; created_at: string; updated_at: string; qr_rotated_at: string | null;
  qr_style: QRStyle | null; retired_codes: number; old_codes: OldCode[];
}
/** An earlier code of a campaign. It keeps opening the campaign unless it was deliberately deactivated. */
export interface OldCode { public_id: string; url: string; retired_at: string; active: boolean; deactivated_at: string | null }
export interface FunnelStep { key: string; label: string; count: number; rate_of_previous: number | null; rate_of_scans: number | null }
export interface RGAnalytics {
  range: { from: string; to: string; timezone: string };
  suggestions: { id: string; label: string; count: number }[];
  ai: AIQuality;
  ratings: RatingStats;
  totals: { suggestion_sessions: number; scans: number; unique_visitors: number; feedback_submitted: number; ai_generation_requests: number; ai_requested: number; manual_selected: number; needs_more: number; drafts_generated: number; regenerations: number; generation_failures: number; drafts_approved: number; review_copied: number; google_redirects: number };
  funnel: FunnelStep[];
  series: ({ date: string } & Record<string, number | string>)[];
  campaigns: { id: string; name: string; status: string; scans: number; feedback_submitted: number; ai_requested: number; manual_selected: number; drafts_generated: number; drafts_approved: number; google_redirects: number; regenerations: number; conversion: number | null }[];
  definitions: Record<string, string>;
}
export interface AITestResult {
  ok: boolean; provider: string; model: string | null; model_served: string | null; language: Lang; style: Style; latency_ms: number | null;
  tokens: { prompt: number; completion: number; calls: number } | null; draft: string | null; rejected_text: string | null;
  checks: { passed: boolean; reason: string | null; unsupported?: string | null; fact_check?: boolean } | null; error: { code: string; message: string } | null;
}
export interface AIQuality {
  requests: number; accepted: number; rejected: number; failed: number; model_calls: number; write_attempts: number; retries: number; tokens_in: number; tokens_out: number;
  cost_usd: number | null; cost_per_accepted_draft_usd: number | null; avg_calls_per_request: number | null; rules_rejection_rate: number | null;
  factcheck_rejection_rate: number | null; latency_ms_avg: number | null; latency_ms_median: number | null;
}
export interface Topic { id: string; en: string; hi: string }
export interface ContextResp {
  tenant_category: string | null; detected_category: string; category_key: string; category_override: string | null; categories: { key: string; label: string }[];
  description: string; services: string[]; languages: Lang[]; suggestions: (Topic & { enabled: boolean })[]; limits: { description: number; services: number }; notes: string[];
}
export type Rating = 1 | 2 | 3 | 4 | 5;
/** The 1-5 stars customers chose on the FlowQr page. NOT the Google rating. */
export interface RatingStats { distribution: Record<"1" | "2" | "3" | "4" | "5", number>; rated: number; unrated: number; average: number | null; source: string }
export interface RGSettings {
  ai: { configured: boolean; provider: string | null; model: string | null; degraded: { code: string; message: string; until: number } | null; used_this_month: number; monthly_limit: number };
  limits: { max_drafts_per_customer: number; max_campaigns: number };
  retention_days: number; google_connected: boolean;
  locations: { id: string; name: string; review_url: string | null; review_url_source: string | null; google_link_available: boolean; review_url_kind: "direct" | "listing" | "unknown" | "none" }[];
  principles: string[];
}

// ---------- colour helpers: any brand colour a business picks must stay readable ----------
function rgb(hex: string): [number, number, number] {
  const h = /^#[0-9a-f]{6}$/i.test(hex) ? hex.slice(1) : "1B46B8";
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}
const toHex = (c: number[]) => "#" + c.map((v) => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, "0")).join("").toUpperCase();
function luminance(hex: string) {
  const [r, g, b] = rgb(hex).map((v) => { const s = v / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
const contrast = (a: string, b: string) => { const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
export const mix = (hex: string, withHex: string, pct: number) => { const a = rgb(hex), b = rgb(withHex); return toHex(a.map((v, i) => v + (b[i] - v) * pct)); };
/** Text colour that is readable ON the brand colour (buttons). */
export const onBrand = (hex: string) => (contrast(hex, "#FFFFFF") >= 4.5 ? "#FFFFFF" : "#171719");
/** The brand colour darkened until it is readable AS text on white (links, accents). */
export function brandInk(hex: string) {
  let c = hex;
  for (let i = 0; i < 12 && contrast(c, "#FFFFFF") < 4.5; i++) c = mix(c, "#000000", 0.12);
  return c;
}

export function landingStyle(color: string): CSSProperties {
  return { ["--brand" as string]: color, ["--on-brand" as string]: onBrand(color), ["--brand-ink" as string]: brandInk(color), ["--brand-tint" as string]: mix(color, "#FFFFFF", 0.9) };
}
export function backgroundStyle(bg: Background, color: string): CSSProperties {
  const tint = mix(color, "#FFFFFF", 0.93);
  switch (bg) {
    case "plain": return { background: "#FFFFFF" };
    case "gradient": return { background: `linear-gradient(180deg, ${mix(color, "#FFFFFF", 0.82)} 0%, ${mix(color, "#FFFFFF", 0.95)} 38%, #FFFFFF 78%)` };
    case "dots": return { backgroundColor: "#FAF9F6", backgroundImage: `radial-gradient(${mix(color, "#FFFFFF", 0.78)} 1.2px, transparent 1.2px)`, backgroundSize: "18px 18px" };
    default: return { background: tint };
  }
}
