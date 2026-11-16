# Cashfree recurring billing: Phase 1 design

Status: **implemented on the isolated branch `billing/cashfree-phase1` and tested locally (backend 1,577 tests, frontend type check and production build). Not pushed, not deployed, no Cashfree sandbox evidence yet.** Production, the VPS and Cashfree are untouched. Section 12 records the decisions the owner approved and what was built; Sections 1 to 11 are the original design. Read with `CASHFREE_BILLING_AUDIT.md`.

## 1. Decisions as understood

| # | Decision | How it is applied |
|---|---|---|
| 1 | Remove card-on-file (migration 0033) | Done on this branch, Section 2. |
| 2 | Plan names | **CORRECTED by the owner: the final names are Launch ₹499, Growth ₹799, Scale ₹1,499.** An earlier reading of the instruction kept Starter / Growth / Pro; that was wrong. The internal codes `starter`, `growth`, `pro` and the prices are unchanged (stable ids; no duplicate plan). Only display names change: migration 0034 renames `billing_plans.name` (only rows still carrying the 0029 names), and the specification, onboarding text, frontend fallback, admin dropdown, tests and living docs are updated. Cashfree plan ids are `flowqr-<code>-<price_paise>` and their display name is `FlowQR Launch / Growth / Scale`. |
| 3 | Seven-day trial; refundable ₹1 authorisation for UPI AutoPay and card; eNACH deferred | Section 3. |
| 4 | Grace period | Stays at the existing **7 days** (`PAST_DUE_GRACE_DAYS`). |
| 5 | Test first with signed payloads and mocked provider; sandbox deployment is a plan only | Sections 9 and 10. Nothing is deployed. |

## 2. Dependency analysis of the card-on-file removal

The feature entered in one commit, `2e3bd24`, mixed with the homepage redesign. It consisted of: migration `0033_trial_card_required` (adds `subscriptions.card_status`), the model column, `TRIAL_REQUIRES_CARD` (config, compose, `.env.example`, docs), the trial lock in `entitlements.py` (`card_required`), two onboarding-checklist strings, three `/billing` response keys, the onboarding **CardStep** (a Razorpay checkout), and the copy helper `trialTerms(cardRequired)` used by the banner, trial note, pricing page, register page and sign-in pitch.

**Removed on this branch (reviewable commit):** all of the above, plus the two tests that exercised it. **Kept:** the 7-day trial default (`TRIAL_DAYS=7`), the redesign, the `trial_days - 1` test fix, and the physical QR-card `card_status` enum (a different, unrelated thing).

**What depends on it, found by search:**
* Nothing revises 0033, and nothing else imports `card_status` on subscriptions.
* **Production** is at 0032 and has no `card_status` column (verified). No production change is needed for the removal.
* **Local dev database** (`flowqr-db-1`) is stamped **0033** with the column. After this branch it will report "Can't locate revision 0033". Repair (local dev only, not run by me): `ALTER TABLE subscriptions DROP COLUMN card_status; UPDATE alembic_version SET version_num='0032';`.
* **Uncommitted work in the main working tree depends on the feature** and is not touched by this branch: `entitlements.py` (`card_blocks`, `require_active_for_setup`), `locations.py` (calls `require_active_for_setup`), `tenants.py` (a `card_required` 402 in business creation). When this branch is merged those three hunks must be dropped (`require_active_for_setup` becomes plain `require_active`). The unrelated "places suggest" work in the same tree is unaffected.
* **A live copy problem.** The redesign helper defaulted to "Card required, no charge until the trial ends" whenever the API did not send the flag, and the production API never sends it. The live home, pricing and register pages say a card is required, but the product needs none (signup works without one). Fixing it means deploying the frontend of this branch, which needs your approval.

**Migration path.** Production: `0032 → 0034`. There is no 0033 file. The Cashfree migration uses revision id **0034** (not 0033) so a database stamped with the old 0033 can never silently skip it, and its upgrade also runs `DROP COLUMN IF EXISTS card_status` so any database that did run the old 0033 converges. The gap is documented in the migration's docstring. (Alternative if you prefer no gap: keep a no-op `0033` stub. I recommend against it because production would then record a revision named 0033 after you said it must not be deployed.)

## 3. Trial and authorisation flow

* **The trial itself needs no card** (existing policy, and what the pricing page already promises). It starts when the business is created, with Growth entitlements, for 7 days.
* A mandate is authorised only when an owner **chooses a plan**. Before Cashfree's checkout opens, the app shows a disclosure screen:
  > "Your free trial ends on **{date}**. To continue after it, authorise a monthly payment of **₹{amount}**. To set this up your bank or UPI app will take **₹1** now and return it automatically. Your first monthly charge of ₹{amount} is on **{date}**, then every month. You can cancel any time in Billing before then and you will not be charged."
  This is not described as a zero-cost trial. The ₹1 is disclosed before the customer reaches Cashfree.
* Request to Cashfree: `authorization_details {authorization_amount: 1, authorization_amount_refund: true, payment_methods: [upi, card]}`, `subscription_first_charge_time = trial_ends_at` (Cashfree allows a first charge within 14 days; 7 fits). **eNACH is not offered** (deferred).
* If the trial is already over when a plan is chosen, there is no free period: the first charge is the earliest date Cashfree allows (to be measured in sandbox) and the disclosure says so.
* Entitlements follow our own dates (`trial_ends_at`, `current_period_end`). **Cashfree's `ACTIVE` means the mandate is registered, not that money was collected**, so the business becomes `active` (paid) only on a verified **successful CHARGE** payment, never on a status alone. This is different from Razorpay and is the main behavioural change.

## 4. Status mapping (existing vocabulary, one new value)

`subscriptions.status` is a plain string. One new value is added: `authorization_pending`.

| Cashfree subscription status (names per FAQ; spelling to confirm in sandbox) | FlowQR status | Notes |
|---|---|---|
| INITIALIZED | `pending` | Checkout created, customer has not authorised. Trial entitlements unchanged. |
| BANK_APPROVAL_PENDING | `authorization_pending` | Authorised, mandate not live yet. Entitlements unchanged. |
| ACTIVE | `trialing` (if the trial is running) or unchanged | Mandate live. `active` only after CHARGE success. |
| ON_HOLD | `past_due` | A charge failed. `past_due_since` set. Grace 7 days. |
| PAUSED, CUSTOMER_PAUSED | `past_due` | No charges will happen; clock runs; ends `halted`. |
| CUSTOMER_CANCELLED, CANCELLED | `canceled` | Access kept until `current_period_end` if a period was paid, otherwise until `trial_ends_at`. |
| COMPLETED, EXPIRED | `expired` | |
| LINK_EXPIRED | back to `trialing` / `expired` | Checkout abandoned: remove the Cashfree link, keep the trial. |
| CARD_EXPIRED | `past_due` with "update payment method" | A new subscription is needed. |

| Cashfree payment | FlowQR `payments.status` |
|---|---|
| SUCCESS (CHARGE) | `captured`; the only trigger for `active` and `current_period_*` |
| SUCCESS (AUTH, the ₹1) | `captured`, `payment_type=AUTH`, never counted as revenue or a billing period |
| FAILED | `failed` with `failure_reason` |
| INITIALIZED / PENDING | `created` |
| CANCELLED / USER_DROPPED | `failed` (with reason) |

Brief states map as: payment_failed = a failed `payments` row; past_due = `past_due`; cancellation_pending = `active`/`trialing` with `cancel_at_period_end`; authorization_pending, pending, trialing, active, cancelled, expired as above.

## 5. Migration design: `0034_cashfree_billing` (down_revision `0032`)

Additive and reversible. No column dropped except the defensive `card_status IF EXISTS`. No backfill (production has only trial rows). New columns inherit the table grants and the RLS already on `subscriptions` and `payments`.

| Table | Change |
|---|---|
| `billing_plans` | `cashfree_plan_id varchar(40) NULL UNIQUE` |
| `subscriptions` | `provider varchar(12) NULL` (cashfree/razorpay/null), `cashfree_subscription_id varchar(250) NULL UNIQUE` (our merchant id), `cashfree_cf_subscription_id varchar(32) NULL`, `authorization_status varchar(24) NULL`, `trial_started_at timestamptz NULL`, `first_charge_at timestamptz NULL`, `next_charge_at timestamptz NULL`, `last_provider_sync_at timestamptz NULL`. `source` gains the value `cashfree`. |
| `payments` | `provider varchar(12) NULL`, `cashfree_payment_id varchar(64) NULL UNIQUE`, `cashfree_cf_payment_id varchar(32) NULL`, `payment_type varchar(8) NULL` (AUTH/CHARGE), `period_start`, `period_end` (timestamptz NULL), `failure_reason text NULL` (existing `error_description` is reused where it fits) |
| `webhook_events` | `subscription_ref varchar(250) NULL`, `payment_ref varchar(64) NULL`, `payload_hash char(64) NULL`, `attempts int NOT NULL DEFAULT 0`, `last_error varchar(300) NULL`, `provider_event_time timestamptz NULL`. `status` gains `failed` and `retrying`. The unique `event_id` carries `sha256(type|payment_id or subscription_id|status|event_time)` (Cashfree sends no event id). |
| `subscriptions` | `DROP COLUMN IF EXISTS card_status` (convergence for any DB that ran the withdrawn 0033) |

The `webhook_events` table stays platform-level (written before the tenant is known); it is admin-readable only. Raw payloads are **not** stored: only allow-listed safe fields and the hash, because payloads carry customer phone and email.

**Migration tests:** (1) fresh database to head; (2) `0032` with realistic seed rows (trial subscriptions) upgraded to `0034`: rows unchanged, new columns null; (3) downgrade to `0032` then up again; (4) a database stamped by the withdrawn 0033 is repaired and upgraded; (5) the existing schema-vs-models check and the RLS sweep (`test_phase2_security_audit.py`) stay green; (6) the grants test for the app role.

## 6. Provider interface (`services/billing_provider.py`)

```python
class ProviderError(Exception): ...               # carries http_status, code, a SAFE message
class ProviderNotConfigured(ProviderError): ...

@dataclass(frozen=True)
class PlanResult:          plan_id: str; status: str
@dataclass(frozen=True)
class SubscriptionResult:  provider_subscription_id: str; cf_id: str | None; status: str; session_id: str | None
                           next_charge_at: datetime | None; first_charge_at: datetime | None; plan_id: str | None
@dataclass(frozen=True)
class PaymentResult:       payment_id: str; cf_payment_id: str | None; payment_type: str  # AUTH | CHARGE
                           status: str; amount_paise: int; scheduled_for: datetime | None; failure_reason: str | None

class BillingProvider(Protocol):
    def ensure_plan(self, *, plan_id: str, name: str, amount_paise: int, max_amount_paise: int) -> PlanResult: ...   # idempotent
    def create_subscription(self, *, subscription_id: str, plan_id: str, customer: Customer, first_charge_at: datetime,
                            authorization_amount_paise: int, refund_authorization: bool, return_url: str, idempotency_key: str) -> SubscriptionResult: ...
    def fetch_subscription(self, subscription_id: str) -> SubscriptionResult: ...
    def list_payments(self, subscription_id: str) -> list[PaymentResult]: ...
    def cancel_subscription(self, subscription_id: str) -> SubscriptionResult: ...
    def change_plan(self, subscription_id: str, plan_id: str) -> SubscriptionResult: ...
    def retry_payment(self, subscription_id: str, payment_id: str, next_attempt_on: date) -> PaymentResult: ...
    def verify_webhook(self, *, raw_body: bytes, signature: str | None, timestamp: str | None, now: datetime) -> WebhookEnvelope: ...  # raises on any failure
```

`services/cashfree.py` implements it over `httpx` with: base URL by `CASHFREE_ENV`; headers `x-client-id`, `x-client-secret`, `x-api-version`, `x-idempotency-key`; amounts converted between paise and rupees in exactly one place; a **redacting** logger (never the secret, never customer details); timeouts and bounded retries only for GET. Tests use a `FakeCashfree` implementing the same protocol, plus an `httpx.MockTransport` test of the real client's request shapes against the documented fields. **No test touches the network.**

Webhook verification: `Base64(HMAC-SHA256(secret, timestamp + raw_body))` compared in constant time to `x-webhook-signature`; reject missing headers; reject a timestamp outside 5 minutes; verify on the raw bytes before any JSON parsing. The secret (documented only as "your secret key") is configured as `CASHFREE_WEBHOOK_SECRET`, defaulting to the client secret, **to be confirmed in sandbox**.

## 7. Service and API changes

Existing paths are kept; the implementation chooses the provider from `BILLING_PROVIDER` (`none` | `cashfree`), so Razorpay code stays dormant and is removed in a later cleanup.

* `GET /billing/plans`: unchanged shape plus `billing.provider`, `authorization_amount_paise`, no key id.
* `POST /billing/subscription/checkout` (owner, verified email): server prices from `billing_plans`; row lock; refuses a second live subscription; creates `pending` + the Cashfree plan once + the subscription; returns `{subscription_session_id, environment, plan, first_charge_at, authorization_amount_paise}`. Idempotent per tenant and plan.
* `POST /billing/subscription/verify`: called by the return page; **re-fetches** the subscription (and payments) from Cashfree and applies it. Never reads the redirect.
* `GET /billing/subscription`, `/history`, `/payments`: add `first_charge_at`, `next_charge_at`, `authorization_status`, failure info.
* `POST /billing/subscription/cancel`: calls Cashfree `CANCEL` (immediate, as documented). During the trial: no charge ever occurs, trial runs to `trial_ends_at`. After payment: `canceled` with access until `current_period_end`.
* `POST /billing/subscription/change-plan`: Cashfree `CHANGE_PLAN` keeps the mandate; `plan_max_amount` is set to the highest plan price so any change is allowed. Takes effect at the **next successful charge** (no proration; no free upgrade). *Decision A below.*
* `POST /api/v1/webhooks/cashfree`: public, rate-limited, 64 KB cap, signature first, persist, dedupe, tenant from our own subscription row, re-fetch, apply idempotently, 2xx only after the event is safely stored. Added to the route manifest and the public-prefix list.
* `GET /admin/subscriptions|payments|finance` extended; new `GET /admin/webhooks` (status, attempts, safe error) and `POST /admin/webhooks/{id}/reprocess`. No endpoint can mark a payment paid.
* **Reconciliation** (Celery, hourly, read-and-apply): for `pending`, `authorization_pending`, `past_due` and mandate-bearing `trialing` subscriptions, fetch and apply. The only write it may make to Cashfree is the documented `RETRY` of a failed card or UPI charge inside the grace period, at most 3 per cycle (Cashfree's own limit); it never raises a charge of its own.

## 8. Money and reporting

* MRR (`services/finance.py`) currently counts only `source == 'razorpay'`. It becomes `source in ('razorpay', 'cashfree')` with the amount read from the plan, and the ₹1 authorisation (`payment_type = AUTH`) is excluded from revenue. Historical Razorpay rows are untouched. Tests cover a mixed history.
* Failed-payment, cancelled and plan-distribution numbers come from the same status mapping.

## 9. Test plan (before any sandbox)

1. Signed-payload factory builds valid and tampered webhooks for each documented event with a test secret.
2. Mocked-provider tests: plan mapping and server-side pricing; browser cannot set a price; duplicate checkout; wrong tenant; webhook valid, bad signature, stale timestamp, duplicate delivery, out-of-order, unknown subscription, tenant spoof by id; payment success activates only on CHARGE; failure starts grace; retry limit; cancel; plan change timing; trial entitlement end; AUTH never counted as revenue; reconciliation; admin reprocess.
3. Migration tests (Section 5). Existing suites unchanged and green; tenant isolation and RLS sweeps green.
4. Frontend: type check, production build, browser tests for the disclosure, return page and billing dashboard against the fake provider locally.

## 10. Sandbox deployment plan (not executed)

Needs from you: Cashfree **sandbox** account with Subscriptions and UPI AutoPay enabled, client id and secret entered on the server through a hidden prompt, and the Subscriptions-tab webhook (version 2026-01-01) pointed at the chosen host.

* **Option A, recommended:** after your approval, deploy the new image to the existing FlowQR stack with `BILLING_PROVIDER=cashfree`, `CASHFREE_ENV=sandbox`, `CASHFREE_SANDBOX_ACK=true` (a production guard refuses sandbox keys otherwise), and the billing UI hidden from customers by the existing allowlist (only listed test accounts). Migration 0034 is additive. Rollback: previous image tag, `alembic downgrade 0032`. Needs: approval for the migration, env change and restart.
* Option B: a separate `flowqr-sandbox` Compose project and hostname: more isolation, more VPS load, a new DNS record and Caddy block (more approvals).
* Option C: a tunnel to a local stack: no VPS change, but an unstable URL and no tunnel tool installed.

**Recurring-charge evidence.** Cashfree's sandbox cannot force a PERIODIC charge early ("a payment becomes PENDING only on its scheduled date"). To produce a real recurring charge, the sandbox test must create a subscription whose first charge is a day or two away, wait, then simulate SUCCESS on the PENDING payment, and again for the next monthly date or use the shortest allowed interval (to be checked: a DAY or WEEK sandbox plan purely for testing). Until a real sandbox recurring charge is observed, recurring billing is **not** claimed to work.

## 11. Open points (all answered, see Section 12)

* **A.** Upgrades and downgrades both take effect at the next successful charge (recommended, no proration). Alternative: upgrade entitlements immediately with a prorated one-off ON_DEMAND charge (more code, more failure modes). Which?
* **B.** Plan names: confirm Starter / Growth / Pro (Section 1).
* **C.** Approve repairing the local dev database as described in Section 2, or tell me to reset it.
* **D.** Approve deploying this branch's frontend to fix the live "Card required" wording (copy only, no backend change).
* **E.** Sandbox option (Section 10) and who enters the sandbox credentials.
* **F.** Whether the revision id gap (0032 → 0034) is acceptable.

## 12. Owner decisions and what was built (2026-11-16)

| Decision | Applied |
|---|---|
| A. Plan changes: next billing cycle only, both directions, no proration, no extra charge, show the effective date, no duplicate mandates | `billing_cashfree.change_plan` tells Cashfree `CHANGE_PLAN` now but sets `pending_plan`; the plan is applied only by a verified CHARGE of the **new** amount (a charge of the old amount leaves the change waiting). The mandate ceiling is the highest plan price, so no new authorisation is needed. The billing page shows `pending_plan_name` and `pending_plan_effective_at`. A second mandate is refused (`already_subscribed`); a different plan chosen while one checkout is open closes the open one first. |
| C. Local dev database repair | Done on `flowqr-db-1` only (backup, one transaction, schema compared with a fresh 0032 database: identical except one harmless grant line). |
| D. Frontend-only copy correction | Deployed (`flowqr-m57az472a`, exported from commit `b5235cb`, 253 files matching their committed blobs, no backend, no migration): the live pages no longer say a card is required. |
| E. Migration 0034 from 0032 | `0034_cashfree_billing`, `down_revision = 0032`, no 0033 file or reference (a test proves one straight history), drops `card_status` if present, additive otherwise, reversible, a plan name an administrator edited is not overwritten, QR-card functionality untouched (a test proves it). |
| F. Option C sandbox | `deploy/sandbox/` (own Compose project, own database, `webhook-gate` that exposes only `POST /api/v1/webhooks/cashfree`, a temporary tunnel started only on request, hidden-prompt credential script). Not started: it needs the owner's sandbox credentials. |

Additional requirements: Razorpay history preserved and Razorpay disabled (the guard refuses both providers at once); MRR counts `razorpay` and `cashfree` sources and a new `mrr_by_provider_paise` shows them apart; the refundable ₹1 authorisation is stored as `kind = sub_auth`, which every revenue query excludes; 7-day trial and 7-day grace unchanged; eNACH refused by the production guard; UPI AutoPay and card only.

### Verified against Cashfree's documentation
Signature `Base64(HMAC-SHA256(secret, timestamp + rawBody))` with headers `x-webhook-signature` and `x-webhook-timestamp` and a 5-minute window; **no event id exists**, so events are stored under `sha256(type | subscription_id | payment_id | status | event_time)` (fields really in the payload) and the real truth is re-read from Cashfree before any state changes; `CANCEL` is immediate; `CHANGE_PLAN` cannot exceed the plan's max amount; the hosted checkout SDK is `@cashfreepayments/cashfree-js` (pinned 1.0.7, MIT, loads `https://sdk.cashfree.com/js/v3/cashfree.js`); a first charge may be at most 14 days ahead (the code uses 13).

### Not verified (sandbox must settle each; see CASHFREE_SANDBOX_TEST.md)
Which key signs webhooks; the timestamp format (milliseconds, seconds and ISO are accepted, anything else refused); exact status spellings; the earliest first-charge date when there is no free period (the code uses 2 days); duplicate plan or subscription id behaviour; how the monthly date falls after the first charge; whether `CHANGE_PLAN` changes the next amount; the card retry behaviour; what `return_url` receives.

### Built (files)
Backend: `core/config.py` (settings, properties, production guard), `models/billing.py`, `models/platform.py`, `alembic/versions/0034_cashfree_billing.py`, `services/cashfree.py` (client, signature, parsing), `services/billing_cashfree.py` (lifecycle, reconcile), `api/v1/webhooks.py`, `api/v1/billing.py`, `api/v1/admin.py`, `services/finance.py`, `services/entitlements.py` (48-hour settlement window), `services/billing.py`, `workers/*` (hourly reconcile), `schemas/billing.py`, `main.py`. Frontend: `components/billing/CashfreeCheckout.tsx` (the disclosure dialog), `app/(app)/settings/billing/return/page.tsx`, billing, payments and admin billing pages, `lib/billing.ts`, `lib/types.ts`, pricing note. Tests: `test_cashfree_provider.py` (33), `test_cashfree_billing.py` (60), `test_migration_0034.py` (7).

## 13. Mandatory payment authorisation before the free trial (owner decision 2026-11-16)

This reverses the earlier "the trial needs no card" decision, for Cashfree only, and replaces the withdrawn Razorpay card-on-file design with one that rests on a verified Cashfree authorisation.

* **State.** With Cashfree configured and `TRIAL_REQUIRES_MANDATE` true (the default), a NEW business is created with `subscriptions.status = 'incomplete'`: no `trial_started_at`, no `trial_ends_at`, nothing unlocked (`reason = authorization_required`). Existing businesses keep their running trials. If Cashfree is switched on but has no credentials, `settings.mandate_required` is false, so nobody is locked out of a platform that cannot take an authorisation.
* **The trial starts in one place only**, `billing_cashfree._start_trial_if_authorized`, and only from Cashfree's own answer: the subscription status read from Cashfree is `ACTIVE` (the mandate is registered). `INITIALIZED`, `BANK_APPROVAL_PENDING`, an opened checkout, a redirect, a query parameter or a webhook body cannot start it. The trial is `min(now + TRIAL_DAYS, first_charge_at)`; the first payment is scheduled for day 8 from when checkout was created, so the 7 trial days fit before it.
* **Too late.** If the authorisation is confirmed within a day of the scheduled first charge, the trial cannot be honoured, so the authorisation is cancelled at Cashfree (`authorization_stale`) and the customer starts again. A mandate is never left live to charge a customer who was promised a trial.
* **Abandoned, failed, expired:** the account stays `incomplete`, nothing is unlocked, the pending plan is cleared, and the customer can retry. Retrying reuses an open checkout for the same plan, closes it before a different plan, and never creates a second live mandate.
* **No bypass:** `POST /tenant/complete-onboarding` answers 402 `authorization_required`; `require_active` blocks every feature route; the only setup call allowed before the plan step is adding the first location (`require_active_for_setup`, only while onboarding is unfinished). There is no endpoint that sets a trial.
* **Onboarding:** Business, First location, **Plan and payment**, Google reviews, First review page. The payment step appears only when the server reports `mandate_required`. It shows the plans, a server-computed disclosure (`GET /billing/subscription/preview`: first payment date and amount, the refundable ₹1, the mandate ceiling), opens Cashfree, and afterwards asks the server what happened. Progress is derived from the server, so leaving checkout loses nothing. Cashfree returns the customer to `/onboarding?checkout=return` while onboarding is unfinished.
* **Payments section:** overview (plan, status, trial start and end, next payment amount and date, payment method kind, authorisation status), retry of a failed card payment (`POST /billing/subscription/retry-payment`, Cashfree's own call, limits as above), update payment method (a new authorisation that first closes the old mandate at Cashfree), resume after cancellation (a new authorisation: Cashfree cancellations cannot resume), plan change at the next payment, cancel (closes the mandate), billing terms.
* **Admin:** `awaiting_authorization` count; MRR counts only verified CHARGE payments and excludes the authorisation; Cashfree and Razorpay revenue are shown apart.

### What is not done or not possible (stated, not hidden)
* **Invoices and receipts:** Cashfree's subscription API (as read) has no invoice or receipt endpoint, and FlowQR does not issue tax invoices. Payment history shows Cashfree's reference; the bank or UPI app shows each debit.
* **Masked card or UPI details:** only the method kind (`upi` or `card`) is stored and shown. Whether Cashfree returns masked details is not documented in what was read, so none is stored or claimed.
* **Swapping the payment method while the current mandate is healthy:** not implemented. Cashfree documents no in-place update, only a new mandate; replacing a healthy one while keeping continuity of the next charge date needs sandbox behaviour to be settled first. Today the customer can re-authorise when the mandate is paused, expired, cancelled or its card has expired.
* **Payment methods:** UPI AutoPay and card are requested; which of them Cashfree actually enables for this merchant account is unverified until the sandbox run. eNACH stays refused.

## 14. Every trial is the complete Growth plan; the selected plan is kept apart (owner decision, final, 2026-11-16)

This replaces an earlier, withdrawn reading ("the trial grants the selected plan's entitlements"). Final rule: **every customer receives the complete Growth feature set for the entire seven-day trial, whichever paid plan they selected.** Launch, Growth and Scale all trial as Growth. Scale's own capabilities (more than one location, up to 50 team members, multi-location management, Scale's higher usage limits) are not available during the trial. The trial is 7 days for every plan.

Two things are stored separately and never overwrite each other:

| What | Where | Value during the trial |
|---|---|---|
| Trial entitlement | `subscriptions.trial_entitlement` (and the entitlement columns every route reads) | always `settings.trial_plan` = `growth` |
| Selected paid plan | `subscriptions.pending_plan` (API: `selected_plan`, `selected_plan_name`) | `starter` (Launch), `growth` or `pro` (Scale), as chosen at checkout or changed in Billing |

* When the server has read the Cashfree mandate as `ACTIVE`, `_start_trial_if_authorized` copies Growth's features and limits onto the subscription row and sets `plan = 'trial'`. `apply_plan` never writes `pending_plan`, so the selection survives.
* The transition happens only on a verified successful charge: `_on_charge_success` applies the plan whose price equals the amount actually charged, if that plan is the selected one (or the current paid plan). A charge of any other amount is recorded as `amount_mismatch` and changes nothing. After the first payment the customer has exactly the selected plan's features and limits (Launch loses Growth-only features such as Insights at that point; Scale gains its higher limits).
* Enforcement is server-side because every route and worker reads the entitlement columns through `entitlements.py`; the screen only reflects them. The browser cannot set either field at sync or return time.
* An account still `incomplete` (selected, not authorised) gets nothing, not even Growth.
* Changing the selected plan during the trial changes only what is billed afterwards (it takes effect at the next charge, no proration); the trial keeps Growth access.
* A business whose trial predates the gate, or that signed up without the gate, has `trial_entitlement` NULL and no selection, and keeps its original Growth trial unchanged.
* Proved by `backend/tests/test_cashfree_trial_entitlements.py` (all three selections: identical Growth access, second location refused, Scale-only features absent, selection preserved, transition only after a successful charge of the selected plan's amount, wrong amount changes nothing).
