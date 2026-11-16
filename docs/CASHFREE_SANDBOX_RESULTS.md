# Cashfree Sandbox results (first real run, 2026-11-16)

Real Cashfree **Sandbox** (`sandbox.cashfree.com`, API version 2026-01-01), driven through the FlowQR Sandbox stack (`deploy/sandbox`, local, own database) and Cashfree's own hosted checkout in a real browser. No production credential, no production data. Tunnel restricted to `POST /api/v1/webhooks/cashfree` (proved: unsigned POST 400, other paths 404, GET 403).

## Claim status

| Claim | Status |
|---|---|
| Recurring billing works | **NOT PROVEN.** No scheduled charge has run. Needs two consecutive successful recurring Sandbox charges (T5). |
| Mandatory authorisation gates the trial | **Proven against real Cashfree for UPI** (below). Card authorisation not completed (below). |
| Webhooks | **NOT PROVEN.** The tunnel works, but the webhook URL has not been registered in the Sandbox dashboard, so no real webhook has arrived. State was learned through the return-page sync only. |

## What was observed (real Cashfree answers)

| # | Test | Result |
|---|---|---|
| T1 | Plan creation | `GET /plans/{id}` for a missing plan returns **HTTP 400** `plan_not_found`, not 404. **Bug found and fixed** (checkout 500). Plan `flowqr-growth-79900` created once and reused. |
| T2 | Subscription creation | Accepted. Session issued, status `INITIALIZED`. Hosted page shows plan, ₹799/month, first charge date and the ₹1 authorisation. |
| T2 | First charge time | We sent 10:00 IST on the date; Cashfree stored `subscription_first_charge_time` as **00:00 IST** (date honoured, time not). `next_schedule_date` was 00:10 IST that day. |
| T3 | UPI authorisation, Simulate Success (test VPA `testsuccess@gocash`) | Cashfree status `ACTIVE`; `authorization_amount` 1, `authorization_amount_refund` true; AUTH payment SUCCESS. FlowQR read it, started the 7-day trial with Growth entitlements (18 features), kept `selected_plan` Growth, recorded `payment_method` upi. Not counted as revenue. |
| T3 | Return to the app | Cashfree returned the customer to `/onboarding` **without our `?checkout=return` query**. The page does not depend on it (server state decides). |
| T3 | UPI authorisation, Simulate Failure | Subscription stays `INITIALIZED`; no trial, nothing charged; the customer sees "We haven't received your authorisation yet" and can retry. No second mandate created. |
| T3 | Card authorisation | Hosted card form accepts Cashfree's documented test card; summary screen shows; method recorded as `card`. The **Confirm step did not advance in headless automation** (no popup, no navigation). **Not completed.** Needs a manual run in a normal browser (OTP 111000 per Cashfree's docs). The card screen says "INR 1 will be deducted" and does **not** say it is refunded, whereas the UPI screen does: confirm the card refund really happens before keeping our "returned automatically" wording for cards. |
| T8 | Change plan during the trial (Growth to Scale) | Cashfree accepted `CHANGE_PLAN`: the subscription's plan became `flowqr-pro-149900` (₹1,499), status stayed `ACTIVE`. FlowQR kept Growth access for the trial and shows Scale as the pending plan. |
| T7 | Cancel during the trial | Cashfree `CANCELLED`; FlowQR `cancellation_pending`, access kept to the end of the trial. |

## Bugs found and fixed here

1. **`plan_not_found` is HTTP 400** (checkout failed with a 500). Fixed in `services/cashfree.py`, with a test using Cashfree's exact answer.
2. **Content Security Policy `form-action 'self'` blocked Cashfree's hosted checkout** (the button spun forever). `frontend/next.config.mjs` now allows `https://*.cashfree.com`.

Both would have broken a live customer's first checkout. They are committed on `billing/cashfree-phase1` and are **not deployed**: production's Cashfree billing was switched off before they were fixed and must not be switched on again until a release containing them is deployed.

## Still to do (needs real time or the dashboard)

* **T4 webhooks:** register `<tunnel>/api/v1/webhooks/cashfree` in the Sandbox dashboard (Payment Gateway, Developers, Webhooks, Subscriptions tab, version 2026-01-01), then repeat an authorisation and read `webhook_events`: which secret signs, timestamp format, status spellings.
* **T5 recurring:** a sandbox-only daily plan subscription so two scheduled charges happen a day apart; then `activated` and `renewed` events and two captured CHARGE rows.
* **T6** failed charge (UPI and card) and retry; **T10** reconciliation with the tunnel stopped; card authorisation and refund (T3).
