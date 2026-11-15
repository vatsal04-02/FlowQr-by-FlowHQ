"use client";
import { Contact, LegalShell } from "@/components/marketing/LegalShell";

export default function Terms() {
  return (
    <LegalShell title="Terms of service" updated="12 November 2026">
      {(i) => (<>
        <p>These terms govern your use of FlowQR, provided by {i?.company ?? "FlowHQ"}. By creating an account you agree to them. Questions: <Contact info={i} />.</p>

        <h2>The service</h2>
        <p>FlowQR provides QR/NFC review cards, a review page, AI writing assistance, and tools to sync, reply to and manage a business&rsquo;s Google Business Profile. Features that depend on Google, payment or messaging providers need those providers&rsquo; approval and may be unavailable or limited; where they are, FlowQR says so instead of pretending.</p>

        <h2>Your account</h2>
        <p>You are responsible for your login, for the people you invite, and for the accuracy of what you enter. You must have the right to manage any Google Business Profile you connect.</p>

        <h2>Reviews: what is not allowed</h2>
        <ul>
          <li>Do not filter, hide or route customers by the rating they give, or ask only happy customers for reviews (&ldquo;review gating&rdquo;).</li>
          <li>Do not offer rewards, discounts or other incentives for reviews, and do not write or post fake reviews.</li>
          <li>Customers write, edit and post their own reviews. FlowQR never posts a review on a customer&rsquo;s behalf.</li>
          <li>You must follow Google&rsquo;s review and Business Profile policies. We may suspend features or accounts that break them.</li>
        </ul>

        <h2>AI content</h2>
        <p>AI output is a draft. You are responsible for what you approve and publish, including its accuracy. For health, legal or other regulated businesses, you must make sure replies and posts comply with your professional and advertising rules; never put patient or confidential details into FlowQR.</p>

        <h2>Plans, trial and payment</h2>
        <p>New accounts get a free trial. After it ends, creating or changing things and AI use are paused until you choose a plan; your data and printed QR codes stay available. Paid plans renew until cancelled; you can cancel at any time and keep access to the end of the paid period. Prices are in rupees, plus GST where applicable. Physical cards are sold separately.</p>

        <h2>Your data</h2>
        <p>You own your business data. You can export it and delete your business at any time (Settings &rarr; Your data). See the <a href="/privacy">Privacy policy</a>.</p>

        <h2>Availability and changes</h2>
        <p>We work to keep FlowQR available but do not promise uninterrupted service. Features, limits and prices may change; we will give notice of material changes.</p>

        <h2>Liability</h2>
        <p>To the extent the law allows, FlowQR is provided &ldquo;as is&rdquo;, and our total liability for any claim is limited to the fees you paid in the 3 months before it. We are not liable for lost profits, for actions of Google or other third parties (including changes to their APIs, policies or your Business Profile), or for content you approve.</p>

        <h2>Ending</h2>
        <p>You may stop using FlowQR and delete your business at any time. We may suspend or end accounts that break these terms or the law.</p>

        <h2>Governing law</h2>
        <p>These terms are governed by the laws of India. Disputes are subject to the courts of the place where {i?.company ?? "FlowHQ"} is registered.</p>
      </>)}
    </LegalShell>
  );
}
