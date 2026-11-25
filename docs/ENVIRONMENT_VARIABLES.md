# Environment variables

Every setting is read by `backend/app/core/config.py` (the source of truth; this table is derived from it) and, for containers, passed through `docker-compose.yml`. `.env.example` is the safe template: it contains **no real secret** and every secret in it is empty or an obvious placeholder. **`APP_ENV=staging` or `production` refuses to start** with a development secret, `COOKIE_SECURE=false`, no SMTP, test Razorpay keys (production), or localhost URLs (`REQUIRE_HARDENED` is set by `docker-compose.prod.yml`, so a forgotten `APP_ENV` cannot skip the guard).

Legend: **S** = secret (never commit, never log, never send to the browser) · **R** = required in production · **D** = owner decision pending.

## Core and security

| Variable | Default | Notes |
|---|---|---|
| `APP_ENV` | `development` | `development`, `test`, `staging`, `production`. The last two are "hardened". **R** |
| `SECRET_KEY` | dev placeholder | **S, R.** 32+ random characters (`openssl rand -hex 32`). Signs sessions and tokens. Rotating it signs everyone out. |
| `TOKEN_ENCRYPTION_KEY` | empty | **S, R.** A Fernet key (`python -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"`). Encrypts Google refresh tokens at rest. **Back it up separately: losing it makes every stored Google connection unusable** (owners reconnect). Must differ from `SECRET_KEY`. |
| `DATABASE_URL` | local | The **non-superuser** role `flowqr_app`. Row-level security only protects data when the app does not connect as a superuser. **S** |
| `MIGRATION_DATABASE_URL` | = `DATABASE_URL` | The table-owner role, used only by Alembic (`migrate` service). **S** |
| `POSTGRES_PASSWORD`, `APP_DB_PASSWORD` | none (compose refuses to start) | **S, R.** Owner and app role passwords. |
| `REDIS_URL` | local | Celery broker and rate limits. |
| `COOKIE_SECURE`, `COOKIE_DOMAIN` | `false`, empty | `true` in production. |
| `SESSION_TTL_HOURS` | 336 | Session lifetime (14 days). |
| `REGISTRATION_MODE`, `REGISTRATION_ALLOWLIST` | empty (automatic), empty | Who may create an account or a business. `closed`, `allowlist` or `open`. **Empty means `allowlist` when `APP_ENV` is staging or production and `open` in development.** An unknown value is treated as `closed` and refused by the production guard. `REGISTRATION_ALLOWLIST` is a comma-separated list of addresses; platform-admin addresses are always allowed; an administrator also manages a database list (Admin API, `python -m app.cli registration`). Existing accounts always keep signing in. See `docs/REGISTRATION_GATE.md`. |
| `ADMIN_SESSION_TTL_HOURS` | 12 | Platform administrators sign in again at least this often (the shorter of the two applies). Administrator rights also need a **verified** email address: a sign-up with an address on `PLATFORM_ADMIN_EMAILS` is an ordinary account until its mailbox is verified (or `set-admin-password` is run on the server). |
| `CORS_ORIGINS`, `FRONTEND_URL`, `PUBLIC_CARD_BASE_URL` | localhost | **R.** `PUBLIC_CARD_BASE_URL` is printed into every QR/NFC card: set the final card domain **before** generating cards. |
| `LEGAL_COMPANY_ADDRESS`, `GRIEVANCE_OFFICER_NAME` | empty | Optional. Shown in the site footer and on the privacy page (business details; the person or title who answers privacy questions and complaints, which the DPDP Rules ask to be published). Empty = not shown. On the VPS both must also be listed in the compose overlay. |
| `API_PUBLIC_URL` | empty | Optional. The address mail apps can reach the API at; when set, notification emails carry the one-click `List-Unsubscribe` header. Empty = header omitted (the Unsubscribe link inside the email works either way). On the VPS it must also be listed in the compose overlay. **Google Marketing Studio needs it as an `https://` address** (e.g. `https://api.flowqr.site`): Google downloads post photos from `<API_PUBLIC_URL>/api/v1/public/mm/<token>`; without it posts can still be written and published, just without photos. |
| `PLATFORM_ADMIN_EMAILS` | empty | Comma-separated; those accounts become platform admins when they register. |
| `RATE_LIMIT_ENABLED`, `RL_*` | on | Rate limits per IP/visitor. |

## Domains (docker-compose.prod.yml / Caddy)

`MARKETING_DOMAIN`, `APP_DOMAIN`, `API_DOMAIN`, `CARD_DOMAIN`, `ACME_EMAIL` (**R**): the four public hostnames and the address for certificate notices.
`NEXT_PUBLIC_SITE_URL` (**R**, build-time): the marketing origin (for example `https://flowqr.co.in`). It is compiled into the frontend image for canonical links, social cards and `sitemap.xml`; changing it needs a frontend rebuild (`docker compose build frontend`). If it is empty they point at `http://localhost:3000`.

## Google

| Variable | Notes |
|---|---|
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` (**S**), `GOOGLE_REDIRECT_URI`, `GOOGLE_SCOPES` | The Business Profile OAuth client customers connect through. Redirect URI must match the Google Cloud console exactly. |
| `GOOGLE_AGENCY_MANAGER_ENABLED` (**false**), `AGENCY_TOKEN_ENCRYPTION_KEY` (**S**; a separate Fernet key, must differ from `TOKEN_ENCRYPTION_KEY` and `SECRET_KEY`), `GOOGLE_AGENCY_NOTICE_HOURS` (48), `GOOGLE_AGENCY_REMOVAL_BUSINESS_DAYS` (7), `GOOGLE_AGENCY_VERIFY_INTERVAL_HOURS` (6), `GOOGLE_AGENCY_VISIBILITY_WAIT_HOURS` (48), `GOOGLE_AGENCY_LOCATION_GROUP_ID` (the FlowQR Location Group clients invite, as its **API resource name** `accounts/114863040359228435467` exactly as `accounts.list` returns it; **not** the short accountNumber `5488245563` that Business Profile Manager shows, which the API does not know; the default for `google-agency-register`), `GOOGLE_AGENCY_OPERATIONS_ENABLED` (**false**; lets an agency-managed connection act and lets onboarding switch and revoke: off, onboarding stops at "access verified"), `GOOGLE_AGENCY_POLICY_REFERENCE` (where Google's written answer on shared-project, multi-business use is recorded; the operations switch is refused in production without it), `GOOGLE_AGENCY_POLL_MINUTES` (60), `GOOGLE_AGENCY_WITHDRAWN_AFTER_MINUTES` (30), `GOOGLE_AGENCY_ORGANIZATION_ID` (FlowQR's Google organisation as its resource name `accounts/110178313486978980497`, not its accountNumber `5234249121`; never used to call Google, only so the group id can be refused if it is the organisation's), `GOOGLE_AGENCY_INVITATION_DISCOVERY` (**false**; a diagnostic that also searches every account the agency user can see for an invitation that is not in the group's own list), `GOOGLE_AGENCY_INDIVIDUAL_FALLBACK` (**false**; allows inviting one person's e-mail when no group-capable login exists), `GOOGLE_AGENCY_MAX_LOCATIONS_PER_ACCOUNT` (0 = unknown, not unlimited), `GOOGLE_AGENCY_ADOPT_EXISTING_ACCESS` (**false**; a client who already added FlowQR's group in Google, so the location is listed under it, is verified directly instead of being invited again; needs the switch and the group id), `GOOGLE_AGENCY_CLIENT_TOKEN_KEEP_HOURS` (**0** = revoke the client's own token at once; 1 to 720 keeps it, unused and encrypted, that long after the switch so `google-agency-rollback` can undo it; the consent wording changes to say so), `GOOGLE_AGENCY_SELF_SERVICE_ENABLED` (**false**; the guided self-service onboarding screens and `/google/agency/journey` APIs; adds no permission of its own and needs `GOOGLE_AGENCY_MANAGER_ENABLED`; docs/AGENCY_SELF_SERVICE_ONBOARDING_RUNBOOK.md) | The agency manager account (docs/audits/GOOGLE_CLIENT_ACCOUNT_OPTIONS.md sections 7 to 10). Off by default; with it off nothing changes. The production guard refuses the switch without the key, and without either the group id or an explicit choice of the individual fallback. **Not yet in `deploy/vps/docker-compose.vps.yml`, so it cannot reach the app until it is added there.** Never run against Google before `docs/runbooks/GOOGLE_AGENCY_TWO_ACCOUNT_TEST.md`. |
| `GOOGLE_LOGIN_CLIENT_ID`, `GOOGLE_LOGIN_CLIENT_SECRET` (**S**), `GOOGLE_LOGIN_REDIRECT_URI` | A **separate** client for "Continue with Google" (identity only). Signing in with Google is never treated as a Business Profile grant. |
| `REVIEW_SYNC_INTERVAL_MINUTES` | 30 |
| `RANK_PROVIDER`, `RANK_PROVIDER_KEY` (**S**) | `google_places` and a Places API (New) key. Without them ranking and maps stay off, and so do the business and address suggestions in onboarding (the forms stay manual; the PIN-code lookup still works). |
| `PLACES_SUGGEST_ENABLED`, `PLACES_SUGGEST_USER_DAILY_CAP`, `PLACES_SUGGEST_MONTHLY_CAP` | true, 150, 3000. Onboarding suggestions use the Places key above (Autocomplete + Place Details, billed per session by Google). One person may spend 150 Google calls a day and the whole platform 3000 a month (0 = no platform cap); every call and refusal is a row in the usage ledger under feature `onboarding_suggest`. Set `PLACES_SUGGEST_ENABLED=false` to turn them off without touching ranking. |

## AI

`GEMINI_DATA_TERMS_VERIFIED` (**false**: review data is not sent to Gemini until the owner has written evidence of the key's data-use terms), `AI_REVIEW_DATA_KILL_SWITCH` (false; true stops review data going to any provider), `PRIVACY_RETENTION_ENABLED` (**false**; the provisional retention job is off until true), `SESSION_RETENTION_DAYS` (30), `PASSWORD_RESET_TOKEN_RETENTION_DAYS` (30), `AUDIT_IP_RETENTION_DAYS` (365), `LEAD_RETENTION_DAYS` (365), `USER_DELETION_CONFIRM_HOURS` (24), `REAUTH_WINDOW_MINUTES` (15) (see `docs/PRIVACY_COMPLIANCE_AUDIT.md` §8-§9), `AI_PROVIDER` (`gemini` default), `GEMINI_API_KEY` (**S**), `GEMINI_MODEL`, `OPENROUTER_*`, `OPENAI_COMPAT_*` (**S** keys), `AI_TIMEOUT_SECONDS`, `AI_REVIEW_RISK_CHECK`, `REVIEW_*`.

`GOOGLE_CONTENT_RETENTION_ENABLED` (**false**), `GOOGLE_CONTENT_RETENTION_DAYS` (30; must be 1 to 30 while enabled), `GOOGLE_CONTENT_RETENTION_ACTION` (`redact` or `delete`), `GOOGLE_CONTENT_DELETE_ON_DISCONNECT` (**false**): expiry of content taken from the Google Business Profile APIs (`services/google_retention.py`, `docs/audits/GOOGLE_RETENTION_ARCHITECTURE.md`). **Off: deploying the code deletes nothing.** Not in the VPS overlay, so it cannot reach the app until added there on purpose. Turn on only after Google's written answer (`docs/audits/GOOGLE_QUESTIONS_TO_SUBMIT.md`); run `python -m app.cli google-retention-report` first.

## Money: plans, prices, budgets (Phase 2)

| Variable | Default | Notes |
|---|---|---|
| `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` (**S**), `RAZORPAY_WEBHOOK_SECRET` (**S**) | empty | Empty = checkout shows "configuration pending". `rzp_test_` keys = test mode. Production refuses test keys. |
| `BILLING_PROVIDER` | empty | Empty switches nothing on. `cashfree` enables Cashfree Subscriptions (needs the next four rows). Razorpay keys must then be unset. |
| `CASHFREE_ENV`, `CASHFREE_CLIENT_ID`, `CASHFREE_CLIENT_SECRET`, `CASHFREE_WEBHOOK_SECRET` | sandbox, empty, empty, empty | Separate sandbox and production credentials, never mixed. Backend only: never in the frontend, Git or logs. The webhook secret defaults to the client secret until the sandbox confirms which key Cashfree signs with. |
| `CASHFREE_SANDBOX_ACK` | false | Must be `true` to run sandbox credentials with `APP_ENV=production`: a deliberate, visible choice. |
| `CASHFREE_METHODS`, `CASHFREE_AUTHORIZATION_PAISE` | upi,card, 100 | Payment methods offered (eNACH is refused) and the refundable authorisation shown before checkout (Cashfree's minimum is 100 = Rs 1). |
| `CASHFREE_PLAN_MAX_AMOUNT_PAISE`, `CASHFREE_CHARGE_SETTLEMENT_HOURS` | 0, 48 | Mandate ceiling (0 = the highest plan price, so a plan change never needs a new authorisation) and how long access continues while a first charge settles. |
| `TRIAL_DAYS`, `TRIAL_PLAN` | 7, `growth` | The trial grants the trial plan's features and allowances. |
| `PAST_DUE_GRACE_DAYS` | 7 | Access continues this long after a failed payment; data is never removed. |
| `CARD_OFFERS` | JSON, 1 card ₹800, 2 cards ₹1,000 | One-time purchases. `[]` turns the bundles off. |
| `CARD_PRICE_PAISE` | unset | Legacy per-card price for bulk orders (10 to 1000). Unset = bulk ordering off. |
| `PROMO_CARD_PLAN`, `PROMO_CARD_DAYS` | `growth`, 30 | **D:** the free plan a card purchase includes, and how long "one month" is. |
| `PROMO_MAX_GRANTS_PER_BUSINESS` | 1 | **D:** whether a second card order earns a second free month. |
| `API_PRICES` | `{}` | JSON, USD per unit by `"<provider>.<operation>"`, e.g. `{"places.searchText": 0.032}`. **Empty by default: an unconfigured price is recorded as unpriced, never as free.** Fill from your Google Cloud billing, not from memory. |
| `AI_PRICE_IN_PER_MTOK`, `AI_PRICE_OUT_PER_MTOK` | 0 | USD per million tokens. |
| `AI_TENANT_MONTHLY_BUDGET_USD`, `AI_TENANT_MONTHLY_TOKEN_BUDGET`, `AI_PLATFORM_HARD_LIMIT_USD`, `AI_PLATFORM_MONTHLY_TOKEN_LIMIT`, `AI_PLATFORM_SOFT_PCT` | 0 / 0 / 0 / 0 / 90 | 0 = no limit of that kind. A USD limit without prices fails closed. |
| `RANK_GRID_ENABLED` (default `false`), `RANK_PLATFORM_DAILY_CAP` (0), `RANK_ALERT_PCT` (80) | | Geo-grid master switch / emergency stop, platform daily Places cap and the Operations alert threshold. **Maps run only when the switch is on, a platform cap is set and `RANK_COST_PER_CALL_USD` is set.** See `docs/GEO_GRID_ENABLEMENT.md`. |
| `RANK_MAX_KEYWORDS_PER_LOCATION`, `RANK_MONTHLY_CHECK_CAP`, `RANK_PLATFORM_MONTHLY_CAP`, `RANK_COST_PER_CALL_USD`, `RANK_RADIUS_M`, `RANK_AUTO_CHECK_DAYS`, `RANK_GRID_MIN_SPACING_M`, `RANK_GRID_MAX_SPACING_M`, `RANK_GRID_AUTO_DAYS` | 10, 300, 0, 0, 3000, 7, 250, 10000, 7 | Places spend controls. Map allowances per plan are **not** environment variables: they are plan limits an admin sets in Admin > Plans and limits. **D** |
| `USD_INR_RATE`, `HOSTING_MONTHLY_INR`, `SUPPORT_MONTHLY_INR`, `PAYMENT_FEE_PCT`, `CARD_UNIT_COST_INR`, `CARD_FULFILMENT_PER_ORDER_INR`, `MARKETING_SPEND_MONTHLY_INR` | unset | Inputs for Admin > Finance and usage. **Unset = shown as missing, never as zero.** `CARD_UNIT_COST_INR` (about 75) is a provisional estimate. |

## Autonomy and retention

`AUTONOMY_EMERGENCY_STOP` (false), `AUTONOMY_FAILURE_SUSPEND` (3), `AUTONOMY_MAX_ATTEMPTS` (4), `AUTONOMY_APPROVAL_TTL_HOURS` (72), `AUTONOMY_AUTO_AUTH_TTL_HOURS` (24), `AUTONOMY_PROPOSAL_TTL_DAYS` (7), `AUTONOMY_STUCK_MINUTES` (10); retention: `AUTONOMY_HISTORY_RETENTION_DAYS` (730, **D, provisional**), `RANK_GRID_RETENTION_DAYS` (400, **D, provisional**), `REVIEW_SESSION_RETENTION_DAYS` (90), `ACCOUNT_DELETION_GRACE_DAYS` (14). See `docs/DATA_RETENTION.md`.

## Email, monitoring, backups

`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` (**S**), `SMTP_FROM`, `SMTP_STARTTLS` (**R** in production). `SENTRY_DSN` (**S**), `SENTRY_ENVIRONMENT`, `SENTRY_TRACES_SAMPLE_RATE`. `BACKUP_STATUS_FILE`, `BACKUP_MAX_AGE_HOURS` (30); script-side: `BACKUP_PASSPHRASE_FILE` (**S**, a file path), `BACKUP_REMOTE`, `BACKUP_KEEP_DAYS` (14), `COMPOSE`.

## Environment audit (what to check before a release)

1. `.env` is mode 600, not in Git (`git check-ignore .env` prints it), not baked into an image.
2. `docker compose config | grep -i -E "secret|password|key"` shows values only for the services that need them; no secret appears in `frontend` (the browser bundle gets only `NEXT_PUBLIC_*`, none of which is a secret).
3. `python -m app.cli preflight` passes on the target environment.
4. Nothing in `git log -p` contains a real key (`git log -p -S"rzp_live_" -S"AIza"` is empty).

## Rotating a secret

| Secret | How | Effect |
|---|---|---|
| `SECRET_KEY` | change, `docker compose up -d api worker beat` | everyone is signed out; nothing else is lost |
| `TOKEN_ENCRYPTION_KEY` | **there is no automatic re-encryption.** Rotating means every business reconnects Google. Do it only after a suspected leak, announce it, and keep the old key until the last connection has been re-established. | Google connections stop until reconnected |
| `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` | rotate in the Razorpay dashboard, update `.env`, restart `api`. Webhooks signed with the old secret are refused (400) until updated: do both within minutes. | brief webhook failures; Razorpay retries |
| `GEMINI_API_KEY`, `RANK_PROVIDER_KEY`, `SMTP_PASSWORD`, `GOOGLE_CLIENT_SECRET` | rotate at the provider, update `.env`, restart `api worker beat` | none beyond the restart |
| `POSTGRES_PASSWORD` / `APP_DB_PASSWORD` | `ALTER ROLE ... PASSWORD`, update `.env` and the URLs, restart | brief downtime |
| Backup passphrase | create a new one; **old backups need the old one**: keep both until the old backups are past retention | none |

| `TRIAL_REVIEW_GENERATIONS`, `TRIAL_REVIEW_REPLIES` | 10, 10 | What a free trial may write and reply with in AI, whatever the plan whose features it borrows (owner decision 2026-11-25). Paid plans: Launch 150/150, Growth 300/300, Scale 500/500 (migration 0071). |
| `RL_REGISTER_PER_HOUR` | 10 | New accounts one network address may create per hour. |
