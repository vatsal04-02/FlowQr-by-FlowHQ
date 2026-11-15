"use client";
import { Contact, LegalShell } from "@/components/marketing/LegalShell";

export default function Privacy() {
  return (
    <LegalShell title="Privacy policy" updated="12 November 2026">
      {(i) => (<>
        <p>{i?.company ?? "FlowHQ"} (&ldquo;we&rdquo;) runs FlowQR, software that helps local businesses collect and manage Google reviews. This page explains what personal data FlowQR handles, why, and what you can do about it. Questions: <Contact info={i} />.</p>

        <h2>Who this covers</h2>
        <ul><li><b>Business owners and their team</b> who sign up for FlowQR.</li><li><b>Customers of those businesses</b> who scan a FlowQR QR code or NFC card and use the review page.</li></ul>
        <p>For the businesses&rsquo; own customer data (for example reviews about them), the business decides how it is used and we process it for them.</p>

        <h2>What we collect</h2>
        <ul>
          <li><b>Account:</b> name, email address, optional phone, and a password stored only as a one-way hash. If you sign in with Google we receive your Google email and name.</li>
          <li><b>Business:</b> business name, category, address, phone, website, locations, brand settings and the knowledge you give the AI.</li>
          <li><b>Google Business Profile data, only if you connect it:</b> your accounts and the locations you select, their reviews (reviewer name, rating, text, replies), profile details, posts, photos and performance statistics. We access only the locations you choose.</li>
          <li><b>QR and NFC scans:</b> time, the card or campaign, and a daily-rotating hashed device fingerprint used to count unique scans. We do not store a customer&rsquo;s name, phone or email from a scan.</li>
          <li><b>Review assistant:</b> if a customer types a few words so the AI can draft a review, we store those words, the draft and the 1&ndash;5 rating they chose. This text is deleted automatically after {i?.review_session_retention_days ?? 90} days; only counts remain.</li>
          <li><b>Payments:</b> handled by Razorpay. We keep plan, status and payment references, never card numbers.</li>
          <li><b>Technical:</b> IP address and browser type for security, rate-limiting and audit logs.</li>
        </ul>

        <h2>How we use it</h2>
        <ul><li>To provide FlowQR: sync reviews, draft replies you approve, publish what you approve, show analytics.</li><li>To keep the service secure and prevent abuse.</li><li>To bill you and support you.</li></ul>
        <p>We do not sell personal data, and we do not use it for advertising.</p>

        <h2>AI processing</h2>
        <p>When AI is used (review drafts, reply drafts), the relevant text is sent to our AI provider{i?.ai_provider ? ` (currently ${i.ai_provider})` : ""} to generate the result. We send only what is needed for that task. AI output is a suggestion: replies and posts are published only after the business approves them, and customers always edit and post their own reviews.</p>

        <h2>Google user data (Limited Use)</h2>
        <p>FlowQR&rsquo;s use and transfer of information received from Google APIs adheres to the <a href="https://developers.google.com/terms/api-services-user-data-policy" target="_blank" rel="noopener noreferrer">Google API Services User Data Policy</a>, including the Limited Use requirements. We use Google data only to provide the review, reply, post and profile features you ask for. We do not use it to train general AI models, do not sell it, and do not allow humans to read it except where you ask for support, for security, or where the law requires. Google access tokens are encrypted at rest and never shown in the browser. You can disconnect at any time in FlowQR or at <a href="https://myaccount.google.com/permissions" target="_blank" rel="noopener noreferrer">myaccount.google.com/permissions</a>.</p>

        <h2>Who else handles data</h2>
        <p>Service providers who process data for us: cloud hosting, our AI provider, Razorpay (payments) and an email sender. They may use it only to provide their service to us.</p>

        <h2>How long we keep it</h2>
        <ul><li>Account and business data: until you delete the business.</li><li>Customer review-assistant text: {i?.review_session_retention_days ?? 90} days.</li><li>After you delete a business: removed after a {i?.deletion_grace_days ?? 14}-day cancellable grace period. Security and billing records we are required to keep may remain for the legally required time.</li></ul>

        <h2>Your rights</h2>
        <p>You can export your data (Settings &rarr; Your data), correct it in the app, disconnect Google, or delete your business. Under India&rsquo;s Digital Personal Data Protection Act, 2023 you may also ask us to access, correct or erase your personal data and to address a grievance: contact <Contact info={i} />. If you are a customer of a business that uses FlowQR, you can contact that business or us.</p>

        <h2>Security</h2>
        <p>Encrypted connections, hashed passwords, encrypted Google tokens, per-business data isolation, role-based access and audit logs. No system is perfectly secure; tell us at once if you suspect a problem.</p>

        <h2>Children</h2>
        <p>FlowQR is for businesses and is not directed at children.</p>

        <h2>Changes</h2>
        <p>If this policy changes materially we will update the date above and notify account owners.</p>
      </>)}
    </LegalShell>
  );
}
