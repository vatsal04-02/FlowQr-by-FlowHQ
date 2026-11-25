"use client";
import { Contact, LegalShell } from "@/components/marketing/LegalShell";

export default function Privacy() {
  return (
    <LegalShell title="Privacy policy" updated="23 November 2026">
      {(i) => (<>
        <p>{i?.company ?? "FlowHQ"} (&ldquo;we&rdquo;) runs FlowQR, software that helps local businesses collect and manage Google reviews. This page explains what personal data FlowQR handles, why, and what you can do about it. Questions: <Contact info={i} />. <a href="/privacy-hi" lang="hi">हिंदी में पढ़ें</a>.</p>

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
          <li><b>Payments:</b> handled by Cashfree Payments, a licensed payment provider. We keep plan, status and payment references, never card numbers or UPI PINs.</li>
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
        <p>Service providers who process data for us: cloud hosting, our AI provider, a payment provider (once payments are switched on) and an email sender. They may use it only to provide their service to us.</p>

        <h2>How long we keep it</h2>
        <ul><li>Account and business data: until you delete the business.</li><li>Customer review-assistant text: {i?.review_session_retention_days ?? 90} days.</li><li>After you delete a business: removed after a {i?.deletion_grace_days ?? 14}-day cancellable grace period. Security and billing records we are required to keep may remain for the legally required time.</li></ul>

        <h2>Consent and why we process your data</h2>
        <p>We process your personal data with your consent (for example when you create an account, connect Google or switch on automation) or for purposes the law allows, such as giving you a service you asked for and meeting legal duties. Each purpose is listed above. You can withdraw consent at any time, as easily as you gave it: disconnect Google or switch off emails and automation in Settings, or delete your business. Withdrawing may mean parts of FlowQR stop working, and it does not affect what we did before you withdrew.</p>

        <h2>Your rights under India&rsquo;s DPDP Act, 2023</h2>
        <ul>
          <li><b>Know and access:</b> ask for a summary of the personal data we process about you, what we do with it and who we have shared it with.</li>
          <li><b>Correct, complete and update:</b> fix inaccurate or incomplete data. Most of it you can change yourself in the app.</li>
          <li><b>Erase:</b> ask us to delete your data. Delete your business yourself under Settings &rarr; Your data (see <a href="/data-deletion">Delete your data</a>), or write to us. We keep only what the law requires us to keep.</li>
          <li><b>Download:</b> Settings &rarr; Your data gives the account owner a copy of the business&rsquo;s data.</li>
          <li><b>Grievance:</b> if you are unhappy about how your data is handled, tell us first. We answer every request and complaint, and always within 90 days.</li>
          <li><b>Nominate:</b> name another person to exercise these rights for you if you die or cannot act for yourself.</li>
          <li><b>Complain to the regulator:</b> once you have raised it with us, you may complain to the Data Protection Board of India.</li>
        </ul>
        <p>To use any of these, write to <Contact info={i} /> from the email address on your account so we can check it is you. If you are a customer of a business that uses FlowQR, you can also contact that business; it decides why your review-page data is used and we handle it for it. This notice is also available in <a href="/privacy-hi" lang="hi">Hindi</a>, and you can ask us for it in another language listed in the Eighth Schedule to the Constitution.</p>

        <h2>Who to contact about your data</h2>
        <p>{i?.grievance_officer ?? "Our privacy contact"}{i?.company ? `, ${i.company}` : ""}: <Contact info={i} />.{i?.company_address ? ` ${i.company_address}.` : ""}</p>

        <h2>If something goes wrong</h2>
        <p>If a personal data breach affects you we will tell you without delay: what happened, the likely effect on you, what we are doing about it, what you can do and who to contact. We also report it to the Data Protection Board of India as the law requires.</p>

        <h2>Cookies and device storage</h2>
        <p>The details are in our <a href="/cookie-policy">cookie policy</a>. FlowQR uses only what is needed to run the service, so there is no cookie banner to accept. We set no advertising, analytics or tracking cookies.</p>
        <ul>
          <li><b>Cookies:</b> a sign-in session cookie and a matching security token (both needed to keep you signed in and to protect against forged requests), and short-lived cookies that last a few minutes while you sign in or connect Google.</li>
          <li><b>Stored on your device:</b> interface choices such as theme, sidebar and selected location. On a business&rsquo;s review page, a customer&rsquo;s unfinished review (stars, topics and any words typed) stays in their browser for 24 hours so returning from Google does not lose it.</li>
        </ul>

        <h2>Security</h2>
        <p>Encrypted connections, hashed passwords, encrypted Google tokens, per-business data isolation, role-based access and audit logs. No system is perfectly secure; tell us at once if you suspect a problem.</p>

        <h2>Children</h2>
        <p>FlowQR is for businesses. You must be 18 or over to create an account, and we ask you to confirm it when you sign up. We do not knowingly process the personal data of anyone under 18, we do not track or monitor children&rsquo;s behaviour, and we show no advertising. A business&rsquo;s review page is open to anyone who scans its code; we do not build profiles of visitors, and scans are counted with a code that changes every day. If you think a child&rsquo;s data was entered, write to us and we will delete it.</p>

        <h2>Changes</h2>
        <p>If this policy changes materially we will update the date above and notify account owners.</p>
      </>)}
    </LegalShell>
  );
}
