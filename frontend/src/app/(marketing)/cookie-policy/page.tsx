"use client";
import { Contact, LegalShell } from "@/components/marketing/LegalShell";

export default function CookiePolicy() {
  return (
    <LegalShell title="Cookie policy" updated="23 November 2026">
      {(i) => (<>
        <p>FlowQR uses only the cookies and device storage it needs to run. We set <b>no advertising, analytics or tracking cookies</b>, and no third-party tracking scripts load on our pages. Because nothing optional is used, there is no cookie banner to accept or refuse. If that ever changes, we will ask for your consent first and update this page.</p>

        <h2>Cookies we set</h2>
        <ul>
          <li><b>flowqr_session</b>: keeps you signed in. Kept for up to 14 days (12 hours for FlowQR staff accounts) or until you log out. Not readable by page scripts.</li>
          <li><b>flowqr_csrf</b>: a security token that protects your account from forged requests. Lasts as long as the session.</li>
          <li><b>flowqr_gl_oauth</b> and <b>flowqr_oauth_state</b>: set for a few minutes while you sign in with Google or connect your Google Business Profile, to make sure the reply comes back to you. Then they expire.</li>
        </ul>

        <h2>Stored on your device (not cookies)</h2>
        <ul>
          <li>Your interface choices: light or dark theme, sidebar open or closed, the location you last picked, and whether the start-up screen has played.</li>
          <li>On a business&rsquo;s review page, a customer&rsquo;s unfinished review (stars, topics and any words typed) stays in their own browser for 24 hours so that coming back from Google does not lose it.</li>
        </ul>
        <p>You can clear all of this in your browser settings. If you block cookies for FlowQR you will not be able to stay signed in.</p>

        <h2>Third parties</h2>
        <p>Our fonts are served from our own domain, not from Google. Payment pages load from our payment provider only when you click to pay. For everything else we collect, see the <a href="/privacy">privacy policy</a>.</p>

        <p>Questions: <Contact info={i} />.</p>
      </>)}
    </LegalShell>
  );
}
