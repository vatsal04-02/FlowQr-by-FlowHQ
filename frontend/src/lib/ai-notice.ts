/**
 * The notice shown to a CUSTOMER before they use AI writing help on a review page (docs/PRIVACY_COMPLIANCE_AUDIT.md, E). One place for the wording, used by both customer pages
 * (the campaign review page and the card page), so English and Hindi cannot drift apart. The wording is the owner's, supplied 2026-11-18; it is a NOTICE shown before use, not a consent
 * box: whether explicit consent is legally required is an open question for the lawyer, and nothing here is pre-ticked or pretends to be consent.
 */
export const AI_NOTICE = {
  en: "AI assistance: If you use this tool, the text you enter may be sent to an AI service provider to help generate or improve your review wording. Please avoid entering sensitive personal information. You can edit the suggested text before using it.",
  hi: "AI सहायता: यदि आप इस टूल का उपयोग करते हैं, तो आपके द्वारा लिखा गया टेक्स्ट आपकी समीक्षा के शब्द तैयार करने या बेहतर बनाने में मदद के लिए AI सेवा प्रदाता को भेजा जा सकता है। कृपया संवेदनशील व्यक्तिगत जानकारी दर्ज न करें। आप सुझाव दिए गए टेक्स्ट को इस्तेमाल करने से पहले बदल सकते हैं।",
} as const;

/** The notice for the page's current language: Hindi when the customer chose Hindi, English otherwise (including Hinglish, which is written in Roman letters). */
export const aiNoticeFor = (lang: string): { text: string; lang: "en" | "hi" } => (lang === "hi" ? { text: AI_NOTICE.hi, lang: "hi" } : { text: AI_NOTICE.en, lang: "en" });
