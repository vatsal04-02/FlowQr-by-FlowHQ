// Run with: npm test. Privacy and account-lifecycle UI (docs/PRIVACY_COMPLIANCE_AUDIT.md). Node strips the TypeScript types for the wording module; the components are checked as source text,
// because this project has no browser test runner in `npm test` (the browser scripts in /e2e exercise the pages for real).
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { AI_NOTICE, aiNoticeFor } from "../src/lib/ai-notice.ts";

const src = (p) => readFileSync(new URL(`../src/${p}`, import.meta.url), "utf8");

const EN = "AI assistance: If you use this tool, the text you enter may be sent to an AI service provider to help generate or improve your review wording. Please avoid entering sensitive personal information. You can edit the suggested text before using it.";
const HI = "AI सहायता: यदि आप इस टूल का उपयोग करते हैं, तो आपके द्वारा लिखा गया टेक्स्ट आपकी समीक्षा के शब्द तैयार करने या बेहतर बनाने में मदद के लिए AI सेवा प्रदाता को भेजा जा सकता है। कृपया संवेदनशील व्यक्तिगत जानकारी दर्ज न करें। आप सुझाव दिए गए टेक्स्ट को इस्तेमाल करने से पहले बदल सकते हैं।";

test("the AI notice is exactly the owner's English and Hindi wording", () => {
  assert.equal(AI_NOTICE.en, EN);
  assert.equal(AI_NOTICE.hi, HI);
});

test("the AI notice follows the selected language: Hindi for Hindi, English for everything else", () => {
  assert.deepEqual(aiNoticeFor("hi"), { text: HI, lang: "hi" });
  for (const l of ["en", "hinglish", "auto", ""]) assert.deepEqual(aiNoticeFor(l), { text: EN, lang: "en" });
});

test("the notice is on BOTH customer pages, only where AI help is offered, and is not a pre-ticked consent box", () => {
  const campaign = src("components/public/ReviewLanding.tsx"), card = src("components/public/CardLanding.tsx"), notice = src("components/public/AiNotice.tsx");
  assert.match(campaign, /page\.ai_available && <div[^>]*><AiNotice lang=\{lang\} \/>/);
  assert.match(card, /data\.ai_available \? \(<>\s*<div className="mt-4"><AiNotice lang=/);
  assert.ok(card.indexOf("<AiNotice") < card.indexOf("Improve my wording"), "the notice comes before the button that sends text for AI help");
  assert.match(notice, /lang=\{n\.lang\}/, "the notice marks its own language for screen readers");
  assert.doesNotMatch(notice, /checkbox|defaultChecked|checked/i, "a notice, not a consent box");
});

test("sign-up: the 18+ declaration is unchecked by default, required, English only, and sent to the server", () => {
  // the form lives in components/auth/RegisterForm.tsx (shared by /register and the pricing popup); the page itself must not grow a second copy
  const page = src("components/auth/RegisterForm.tsx");
  assert.ok(!src("app/(auth)/register/page.tsx").includes("age_confirmed"), "the page uses the shared form, it has no copy of its own");
  assert.match(page, /const \[age, setAge\] = useState\(false\)/, "starts unchecked");
  assert.doesNotMatch(page, /defaultChecked/);
  assert.ok(page.includes("I confirm that I am 18 years of age or older."));
  assert.ok(!page.includes("मैं पुष्टि करता"), "the sign-up declaration is English only (owner decision 2026-11-18)");
  assert.match(page, /if \(!age\) \{ needAge\(\); return; \}/, "submit stops without it");
  assert.match(page, /age_confirmed: true/);
  assert.match(page, /aria-required="true"/);
  assert.match(page, /role="alert"/, "the missing-declaration message is announced");
  assert.doesNotMatch(page, /type="date"|label="[^"]*(birth|dob|age\b)/i, "no date of birth or age field is collected");
});

test("sign-up with Google cannot start until the declaration is ticked, and then says so to the server", () => {
  const g = src("components/GoogleAuth.tsx");
  assert.match(g, /if \(onNeedAge && !ageConfirmed\)/);
  assert.match(g, /\?age=1/);
  assert.match(g, /age_required:/, "the login page explains a refused brand-new Google account");
});

test("the refund page is a real draft policy, kept out of search until it is confirmed", () => {
  const page = src("app/(marketing)/refund-policy/page.tsx"), layout = src("app/(marketing)/refund-policy/layout.tsx");
  assert.doesNotMatch(page, /LEGAL TEXT TO BE PROVIDED|has not been published yet/);
  assert.match(page, /Cancelling a subscription/);
  assert.match(page, /When we refund/);
  assert.match(layout, /index: false/);
});

test("deleting my own account: email typed, password for password accounts, never offered to a sole owner", () => {
  const p = src("components/DeleteMyAccountPanel.tsx"), c = src("app/(auth)/confirm-account-deletion/page.tsx");
  assert.match(p, /confirm_email: email/);
  assert.match(p, /needsPassword \? password : undefined/);
  assert.match(p, /disabled=\{!!d\?\.blocked_by\.length/);
  assert.match(p, /does not delete any business/i);
  assert.match(c, /Yes, delete my account/, "opening the emailed link does not delete anything by itself; a person presses a button");
});
