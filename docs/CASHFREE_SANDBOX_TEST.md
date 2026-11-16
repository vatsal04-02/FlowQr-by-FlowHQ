# Cashfree sandbox test: runbook and evidence rules

Everything here runs on your own machine against Cashfree's **sandbox**. No VPS, no production database, no live Cashfree credential. The automated suite (`backend/tests/test_cashfree_*.py`) proves how FlowQR behaves **when Cashfree behaves as documented**. This runbook is how we find out whether Cashfree really does.

## What the automated tests do NOT prove (the sandbox must)

| Unverified fact | Where it matters | Sandbox check |
|---|---|---|
| Which secret signs webhooks, and the exact `x-webhook-timestamp` format | `cashfree.verify_webhook` (currently milliseconds, seconds or ISO accepted; any other refused) | T4 |
| That `subscription_first_charge_time` is honoured and what the customer sees (date, amount) | the whole free-trial promise | T2 |
| The exact spelling of subscription and payment statuses | `AUTH_OF`, `PAYMENT_STATUS` (unknown statuses are ignored safely, but then nothing would activate) | T2, T3, T5 |
| Duplicate plan or subscription id behaviour | `ensure_plan` fetches first, so a duplicate is not expected | T1 |
| How the monthly date falls after the first charge | `current_period_end` | T5 |
| Whether `CHANGE_PLAN` changes the next charge amount | next-cycle plan changes | T8 |
| Retry behaviour of a failed card charge | `maybe_retry` | T6 |
| Whether `redirectTarget: "_self"` returns to our page and what `return_url` receives | the return page | T3 |
| Earliest first-charge date allowed when no free period is left (we use 2 days) | `NO_FREE_PERIOD_FIRST_CHARGE_DAYS` | T2 |

## Before starting (you)

1. A Cashfree **sandbox** account with Subscriptions enabled. UPI AutoPay must be activated for the account (Cashfree support; it applies to sandbox and production). Without it the checkout fails with `payment_mode_invalid_for_action`.
2. In your own terminal: `bash deploy/sandbox/set-credentials.sh` (hidden prompts; writes `deploy/sandbox/.env.sandbox`, mode 600, git-ignored). Never paste the secret in chat.
3. `bash deploy/sandbox/run.sh up`, then open <http://localhost:3300>. Register a test owner (registration is open on this local stack only; mail goes to the container log: `docker compose -f deploy/sandbox/docker-compose.sandbox.yml logs api | findstr token`).
4. `bash deploy/sandbox/run.sh tunnel` prints `https://<random>.trycloudflare.com`. In the Cashfree dashboard (Payment Gateway > Developers > Webhooks > **Subscriptions** tab, version **2026-01-01**) set the URL to `<address>/api/v1/webhooks/cashfree`. The tunnel reaches only that one path and method (proved by test), and stops with `run.sh down`.

## Test matrix

| # | Do | Record (evidence) | Pass when |
|---|---|---|---|
| T1 | Checkout twice for the same plan; also call `ensure_plan` again | Cashfree plan list shows one plan per code; our `billing_plans.cashfree_plan_id` | no duplicate plan; second call reuses |
| T2 | Business with a running trial chooses a plan; read the Cashfree authorisation screen | screenshot; `subscription_first_charge_time`, `next_schedule_date`, `authorization_amount` from `GET /subscriptions/{id}` | first charge = trial end; the screen shows the ₹1 authorisation and the first-charge date/amount; a refundable authorisation is returned |
| T3 | Authorise with UPI AutoPay (sandbox VPA) and with a test card | return-page screenshot; statuses seen (`INITIALIZED`, `BANK_APPROVAL_PENDING`, `ACTIVE`); `SUBSCRIPTION_AUTH_STATUS` | page shows "Payment set up"; business stays `trialing`; AUTH payment stored as `sub_auth`; nothing counted as revenue |
| T4 | Watch real webhooks arrive (`webhook_events` rows); resend one; send one with a wrong signature using `curl` | real headers (names, timestamp format), secret that verified, duplicate handling, the 400 | signature verifies with the documented algorithm and the right secret; duplicates are `duplicate`; forged is refused |
| T5 | **Recurring evidence.** Create a subscription with the earliest allowed first charge. When its payment becomes PENDING on the scheduled date, `POST /simulate` SUCCESS (see below). Then the next cycle | `payments` rows (two `CHARGE` rows, two payment ids, `captured`), `subscription_events` (`activated`, then `renewed`), `current_period_end` moved by one interval | **two consecutive successful CHARGE payments** on distinct payment ids, one billing interval apart, each arriving by webhook or reconciliation |
| T6 | `POST /simulate` FAILED on a PENDING charge, for UPI and for a card | `past_due`, the owner email, grace date, retry request (card) | `past_due` + notice; access continues 7 days; recovery on a later SUCCESS |
| T7 | Cancel during trial and after payment | Cashfree status `CANCELLED`; our `canceled`; access until period end | no later charge; access ends on the stated date |
| T8 | Change plan during an active period | `CHANGE_PLAN` response; next charge amount at Cashfree | our plan changes only when the new amount is charged |
| T9 | Abandon a checkout; let a link expire | `LINK_EXPIRED`/`EXPIRED` | trial untouched; a fresh checkout works |
| T10 | Stop the tunnel, simulate a SUCCESS, wait for the hourly job (or run `cfb.reconcile`) | the payment is applied without a webhook | state matches Cashfree |

`/simulate` (sandbox only): `POST https://sandbox.cashfree.com/pg/simulate`, header `x-api-version: 2026-01-01`, body `{"entity":"SUBS_PAYMENTS","entity_id":"<payment_id>","entity_simulation":{"payment_status":"SUCCESS","payment_error_code":""}}`. It works **only when the payment is PENDING**; for a PERIODIC plan that happens on the scheduled date, and Cashfree states the sandbox cannot bring it forward.

## How a real recurring charge is observed in a few days, not a month

A PERIODIC plan's charge date is the first-charge time, and later dates follow the plan interval. To see two charges in days rather than a month, create **a sandbox-only test plan** with `plan_interval_type = DAY` (or WEEK) and a different id such as `flowqr-sandbox-daily-test`, point a test subscription at it, and observe two scheduled charges a day apart. This test plan is never created by the application and never used in production; its sole purpose is evidence that scheduled recurring collection reaches our webhook and reconciliation path. Whether Cashfree allows a DAY interval in the sandbox is itself something to record.

## The claim rule

* "Recurring billing works" may be written only when T5 has produced **two consecutive successful CHARGE payments** in the sandbox, with the evidence above attached to the report.
* A successful authorisation (T3), a single successful charge, or a simulated payment on an ON_DEMAND plan is **not** that evidence.
* If any "unverified fact" above turns out different, the code is changed and the affected automated tests are updated **before** the claim is made.

## Cleaning up

`bash deploy/sandbox/run.sh down -v` removes the sandbox stack and its database. In the Cashfree dashboard remove the webhook URL, and revoke or rotate the sandbox secret if it was ever shown on a screen that was shared.
