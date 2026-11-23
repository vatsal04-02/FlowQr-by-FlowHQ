"use client";
import { Contact, LegalShell } from "@/components/marketing/LegalShell";

// DRAFT policy written 2026-11-23 from the product's behaviour (docs/DPDP_ARTIFACTS.md lists every number that is an assumption). The page is kept out of search engines
// by refund-policy/layout.tsx until the owner and a lawyer have confirmed it.
export default function RefundPolicy() {
  return (
    <LegalShell title="Refund and cancellation policy" updated="23 November 2026">
      {(i) => (<>
        <p>This policy explains how cancelling, payments and refunds work for FlowQR, provided by {i?.company ?? "FlowHQ"}. Prices are in Indian rupees, plus GST where applicable. Payments are taken by our payment provider, and we never see or store your card or UPI details. Questions: <Contact info={i} />.</p>

        <h2>Free trial</h2>
        <p>You are not charged during the free trial. If you cancel before it ends, you pay nothing.</p>

        <h2>Cancelling a subscription</h2>
        <ul>
          <li>You can cancel at any time in Settings &rarr; Billing. It takes effect for the next renewal; nothing further is charged.</li>
          <li>You keep access until the end of the period you already paid for. We do not refund the unused part of a period, except as set out below.</li>
          <li>If a renewal payment fails, we do not keep trying indefinitely: your plan pauses and you can pay again whenever you choose. Your data and printed QR codes stay available.</li>
        </ul>

        <h2>One-time prepaid plans</h2>
        <p>A prepaid plan gives you the plan for the period you bought and does not renew by itself. The same refund rules below apply.</p>

        <h2>When we refund</h2>
        <ul>
          <li><b>Charged twice or the wrong amount:</b> we refund the extra amount in full.</li>
          <li><b>Paid but the plan was not activated</b> and we cannot fix it quickly: we refund in full.</li>
          <li><b>First payment:</b> if you ask within 7 days of your first payment for a plan, we refund it in full.</li>
          <li><b>Where the law requires it.</b></li>
        </ul>

        <h2>Printed QR/NFC cards</h2>
        <p>Cards are made for your business, so we cannot refund them once printing has started. If a card arrives damaged, faulty or not as ordered, tell us within 7 days of delivery with a photo and we will replace it or refund it.</p>

        <h2>How to ask for a refund</h2>
        <p>Write to <Contact info={i} /> from the email address on your account with the payment reference or order number. We reply within 3 working days. When a refund is approved we send it to the payment method you used, normally within 7 working days; your bank or UPI app may take longer to show it.</p>

        <h2>If you disagree</h2>
        <p>Tell us and we will look again. You can also use the grievance process in our <a href="/privacy">privacy policy</a>.</p>
      </>)}
    </LegalShell>
  );
}
