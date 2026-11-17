# Prepaid plans: one-time Cashfree Payment Gateway checkout

**Status: built and tested; OFF.** Nothing here is enabled anywhere until `PREPAID_CHECKOUT_ENABLED=true` is set on a server (each environment needs its own approval). With the switch off the pricing screen shows prices and keeps its payment button disabled ("Payment opens soon").

## What it is, and is not
A customer pays **once** for 1, 3, 6 or 12 months of Launch, Growth or Scale through a Cashfree **Payment Gateway order**. It is **not** Cashfree Subscriptions: no mandate, no UPI AutoPay, no Rs 1 authorisation, no recurring charge, nothing stored for a later debit. The old subscription integration (`BILLING_PROVIDER=cashfree`, `/webhooks/cashfree`, `/billing/subscription/*`) is untouched and stays dormant; prepaid does **not** depend on `BILLING_PROVIDER`.

## Flow
1. Pricing screen: customer picks plan and term, enters a mobile number (Cashfree requires it; it is passed on and **not stored**).
2. `POST /billing/prepaid/checkout` `{plan, months, phone}` (owner, verified email). **No amount is sent.** The server prices the order from `services/plans.py` `TERM_PRICES_PAISE`, stores a `prepaid_orders` row, creates the Cashfree order (`POST /pg/orders`, API version `CASHFREE_PG_API_VERSION`, default 2025-01-01) and returns `payment_session_id`.
3. The browser opens Cashfree's hosted page (`cashfree.checkout({paymentSessionId, redirectTarget:"_self"})`) and comes back to `/settings/billing/pay-return?order_id=...`.
4. The return page calls `POST /billing/prepaid/verify`. **The server asks Cashfree** (`GET /pg/orders/{id}` and `/payments`). Access is granted only if the order is `PAID` for exactly the stored amount and currency. A different amount grants nothing (`mismatch`, audit entry, support).
5. Three independent paths reach the same idempotent activation: the return page, the webhook `POST /webhooks/cashfree-pg` (a hint: the order is looked up by our own id and the truth is re-read from Cashfree), and an hourly `prepaid_reconcile` over orders from the last 3 days. The order row is locked and `activated_at` is set once, so a plan is granted once however many arrive.
6. Activation writes `subscriptions`: `status=active`, `provider=prepaid`, `source=prepaid`, the plan's limits and features, `current_period_start/end`; a `payments` row (`kind=subscription`, `payment_type=PREPAID`); a `subscription_events` row; an audit entry; an email to the owners.

## Rules (all covered by `tests/test_prepaid_checkout.py`)
- Failed, abandoned, pending or expired payments change nothing about access.
- Access ends **by the clock**: `entitlements._compute` treats a prepaid term as inactive (`plan_expired`) once `current_period_end` passes; the hourly housekeeping then records `expired`. Nothing renews it.
- Terms are calendar months, clamped to the end of a short month.
- A running prepaid term, or a live monthly mandate, blocks a second purchase (409). If two orders are nonetheless paid (two tabs), the same plan **adds** the time and a different plan carries the unused time: money is never taken without service.
- One business can never read or verify another business's order (RLS and a tenant check).
- No card/UPI detail, phone, payment session or secret is stored or logged.

## Enabling (a separate approval, per environment)
Server env: `PREPAID_CHECKOUT_ENABLED=true`, `CASHFREE_CLIENT_ID`, `CASHFREE_CLIENT_SECRET`, `CASHFREE_ENV` (`sandbox` or `production`, matching the credentials), optionally `PREPAID_NOTIFY_URL=https://api.flowqr.site/api/v1/webhooks/cashfree-pg` (sent with every order, so the Cashfree dashboard needs no webhook setting) and `CASHFREE_WEBHOOK_SECRET` (defaults to the client secret). Run migration `0040`. Recreate api, worker and beat with **both** compose files. The compose file must pass the new variables through. Rollback: unset the switch and recreate; the table is additive.

## Migration numbering
`0040_prepaid_orders` chains on production's head `0037`. `0038` (consent grants) and `0039` (trial grants) exist on other unreleased branches; whichever lands second changes **one line** (`down_revision`) to the then-current head, as in `docs/CARDLESS_TRIAL.md` section 3.

## Not done / not proven
- **Not run against the real Cashfree sandbox from this branch**: the request and response field names follow Cashfree's documented Orders API but are checked here only against a test double. First real step after approval: one sandbox order created, paid with a sandbox test instrument, and confirmed through all three paths.
- GST: prices are the amounts charged. FlowQR issues no tax invoice from this screen; whether to add one is a decision for the owner and an accountant.
- Refunds are manual (Cashfree dashboard); there is no refund automation or "refunded" state yet.
- Plan changes in the middle of a term are not automatic (support).
