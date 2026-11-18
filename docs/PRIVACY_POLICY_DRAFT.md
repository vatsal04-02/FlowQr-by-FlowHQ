# Privacy policy: first draft

**Not for publication yet.** Built from what the code actually does on 2026-11-18 (`docs/PRIVACY_COMPLIANCE_AUDIT.md`). `[FILL IN]` marks a business fact only the owner knows. `[LAWYER]` marks wording or a legal position that needs review. `[DECISION]` marks something the owner has not yet decided (the draft states the current behaviour and does not pretend a rule exists). Nothing below invents a fact about the business. The live page (`frontend/src/app/(marketing)/privacy/page.tsx`) has not been changed.

> **OWNER AND LAWYER ACTION ITEMS (read before editing this draft).** Updated 2026-11-18. This file is a **draft** and is not published; the live privacy page was not changed.
> *Owner:* (1) fill every `[FILL IN]` (legal name, registered address, registration number, support, privacy and security emails, processor names, session length, backup retention incl. off-site); (2) name the AI provider and plan and add the written evidence that its terms do not allow training on prompts (**unresolved: no evidence yet**); (3) confirm the final retention periods after the dry-run report; (4) decide whether the customer AI notice stays a notice or becomes a consent step.
> *Lawyer:* every `[LAWYER]`: lawful basis per purpose (India DPDP; EU/UK if targeted), the 18+ statement, children and the daily hashed visitor code, international transfers, processor agreements, the wording about Google data and Limited Use, **Google's content-retention rules for reviews and metrics (unresolved)**, what survives a deletion (audit entries without IP, anonymised user tombstones, scan counts, usage counters, email addresses in admin audit metadata), response periods, grievance officer details.
> New since the first draft: the 18+ declaration, deleting one's own account, retention of sessions, reset tokens, audit IPs and demo requests (periods are **provisional** and **not** a statement of compliance), the AI notice on review pages, and the reviewer's name no longer being sent to the AI provider. Update sections 2, 5, 7, 8 and 9 to match once approved.

---

# FlowQR Privacy Policy

Last updated: [DATE]

## 1. Who we are

FlowQR is run by **[FULL LEGAL NAME OF THE COMPANY]** ("FlowHQ", "we", "us"), [REGISTERED ADDRESS], [REGISTRATION / CIN NUMBER]. You can reach us at **[PRIVACY EMAIL]** or [POSTAL ADDRESS]. Our grievance officer is **[NAME, EMAIL, PHONE]** [LAWYER: confirm required details for India; add a representative or data protection officer if EU/UK law applies].

FlowQR helps local businesses ask customers for Google reviews, reply to reviews, and manage their Google Business Profile. Two groups of people give us personal data:

* **Business owners and their team** who sign up. For this data, we decide why and how it is used.
* **Customers of those businesses** who scan a FlowQR QR code or NFC card. The business decides why this data is collected; we handle it for the business.

## 2. What we collect, and why

| What | Examples | Why | Basis [LAWYER] |
|---|---|---|---|
| **Account** | name, email, optional mobile number, a one-way hash of your password (never the password itself); if you sign in with Google, your Google email and name | to create and secure your account, send verification and password-reset emails | [contract / consent] |
| **Your business** | business name, category, address, phone, website, locations, brand settings, and the notes you give the AI | to run the service you asked for | [contract] |
| **Google Business Profile data, only if you connect it** | the Google accounts and locations you choose; reviews (reviewer name, rating, text, replies); profile details, posts, photos; performance statistics; search terms people used to find you; a secure sign-in token, stored encrypted | to show your reviews and results, draft replies, and publish what you approve. We only access locations you select. | [consent, given when you connect, and again per action: see section 6] |
| **QR and NFC scans** | time, which card or campaign, whether it looks like a bot, and a **hashed device code that changes every day**, used only to count unique visitors | to show businesses how many people scanned | [LAWYER: legitimate use / consent; see Children] |
| **Review assistant** | the stars and topics a customer picks, the few words they may type, and the draft the AI wrote | to help a customer put their own experience into words. Deleted automatically after **[90] days**; only counts remain. | [consent] |
| **Payments** | plan, status, amount, payment-provider references; **never card numbers** | to bill you and keep tax and accounting records | [contract / legal duty] |
| **Technical** | IP address and browser details for login sessions, security and audit logs | to keep accounts safe and investigate abuse | [legitimate interest] |
| **Demo requests** | name, business name, city, business type, number of locations, mobile number, whether you agreed to WhatsApp, preferred time, a one-way hash of your IP address | to contact you about a demo | [consent] |

We do not ask customers who scan a card for their name, phone or email.

## 3. Cookies and what is stored on your device

We use only what the site needs to work. We do not use advertising, analytics or session-recording cookies or scripts.

| Name | What it is for | Lasts |
|---|---|---|
| `flowqr_session` | keeps you logged in (not readable by scripts) | [SESSION LENGTH: from `SESSION_TTL_HOURS`] |
| `flowqr_csrf` | protects your actions from forged requests | same |
| `flowqr_gl_oauth`, `flowqr_oauth_state` | complete "Sign in with Google" or "Connect Google" safely | about 10 minutes |
| Device storage (not cookies): theme, sidebar and selected-location choices, start-up screen | remember your settings | until you clear your browser |
| Device storage on the customer review page | keeps a customer's unfinished review so they do not lose it when they go to Google and come back | up to 24 hours; never sent to us until the customer chooses to continue |

Fonts are served from our own domain, so your browser does not contact Google's font servers. [LAWYER: if analytics or ads are ever added, a consent banner that blocks them until you accept becomes necessary first.]

## 4. Who we share data with

We do not sell personal data and we do not use it for advertising. We share it only with companies that help us run FlowQR, under [LAWYER: processor agreements]:

* **Google**: when you connect your Business Profile, we read and, only with your permission, change it through Google's official APIs.
* **An AI provider** ([FILL IN: provider and plan; currently Gemini unless configured otherwise]): to write drafts. We send only what a task needs: for a reply, the review text, the reviewer's name and your business notes; for a customer's review assistant, the stars, topics and words they typed. [OWNER: confirm the provider's terms do not allow it to train its models on this data, and write that here.]
* **Cashfree** [or the provider in use]: to take payments. Card or UPI details go to them, not us.
* **Cloud hosting and an email sender** ([FILL IN: names]).
* **An error-monitoring service**, only if enabled ([FILL IN]); we strip request bodies, cookies and personal details before anything is sent.
* The authorities, when the law requires it.

Where a provider is outside India, your data may be processed outside India. [LAWYER: transfer wording and safeguards.]

## 5. AI

FlowQR uses AI to draft review replies, Google posts and, when a customer asks for help, review wording. **AI output is a draft.** Replies and posts reach Google only after the business approves them (or, if the owner has chosen to switch it on for a particular location and type of action, within limits they set: see section 6). A customer always edits and posts their own review. We label AI drafts inside the app. [LAWYER: confirm any duty to label AI-generated content to customers; the customer review page should say that an AI tool helps word the review.]

## 6. Google data and your control

Our use and transfer of information received from Google APIs adheres to the [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy), including the Limited Use requirements [LAWYER: confirm this statement applies to the permission FlowQR requests].

* We use Google data only to provide the review, reply, post and profile features you ask for. We do not use it to train general AI models, we do not sell it, and people at FlowQR read it only for support you request, security, or legal reasons.
* **Nothing is changed on your Google profile without your permission.** For each location and each type of action (for example, replying to a positive review), you grant or refuse permission separately in FlowQR, you can withdraw it at any time, and withdrawing stops anything still waiting. Changes with higher risk, such as editing your business name or categories, are never automatic. We record what was proposed, who approved it, and what Google held before and after.
* You can disconnect Google at any time in FlowQR or at [myaccount.google.com/permissions](https://myaccount.google.com/permissions). We then delete the stored sign-in token. Within [DECISION: 7 business days is Google's stated limit for removing access for a departing client] we stop using your connection.

## 7. How long we keep it

| Data | Kept | Note |
|---|---|---|
| Account and business data | until you delete your business, then removed after a **14-day** grace period you can cancel | |
| Customer review-assistant text | **[90] days** | counts only afterwards |
| Change history of actions on your Google profile | **[730] days**, then erased | so you can see who changed what and why |
| Map scans | **[400] days** | |
| Reviews and daily statistics copied from Google | **[DECISION PENDING]** | Google's API policy limits how long its content may be stored; we are confirming how that applies to FlowQR. Until then do not rely on a stated period. [LAWYER] |
| Login sessions (IP, browser) | **[DECISION: proposed 30 days after they end]** | currently no automatic deletion |
| Audit-log IP addresses | **[DECISION: proposed 12 months]** | currently no automatic deletion |
| Demo requests | **[DECISION: proposed 12 months unless you become a customer]** | currently no automatic deletion |
| Payment and tax records | as the law requires [LAWYER: period] | |
| Backups | deleted data leaves our backups within **[14] days** [FILL IN: your real backup retention, including off-site copies] | |
| Some records survive a business deletion: a log line that the deletion happened, anonymous scan counts, and usage counters without content | [LAWYER: confirm acceptable] | |

## 8. Your rights and how to use them

* **See and download your data**: Settings, Your data, "Download my data" (a ZIP of your business's records; it never includes passwords or tokens).
* **Correct it**: edit it in the app, or write to us.
* **Delete it**: Settings, Your data, "Delete this business". Deletion is scheduled and you have 14 days to cancel. After that we remove the business's data and revoke our access to your Google account. If you have a paid plan, cancel it first.
* **Withdraw consent**: for Google actions, in the app at any time; for emails, in Settings, Notifications.
* **Complain**: write to our grievance officer at [EMAIL]. If you are in India you may also approach the Data Protection Board of India; [LAWYER: EU/UK people may complain to their supervisory authority].
* **If you are a customer of a business that uses FlowQR**: contact that business, or write to us with the business name and the approximate time; we will pass it on or act as the business directs.

We will reply within [LAWYER: response period].

## 9. Children

FlowQR is for businesses. You must be [18] or over to create an account [LAWYER: confirm wording; sign-up does not yet ask]. Our public review pages are not designed for children, and we do not knowingly collect personal data from anyone under 18 [LAWYER: Indian law restricts tracking and behavioural monitoring of children; confirm the daily-rotating visitor code is acceptable].

## 10. Security

Encrypted connections, one-way hashed passwords (Argon2), encrypted Google tokens, separation of every business's data inside the database, role-based access, a tamper-evident history of changes to Google profiles, and audit logs. No system is perfectly secure. If a personal-data breach affects you we will tell you and the authorities as the law requires, see [our incident process]. Tell us at once if you suspect a problem: [SECURITY EMAIL].

## 11. Changes

If we change this policy in a way that matters we will update the date and tell account owners by email [and in the app].
