# Cashfree recurring billing: Phase 0 audit and proposed architecture

Written 2026-11-16. Nothing in production, the database, Vercel or Cashfree was changed to produce this. Cashfree facts come from the pages linked at the end; anything marked **UNVERIFIED** was not confirmed on a Cashfree page and must be checked in the Cashfree sandbox before it is relied on.

## 1. What already exists (do not duplicate)

A complete subscription stack is already built and deployed, on **Razorpay**. It is dormant in production (no Razorpay keys, so billing shows "configuration pending").

| Area | Existing implementation |
|---|---|
| Plans | `billing_plans` (starter 49900, growth 79900, pro 149900 paise; essential and multi retired). Entitlements: locations, staff, review generations, review replies, `limits` JSON, `features` list. Column `razorpay_plan_id`. |
| Subscription | `subscriptions`, one row per tenant (unique `tenant_id`), RLS-protected. Status is a plain string: `trialing`, `active`, `pending`, `past_due`, `halted`, `expired`, `canceled`, `manual`. Has `trial_ends_at`, `current_period_start/end`, `cancel_at_period_end`, `canceled_at`, `past_due_since`, `pending_plan`, `source` (trial/razorpay/manual), `razorpay_subscription_id`, `last_event_at`. |
| Trial | App-owned, no mandate: `start_trial()` creates `trialing` with `trial_ends_at = now + TRIAL_DAYS(7)` on the Growth plan's entitlements; the hourly `billing_refresh` task expires it. Choosing a plan during the trial already creates a provider subscription whose first charge is scheduled at trial end (`start_at`). |
| Entitlements | `services/entitlements.py` is the single source of truth. `trialing`/`active`/`manual` are active; `past_due` is active for `PAST_DUE_GRACE_DAYS` (**7** today); `canceled` keeps access until `current_period_end`. Every feature gate calls it on the backend. |
| History | `subscription_events` (append-only, RLS), `payments` (RLS, indexed by tenant), `webhook_events` (provider + unique event_id, platform-level, not tenant-scoped), `audit_logs`. |
| API | `GET /billing/plans`, `GET /billing/subscription`, `GET /billing/subscription/history`, `POST /billing/subscription/checkout`, `/verify`, `/cancel`, `/change-plan`, `GET /billing/payments`, `POST /billing/razorpay/webhook`. Owner-only mutations, `ensure_verified`, row lock `_locked_sub`, downgrade guard, idempotent checkout. |
| Admin | `/admin/subscriptions`, `/admin/payments`, `/admin/finance` (MRR etc.), manual override with audit. **MRR counts only `source == "razorpay"`** (`services/finance.py`). |
| Frontend | `settings/billing/page.tsx`, `settings/billing/payments/page.tsx`, `lib/billing.ts` (`openCheckout` loads Razorpay's script), marketing `PlansFromConfig`, admin billing pages. |
| Tests | `test_billing.py` (24), `test_phase2_plans.py` (33), plus finance, admin, config guard, security audit; they use a fake Razorpay client. |
| Physical cards | `card_orders` and card-purchase promo grants are paid through **Razorpay orders**. Card ordering is off today (`CARD_PRICE_PAISE` empty). |

## 2. Conflicts with the Cashfree brief

1. **Branch carries unreviewed card-on-file work.** `2e3bd24` on `phase-2/commercial-readiness` (already pushed) added migration `0033_trial_card_required`, `subscriptions.card_status`, `TRIAL_REQUIRES_CARD`, `card_blocks()` in entitlements, and "card on file" copy in the frontend. Production is at migration **0032**. A Cashfree migration must also follow 0032, so the repository would have **two heads** unless 0033 is removed or replaced. This needs an owner decision (Section 8, decision 1).
2. **Provider-specific names are baked into the schema**: `razorpay_plan_id`, `razorpay_subscription_id`, `payments.razorpay_*`, `source = 'razorpay'`, `has_razorpay_subscription` in the API. Cashfree identifiers cannot reuse them honestly.
3. **No unique event id in Cashfree webhooks** (Razorpay sends one). The existing `webhook_events.event_id UNIQUE` scheme needs a synthesised key.
4. **Cashfree cannot "cancel at period end"** (documented `CANCEL` is immediate). The existing entitlement rule (cancelled keeps access until `current_period_end`) already gives the same customer experience.
5. **Physical-card payments are Razorpay.** "Cashfree is the only provider" means card ordering stays off until it is separately moved to Cashfree one-time orders (out of scope here).
6. **Plan names disagree inside the brief**: Section 1 says Starter/Growth/Pro; Section 10 says Launch/Growth/Scale. The code, database and public site say Starter/Growth/Pro.
7. **Grace period**: brief recommends 3 days, code uses 7.

## 3. What Cashfree really supports (checked against its docs)

* Base URLs: sandbox `https://sandbox.cashfree.com/pg`, production `https://api.cashfree.com/pg`. Headers `x-client-id`, `x-client-secret`, `x-api-version: 2026-01-01` (examples elsewhere use 2025-01-01 / 2025-08-01: confirm in sandbox).
* Plan: `POST /plans`; merchant-chosen `plan_id` (1-40 chars, alphanumeric . - _), `plan_type PERIODIC`, `plan_recurring_amount`, `plan_max_amount` (required), `plan_interval_type MONTH`, `plan_intervals 1`, `plan_max_cycles`. Optional `x-idempotency-key` (same key + different body gives HTTP 422). Duplicate `plan_id` behaviour: **UNVERIFIED**.
* Subscription: `POST /subscriptions`; merchant-chosen `subscription_id`; required `customer_details` (email, phone) and `plan_details.plan_id`; `authorization_details {authorization_amount, authorization_amount_refund, payment_methods [enach|pnach|upi|card]}`; `subscription_first_charge_time` (PERIODIC only); `subscription_expiry_time`; `subscription_meta.return_url`. Response gives `cf_subscription_id`, `subscription_session_id`, `subscription_status`, `next_schedule_date`.
* Hosted checkout: JS SDK `Cashfree({mode}).subscriptionsCheckout({subsSessionId, redirectTarget})`. The script URL is **UNVERIFIED** (not on the pages read). Return-URL query parameters are not documented, so the return page must call our backend and never trust the URL.
* Statuses (verbatim FAQ names, enum spelling **UNVERIFIED**): INITIALIZED, BANK_APPROVAL_PENDING, ACTIVE, ON_HOLD, PAUSED, CUSTOMER_PAUSED, CUSTOMER_CANCELLED, CANCELLED, COMPLETED, EXPIRED, LINK_EXPIRED, CARD_EXPIRED.
* Manage: `POST /subscriptions/{id}/manage` with `action` CANCEL | PAUSE | ACTIVATE | CHANGE_PLAN (`action_details.plan_id`). Plan change keeps the mandate, customers are not notified, and the new amount cannot exceed the original plan's `plan_max_amount`.
* Payments: `GET /subscriptions/{id}/payments`; failed-charge `RETRY` via `POST /subscriptions/{id}/payments/{payment_id}/manage` with `action_details.next_scheduled_time`.
* Webhooks: event types `SUBSCRIPTION_STATUS_CHANGED`, `SUBSCRIPTION_AUTH_STATUS`, `SUBSCRIPTION_PAYMENT_NOTIFICATION_INITIATED`, `SUBSCRIPTION_PAYMENT_SUCCESS`, `SUBSCRIPTION_PAYMENT_FAILED`, `SUBSCRIPTION_PAYMENT_CANCELLED`, `SUBSCRIPTION_REFUND_STATUS`, `SUBSCRIPTION_CARD_EXPIRY_REMINDER`. Envelope `{type, event_time, data}`. Signature: headers `x-webhook-signature` and `x-webhook-timestamp`; Base64(HMAC-SHA256(secret, timestamp + rawBody)); 5-minute window recommended. Which secret is used is **UNVERIFIED** (docs say "your secret key"). Subscription webhooks are configured under Payment Gateway > Developers > Webhooks > **Subscriptions** tab, version 2026-01-01.
* **No event id, no documented retry schedule, no replay, no ordering guarantee.** Cashfree says missed webhooks cannot be re-sent and to poll the payment API. Therefore every webhook must be treated as a hint, and the handler must re-read the subscription and payment from Cashfree before changing anything, with a periodic reconciliation job as the safety net.
* Failed debits: UPI AutoPay retries up to 3 times by itself; eNACH and card standing instructions do not retry automatically, the subscription goes `ON_HOLD`, and the merchant may retry (up to 3 per cycle). Expired card or cancelled mandate needs a **new** subscription/mandate.
* Sandbox: `POST /simulate` can set a payment to SUCCESS, FAILED, PENDING or USER_DROPPED, but **only when the payment is PENDING**, and for PERIODIC subscriptions a payment becomes PENDING only on its scheduled date and "the sandbox does not support forcing this transition early". UPI AutoPay must be activated by Cashfree support on the account (also for sandbox).

## 4. The seven-day trial: what is and is not possible

Supported: authorise the mandate on day 0 and set `subscription_first_charge_time` to trial end (day 7 or 8). Cashfree allows a first charge up to 14 days out, so 7 days fits.

Not exactly the stated experience:
* **UPI and card cannot authorise for zero.** The minimum authorisation amount is **₹1**; it can be refunded automatically (`authorization_amount_refund: true`). Only eNACH authorises at ₹0. So the customer sees a ₹1 debit on day 0 for UPI/card.
* eNACH bank approval can take time (**UNVERIFIED**: "24-48 hours"), which eats into a 7-day trial.
* Subscription arithmetic after the first charge (same day each month?) is not spelled out: confirm in sandbox.
* Cashfree's `ON_HOLD` after one failed debit plus no automatic retry on eNACH/card means recovery needs our trigger of Cashfree's own RETRY action. That is still a Cashfree-owned collection, not an independent charge.

**Recommendation:** UPI AutoPay and card (₹1 authorisation, auto-refunded, disclosed on the pricing and checkout screens) and eNACH (₹0), first charge at `trial_ends_at`. Entitlements follow `trial_ends_at` in our database; Cashfree collects. Needs owner approval (decision 3).

## 5. Proposed architecture

Reuse, extend, do not fork. One billing service, one set of endpoints, one entitlement function.

**Provider seam.** `services/billing_provider.py`: a small `BillingProvider` protocol (create_plan, create_subscription, fetch_subscription, list_payments, manage_subscription (cancel/change plan), retry_payment, verify_webhook). `services/cashfree.py` implements it (HTTP client, signature check, status maps) and never logs secrets. Razorpay stays as-is behind the same seam but unconfigured; it is deleted in a later cleanup, not copied.

**Settings** (backend only, guarded in production): `CASHFREE_ENV` (sandbox|production), `CASHFREE_CLIENT_ID`, `CASHFREE_CLIENT_SECRET`, `CASHFREE_API_VERSION`, `CASHFREE_WEBHOOK_SECRET`, `BILLING_PROVIDER` (none|cashfree), `PAST_DUE_GRACE_DAYS` (3 per brief). Production guard: sandbox credentials refused in production and the reverse; both halves required together.

**Database (additive only, one reversible migration, applied after 0032; no column dropped):**
* `billing_plans`: `cashfree_plan_id`.
* `subscriptions`: `provider` (null|cashfree), `cashfree_subscription_id` (our `subscription_id`, unique), `cashfree_cf_id`, `authorization_status`, `trial_started_at`, `next_charge_at`, `first_charge_at`.
* `payments`: `provider`, `cashfree_payment_id` (unique), `cashfree_cf_payment_id`, `payment_type` (AUTH|CHARGE), `period_start`, `period_end`, `failure_reason`.
* `webhook_events`: `subscription_ref`, `payment_ref`, `attempts`, `payload_hash`, a status set `received|processed|ignored|failed|retrying`; dedupe key = sha256(type | payment_id or subscription_id | status | event_time).
* New statuses are added as values, not a new enum (the column is a string): `authorization_pending`. Mapping to the brief's states: pending = `pending`; authorization_pending = `authorization_pending`; trialing = `trialing`; active = `active`; payment_failed/past_due = `past_due` (the payment itself is `FAILED` in `payments`); cancellation_pending = `active` or `trialing` with `cancel_at_period_end` (access until period end); cancelled = `canceled`; expired = `expired` and `halted`.
* All new columns stay inside the existing RLS-protected tables. `webhook_events` stays platform-level (read by admin only), as today.
* Migration is tested up, down and up on a disposable database before anything else.

**Lifecycle.** Customer (owner role, verified email) picks a plan; backend prices it from `billing_plans` only; creates `pending` with a Cashfree plan (created once, idempotent via `x-idempotency-key` and a stored id) and a Cashfree subscription whose first charge is `trial_ends_at`; returns `subscription_session_id`; the browser opens Cashfree hosted checkout; the return page calls `POST /billing/subscription/verify`, which **re-fetches** the subscription from Cashfree and only then sets `authorization_pending`/`trialing`/`active`. `plan_max_amount` is set to the highest plan price so upgrades and downgrades use `CHANGE_PLAN` without a new mandate. Entitlements keep following `trial_ends_at` / `current_period_end`; Cashfree owns collection.

**Webhook.** `POST /api/v1/webhooks/cashfree` (public, rate-limited, its own signature check on the raw body, 5-minute timestamp window, constant-time compare). Persist first, dedupe, resolve the tenant **from our own subscription row** (never from the payload), re-fetch from Cashfree, apply idempotently, reject out-of-order by `event_time` plus the re-fetched truth, return 2xx only after the event is safely stored. A failed processing keeps the stored event for retry.

**Reconciliation.** Celery job (hourly): for subscriptions in `pending`, `authorization_pending`, `past_due`, `trialing`-with-mandate, fetch from Cashfree and sync. It only reads and applies; the one write it may make is Cashfree's own `RETRY` for an eNACH/card failure inside the grace period. It never creates a charge of its own.

**Failure policy.** First failed charge: `past_due`, `past_due_since` set, customer emailed, banner in the app. Grace 3 days (setting). UPI: Cashfree retries; eNACH/card: our scheduled `RETRY` calls. Access returns only after a verified `SUCCESS`; after grace the status becomes `halted` (restricted, data kept). Expired card or revoked mandate: new subscription flow.

**Admin.** Extend the existing finance and subscription pages: counts by status and plan, MRR from `source = 'cashfree'`, failed payments, recent transactions, webhook list with status and a safe "retry processing" action. No admin action can set a payment to paid.

**Frontend.** Same design system. `lib/billing.ts` `openCheckout` becomes provider-aware; pricing and billing pages show the ₹1 authorisation disclosure, the first-charge date, the recurring amount and the cancellation rule. Never marks anything active from the browser.

**Physical cards.** Stay disabled; Razorpay code is not used.

## 6. Security risks to design against

* Forged or replayed webhooks (signature, timestamp window, dedupe, re-fetch before acting).
* Cross-tenant update through an id in a payload (tenant comes only from our own row looked up by our `subscription_id`).
* Browser-supplied price or plan (server maps plan code to price).
* Treating the return redirect as proof (never; `verify` re-fetches).
* Secrets in logs, bundles, Git or browser storage (backend env only; redaction tested).
* Duplicate subscriptions (row lock plus unique ids plus status check).
* Webhook endpoint abuse (rate limit, body-size cap, no secret in errors).
* Unknown webhook secret semantics: verify in sandbox before enabling.

## 7. Sandbox test plan

Needs a Cashfree **sandbox** account with Subscriptions and UPI AutoPay enabled, sandbox client id and secret, the Subscriptions-tab webhook configured, and a reachable HTTPS endpoint for real webhook delivery.
1. Create plan, create subscription, authorise through hosted checkout (UPI/card/eNACH as enabled), verify state.
2. First charge date: create with `subscription_first_charge_time` at T+7, confirm what Cashfree and the customer screen show, and the next monthly date.
3. Recurring success: wait for the payment to become PENDING on its schedule date and `POST /simulate` SUCCESS. Failure path with FAILED. (Because forcing the schedule is not supported, the recurring cycle can only be exercised on real elapsed dates in PERIODIC mode: plan for a short elapsed wait, or use an ON_DEMAND plan purely for exercising the webhook and failure handling, clearly labelled as such. **A recurring monthly success is not claimed from first authorisation alone.**)
4. Webhooks: real delivery, duplicate delivery, bad signature, out-of-order (fixtures), reconciliation without webhooks.
5. Cancel, change plan, expiry, card expiry reminder.
6. Entitlement transitions at each step, tenant isolation, existing suites green.

## 8. Decisions needed before Phase 1

1. **Migration 0033 and the card-on-file code on the branch.** Recommended: remove them in one reviewable commit (migration file, `card_status`, `card_blocks`, `TRIAL_REQUIRES_CARD`, the "card on file" copy) so the Cashfree migration is the next revision after 0032. Production has never run 0033.
2. **Plan names**: keep Starter / Growth / Pro (code, database, site) or rename to Launch / Growth / Scale?
3. **Trial authorisation disclosure**: accept a ₹1 authorisation on UPI and card (auto-refunded) with first charge at trial end, plus eNACH at ₹0? Which payment methods to offer (upi, card, enach)?
4. **Grace period**: change `PAST_DUE_GRACE_DAYS` from 7 to 3 as the brief recommends?
5. **Sandbox**: provide sandbox credentials (entered on the server or locally through a hidden prompt, never in chat), confirm UPI AutoPay is enabled on the sandbox account, and choose how real sandbox webhooks reach us (see below).

Sandbox webhook delivery needs a public HTTPS URL. Options: (a) deploy the new code to the production VPS with `CASHFREE_ENV=sandbox` and `BILLING_PROVIDER=cashfree` after your approval, with billing UI still hidden for customers; (b) a temporary tunnel to a local stack; (c) test signed fixtures only and defer real delivery until (a). (a) needs your explicit deployment approval; nothing is deployed by this document.

## Sources

* Create Plan: https://www.cashfree.com/docs/api-reference/payments/latest/subscription/plans/create
* Create Subscription: https://www.cashfree.com/docs/api-reference/payments/latest/subscription/mandate/create
* Hosted checkout: https://www.cashfree.com/docs/payments/subscription/hosted-checkout
* Subscription FAQ: https://www.cashfree.com/docs/payments/subscription/faq
* Webhook events: https://www.cashfree.com/docs/api-reference/payments/latest/subscription/webhooks
* Webhook signature: https://www.cashfree.com/docs/payments/subscription/webhook-signature
* Manage subscription and payments: https://www.cashfree.com/docs/api-reference/payments/latest/subscription/overview
