# WhatsApp Automation: Phases 1 to 5, and the second round (opt-in, prices, greetings, clicks, audiences)

Status: **Phases 1 to 5 are implemented in the repository and tested locally; not deployed; every flag OFF by default.** Phases 2 and 3 are described in the section "Phases 2 and 3" Phase 4 in "Phase 4" and Phase 5 in "Phase 5" below; the rest of this document describes Phase 1. No real Meta account, number, customer or message has been involved. Nothing in this document has been applied to production.

Branch `feature/whatsapp-automation`, migrations **0048** (Phase 1, parent 0047) **0049** (Phases 2 and 3, parent 0048) and **0050** (Phase 4, parent 0049). Official Meta WhatsApp Cloud API only: no WhatsApp Web automation, no unofficial libraries.

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

## Phase 4 (campaign manager)

Migration **0050** (parent 0049, single head): `whatsapp_contacts.location_id` (optional, SET NULL if the location is deleted) and `whatsapp_templates.simple` (true when the approved template has only a text body). Still local only; nothing sends unless the Phase 2 switches are on.

- **Scheduling.** A campaign can start as soon as it is approved or at a chosen day and time (India time; a time without a zone is read as India time; it must be in the future and within 90 days). A draft or an approved-but-not-started campaign can be moved (`POST /campaigns/{id}/reschedule`, audited); once started it can only be paused.
- **Sending hours.** Offers go out only between `WHATSAPP_SEND_WINDOW_START` and `WHATSAPP_SEND_WINDOW_END` (default 9 am to 9 pm India time; 0 and 24 = any time). Outside them a campaign waits and nothing is lost; the preview says when it will really start. Automation replies (thank-yous, review requests) are not held by these hours. The production config check validates the two values.
- **Audience by plan.** Growth: everyone, a group, new customers, earlier customers. Pro adds **location** (customers can be placed at one of the business's own locations), several groups (any / all), groups to leave out, "not sent an offer in the last N days" and "never sent an offer", computed from the real send history. Starter has no campaigns. Using a Pro option on Growth is refused with `plan_required`.
- **Choosing the message.** Any of the business's own **approved**, **marketing**, **text-only** templates can be used (the standard Offer message, or one the business created itself and FlowQR read with "Check with WhatsApp"). Templates with a header, picture or button are refused (`simple` is false). Each blank is filled from the customer's first name, the business name, or fixed text the owner writes (1 to 200 characters, single line); the count of blanks must match. A message another business owns is never reachable.
- **Results.** Per-day timeline (India dates), delivery rate and read rate (read as a share of delivered, only where read receipts are on), a side-by-side comparison of started campaigns (`GET /campaigns/compare`), and a results file (`GET /campaigns/{id}/results.csv`: name, phone, result, reason, delivered and read times; spreadsheet formulas neutralised; audited). Results still claim no sales or revenue.
- **Duplicate** (`POST /campaigns/{id}/duplicate`): a new draft with the same message, audience and wording; approval, schedule and results are never copied.
- **Screens.** The Offers page gains message choice with blank-filling, "More ways to choose (Pro)", a start-time picker, a sending-hours explanation, change start time, make a copy, download results, a day-by-day bar chart with the numbers written out (not colour-only) and a comparison table; Customers gain an optional location and a location filter.

Remaining after Phase 4: Phase 5 (first-run connection wizard, a guided test message, activation checklist), the QR review page opt-in, birthday and win-back, click tracking, an administrator screen for Meta rates, and everything that needs real Meta credentials and approval.

## Phase 5 (first-run set-up)

No migration (the checklist is derived from existing records). Still local only; the test message goes through the same gate as every message, so nothing sends unless sending is switched on.

- **A six-step checklist** (`GET /api/v1/whatsapp/setup`, `services/whatsapp/setup.py`), each step computed from real records, never from a box the owner ticks: **plan** (the add-on is on), **connect** (the number is connected and healthy), **messages** (WhatsApp approved the standard messages), **customers** (at least one customer agreed to visit updates), **test** (a test message to the owner's own number was accepted), **helper** (at least one helper is on). Each step reports `done`, `todo`, `waiting` (nothing for the owner to do: for example WhatsApp is reviewing a message, or FlowQR has not finished its Meta set-up, or sending is not switched on yet) or `blocked` (an earlier step comes first), with a sentence in plain words. The Overview shows the progress; the new **Set up** screen walks the owner through it and picks up where they left off.
- **One click to prepare the messages** (`POST /setup/prepare-messages`): submits the messages the helpers use (review request, enquiry thank-you, enquiry follow-up; the offer message on request) to WhatsApp for approval. Safe to repeat.
- **Test message** (`POST /setup/test-message`): sends the enquiry thank-you to the owner's own number so they see exactly what customers receive. The owner must confirm the number is their own; that records a visit-updates consent for that number, written by the owner about themselves (source `owner_entry`, with an explicit note, never offers). It uses the normal sender and gate (consent, approved template, limits, emergency stop), is idempotent within a minute, limited to five an hour, counted in usage like any other message, audited, and a failed try is kept so the checklist can say "your last try did not go through". The screen follows delivery (sent, delivered, read) for a short while.
- **Recommended helpers** for the kind of business (clinic, salon and gym: reviews and enquiries; restaurant and shops: offers and reviews; trades and professionals: enquiries and reviews), as a suggestion the owner can ignore.
- **Add yourself as the first customer** inside the wizard (with the "this person agreed" confirmation and a note on how they agreed), and **switch on the first helper** from the recommended cards.

Remaining after Phase 5: the QR review page opt-in (a product decision: that page does not collect a phone number today), birthday and win-back, click tracking, an administrator screen for dated Meta rates, and everything that needs real Meta credentials and approval (Tech Provider status, Embedded Signup configuration, template approvals, India rates, coexistence eligibility).

# Second round

Rules for every phase below: every send goes through the single sender and gate (nothing here bypasses it); consent is stored per purpose with its exact wording and timestamp; only the customer can opt back in after STOP; only approved text-only templates are sent; cost is always an estimate and apart from FlowQR's fee; everything ships OFF behind the existing add-on switches. Nothing in this round is deployed until the owner says so.

## Second round, Phase 1: opt-in without a phone number (migration 0051) - DONE, not deployed
**Status: built and tested locally; not deployed; every WhatsApp flag stays off.**

- **The QR review page** can show an optional button, **Get updates on WhatsApp**. It is a plain `wa.me` link to the business's own connected number with a message already written, containing a short per-business code. **No phone number is collected or typed on the page.** The link is returned by the public landing endpoint only when: WhatsApp automation is on, the business switched the button on, its number is connected and the add-on is active. If anything fails, the review page works as before.
- **The customer's message is the consent.** An inbound message on the business's own verified number (signature checked; the business comes only from the verified phone-number id) counts **only if its text equals the prefilled text** (ignoring case and spacing). An edited sentence, a wrong code, another business's text, a disabled button or an extra word creates nothing. The consent is limited to the **purpose named in the prefilled text** (visit updates / offers / both); no offers consent is ever recorded unless the text said so. It stores the exact wording, wording version `optin-1`, the time and the source `qr_click_to_chat`.
- **Opt-in keywords** sit beside STOP. Up to **5 per business**, each lower-case, 3 to 20 letters or numbers, never a common or reserved word (yes, ok, hi, join ... and every STOP word). The **whole message** must equal the keyword (trailing punctuation allowed); a keyword inside a sentence does nothing. Each has its own purpose and optional confirmation, stores its exact wording (source `keyword_opt_in`) and is audited.
- **STOP always wins.** STOP is checked first. Re-joining after STOP is the customer's own act and lifts only the opt-out of the **same purpose**; the owner and CSV imports still cannot lift an opt-out.
- **One confirmation reply**, only when a consent was newly recorded and the owner left it on. It is sent with `sender.send_template` like every other message (approved own-connection template, sending switch, emergency stop, connection, consent for the template's real category, limits, idempotency key). If it cannot be sent the consent is still kept. A temporary Meta failure retries the whole event (nothing is half-recorded). Two new fixed messages: `flowqr_optin_confirm_en` (utility) and `flowqr_optin_confirm_offers_en` (marketing); they are submitted with the one-click set-up when asked but the checklist still counts only the three core messages.
- **A confirmation never uses up the offer gap**: messages of kind `optin_confirm` are excluded from the 72-hour marketing frequency rule (and do not count towards it).
- **Where it shows**: the owner screen **WhatsApp > Sign-ups** (button on or off, purpose, the exact message customers send, keywords, confirmation approval state); each customer shows how they joined; the customer export now has `marketing_consent_source` and `utility_consent_source` columns; the account export and deletion cover the two new tables.
- **Data**: `whatsapp_optin_settings` (code, switch, purpose, confirmation switch), `whatsapp_optin_keywords`, `whatsapp_messages.kind`; forced row-level security; the consent source check allows the two new sources.
- **Webhook text kept**: an inbound text is stored only if it is 64 characters or fewer, or is a longer message ending in `Code: XXXXXX` (an opt-in). Ordinary chat is not kept.

## Second round, Phase 5: Meta price admin (migration 0052) - DONE, not deployed
**Status: built and tested locally; not deployed; no flag changes.** Done before the other second-round phases because every cost estimate depends on it.

- **Prices are dated rows that are never overwritten.** `whatsapp_rates` already had country, category (marketing, utility, authentication, service), INR rate, effective-from date and a source note; the application role can only read and add rows. A change is a new row with a later date, and the old row stays in the history. New: `free_per_number_month` (Meta's free allowance for that category, 0 = none).
- **Checking a price is a separate, append-only record** (`whatsapp_rate_verifications`: which row, matches yes/no, a note of at least ten characters, who, when). The rate row is never touched. The admin screen shows the **latest** check for each row; a row with no check shows UNVERIFIED. Adding a price as "verified" writes the same kind of record. Every check is audited (`admin.whatsapp_rate_verification`).
- **Starting values loaded, all UNVERIFIED**, India, effective **1 Oct 2026**: marketing 1.09, utility 0.145, authentication 0.145, service 0.145 with the **first 1,000 service messages per number per month free**. Their source note reads "AiSensy pricing page, not Meta, unverified": they come from AiSensy's pricing page, not from Meta, and have **not** been checked against Meta's rate card (that is item 2 of `docs/WHATSAPP_META_CHECKLIST.md`). The January 2026 rows remain as history. From 1 Oct 2026 the newer rows are the ones in force, so cost estimates went up from about 0.86 to 1.09 per offer message and from 0.115 to 0.145 per update message.
- **Free allowance in the estimate.** `pricing.estimate(category, count, already_used)` subtracts what is still free that month and says how many were free; the message ledger records 0 for a message that falls inside a category's monthly allowance (`est_rate_for_send`). FlowQR sends templates only, so in practice the allowance matters for the service category; marketing and utility have none.
- **An approved offer keeps its estimate.** When an offer is approved, the rate, the date that price took effect and whether it was verified at that moment are stored with it (`approved_price`). The offer screen and results show that frozen estimate, labelled with the price date; only new estimates use newer prices. An offer approved before this existed says its price date was not recorded and is shown as unverified.
- **Warning while a price in use is unverified.** `GET /whatsapp/usage` carries `price_warning` and every estimate carries `warning`; the Messages screen and the offer preview show a banner above the cost figures until the marketing and utility prices in force have a latest check of "matches". Estimates stay labelled as estimates, apart from FlowQR's fee.
- **Screen:** platform admin, **WhatsApp prices** (`/admin/whatsapp-prices`): the price in force for each category with its status and latest check, "Record a check", "Add a new price", and the full history. API: `GET/POST /api/v1/admin/whatsapp/rates`, `POST /api/v1/admin/whatsapp/rates/{id}/verification` (platform administrators only).

## Second round, Phase 2: birthday and festival greetings (migration 0053) - DONE, not deployed
**Status: built and tested locally; not deployed; every flag stays off. The two helpers are off until a business turns them on.**

- **Two helpers**, each counting against the plan's helper limit: **Birthday wishes** and **Festival wishes**. **Growth and Pro only** (Starter gets a clear "part of Growth and Pro" refusal; the two greeting messages are not even submitted for Starter). The greeting is a fixed, neutral, text-only message (`flowqr_occasion_birthday_en`, `flowqr_occasion_festival_en`); it contains **no offer, no discount, no number or symbol**, and a festival's name is checked (plain letters, nothing that sounds like an offer).
- **Fail-closed consent (decision 4).** A greeting needs, always: **occasion consent** (its own agreement, with its own wording, recorded like any other consent) and **no STOP**. While the greeting's category is **marketing, or WhatsApp has not yet reported it**, it also needs **offers consent**, and an **offers opt-out blocks it**. "Not yet known" is stored: `whatsapp_templates.category_confirmed` is true only once WhatsApp's own status listing (Check with WhatsApp / sync) has reported the category; creating or re-submitting a template resets it. The greeting templates are asked for as **marketing** (a greeting is not an update about a visit). **The Messages-set-up preview shows the category, whether it is confirmed, who would really get it (agreed, would receive, left out) and a warning.** This is relaxed only after the Meta checklist (item 1) confirms Meta's real rule: when WhatsApp reports a greeting as utility, occasion consent alone is enough (the code path exists and is tested; nothing switches it on by itself).
- **STOP** revokes occasion consent along with offers consent and blocks greetings; it never touches **visit and enquiry updates** (utility consent is kept). The owner cannot give a greeting consent back after STOP; only the customer can.
- **Birthdays**: the customer's **birth day and month only, never a year** (the database refuses a 31 April, a 30 February or a half date). Typed by hand, uploaded (`birth_day` and `birth_month` columns, or `birthday` like 14-03; a value with a year is refused, not trimmed), exported and deleted with the customer or the business. **Setting one needs the existing "they agreed" confirmation** (and a note). The date is never written to the audit log. A birthday is not consent: greetings go only to customers who also agreed to occasion greetings. **Once per customer per year**; **29 February birthdays are greeted on 28 February in years without a 29th**.
- **Festivals**: a dated list kept by FlowQR staff (name, date, region; never deleted, only switched off; admin screen **WhatsApp festivals**). A business chooses which festivals to greet on (**Greetings** screen); nothing is sent for one it has not chosen. Only customers who agreed to greetings get it. The list starts empty: FlowQR staff add festival dates (no dates are guessed here).
- **Hours and day**: the owner picks an hour from **9 am to 8 pm India time** (default 10). The sender refuses any greeting outside **9:00 to 21:00 India time** whatever the setting. A greeting that missed its day (worker down, hours closed) is **skipped, never sent late** ("outside_hours", "day_passed").
- **Caps (decision 2)**: greetings have their **own cap**, default **14 days** apart per person (`WHATSAPP_OCCASION_GAP_DAYS`), and are **excluded from the 72-hour offer gap** in both directions. The offer gap and the 30-day review rule are untouched.
- **No bypass**: the sender's `kind` argument is checked against the message it is used with (`kind_mismatch`), so no offer can be sent under a kind that skips the offer gap. Greetings pass through the same single send gate as everything else (switches, emergency stop, add-on, healthy connection, approved own-connection template, limits, idempotency). They are scheduled by the existing worker tick (`whatsapp_run_due`), which does nothing unless sending is allowed.
- **Cost shown before switching on**: each greeting card on the Greetings screen shows the likely WhatsApp charge per greeting (marketing price unless WhatsApp has confirmed utility; labelled an estimate, with the price date, and the unverified warning while the price in use is unverified), apart from FlowQR's fee.
- **Set-up**: the one click that prepares the three core messages also submits the two greeting messages for Growth and Pro; **the checklist still counts only the three core messages**.
- **Data**: `whatsapp_contacts.birth_day/birth_month`, consent purpose `occasion`, `whatsapp_templates.category_confirmed`, automation keys `birthday` and `festival`, `whatsapp_festivals` (global), `whatsapp_festival_optins` (per business, forced row-level security). Account export covers the new business tables and the contact columns.

## Second round, Phase 3: click tracking (migration 0054) - DONE, not deployed
**Status: built and tested locally; not deployed; no flag changes. Pro add-on only, and off until the business turns it on for the review request.**

- **What it does.** With **"Count when a customer opens the review link"** on (Pro, on the review helper), the review request carries a FlowQR link instead of the plain review link: `https://api.flowqr.site/api/v1/l/{token}` (`WHATSAPP_LINK_BASE_URL`; no server or DNS change). It leads to the same Google review page. A click is recorded as **"Link clicked"** and is shown that way everywhere (Messages screen: a tile, a small by-day chart and a badge on each message; the message export has a `link_clicked` and `link_clicked_at` column). **It is never shown as "review left", a rating, a sale or revenue**: a click only means someone opened the link.
- **Not an open redirect.** The token is 43 characters of randomness (256 bits). The destination is stored when the link is made (the business's own review page, https only) and **the route accepts no URL, no redirect target and no other parameter**; the OpenAPI description of the route has the path token and nothing else, and tests send `?url=`, `?to=`, `?redirect=` and so on to prove they change nothing. Unknown or malformed tokens give 404 and record nothing.
- **Rate limits without keeping the address.** Per visitor (60 a minute) and per link (30 a minute). The counter key is a keyed hash of the address (server secret), so even the short-lived counter never holds the address. The counters live only in Redis, where each expires about a minute after its window starts (61 seconds), or, if Redis is unreachable, in process memory, where finished counters are swept at least once a minute. No database table holds them.
- **What counts as a click.** Only a GET from a browser. **HEAD never counts.** Known bot, preview and scanner agents (WhatsApp's own preview fetcher, Facebook, Google, Slack, Telegram, mail-security scanners, HTTP libraries, headless browsers, an empty browser name) are redirected but **never counted**. **Repeat opens of one link inside 60 seconds count once.** **Even so a click is a guide, not proof that a person read the message**: previews and security scanners that disguise themselves can still inflate it, and the screen says so.
- **What is stored per click:** the link, the customer, the message and the time. **No address, no browser, no place.** Deleted with the customer (their clicks go) and with the business.
- **Tokens die only with the business.** If the message or the customer a link was sent to is deleted, the link still redirects to its fixed page (so a customer holding an old message is not left with a dead link); it simply counts nobody. After a downgrade from Pro the link still works but new clicks are not recorded.
- **Moving tracked links to a separate domain later.** Today the link uses the API host, which also serves the app's API. Meta will see a link domain that is not the business's own. Before real use, move tracked links to a short domain used for nothing else (for example a `go.`-style host pointing at the same route), set `WHATSAPP_LINK_BASE_URL`, and add that host to the Caddy config. Links already sent keep working on the old host as long as it still serves `/api/v1/l/`. Whether Meta cares about the domain is item 6 of `docs/WHATSAPP_META_CHECKLIST.md`.
- **Data:** `whatsapp_links` (token, fixed destination, the message and customer as nullable references) and `whatsapp_link_clicks`, both with forced row-level security; covered by the account export; the public redirect is listed in the route manifest as a public route.


## Known time-dependent test (not related to WhatsApp)
`tests/test_cashfree_billing.py::test_first_charge_is_at_trial_end_and_a_business_with_no_free_period_left_waits_two_days` depends on the clock. For a business with no free period left, the first charge is set to 10:00 India time two calendar days ahead, and the test expects that to be between 1.5 and 2.6 days from now. Between 22:00 and midnight India time (16:30 to 18:30 UTC) the gap is under 1.5 days, so the test fails. It fails in exactly the same way on the commit that is in production (`e71f1d8`) at the same clock, and passes when the clock is moved outside that window, so it is not caused by anything in this branch. It is deliberately left unchanged here. Re-run it outside that window, or fix the bound separately in the billing code's own change.

## Second round, Phase 4: engagement audiences and win-back (migration 0055) - DONE, not deployed
**Status: built and tested locally; not deployed; no flag changes. Pro add-on only (the same "advanced audience" level as choosing by location). Phase 6 (outside triggers) stays out.**

- **What it is.** More ways to choose WHO an ordinary offer is for. It adds no new way to send: a win-back is a normal marketing offer with a normal approval. Offers consent, the 72-hour gap, STOP, sending hours (India time), plan limits, the emergency stop and the approval tied to the preview count all still apply, and the single send gate re-checks every recipient at the moment of sending.
- **The choices** (campaign audience; each checked, 402 `plan_required` below Pro):
  - **Read a message** in the last N days (only customers who have read receipts on can ever show up);
  - **Wrote to you** in the last N days (`last_replied_at`);
  - **Opened a tracked link** in the last N days (**only has data from the time link click counting was switched on**; the limit is shown beside the count);
  - **Delivered but not read** in the last N days, labelled **"may include people with read receipts turned off"**. It is never called ignored and the screen says it does not show whether they saw the message;
  - **Did not read, reply to or click their last N offers** (1 to 10): an offer is a campaign message that reached the phone; the customer needs at least N of them, none read, no reply and no click since the oldest of the N;
  - **Win back: not visited or messaged in the last N days** (customers added inside the window are never included). **Any outbound message counts, greetings included** (failed ones do not). "Not visited" uses **only visits the owner marked** (recorded whenever "Visit done" is pressed, even with the review helper off); if no visit has ever been marked it **falls back to messages only** and the preview says so. A website enquiry that came with a WhatsApp agreement also counts as recent contact.
- **Only timestamps.** `whatsapp_contacts.last_replied_at`, `last_visit_at`, `last_enquiry_at`. **No message text is stored**: a reply records only when it arrived, and a processed webhook event has the message text blanked (it was only needed to recognise STOP and sign-ups). **A STOP never sets `last_replied_at`** (STOP is handled first, in every wording), and neither does an opt-in keyword or QR sign-up; a message from a number that is not a customer creates nothing. The columns are exported with the customer (`last_visit_at`, `last_enquiry_at`, `last_replied_at`) and deleted with the customer and the business.
- **The preview** shows the count, how many customers the choices picked out, and **how many were left out because they asked to stop offers or never agreed to receive them**, plus the limits of the choices in plain words.
- **The approved list is fixed at approval (a change to Phase 4 of the first round).** Approving a campaign now fixes the recipient list to exactly the customers the owner was shown. Before, the list was worked out again when sending started. Now anyone who **opts out or loses consent after approval is skipped by the gate at send time, with the reason, and counted as skipped in the results**; anyone who becomes eligible after approval is not added. Campaigns approved before this change (no list yet) still fix their list when sending starts.
- **Visit recording changed.** `POST /contacts/{id}/visit` now always saves the visit and answers 200 with `visit_recorded: true`; with the review helper off it says `scheduled: false, reason: automation_off` instead of an error. "Visit done" is available for every customer.


## Turning flags on in production (read this before enabling anything)
The production compose files list the app's environment **one variable at a time**. A variable written in `.env.production` only reaches the API, worker and scheduler if it is also listed in `docker-compose.yml` or in the server overlay `deploy/vps/docker-compose.vps.yml`. Until 2026-11-20 no `WHATSAPP_` or `META_` variable was listed, so none of them could be turned on from `.env.production`.
- `WHATSAPP_ENABLED` is now passed through (in the overlay's `x-hardened` block, default `false`). With it `true` the WhatsApp section appears for every business; connecting, sending and the webhook remain off, and the add-on must still be switched on by an administrator. Switching it on makes the production config guard require `TOKEN_ENCRYPTION_KEY` (it is set).
- Not passed through yet, on purpose: `WHATSAPP_SIGNUP_ENABLED`, `WHATSAPP_WEBHOOK_ENABLED`, `WHATSAPP_SENDING_ENABLED`, `WHATSAPP_WEBHOOK_VERIFY_TOKEN`, `META_APP_ID`, `META_APP_SECRET`, `WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID`, the limits and `WHATSAPP_LINK_BASE_URL`. Add each one to the overlay deliberately, with its default, when the matching Meta check in `docs/WHATSAPP_META_CHECKLIST.md` is done. Recreate with both compose files and `--no-deps`, and check `docker exec flowqr-production-api-1 python -c "from app.core.config import settings as s; print(s.whatsapp_enabled, ...)"` afterwards: a variable that is not passed through is silently ignored.
