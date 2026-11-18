# Privacy, data-protection and consumer-law audit (pre-launch)

Date: 2026-11-18. Scope: whole repository (frontend, backend, config, deploy files, email text, third-party calls). Audience: the owner, before launch, for India, EU/UK and US users. **This is an engineering audit, not legal advice.** Every item that needs a lawyer is marked **ASK A LAWYER**.

Nothing was deployed, pushed or committed. Code changes are listed in section 4; they are in the working tree only.

> **Update 2026-11-18:** the owner's approved decisions have been implemented in the working tree (not deployed). See sections 8 to 14 at the end of this file, and [LAUNCH_READINESS_CHECKLIST.md](LAUNCH_READINESS_CHECKLIST.md). Sections 1 to 7 below are the original audit and describe the state **before** those changes.

## 1. Result in one paragraph

FlowQR's technical privacy basics are strong: no analytics, ad pixels, session replay or chat widgets exist in the frontend; passwords use Argon2id; no secret has ever been committed; every tenant table has forced row-level security (a test enforces it); error pages are generic; Sentry is scrubbed; export and 14-day-grace deletion exist and are tested. The gaps are (a) Google Fonts were loaded from Google's servers (fixed), (b) the data export omitted 21 tables (fixed), (c) a pre-ticked WhatsApp consent box and no privacy link on the demo form (fixed), and (d) a larger group that code cannot fix: no breach plan, a placeholder refund-policy page, undefined retention for several kinds of personal data, no age statement, no consent/notice wording review, an open question about the AI provider's data-use terms, and the already-known Google 30-day storage question (`GOOGLE_DATA_RETENTION_FINDINGS.md`).

## 2. Checklist (PASS / FAIL / NOT APPLICABLE)

### A. Children and age
| # | Item | Result | Evidence |
|---|---|---|---|
| 1 | Sign-up asks date of birth or age | **FAIL** | `frontend/src/app/(auth)/register/page.tsx:35` collects name, email, phone, password only. The privacy page says "not directed at children" (`privacy/page.tsx:47`) but nothing checks it. |
| 2 | Under 18 (DPDP) / under 13 (COPPA) blocked or parental consent | **FAIL** | No age gate, no parental-consent flow. FlowQR is B2B, so the risk is low for account holders; see 3 for customers. **ASK A LAWYER** whether a plain "you must be 18 or over" term is enough. Adding a checkbox changes sign-up, so it is not done without approval. |
| 3 | Children excluded from tracking and behavioural monitoring | **FAIL (medium)** | Public review pages (`/q`, `/r`, `/c`, `/n`) are open to anyone, including minors. Scans store a daily-rotating **hashed device fingerprint** (`scan_events.visitor_hash`) to count unique visitors, and the customer's typed words go to the AI provider. DPDP s.9 forbids tracking or behavioural monitoring of children. **ASK A LAWYER** whether a rotating hash used only for counting is "tracking". |

### B. Consent, privacy notice and policy
| # | Item | Result | Evidence |
|---|---|---|---|
| 4 | Privacy policy linked from sign-up and footer, plain language, what/why/who/how long | **PASS (with gaps)** | Linked from `register/page.tsx:86` and the footer (`FooterCards.tsx:12`). Content gaps: does not name Google Fonts-style third parties (now moot), does not mention prospects/leads, backups, session and IP logs, device storage, or retention of Google data (`privacy/page.tsx`). Draft improvements: `docs/PRIVACY_POLICY_DRAFT.md`. **ASK A LAWYER** before publishing. |
| 5 | Consent asked before collecting personal data, separately per purpose, not pre-ticked | **FAIL → partly fixed** | Demo form pre-ticked "You can also message me on WhatsApp" (`DemoForm.tsx:12`) and had no privacy link. **Fixed** (unticked; link added). Sign-up uses "by creating an account you agree" (`register/page.tsx:86`), one sentence for Terms and Privacy, no separate boxes; whether contract/legitimate-use is enough under DPDP/GDPR is **ASK A LAWYER**. Google-data actions already require a per-location, per-action consent stored with its wording (Milestone 2: `services/consent.py`). |
| 6 | Withdraw consent as easily as given | **PASS** | Google consents: owner revoke endpoint (`autonomy_actions.py`); notification emails: `/settings/notifications`; Google disconnect in Settings. No separate consent exists that cannot be withdrawn. |
| 7 | US opt-out of sale/sharing | **NOT APPLICABLE** | The policy states no sale and no advertising (`privacy/page.tsx:27`); the code sends no data to ad networks. If that ever changes, a "Do not sell or share" link becomes mandatory. |

### C. Third-party requests
| # | Item | Result | Evidence |
|---|---|---|---|
| 8 | List of every third-party domain | **DONE** | Section 3. |
| 9 | Self-host fonts; no requests to fonts.googleapis.com / fonts.gstatic.com | **FAIL → fixed** | `frontend/src/app/layout.tsx:21-24` (before the change) loaded Geist, Inter, Geist Mono, Plus Jakarta Sans and Noto Sans Devanagari from Google on every page, sending visitors' IP and browser details to Google. **Fixed** with `next/font` (files downloaded at build, served from FlowQR's domain). The built output contains no reference to either host (checked). |
| 10 | Embeds only after click/consent | **PASS** | No YouTube, map or social embed exists. Razorpay and Cashfree scripts are injected only after the user clicks a pay button (`frontend/src/lib/billing.ts:27-31,46`). Wikimedia pictures on `/industries` are text credit links, not loaded resources. |

### D. Cookies, analytics, session replay
| # | Item | Result | Evidence |
|---|---|---|---|
| 11 | Consent banner blocking non-essential cookies/scripts | **NOT APPLICABLE (nothing to block)** | FlowQR sets only strictly necessary cookies: `flowqr_session` (HttpOnly), `flowqr_csrf`, and short-lived Google sign-in/connect state cookies `flowqr_gl_oauth` and `flowqr_oauth_state` (`core/deps.py:20-21`, `api/v1/auth.py:47-50`, `auth_google.py:40,57`, `google.py:31,71`). Device storage holds only interface choices (theme, sidebar, selected location, start-up screen) plus **one customer-facing entry: the review page keeps the customer's unfinished review text, stars and topics in the browser for 24 hours so a return from Google does not lose it** (`components/public/ReviewLanding.tsx:37,123,149`). It never leaves the device, but it belongs in the privacy policy's device-storage section. No analytics, advertising or replay script exists. A banner would gate nothing and would only mislead. **One trap:** `frontend/src/lib/track.ts` pushes marketing events to `window.dataLayer` for "an analytics tag if installed". The day anyone installs Google Tag Manager, GA or a pixel, a consent banner that blocks the tag until "Accept" is mandatory first. |
| 12 | Session replay, heatmaps, keystroke recording off by default and masked | **PASS** | None present. |
| 13 | Chat widgets / form-capture tools sending typed text to third parties | **PASS (for third-party widgets) / see 26 for AI** | No widget. Typed text does go to the AI provider (item 26). |

### E. Emails and messages
| # | Item | Result | Evidence |
|---|---|---|---|
| 14 | Marketing emails: unsubscribe, postal address, honoured | **NOT APPLICABLE** | FlowQR sends no marketing email: only verification, password reset, invitations, payment-failed and the per-person notification digest (`mailer.send_email` call sites). The digest has a "change which emails you get" link (`services/notifications.py:130`). If marketing email is ever added, unsubscribe + postal address + a suppression list are required first. |
| 15 | Marketing and transactional separated; no marketing without opt-in | **PASS** | No marketing email exists. The demo-request form does not subscribe anyone to anything. |

### F. Security basics
| # | Item | Result | Evidence |
|---|---|---|---|
| 16 | No secrets in frontend, git history or public env | **PASS** | `.gitignore` excludes `.env*` (`.env.example` only is tracked); no `.env` was ever added in history; the only key-shaped history match is the fake `GOCSPX-super-secret-value` in a test; CI scans for `rzp_live_`, `AIza…`, private keys (`.github/workflows/ci.yml:83`). `NEXT_PUBLIC_*` variables hold only site URL, API URL and a WhatsApp number. |
| 17 | RLS on every table; no public buckets | **PASS** | `tests/test_phase2_security_audit.py:247` asserts forced RLS and a policy on every tenant table; the app role cannot bypass RLS (`:261`). Photos and logos are stored in the database (`services/media.py`), never in a public bucket. |
| 18 | Hashed passwords, HTTPS, rate limits, validation | **PASS** | Argon2id (`core/security.py:6,12`); HSTS at the proxy (`deploy/Caddyfile:9`, `deploy/vps/Caddyfile.flowqr-api:16`); limits on login (per IP and per email), register, reset request/confirm, verify, resend, set-password (`api/v1/auth.py:83,103-107,198,210,227,241,262`); Pydantic validation on bodies; `test_security_audit.py`. Low note: uvicorn runs `--forwarded-allow-ips=*` (`backend/Dockerfile:15`); safe only while the API port is reachable solely through Caddy, which overwrites `X-Forwarded-For` (`Caddyfile.flowqr-api:24`). |
| 19 | Errors and logs expose no personal data or stack traces | **PASS** | Unhandled errors return one generic sentence (`main.py:56-60`); login, reset and verification answers are generic; Sentry drops bodies, cookies, headers and local variables (`core/monitoring.py:22-35`) and access logs redact tokens. Low note: a few routes return a custom exception message (`api/v1/qr.py:92,318`, `admin.py:143`) but those are FlowQR's own poster-render messages, not internals. Register tells a visitor an email already exists (`auth.py:88`, 409), a common, accepted trade-off behind the allowlist gate (`registration.gate_new_account` runs first). |

### G. User rights and data lifecycle
| # | Item | Result | Evidence |
|---|---|---|---|
| 20 | Download data and delete account; deletion really removes data incl. backups on a schedule | **PARTLY FAIL → export fixed** | Export and deletion exist and are tested (`api/v1/account.py`, `services/account.py`, `tests/test_account_lifecycle.py`). **Gap found and fixed:** the export left out 21 tenant tables (knowledge base, scheduled posts and photos, stored Google snapshots and daily metrics, competitor and ranking records, notification choices, usage and plan history). Deletion cascades (checked: every tenant table has `ON DELETE CASCADE` except three intentionally retained, below). **Still open:** (a) deletion exists only for a *business* by its owner; a team member, or a person who owns one of several businesses, has no "delete my own account"; (b) backups are not mentioned to users (`docs/DATA_RETENTION.md` §5 step 6 says they should be); (c) no deletion/export confirmation email; (d) three records survive deletion by design: `audit_logs` rows (tenant set null; an `account.deleted` line), `scan_events` (tenant set null) and `ai_call_ledger` / `api_usage_ledger` (no tenant foreign key). **ASK A LAWYER** whether these satisfy erasure. |
| 21 | Retention rule: delete what you no longer need | **FAIL (partial)** | Rules exist for review-assistant text (90 days), autonomy history (730), map scans (400) (`workers/celery_app.py:26-30`). **No rule** for: expired and revoked login sessions (store IP and browser, `models/tenancy.py:119-120`), used/expired reset and verification tokens, `audit_logs.ip`, **demo-request leads** (name, phone, business: kept forever), reviews, daily metrics, competitor data, and Google Places coordinates. The Google rows are the open launch blocker D3. Proposed numbers are in section 5. |
| 22 | Written breach plan | **FAIL** | None existed. A draft runbook with placeholders is in `docs/INCIDENT_AND_BREACH_RESPONSE.md`. **ASK A LAWYER** for the DPDP Rules timelines and the regulator wording. |

### H. Payments and subscriptions
| # | Item | Result | Evidence |
|---|---|---|---|
| 23 | Price, billing period, auto-renewal next to subscribe button; cancelling as easy as signing up | **PASS (with one gap)** | Price "/ month", "+ GST as applicable" and the Cashfree renewal/₹1/first-payment-after-trial text appear on the pricing cards (`components/marketing/PlansFromConfig.tsx:40-49`); billing terms and an in-app "Cancel subscription" button exist (`settings/billing/page.tsx:77,172`). **Gap: `refund-policy/page.tsx` is a placeholder; every section reads "[LEGAL TEXT TO BE PROVIDED]" and it is linked from the footer.** The terms also say "cancel at any time", the billing page promises the ₹1 is returned, and cards are sold separately, so a real refund/cancellation policy is needed. **ASK A LAWYER.** The checkout is not in this audit's scope beyond copy; it was not changed. |
| 24 | Card details never stored | **PASS** | Hosted checkout (Cashfree/Razorpay); `Payment` rows hold references only. |

### I. User content and AI
| # | Item | Result | Evidence |
|---|---|---|---|
| 25 | Terms, report-content route, takedown process | **FAIL (low-medium)** | Terms exist (`terms/page.tsx`). No "report content" route and no copyright-takedown or grievance-officer process. Customers write review text that FlowQR forwards to Google; owners upload photos and write posts. **ASK A LAWYER** whether an Indian IT-rules grievance officer / notice-and-takedown page is required for this model. |
| 26 | AI use: AI content disclosed, personal data to AI disclosed, provider retention checked | **FAIL (medium-high)** | (a) Owner screens label drafts "AI draft". (b) The **customer-facing review page does not say an AI tool drafts the wording or that the stars and typed words are sent to an AI provider**: it says only "We don't ask for your name, phone or email" (`lib/review-growth.ts:34`) and "Written from your answers" (`:41`). (c) Reviewer names and review text are sent to the AI provider to write replies (`services/ai/replies.py:69`). (d) The policy discloses an AI provider in general terms (`privacy/page.tsx:29-31`) but not what is sent. (e) **The provider is Gemini by default (`core/config.py:60`). Whether Google's Gemini API terms for the key in use allow Google to use prompts to improve its products depends on the account tier. This has not been checked and cannot be from code. Owner action: confirm the key is on the paid tier with the "do not use for training" setting, and record it.** |

## 3. Every third-party domain the app calls

| Domain / service | Where | When | Personal data involved |
|---|---|---|---|
| `fonts.googleapis.com`, `fonts.gstatic.com` | browser, every page | **removed** | visitor IP, browser |
| `checkout.razorpay.com` | browser | only after clicking pay (Razorpay path; not the live provider) | visitor IP, payer details |
| `sdk.cashfree.com`, `*.cashfree.com` | browser | only after clicking pay; form posts allowed by CSP | payer details |
| `accounts.google.com` | browser redirect | when signing in or connecting Google | Google account |
| `api.flowqr.site` | browser | every app/API call (first party) | everything |
| `wa.me` | links only | when a user taps a WhatsApp link | none sent by FlowQR |
| `g.page`, `myaccount.google.com`, `developers.google.com` | links only | on click | none |
| Google Business Profile, Places, OAuth APIs | server | Google features | reviews, reviewer names, profile, metrics, tokens |
| Gemini (or OpenRouter / OpenAI-compatible, per `AI_PROVIDER`) | server | AI drafting | review text, reviewer first name, owner knowledge base, customers' typed words |
| Cashfree / Razorpay APIs and webhooks | server | billing | payer email/references |
| SMTP provider (`SMTP_HOST`) | server | transactional email | recipient address, content |
| Sentry (only if `SENTRY_DSN` set) | server | errors | scrubbed: no bodies, cookies, headers, locals |
| Redis, PostgreSQL | own infrastructure | always | everything |

## 4. Fixes made (in the working tree; not committed)

| Change | Files | Verification |
|---|---|---|
| Fonts self-hosted through `next/font`; Google font `<link>` tags removed; Tailwind and CSS use the new CSS variables; the share-image canvas reads the page's own font | `frontend/src/app/layout.tsx`, `frontend/tailwind.config.ts`, `frontend/src/app/globals.css`, `frontend/src/app/(app)/growth/page.tsx` | `tsc --noEmit` clean; `npm run build` succeeds; the built output contains no `fonts.googleapis`/`fonts.gstatic` reference and the `.woff2` files are bundled; 23 frontend unit tests pass |
| Demo form: WhatsApp box no longer pre-ticked; privacy-policy link added beside "we use these details only to contact you" | `frontend/src/components/marketing/DemoForm.tsx` | build clean |
| Data export now includes 21 more tables; `publish_token` and `dedupe_key` are never exported; a note says photo files are not in the export; a test fails if a new tenant table is added without being exported | `backend/app/services/account.py`, `backend/tests/test_account_lifecycle.py` | 25 tests pass (account lifecycle + retention) |
| New documents | `docs/PRIVACY_COMPLIANCE_AUDIT.md`, `docs/INCIDENT_AND_BREACH_RESPONSE.md`, `docs/PRIVACY_POLICY_DRAFT.md` | n/a |

`backend/app/services/account.py` also holds the earlier, uncommitted Milestone 2 change (consent grants in the export). Review both together.

Design note on fonts: this makes the **build** download the fonts from Google once (the marketing layout already did this for Inter Tight). The build machine needs internet access; visitors do not touch Google.

## 5. Needs your approval (changes what the product does, or sets a number)

1. **An age statement at sign-up** ("I am 18 or over") and the same line in the Terms. Changes the sign-up form.
2. **A "Delete my account" for individual people** (a team member, or someone leaving one of several businesses). Today only an owner can delete a whole business.
3. **Confirmation emails** when deletion is requested, cancelled and completed (and after an export). Adds mail the product does not send now.
4. **Retention jobs.** Proposed defaults (all configurable, all flag-guarded, whole-record deletes, counts only in the audit log): expired or revoked login sessions after 30 days; used or expired reset/verification tokens after 30 days; `audit_logs.ip` cleared after 12 months; demo-request leads deleted after 12 months unless converted. Setting numbers is a decision, not a technicality.
5. **Customer review page notice**: add one line, in English and Hindi, such as "An AI tool helps word your review from your stars and picks. We do not ask for your name, phone or email." This is customer-facing copy.
6. **Per-person erasure of the AI/usage ledgers** (`ai_call_ledger`, `api_usage_ledger` carry a tenant id and survive deletion).
7. **`--forwarded-allow-ips=*`**: restrict to the proxy's address. Touches deploy configuration, so not done.

## 6. Cannot be fixed in code: ASK A LAWYER

1. Privacy policy wording and completeness (draft: `docs/PRIVACY_POLICY_DRAFT.md`), including a clear statement of lawful basis/consent per purpose for India (DPDP Act 2023), and EU/UK (GDPR) if those users will be targeted; whether an EU/UK representative or DPA is required.
2. Refund and cancellation policy text (page is a placeholder).
3. Breach response: the DPDP Rules notification duties to the Data Protection Board and affected people, GDPR's 72-hour rule, who decides (`docs/INCIDENT_AND_BREACH_RESPONSE.md`).
4. Children: whether a rotating hashed device fingerprint on public review pages is "tracking", and whether a 18+ term is sufficient.
5. Google data retention (30 calendar days) and Limited Use applicability (`docs/GOOGLE_DATA_RETENTION_FINDINGS.md`).
6. Data processing terms with each provider (Google, Gemini, Cashfree, email sender, host), international transfers, and whether the tenant ids left in the audit and usage ledgers after deletion are personal data.
7. Takedown / grievance process and officer details.
8. Whether the 14-day deletion grace period and the unspecified backup window satisfy erasure duties.
9. Registrations: contact/grievance details to show on the policy, GST/invoice duties, any sector rules for health businesses (clinics are customers).
10. Owner action, not legal: confirm the Gemini key's data-use terms (item 26e).

## 7. Where personal data lives (for deletion and export)

Own database (all removed when a business is deleted unless noted): `users`, `memberships`, `membership_locations`, `auth_sessions` (IP, browser), `password_reset_tokens`, `email_verification_tokens`, `invitations`, `tenants`, `locations`, `google_connections` (encrypted tokens; wiped on disconnect), `google_locations`, `reviews` (reviewer names and text), `reply_drafts`, `reply_logs`, `review_sessions` / `review_drafts` (customer words, 90 days), `review_events`, `scan_events` (hashed visitor, **survives deletion with tenant unset**), `qr_cards`, `qr_styles` (logo), `review_campaigns`, `subscriptions`, `payments`, `subscription_events`, `card_orders`, `audit_logs` (IP; **survives deletion, tenant unset**), `ai_generation_logs`, `ai_outputs`, `ai_call_ledger` and `api_usage_ledger` (**no tenant link; survive**), `business_knowledge`, `agent_*` and autonomy tables, `consent_grants`, `gbp_snapshots`, `gbp_metric_daily`, `rank_*`, `competitor_snapshots`, `pinned_competitors`, `scheduled_posts`, `scheduled_media` (photo bytes), `notification_prefs`, `promotional_grants`. Not tenant data: `leads` (demo requests; **no deletion path or retention**), `webhook_events` (payload hashes), `registration_allowlist` (email addresses).

Outside the database: Google (revoked on deletion, best effort); the AI provider (stateless per request from FlowQR's side; provider-side retention unverified); Cashfree (the owner must cancel first; FlowQR holds references only); SMTP provider (recipient addresses in delivery logs); database backups (age out in `BACKUP_KEEP_DAYS`, default 14; off-site per the remote lifecycle); Sentry if enabled (scrubbed).

---

# Implementation record, 2026-11-18 (the owner's approved decisions)

> **Status of this section.** Everything below is in the working tree: not committed, not pushed, not deployed, no production database, environment, email or Google call touched. The worker and beat stay stopped, the emergency stop stays on, autonomy and automatic replies stay off. Google content retention and the Gemini data-use terms are **UNRESOLVED**: no fix has been applied to either, and nothing below claims otherwise. Retention periods are **provisional operating settings pending legal review**, never statements of compliance. [LAUNCH_READINESS_CHECKLIST.md](LAUNCH_READINESS_CHECKLIST.md) lists what is done, what needs the owner, and what needs a lawyer.

## 8. What was implemented

Migration: **0039** (one new migration for all of it; chain 0036 -> 0037 -> 0038 -> 0039). Test files: `backend/tests/test_privacy_lifecycle.py` (new), `frontend/tests/privacy-ui.test.mjs` (new), and updates to existing tests listed in §13.

### A. Age declaration (audit item 1, 2)
* **Previous state:** sign-up collected name, email, phone, password. Nothing about age.
* **Change:** an unticked checkbox, English and Hindi, above both sign-up methods (`register/page.tsx`). Password sign-up is refused on the server (422 `age_declaration_required`) unless `age_confirmed` is true; the check runs after the registration gate (so a refused address still learns nothing) and before the duplicate check. A brand-new **Google** account is refused (`age_required`) unless the sign-up page sent `?age=1`, carried in the existing signed, 10-minute flow cookie; people who already have an account sign in as before. The declaration is stored as `users.age_confirmed_at` plus `age_declaration_version` (`2026-11-18.1`), and noted in the sign-up audit entry. **No date of birth.** Existing users are **not** touched: their status stays NULL ("unknown"), and logging in never sets it (tested). The Google button does nothing but ask for the declaration until it is ticked.
* **Files:** `backend/app/schemas/auth.py`, `backend/app/api/v1/auth.py`, `backend/app/api/v1/auth_google.py`, `backend/app/services/registration.py` (version constant), `backend/app/models/tenancy.py`, `frontend/src/app/(auth)/register/page.tsx`, `frontend/src/components/GoogleAuth.tsx`; API/e2e register calls updated.
* **Remaining (lawyer):** whether this declaration is sufficient; the Terms do not yet say "18 or over" (not changed).

### B. Deleting one's own account
* **Previous state:** only an owner could delete a whole business. No way for a person to leave and be erased.
* **Change:** `GET/POST/DELETE /account/me/deletion` and public `POST /account/me/deletion/confirm`; page `/confirm-account-deletion`; panel "Delete my account" in Settings, Account. Flow and rules are in the header of the new block in `backend/app/services/account.py`. In short: typed email + password (Google-only accounts: a sign-in within 15 minutes) -> single-use emailed link (256-bit random, only its SHA-256 stored, 24 h, cleared on use, one identical error for every failure) -> every session revoked -> 14-day grace (the existing setting) that the person can cancel by signing in -> the hourly job **anonymises** the user row (a tombstone: no name, email, phone, password hash, Google id; address freed so they may register again). It also: removes memberships, sessions, reset and verification tokens, notification choices, and invitations addressed to their email; revokes (best effort) and wipes the Google grants they made; cancels their still-queued (approved or scheduled) posts and photos; sets the IP to NULL on their audit entries (the entries stay). Never deletes a business. **Last owner:** refused at request time with the business named, and re-checked when the grace ends (if they have become the only owner meanwhile, the request is cancelled and they are told). Platform administrators are refused. Idempotent (a second run reports `already_deleted`). The completion time is `users.deleted_at` plus a counts-only audit entry.
* **Rate limits:** request 5 per hour per person; confirm 10 per 5 minutes per IP.
* **Files:** `backend/app/services/account.py`, `backend/app/api/v1/account.py`, `backend/app/workers/tasks.py` (the existing hourly `purge_deleted_accounts` now also handles people), `backend/app/models/tenancy.py`, migration 0039, frontend `DeleteMyAccountPanel.tsx`, `confirm-account-deletion/page.tsx`, `settings/account/page.tsx`.
* **Cached personal data:** Redis holds only short-lived rate-limit counters (their keys can contain an IP address or, for login, an email address, for at most 15 minutes) and AI status flags, and they expire by themselves; no other cache of personal data was found in the code.
* **Not done on purpose:** pending autonomy actions the person proposed are left (they belong to the business and need an owner anyway); `google_connections.connected_by` and similar references keep pointing at the anonymised tombstone (no personal data).
* **Remaining (owner):** decide whether a person who is the only owner should be offered a one-click "transfer ownership". **Remaining (lawyer):** whether the surviving pseudonymous references, audit entries and the tombstone satisfy erasure.
* **Launch dependency:** the confirmation and the hourly job run on the **worker and beat**, which are stopped. Until the owner starts them, a confirmed deletion stays scheduled and is not performed.

### C. Lifecycle emails
* **Previous state:** none for export or deletion.
* **Change:** `backend/app/services/account_mail.py`, using the existing mailer and plain-text style. Emails: data export downloaded; **business** deletion requested (once) and completed (once); **personal** deletion requested (the only one with a link), completed, and "could not be completed". Never any exported data, password, address list or review text. Delivery is recorded as an audit entry `email.sent` or `email.failed` with only `{"kind": ...}` (no address, text or link); a mail failure never undoes an export or a deletion. Duplicates: export notices at most one per person and business per ten minutes; the request email is sent only when a new link is created; completion is sent once, after the deletion has committed.
* **Files:** `account_mail.py` (new), `api/v1/account.py`, `workers/tasks.py`, `services/account.py` (captures the owners to tell before a business is deleted).

### D. Retention (provisional)
* **Previous state:** no expiry for ended sessions, reset tokens, audit-log IPs or demo requests.
* **Change:** `backend/app/services/retention.py`; task `flowqr.privacy_retention` on the **existing** beat; CLI `python -m app.cli privacy-retention-report` (counts only). Periods (settings, 0 = keep): ended sessions 30 days after they ended; password-reset tokens 30 days after creation; audit-log IP 365 days (only the IP is cleared); leads 365 days. **Off until `PRIVACY_RETENTION_ENABLED=true`.** A row exactly N days old is kept; all times UTC. Steps are independent (one failing is reported, the rest run), repeatable, and counted in the audit log (counts, never content). Migration 0039 gives the application role `UPDATE (ip)` on `audit_logs` **only** and `DELETE` on `leads`, and adds a trigger that refuses any audit update except clearing the IP (or the database's own SET NULL of tenant/user), so the audit content stays append-only even for the table owner (tested).
* **Not touched:** payments, invoices, subscriptions, reviews, metrics, Google data, the autonomy history (own rules in `DATA_RETENTION.md`).
* **Remaining (owner):** review the dry-run report, then enable. **Remaining (lawyer):** the periods.

### E. AI notice on customer review pages
* **Previous state:** the page said only "We don't ask for your name, phone or email."
* **Change:** the owner's exact English and Hindi wording in `frontend/src/lib/ai-notice.ts`, rendered by `components/public/AiNotice.tsx` on the campaign review page and the card page, before any text can be sent for AI help, always visible, 13.5 px, marked with its own language, Hindi when Hindi is chosen (English for English, Hinglish, "same as I wrote" on an English page). It appears only when AI help is offered (and AI help is now hidden while the safeguard in §9 blocks it). It is a **notice, not a consent box**: nothing is pre-ticked, and no consent step was added because the legal design is undecided (owner and lawyer, checklist O4/L3). The pages already say the customer posts their own review.
* **Files:** `ai-notice.ts`, `AiNotice.tsx`, `ReviewLanding.tsx`, `CardLanding.tsx`.

### Legal documents (section 5 of the brief)
* The public refund page no longer shows "[LEGAL TEXT TO BE PROVIDED]" as policy: it says the policy is not published yet, points to support, states only what the Terms already say about cancelling, invents no refund terms, and is set not to be indexed (`RefundPending.tsx`).
* `PRIVACY_POLICY_DRAFT.md` and `INCIDENT_AND_BREACH_RESPONSE.md` stay drafts and now open with a clearly labelled owner/lawyer action list. The live privacy page and Terms were **not** changed (they are unapproved legal text for the lawyer to revise). No lawyer approval, deadline, lawful basis, grievance officer, address or contact has been invented anywhere.

## 9. The Gemini safeguard (interim; does not resolve finding 26e)

* **Every path that sends review data to a provider** (all go through `services/ai/`): reply drafting (`replies.draft_reply_scored`, used by the reviews screen, the agent plan and auto-draft), the customer writing assistant (`review_assist.improve_review`), the review generator (`review_generate.generate_review`, including its fact-check), and the AI review-risk check (`risk.classify`). Google post drafts, post ideas and profile descriptions use only the owner's business facts (and counted theme words), not review text, and are not gated.
* **Minimised:** the **reviewer's name is no longer sent at all**; e-mail addresses, phone numbers and links in review text and in customers' typed words are replaced by placeholders (`services/ai/privacy.redact`). Names written inside free text cannot be reliably found and are **not claimed** to be removed.
* **Settings and default-safe behaviour:**

| Setting | Default | Effect |
|---|---|---|
| `GEMINI_DATA_TERMS_VERIFIED` | `false` | Review data is **not** sent to Gemini. The AI feature reports "unavailable" **before any prompt is built**; the product carries on (a person writes the reply or the review; an unchecked 3-star review goes to a person; customers are not offered AI help; owners see why on the assistant page). Set to `true` **only** when the owner holds written evidence about the key's terms. |
| `AI_REVIEW_DATA_KILL_SWITCH` | `false` | `true` stops review data going to **any** provider immediately. |

* Other providers (OpenRouter, an OpenAI-compatible endpoint) are not covered by the Gemini rule; they are off unless configured and their terms are for the owner to check. No provider was switched and no paid model introduced.
* **What this does not do:** it does not claim Gemini's terms are acceptable or unacceptable, and it is not a data processing agreement. **Production effect of deploying this: review AI stays off until the owner sets `GEMINI_DATA_TERMS_VERIFIED=true`.**

## 10. Google-derived data map (NO FIX APPLIED; owner and lawyer must decide first)

Nothing below was changed. Counts of stored rows were not read from production. "Now" is how long FlowQR keeps it today. The governing wording is in [GOOGLE_DATA_RETENTION_FINDINGS.md](GOOGLE_DATA_RETENTION_FINDINGS.md).

| Data type | Stored in | Source | Now | Read by (main) | Possible options (not chosen) |
|---|---|---|---|---|---|
| Reviews: reviewer name, rating, text, Google's reply text and time | `reviews` | Business Profile reviews | indefinitely (disconnect keeps them as history) | reviews screens and API, reply drafting, agent plan tasks, health, review intelligence (themes), growth score, insights, notifications, onboarding, auto-reply eligibility, outcomes | (a) keep, with Google's written confirmation; (b) keep a rolling window of at most 30 days and store only FlowQR-owned counters (answered this month, rating mix) as numbers; (c) fetch on demand and keep none |
| Daily performance metrics | `gbp_metric_daily` | Performance API | indefinitely | `services/gbp_metrics.py` -> SEO performance page, growth score | (a) keep with confirmation; (b) 30-day window plus owner-held monthly totals (an aggregate: itself a question); (c) show only what a live call returns |
| Profile, posts, media, 56-day performance and search terms | `gbp_snapshots` | Business Information and v4 APIs | replaced on each refresh (about daily) | agent plan, health, optimiser, SEO engine, executor read-back, intelligence, growth score, reports, posts and SEO APIs | likely already "temporary"; confirm the refresh interval stays under the ceiling |
| Location row, title, place id, **coordinates** | `google_locations`, `locations.lat/lng` | Business Profile; Places | indefinitely | rank checks and grids, SEO | place id is stated as storable; coordinates: store only the place id and re-fetch (a paid call, D6), or keep to 30 days |
| Coordinates of search centres and map points | `rank_keywords`, `rank_grids.center_*`, `rank_grid_points.lat/lng` | derived from the location | 400 days (scans) / indefinitely (centres) | geo-grid (disabled) | same question as above; geo-grid stays disabled |
| Competitor names, ratings, review counts, positions | `rank_checks.top_results`, `competitor_snapshots`, `pinned_competitors` | Places | indefinitely (map scans 400 days) | rank tracker, competitors, growth score, ops | depends on the Places Service Specific Terms (page returned empty when read): confirm field by field |
| What Google held before and after each FlowQR change | `agent_actions.current_value/proposed_value/verification` | Business Information | 730 days | autonomy, history screens | whether audit evidence of FlowQR's own actions is "Content": unresolved |
| FlowQR-written replies and drafts derived from reviews | `reply_drafts`, `reply_logs` | FlowQR (about a review) | indefinitely | reviews, auto-reply, analytics, reports | FlowQR's own content; whether the review text inside a draft is Content: unresolved |
| Derived records (task titles naming a reviewer, health scores) | `agent_tasks.title/evidence`, `health_snapshots` | derived from reviews and metrics | indefinitely | agent UI | derived data and aggregates are a question of their own ("cannot be manipulated or aggregated") |
| OAuth tokens | `google_connections` (encrypted) | OAuth | until disconnect, then wiped | sync, writes | not "Content"; wiped on disconnect and on personal deletion |
| Backups | database backups | all of the above | `BACKUP_KEEP_DAYS` (local) and the remote lifecycle | restore only | state the window to users |

**Open questions** (all unresolved; owner and lawyer): (1) does "Content storage" apply to reviews and metrics for a product that exists to sync and analyse them? (2) is `business.manage` a scope the Limited Use rules cover, and do they reach derived and aggregated data? (3) the Places field-by-field caching periods; (4) whether disconnecting must delete stored Content, and within what time; (5) whether FlowQR-authored replies, derived scores and counters are "Content"; (6) how backups count. **Do not** implement a 30-day deletion, and do not describe one as resolving Google's rules, until answers exist.

## 11. Security review (what was verified, and what could not be)

| Check | Result | Evidence and limits |
|---|---|---|
| `--forwarded-allow-ips=*` is safe only if Caddy is the sole trusted ingress | **Not guaranteed on the shared VPS.** | `backend/Dockerfile:15`. The VPS override publishes the API on `127.0.0.1:18000` and the **docker0 gateway `172.17.0.1:18000`** (`deploy/vps/docker-compose.vps.yml:32`); the production compose resets other published ports; Caddy overwrites `X-Forwarded-For` (`Caddyfile.flowqr-api:24`). The internet reaches the API only through Caddy. But the server also runs the clinic's containers, and a container on that host can reach `172.17.0.1:18000` and send any `X-Forwarded-For`, which uvicorn then trusts. **Effect:** it could dodge a per-IP rate limit and write a false IP into sessions and audit entries. It cannot bypass login, CSRF or row-level security. **Not fixed** (deploy file, production). **Owner action:** on the server, from another container run `curl -H 'X-Forwarded-For: 203.0.113.9' http://172.17.0.1:18000/api/health` and `docker network inspect`; then set `--forwarded-allow-ips` to the proxy's address as the API sees it. |
| Application ports are not publicly exposed | **Confirmed from files only** | See above. The live server was not inspected and nothing was changed there. |
| Forwarded headers cannot be spoofed through another path | **No**, same finding | |
| Deletion cannot bypass tenant RLS | **Confirmed** | The personal-deletion routes act only on the caller's own user row. The hourly job uses a bypass session by design (like the business-deletion job) but touches only rows owned by that person (memberships, sessions, tokens by user id; posts, photos and connections by `created_by` / `connected_by`). Tested: both businesses and the co-owner are intact; a blocked deletion changes nothing. |
| Confirmation links are signed, expiring, single-use | **Confirmed, with a wording note** | Random 256-bit tokens (not HMAC-signed), only the SHA-256 is stored, 24 h expiry, cleared on use, one identical answer for any failure (tested). The business-deletion request has no link (owner types the name and password). |
| Export files are private, temporary, tenant-scoped | **Confirmed** | Built in memory and streamed, never written to disk; `Cache-Control: private, no-store`; owner only; tenant-scoped under RLS; tests show other businesses' rows are absent. |
| Deletion and export endpoints are rate-limited | **Confirmed after one addition** | Export 3 per hour per business; personal request 5 per hour per person; confirm 10 per 5 minutes per IP. The existing **business-deletion request had no limit** on password attempts: a limit of 5 per hour per person was added. |
| Audit logs do not capture secrets, tokens or review text | **Confirmed, one finding** | Every `audit(... meta=...)` call was read: no tokens, passwords or review text. **Finding:** admin actions write **email addresses** into audit metadata (`admin.registration_allow/disallow`, `admin.user_lookup`, the same actions in the CLI). The audit content is append-only, so a personal deletion does not erase them. The registration gate already stores only a hash. Decision O6; the retention job and the deletion service clear **IP addresses only**. |

## 12. Content reporting and takedown

* **Audit:** there is **no** mechanism for reporting abusive, fraudulent or inappropriate content, no copyright or takedown process, and no grievance route in the application (searched the backend and frontend). The privacy page mentions a grievance only as "contact us".
* **What content exists:** customers' typed words (deleted after 90 days), review text and replies (Google's, copied in), owners' posts and photos (sent to Google), business names and logos. FlowQR does not host public user-generated pages other than the owner-configured review page (business name, welcome message, logo).
* **Minimal design (not built, because the process and any response times are legal decisions):**
  * Table `content_reports` (tenant-less, like `leads`): id, created_at, `kind` (abusive | fraudulent | inappropriate | copyright | other), `target_type` (review_page | business_listing | post | other) and `target_ref` (campaign public id, card token, or free text), `description` (free text, length-limited, flagged as possibly personal), optional reporter name and contact (both optional), `status` (new -> in_review -> actioned | dismissed | needs_info), `decided_by`, `decided_at`, `decision_note`.
  * Audit trail: one `audit` entry per status change (counts and ids, never the description), plus the table's own timestamps.
  * Public entry: one rate-limited, honeypot-protected form (same pattern as `/public/leads`) that never reveals whether the target exists or who owns it.
  * Admin workflow: a queue in the existing admin area, filter by status, an action that can pause a review campaign or card (existing pause controls) and records the decision. Reporter is told only what the lawyer approves.
  * **Not decided, so not built:** the grievance officer, the contact address, any acknowledgement or response deadline, the copyright (notice and counter-notice) steps, who may be told what.
* **Technical pieces that need no legal decision were not added**, to avoid a half-finished public route.

## 13. Tests executed

Run 2026-11-18 on the working tree, against real PostgreSQL in the project's Docker test harness (no production, no live Google, no live AI, no real email).

| Suite | Command | Result |
|---|---|---|
| **Backend, everything** | `pytest tests` (the whole backend suite) | **1,780 passed, 0 failed, 0 skipped** (14 min 1 s) |
| New backend tests | `tests/test_privacy_lifecycle.py` | 34 tests, all in the figure above: age declaration (password and Google, existing users untouched), the full deletion flow across two businesses, last-owner protection (at request and at the end of the grace period), platform admin refusal, link expiry and single use, Google-only re-authentication, queued posts and Google grants, rate limits (personal and business deletion), anonymous access, the three lifecycle emails (no data, no duplicates, failure recorded without contents), retention (exact 30 d / 365 d boundaries including a +05:30 timestamp, used and unused tokens, IP removal with the entry kept, the database trigger, leads, zero = keep, repeat run finds nothing, disabled = no-op, dry run counts only, one failing step does not stop the rest, beat entry and approved periods), AI gate (default blocked, kill switch on any provider, non-Gemini unaffected, reviewer name never sent, masking, assistant and risk check and generator gated, public pages and owner settings) |
| Existing tests changed | register calls now send the declaration; the Google test helper sends `?age=1`; migration pins (head 0039); the route manifest (4 reviewed routes); two security-audit allow-lists (the confirm link route, reviewed); the review-growth and AI-cost fixtures declare the Gemini terms verified (they test generation and budgets, not the gate); the SEO metrics date test now uses the business's own timezone (a time-of-day flake that predates this work) | |
| Existing tests that stayed as they were | consent (`test_consent.py`), account lifecycle, retention and live-prep, security audits, RLS tests | pass |
| Migration checks | `tests/test_migration_0037.py` (one straight line to head 0039; the downgrade to 0036 and re-upgrade, which runs 0039 down and up) | pass, inside the 1,780 |
| **Frontend unit tests** | `npm test` | **30 passed, 0 failed, 0 skipped** (23 existing + 7 new in `tests/privacy-ui.test.mjs`) |
| **TypeScript** | `npx tsc --noEmit` | exit 0, no errors |
| **Production build** | `npm run build` | compiled, 92 static pages; `/confirm-account-deletion`, `/refund-policy`, `/register` present; **no reference to fonts.googleapis.com or fonts.gstatic.com** in the output |
| Rendered check | served the production build locally and read the HTML | sign-up page: declaration checkbox present, no `checked` attribute, English and Hindi wording present; refund page: no placeholder text, "not been published yet" present, noindex present |

The first full run had **5 failures**, all explained and resolved: three were the new AI gate correctly blocking test stubs named "gemini" (fixtures now declare the terms verified; the gate has its own tests), one was the prompt-fingerprint pin firing because the reply prompt no longer carries the reviewer's name, and one was the timezone flake above. **About the prompt pin:** the four reply fingerprints (`reply-coaching-1`, `reply-dental-1`, `reply-physio-2`, `reply-salon-3`) were rewritten through the test's own update switch. The quality benchmark the test asks for (`ai-eval`) was **not re-run**: it calls a live AI provider, and review data is deliberately blocked from Gemini by default. Whether replies without the reviewer's name are as good as before is therefore **unmeasured**.

**Not executed:** the Playwright scripts in `e2e/` (updated to send the declaration, but they need the whole stack and a browser, and were not run); any live Google, Gemini, Cashfree or SMTP call; anything on the production server; the AI benchmark; the retention job against any real data (the tests use the test database only).

## 14. Production deployment sequence (DOCUMENTATION ONLY: none of this was run)

Prerequisites: owner decisions O2 in [LAUNCH_READINESS_CHECKLIST.md](LAUNCH_READINESS_CHECKLIST.md); a verified recent backup. Production's schema head today is **0037** (Cashfree); this release carries **0038** (consent: switches every tenant's autonomy and auto-reply OFF, consistent with the emergency stop) **and 0039**.

1. Back up the database and record the release tag and `alembic_version` (`docs/PRODUCTION_BACKUP_RESTORE.md`). Confirm the backup restores.
2. When the owner asks for it: commit, tag, build the backend image and the frontend (the owner does the commit and push; this task did not).
3. Production environment file on the server (never in git): leave `GEMINI_DATA_TERMS_VERIFIED` unset (false); `AI_REVIEW_DATA_KILL_SWITCH=false` (or `true` to be extra careful); `PRIVACY_RETENTION_ENABLED=false`; keep `AUTONOMY_EMERGENCY_STOP=true`, `REGISTRATION_MODE=allowlist`. The four retention periods, `USER_DELETION_CONFIRM_HOURS` (24), `REAUTH_WINDOW_MINUTES` (15) have safe defaults.
4. Deploy the backend with **both compose files** (`docs/PRODUCTION_DEPLOYMENT.md`, `vps-compose-override`): the migrate service runs `alembic upgrade head` (0038, 0039). Check `/api/ready` (it fails if the schema is not at the expected head).
5. Deploy the frontend (Vercel, root-directory recipe). Backend first: the old form never sends the declaration, so the new backend refuses it until the new frontend is live; production sign-up is allowlist-only, so the window affects no public sign-up. (Frontend first also works: the old backend ignores the extra field, but the deletion panel would call routes that do not exist yet.)
6. Verify with the owner's **own test accounts only** (never the clinic accounts): register with the box ticked and unticked; download an export and receive the notice; open a throwaway account's deletion request and read the email (this sends real mail to a mailbox the owner controls); check a customer review page shows the notice in both languages **only if AI help is on**; check `python -m app.cli privacy-retention-report` prints counts and changes nothing.
7. **Worker and beat remain stopped.** Personal deletions, business deletions and retention all run there. Starting beat also starts the other schedules; the owner decides if and when, with the emergency stop still on. Until then confirmed deletions wait.
8. Retention: review the report, then set `PRIVACY_RETENTION_ENABLED=true` when the owner approves the periods.
9. Gemini: set `GEMINI_DATA_TERMS_VERIFIED=true` only after the written evidence exists (O1).
10. Rollback: redeploy the previous application tag (the schema may stay: the old code ignores the new columns and the new grants are harmless). Downgrading 0039 drops the declarations and any pending self-deletions and removes the audit IP guard; do that only deliberately.
