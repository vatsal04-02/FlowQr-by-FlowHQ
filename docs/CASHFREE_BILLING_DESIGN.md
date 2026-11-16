# Cashfree recurring billing: Phase 1 design

Status: **proposal for review. No Cashfree code is written yet.** The only code change on this branch is the removal of the card-on-file feature (Section 2). Production, the VPS, Vercel, the database and Cashfree are untouched. Read with `CASHFREE_BILLING_AUDIT.md`.

## 1. Decisions as understood

| # | Decision | How it is applied |
|---|---|---|
| 1 | Remove card-on-file (migration 0033) | Done on this branch, Section 2. |
| 2 | Plan names | The instruction names "Launch / Growth / scale" but also says these are the *existing* names and not to introduce Launch or Scale. The code, database, live API and site say **Starter ₹499, Growth ₹799, Pro ₹1,499** (verified), and "Launch"/"Scale" appear nowhere. This design uses **Starter / Growth / Pro**. The display name is read from `billing_plans.name`, so a later rename is a one-row data change, no code. **Please confirm.** |
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

## 11. Open points

* **A.** Upgrades and downgrades both take effect at the next successful charge (recommended, no proration). Alternative: upgrade entitlements immediately with a prorated one-off ON_DEMAND charge (more code, more failure modes). Which?
* **B.** Plan names: confirm Starter / Growth / Pro (Section 1).
* **C.** Approve repairing the local dev database as described in Section 2, or tell me to reset it.
* **D.** Approve deploying this branch's frontend to fix the live "Card required" wording (copy only, no backend change).
* **E.** Sandbox option (Section 10) and who enters the sandbox credentials.
* **F.** Whether the revision id gap (0032 → 0034) is acceptable.
