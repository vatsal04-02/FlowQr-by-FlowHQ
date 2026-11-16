# Cashfree billing: production deployment plan (for review; nothing here has been done)

Prerequisite: the sandbox runbook (`CASHFREE_SANDBOX_TEST.md`) has passed, including T5 (two consecutive successful recurring CHARGE payments). Each numbered step below needs your **separate explicit approval** before it is run. Registration stays `allowlist`, `AUTONOMY_EMERGENCY_STOP` stays `true`, and the clinic containers are compared with their baseline before and after every step.

## What ships

* Backend image built from the reviewed branch commit (adds `services/cashfree.py`, `services/billing_cashfree.py`, `api/v1/webhooks.py`, migration **0034**, the Compose passthrough). `BILLING_PROVIDER` is empty by default, so the image does nothing new until the setting is changed.
* Frontend build (adds the disclosure dialog, return page, billing and admin screens, the pinned `@cashfreepayments/cashfree-js` 1.0.7 dependency).
* Migration `0034`: additive columns, plan display names Launch / Growth / Scale (only rows still carrying the names 0029 gave them), defensive `card_status` drop. Production goes `0033 -> 0034` (production is stamped 0033; see design doc section 15).

## Order of work

| Step | Action | Needs approval | Verification | Rollback |
|---|---|---|---|---|
| 1 | Back up the production database (`pg_dump`, and the encrypted nightly backup status), record the clinic baseline, check memory >= 2.5 GB | yes | dump restores into a throwaway database (`deploy/verify-restore.sh`) | n/a |
| 2 | Transfer the new backend image (`docker save | ssh docker load`); nothing runs yet | yes | image ID matches | remove the image |
| 3 | Run migration `0034` as a one-off container | yes | `alembic current` = 0034; `billing_plans.name` = Launch/Growth/Scale, prices unchanged; row counts unchanged | `alembic downgrade 0032` (only Cashfree columns are lost; there is no Cashfree data yet) |
| 4 | Recreate `api`, `worker`, `beat` on the new image with `BILLING_PROVIDER` still empty | yes | `/api/ready`; `/api/v1/billing/plans` shows Launch / Growth / Scale; Razorpay and Cashfree both off; everything behaves as before | previous image tag in `.env.production` |
| 5 | Deploy the frontend (clean export of the reviewed commit) | yes | public browser phase passes; pricing shows Launch / Growth / Scale; no Cashfree wording yet (provider off) | previous Vercel deployment |
| 6 | Enter **production** Cashfree credentials on the server through a hidden prompt (a script like `deploy/vps/set-smtp.sh`; backup of `.env.production`, mode 600); set `CASHFREE_ENV=production`, `BILLING_PROVIDER=cashfree`; recreate `api`, `worker`, `beat` | yes | config guard passes (it refuses a sandbox/production mismatch, eNACH, Razorpay alongside); `/api/v1/billing/plans` shows `provider: cashfree`, `configured: true`, no key | clear `BILLING_PROVIDER` and recreate |
| 7 | In Cashfree's production dashboard set the Subscriptions webhook (version 2026-01-01) to `https://api.flowqr.site/api/v1/webhooks/cashfree`. Caddy already proxies `/api/*`: no Caddy change | yes | a test event from the dashboard returns 400 for a bad signature and is accepted for a good one | remove the URL |
| 8 | **Live payment test with your own account only** (allowlist-only registration means no one else can reach it): choose the cheapest plan with a real UPI AutoPay or card, check the disclosure, the refundable ₹1 and its return, the first-charge date | yes, and your own money | statuses, webhook, return page, history, `payments` rows, MRR unchanged until the first CHARGE succeeds | cancel in Billing (and in your UPI app); refund through Cashfree if needed |
| 9 | Observe the first real scheduled charge and one month if you want a full cycle before opening to anyone else | you decide | `activated` then `renewed` events | cancel |

## Production settings introduced

`BILLING_PROVIDER=cashfree`, `CASHFREE_ENV=production`, `CASHFREE_CLIENT_ID`, `CASHFREE_CLIENT_SECRET` (and `CASHFREE_WEBHOOK_SECRET` if Cashfree issues a separate one), left at their defaults: `CASHFREE_METHODS=upi,card`, `CASHFREE_AUTHORIZATION_PAISE=100`, `PAST_DUE_GRACE_DAYS=7`, `TRIAL_DAYS=7`. Razorpay variables stay unset. None of these is ever in Git, the frontend bundle, a log or chat.

## Risks and how they are contained

* **A webhook the sandbox showed differently from the docs:** state follows Cashfree's own answer, and the hourly reconcile covers missed events; an unknown status changes nothing.
* **Customer confusion about the ₹1:** it is disclosed before checkout and again on the return page; the history shows it as "Authorisation (returned to you)", never as a payment.
* **First payment not confirmed quickly:** access continues for the 48-hour settlement window; a failed charge goes to the 7-day grace period with an email.
* **A wrong amount:** an unexplained charge never changes entitlements and is flagged for support.
* **Rollback of the whole feature:** set `BILLING_PROVIDER` empty and recreate the services; subscriptions already authorised keep their Cashfree mandates until cancelled (cancel them in Cashfree first if the feature is being withdrawn).

## Not done and not claimed

Nothing in this plan has been run. The sandbox evidence (T1 to T10) does not exist yet. Recurring billing is therefore **not** claimed to work.
