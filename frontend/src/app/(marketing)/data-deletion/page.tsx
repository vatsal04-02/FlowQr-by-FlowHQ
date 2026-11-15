"use client";
import { Contact, LegalShell } from "@/components/marketing/LegalShell";

export default function DataDeletion() {
  return (
    <LegalShell title="Delete your data" updated="12 November 2026">
      {(i) => (<>
        <p>You can remove your data from FlowQR yourself, at any time.</p>

        <h2>Delete your business and all its data</h2>
        <ol className="ml-5 list-decimal space-y-1.5">
          <li>Log in as the business <b>owner</b>.</li>
          <li>Go to <b>Settings &rarr; Your data</b>. Download your data first if you want a copy.</li>
          <li>Choose <b>Delete this business</b>, type the business name and confirm.</li>
        </ol>
        <p>Deletion is scheduled, not instant: you have {i?.deletion_grace_days ?? 14} days to change your mind and cancel it in the same place. After that FlowQR permanently deletes the business&rsquo;s locations, reviews, replies, QR campaigns, scan records, team, billing records, Google connections and AI logs, and revokes our access to your Google account. Physical cards you hold stop opening your page. If you have a paid plan, cancel it first so you are not charged again.</p>

        <h2>Only disconnect Google</h2>
        <p>In FlowQR open <b>Google connection</b> and choose <b>Disconnect</b>; FlowQR revokes its access and removes the stored tokens. You can also remove FlowQR&rsquo;s access at <a href="https://myaccount.google.com/permissions" target="_blank" rel="noopener noreferrer">myaccount.google.com/permissions</a>. Reviews already copied into FlowQR stay until you delete the business.</p>

        <h2>You are a customer, not a business owner</h2>
        <p>If you used a business&rsquo;s FlowQR review page, the words you typed for the AI assistant are deleted automatically after {i?.review_session_retention_days ?? 90} days, and we store no name, phone or email from a scan. To ask for earlier deletion, contact <Contact info={i} /> with the business name and approximate time. Reviews you posted on Google are yours and are controlled on Google.</p>

        <h2>Can&rsquo;t log in?</h2>
        <p>Contact <Contact info={i} /> from the email address on the account. We will verify it is you before deleting anything.</p>
      </>)}
    </LegalShell>
  );
}
