# WhatsApp Automation: Phases 1 to 3

Status: **Phases 1, 2 and 3 are implemented in the repository and tested locally; not deployed; every flag OFF by default.** Phases 2 and 3 are described in the section "Phases 2 and 3" below; the rest of this document describes Phase 1. No real Meta account, number, customer or message has been involved. Nothing in this document has been applied to production.

Branch `feature/whatsapp-automation`, migrations **0048** (Phase 1, parent 0047) and **0049** (Phases 2 and 3, parent 0048). Official Meta WhatsApp Cloud API only: no WhatsApp Web automation, no unofficial libraries.

## Product decisions (confirmed)

- Each business connects **its own** WhatsApp Business number through Meta **Embedded Signup**; customers see the business's number.
- Customer data comes only from: explicit opt-in on QR review pages and website forms (service ready, wiring is Phase 2), manual entry with a consent record, and CSV import with an explicit attestation. **Nothing is ever assumed to be consent**: review submissions, enquiries and existing contacts create no consent.
- Meta's per-message charges and FlowQR's add-on fee are separate. The add-on (Starter ₹299, Growth ₹499, Pro ₹799 per month, 3/8/15 automations) is **recorded by hand** by an administrator; no billing, no plan change, no Cashfree.
- Coexistence with the WhatsApp Business app is **not promised**; eligibility must be verified with Meta (see Meta prerequisites).

## What is implemented in Phase 1

| Area | Implemented | Where |
|---|---|---|
| Data model, forced RLS | 8 tables | `models/whatsapp.py`, `alembic/versions/0048_whatsapp_foundation.py` |
| Connection (Embedded Signup server side) | start (one-time state), complete (code exchange, ownership check, encrypted token, webhook subscription), check, disconnect | `services/whatsapp/connection.py`, `meta.py` |
| Webhook | verification, HMAC signature on the raw body, sanitised and de-duplicated storage, async processing, status updates, STOP handling, account alerts | `services/whatsapp/webhook.py`, `api/v1/whatsapp_webhook.py`, Celery task |
| Consent | contacts, per-purpose consent with wording, opt-out, suppression, CSV import, export, erasure | `services/whatsapp/consent.py` |
| Send gate | `preflight()` answers (ok, reason); **nothing may send in Phase 1** | `services/whatsapp/gate.py` |
| Add-on entitlements | manual tier per business, audited | `services/whatsapp/addons.py`, `api/v1/admin_whatsapp.py` |
| Owner screens | Overview, Connect (status), Customers (consent), Automations catalogue | `frontend/src/app/(app)/whatsapp/*` |
| Admin | WhatsApp add-on card on the business page | `components/admin/WhatsAppAddonCard.tsx` |
| Housekeeping | re-queue unprocessed events, purge old events, re-check connections | `flowqr.whatsapp_housekeeping` (every 10 min) |

**Not implemented (Phase 2 onward):** template synchronisation, the message sender, delivery usage ledger, Meta pricing table, any automation, campaigns, wiring the opt-in tick into the QR review page and the website enquiry form, notifications.

## Feature flags (all default OFF)

| Variable | Default | Effect |
|---|---|---|
| `WHATSAPP_ENABLED` | false | Master switch. Off: every WhatsApp route answers 404 `whatsapp_disabled`, the webhook answers 404, no menu entry, the Celery jobs do nothing. |
| `WHATSAPP_SIGNUP_ENABLED` | false | Lets a business start Embedded Signup (needs Meta credentials). |
| `WHATSAPP_WEBHOOK_ENABLED` | false | The webhook accepts events (needs the app secret and verify token). |
| `WHATSAPP_SENDING_ENABLED` | false | Reserved for Phase 2. **No code path sends a message in Phase 1.** |
| `WHATSAPP_EMERGENCY_STOP` | false | Platform-wide stop, checked by the send gate. |
| `WHATSAPP_REQUIRE_ADDON` | true | A business needs an active add-on before it can connect a number. |

Other variables: `META_APP_ID`, `META_APP_SECRET` (these already existed as unused placeholders), `WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID`, `WHATSAPP_WEBHOOK_VERIFY_TOKEN` (24+ chars), `WHATSAPP_GRAPH_VERSION` (default `v23.0`), `WHATSAPP_GRAPH_BASE_URL` (default `https://graph.facebook.com`; tests point it at a mock), `WHATSAPP_EVENT_RETENTION_DAYS` (30), `TOKEN_ENCRYPTION_KEY` (already used for Google tokens). The older single-number `WHATSAPP_PHONE_NUMBER_ID` / `WHATSAPP_ACCESS_TOKEN` settings are unused by this multi-tenant design. The production config check refuses to start with `WHATSAPP_ENABLED=true` and any required value missing.

## Database (migration 0048)

`whatsapp_connections`, `whatsapp_contacts`, `whatsapp_consents`, `whatsapp_suppressions`, `whatsapp_templates`, `whatsapp_messages`, `whatsapp_webhook_events`, `tenant_addons`. All have `tenant_id`, **forced RLS** with the standard tenant policy, and are in the account export (secrets excluded by column) and removed with the business.

- One live connection per business and one business per `phone_number_id` (partial unique indexes). That mapping is the only way a webhook or a send is attributed to a business.
- `whatsapp_consents`: the application role can INSERT and can UPDATE **only** `revoked_at`, `revoked_source`, `revoked_by` (column-level grant). Wording, source and time cannot be edited. A new consent after a withdrawal is a new row; one active row per contact and purpose.
- `whatsapp_suppressions` stores a keyed HMAC of the number, so an erased person who opted out can never be re-added by mistake.
- `tenant_addons`: at most one active WhatsApp tier per business.
- **Alembic graph:** 0045 → 0046 → 0047 → **0048** (single head). `feature/cardless-trial` still carries a conflicting 0039 and must be renumbered when it ships.

## API (owner: `/api/v1/whatsapp`, reads need membership, changes need owner/admin)

`GET /status`, `POST /connect/start`, `POST /connect/complete`, `POST /connection/check`, `POST /connection/disconnect`, `GET|POST /contacts`, `POST /contacts/import`, `GET /contacts/export`, `PATCH|DELETE /contacts/{id}`, `POST /contacts/{id}/consent`, `POST /contacts/{id}/opt-out`, `GET /templates`, `GET /automations`.
Admin (platform administrators): `GET /admin/tenants/{id}/whatsapp`, `PUT /admin/tenants/{id}/whatsapp-addon`.
Webhook (public, self-authenticating): `GET|POST /api/v1/webhooks/whatsapp`.
No response contains an access token, the signup state or any Meta secret. The route access manifest lists every route.

## Embedded Signup, step by step

1. The owner (or admin) presses **Connect WhatsApp**. `POST /connect/start` checks the add-on and the email verification, mints a one-time `state` (only its hash is stored, valid 15 minutes) and returns the **public** values: app id, configuration id, Graph version, state.
2. The browser loads Meta's SDK and opens the Embedded Signup window (`launchEmbeddedSignup`, `frontend/src/lib/whatsapp.ts`). Meta returns a one-time `code` (from `FB.login`) and, through a window message from a Meta origin only, the chosen account and number ids.
3. `POST /connect/complete` sends state, code and ids. The server checks the state (single use, this business, this user, not expired), exchanges the code for a business token **on the server**, asks Meta (`debug_token`) which accounts the token was granted and **refuses if the browser's account id is not among them**, reads the number's details, subscribes FlowQR's app to the account's webhooks, stores the token **encrypted (Fernet)** and records tenant → account → phone_number_id.
4. A failed webhook subscription connects but marks the connection **needs attention** with a plain-words reason; **Check connection** retries it.
5. **Disconnect** unsubscribes (best effort), wipes the token and keeps the customers and their consents.
6. A daily check re-validates tokens, notices revoked or expiring ones, and asks the owner to reconnect.

## Webhook

Verification needs the exact verify token (constant time). A delivery needs `X-Hub-Signature-256` = HMAC-SHA256(app secret, **raw body**), checked before the body is parsed or stored; bodies over 1 MB are refused; per-IP rate limit. The stored body is **sanitised** (statuses, the few inbound fields the opt-out rule needs; no profile names, no message text beyond a 64-character keyword check, no media) and keyed by the SHA-256 of the raw body, so a redelivery is recognised and processed once. A Celery task processes it with retries and exponential backoff; if the broker is down the event stays `received` and housekeeping re-queues it; after the last attempt it is marked `failed`, never dropped. **The tenant is never read from the payload**: it is looked up from the verified `phone_number_id`; an unknown, pending or disconnected number is ignored and creates nothing. A body spanning several businesses is handled item by item under each item's own mapping.

Handled in Phase 1: delivery statuses (monotonic: sent → delivered → read; `failed` records Meta's error code and is ignored after delivery), a customer's `STOP` (exact message only; a sentence that merely contains the word is not an opt-out), and account alerts (disabled, violation, partner removed → connection needs attention).

## Consent and compliance model

- Two purposes, kept separate: **marketing** (offers and updates) and **utility** (updates about a visit, booking or enquiry). Each is its own record with the exact wording shown, its version, source (`qr_page`, `website_form`, `customer_message`, `owner_entry`, `csv_import`, `admin_entry`) and time.
- Customer-originated sources are the customer's own act. Owner-side sources need an **explicit attestation** and a **written note** of how consent was obtained; a CSV needs one attestation and one note for the whole file, with the file's own columns never trusted as consent.
- **Opt-out** (customer STOP, or the owner withdrawing): revokes the marketing consent, flags the contact, suppresses the number. Afterwards **only a new consent by the customer themselves can lift it**; an owner, a CSV or an administrator cannot. STOP revokes marketing only; utility consent is its own record.
- Never import contacts and assume consent; the Customers screen says so, and the upload dialog requires the confirmation.
- Contact deletion removes the person and their consents; an opted-out number stays only as a keyed hash. Contact export is a CSV with spreadsheet-formula protection and is audited.
- Meta's 24-hour service window, template categories and approval rules are enforced at send time in Phase 2 (`gate.preflight`); Phase 1 only proves the consent part and refuses everything while sending is off.

## Security controls

Forced RLS on every table; owner routes tenant-scoped through the verified session; admin routes `require_platform_admin`; add-on and connection changes audited (no secrets in audit meta); token Fernet-encrypted, never returned, logged, exported or placed in the audit log; Meta errors are redacted of tokens and secrets; webhook signature, replay-safe de-duplication, tenant from the verified number only; phone numbers validated; invisible and bidirectional characters stripped from names; rate limits on connect, import and the webhook; CSV size and row limits; `WHATSAPP_ENABLED` off by default with a config guard.

## Tests

`backend/tests/test_whatsapp.py` (69 tests against a mock of Meta's Graph API), the route access manifest, the account export drift test, config guard, and migration graph tests; `frontend/tests/whatsapp.test.mjs` (the Embedded Signup message parser incl. origin checks, plain-language wording, CSV preview). Exact results are in the release report.

## Local development

Local mock: set `WHATSAPP_ENABLED=true`, `WHATSAPP_SIGNUP_ENABLED=true`, `WHATSAPP_WEBHOOK_ENABLED=true`, `META_APP_ID`, `META_APP_SECRET`, `WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID`, `WHATSAPP_WEBHOOK_VERIFY_TOKEN` and `WHATSAPP_GRAPH_BASE_URL=http://<a local mock>`. The Embedded Signup popup itself needs Meta's real SDK and a real app; everything server-side can be driven with the mock.

## Meta prerequisites (nothing here has been done)

- **Needs Meta approval:** Tech Provider status (a verified Meta Business Portfolio, a Meta developer app, App Review for **Advanced Access** to `whatsapp_business_management` and `whatsapp_business_messaging`), an Embedded Signup configuration (build on the current version; v2 is deprecated), and, for each message category you will use, approved templates. Review timelines are Meta's, not ours.
- **Needs credentials:** `META_APP_ID`, `META_APP_SECRET`, the Embedded Signup configuration id, a webhook verify token you choose, and the webhook URL registered in the Meta dashboard (`https://api.<domain>/api/v1/webhooks/whatsapp`, subscribed to `messages` and `account_update`).
- **Verify before promising:** WhatsApp Business app **coexistence** eligibility for India; whether the business can pay Meta directly under the Indian billing arrangement; current India per-message rates (they change and sources disagree).
- **Per business:** a Facebook login, a number that can receive a code, a payment method on Meta, and a display-name approval.

## Phase 2 (next)

Template synchronisation and approval tracking; the sender (consent gate, 24-hour window, category match, rate limits, idempotency keys, retries, dead-letter, emergency stop); a usage ledger and a dated Meta pricing table with cost estimates; wiring the WhatsApp opt-in tick into the QR review page and the website enquiry form (using `consent.grant` with `qr_page` / `website_form`); then Phase 3 automations (review follow-up, enquiry follow-up, promotional campaigns) and Phase 4 campaign manager.

## Deployment and rollback (NOT performed; needs explicit approval)

Deploy the code with all flags off (migration 0048 adds eight empty tables; additive), verify, then enable only after Meta approval and credentials, per business, starting with a Meta test number. Rollback: set `WHATSAPP_ENABLED=false` (everything answers disabled; nothing sends); the previous image works with 0048 present; do not downgrade the schema while data exists.

## Phases 2 and 3 (messaging, automations, campaigns)

Still local only and still mock-tested: **no real message has ever been sent, and no code path sends unless `WHATSAPP_ENABLED` and `WHATSAPP_SENDING_ENABLED` are both true and `WHATSAPP_EMERGENCY_STOP` is off.** Migration **0049** adds five tables (`whatsapp_rates`, `whatsapp_automations`, `whatsapp_automation_runs`, `whatsapp_campaigns`, `whatsapp_campaign_recipients`) and four columns on `whatsapp_messages` (`campaign_id`, `run_id`, `idempotency_key` unique per business, `est_rate`). Alembic: 0047 → 0048 → **0049** (single head).

### Templates (`services/whatsapp/templates.py`)
The business never writes a template. FlowQR submits four fixed, neutral ones to Meta on the business's own account (`flowqr_review_followup_en`, `flowqr_enquiry_ack_en`, `flowqr_enquiry_followup_en`, `flowqr_offer_en`), then tracks what Meta decided. Meta's rules are kept (a variable never starts or ends the body, variables are short single-line text). **The category is what Meta says, not what FlowQR asked for**: if Meta re-classifies the review request as marketing, it is sent only to people who agreed to offers. Sync reads the account's templates (status, category, rejection reason) and marks vanished ones disabled. Only an `approved` template of the business's own connection can ever be sent.

### The sender (`services/whatsapp/sender.py`)
The only place a message is sent. A send needs, in order: the platform switches; the add-on and a healthy connection of the business's own; consent of the kind the template's real category needs, with no opt-out; an approved, own-connection, marketing-or-utility template; clean variables; an unused idempotency key (a retry, a re-run or two workers can never send twice); no marketing message to the same person within `WHATSAPP_MARKETING_GAP_HOURS`; and the per-minute and per-day limits. Only templates are sent, never free text. A temporary Meta failure leaves no trace and is retried with the same key; a final failure is recorded with Meta's error code; a token error marks the connection as needing attention.

### Pricing and usage (`pricing.py`, `usage.py`)
Meta's per-message rates are **dated data** in `whatsapp_rates` (country, category, effective date, source, verified flag), never constants. Rows are never edited: a change is a new row with a later date (platform administrators: `POST /admin/whatsapp/rates`). The seed rows are an **unverified** estimate from third-party summaries of Meta's India rate card (marketing about 0.86, utility about 0.115 rupees per delivered message); an administrator must replace them with Meta's own numbers. Every money figure is labelled an estimate, says whether its rate is verified, and is shown separately from FlowQR's fee. Usage keeps attempted, sent, delivered and read apart (delivered is never called read) and estimates cost on **delivered** messages only, at the rate in force when each was sent.

### Automations (`automations.py`)
- **Review follow-up** ("Get more customer reviews"): the owner marks a customer's visit done (a button on the Customers screen, `POST /contacts/{id}/visit`; appointment management is deliberately not part of this). One neutral request for honest feedback with the business's own review link is scheduled after a delay (default 60 minutes), never more than one a day and never more often than `WHATSAPP_REVIEW_GAP_DAYS` (30). It goes to everyone who agreed to visit updates: **no filtering or steering by expected rating, and no reward**; the wording is tested for neutrality.
- **Enquiry follow-up**: a website enquiry form can show an optional "updates on WhatsApp" tick (a switch in the site editor's Contact section). If the visitor ticks it, their own consent to visit/enquiry updates is recorded (source `website_form`) and an acknowledgement and, if nobody has replied by then, one follow-up are scheduled. Without the tick nothing is recorded or sent. A failure here never loses the enquiry.
- **Engine**: trigger → one scheduled run with a unique idempotency key → the worker (`flowqr.whatsapp_run_due`, every minute) executes due runs under a row lock through the sender. Temporary failures retry with growing delays up to `WHATSAPP_SEND_MAX_ATTEMPTS`, then the run is `failed` with its reason (the dead letter, visible to the owner). Pausing or switching off cancels what has not been sent. The add-on limits how many helpers can be on (3/8/15); switching one on submits its standard messages for approval and refuses until WhatsApp has approved them.

### Campaigns ("Offers", `campaigns.py`)
Create (name, the approved Offer message, audience: everyone / a group / new customers / earlier customers, the offer text) → **preview** (how many people, the message as they will read it, an estimated charge) → **explicit approval** → batched sending → results. Growth and Pro only. Approval must repeat the recipient count shown (if the audience changed it is refused and the new count shown), must confirm the estimate, and the approved count is a ceiling. Consent is re-checked for every person at the moment of sending. Pause, resume, cancel at any time; the emergency stop holds everything and sending continues afterwards. Results report sent, delivered, read (only where the customer allows read receipts), failed, waiting, skipped (with reasons) and customers who asked to stop afterwards, and **never claim sales or revenue**.

### Screens added
Automations (real controls, settings, checklist, recent activity), Offers (create, preview, approve, pause/cancel, results), Messages and costs (your approved messages with status, this month's usage and estimated charge, recent messages), a "Visit done" action on Customers.

### Still open after Phase 3
- Wiring a WhatsApp opt-in into the **QR review page** is not done: that page does not collect a phone number today, so adding one is a product decision.
- Birthday/festival wishes and win-back are listed as coming soon (they need customer date and visit data FlowQR does not hold).
- Click tracking on review links, a guided test message and a first-run checklist (Phase 5).
- An administrator screen for entering dated Meta rates (the API exists).
- Real-Meta validation: template approval behaviour, the exact error codes, delivery statuses and pricing must be checked with a Meta test number before any customer is connected.
