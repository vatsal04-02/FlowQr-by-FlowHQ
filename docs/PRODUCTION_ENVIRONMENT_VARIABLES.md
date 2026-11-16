# Production environment variables (flowqr.site)

Every name here is read by the code: the backend through `backend/app/core/config.py` (passed in by `docker-compose.yml`), the frontend through `process.env`. The complete list with defaults and meanings is `docs/ENVIRONMENT_VARIABLES.md`; this file says **where each production value lives and what it must be**. The template for the server is `deploy/vps/.env.production.example`. **Never commit a filled file; never copy `.env` between machines; do not reuse the development `.env`.**

## Vercel (frontend project `flowqr`): browser-visible, so no secrets

| Variable | Production value | Set | Notes |
|---|---|---|---|
| `NEXT_PUBLIC_API_URL` | `https://api.flowqr.site` | yes (Production and Preview) | compiled in at build: change means redeploy. Empty would make the browser call its own origin, which is wrong on Vercel |
| `NEXT_PUBLIC_SITE_URL` | `https://flowqr.site` | yes (Production and Preview) | canonical links, sitemap, social cards. Compiled in |

No other frontend variable is needed. `BACKEND_URL` (Docker only) is unused on Vercel because nothing is proxied.

## VPS (`/opt/flowqr/.env.production`, mode 600)

| Variable | Production value | Required | Notes |
|---|---|---|---|
| `APP_ENV` | `production` | yes | enables the strict guard; debug, docs and OpenAPI off |
| `SECRET_KEY` | 64 random hex characters | yes | signs OAuth state; at least 32 characters |
| `TOKEN_ENCRYPTION_KEY` | Fernet key (url-safe base64 of 32 bytes), different from `SECRET_KEY` | yes | **keep a copy off the server** |
| `POSTGRES_PASSWORD`, `APP_DB_PASSWORD` | random, different | yes | owner role vs the non-superuser application role |
| `FRONTEND_URL` | `https://flowqr.site` | yes | link targets in emails and redirects after OAuth |
| `CORS_ORIGINS` | `https://flowqr.site,https://www.flowqr.site` | yes | explicit; must include `FRONTEND_URL`'s origin (the guard checks) |
| `COOKIE_SECURE` | `true` | yes | the guard requires it |
| `COOKIE_DOMAIN` | `.flowqr.site` | **yes, because site and API differ** | must cover both hosts (the guard checks). **Was not passed through Compose before this pass** |
| `GOOGLE_REDIRECT_URI` | `https://api.flowqr.site/api/v1/google/callback` | when Google is enabled | register this exact URI in Google Cloud |
| `GOOGLE_LOGIN_REDIRECT_URI` | `https://api.flowqr.site/api/v1/auth/google/callback` | when Google sign-in is enabled | |
| `GOOGLE_CLIENT_ID/SECRET`, `GOOGLE_LOGIN_CLIENT_ID/SECRET` | two **separate** OAuth clients | optional | leave empty until the consent screen allows the intended users |
| `PUBLIC_CARD_BASE_URL` | **decision pending**: `https://flowqr.site` or `https://go.flowqr.site` | yes | **printed on cards, permanent** |
| `PLATFORM_ADMIN_EMAILS` | your admin address(es) | yes | administrator only after **verified** email |
| `REQUIRE_VERIFIED_EMAIL` | `true` | yes | the guard requires it |
| `SMTP_HOST/PORT/USER/PASSWORD/FROM/STARTTLS` | a real provider | **yes** | the app refuses to start without it; a local mail sink is refused in production |
| `SUPPORT_EMAIL`, `LEGAL_COMPANY_NAME` | monitored address; `FlowHQ` | recommended | shown on the legal pages. **Were not passed through Compose before this pass** |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | key; `gemini-3.5-flash` | for AI features | |
| `AI_PRICE_IN_PER_MTOK`, `AI_PRICE_OUT_PER_MTOK`, `AI_PLATFORM_HARD_LIMIT_USD`, `AI_TENANT_MONTHLY_BUDGET_USD` | **unset today** | decision | dollar budgets refuse AI calls while unpriced |
| `RANK_PROVIDER`, `RANK_PROVIDER_KEY` | `google_places`, a new restricted key | for maps and for the business/address suggestions in onboarding | rotate the exposed development key; do not reuse it. Enable Places API (New), restrict the key to this server's IP, link billing |
| `RANK_PLATFORM_MONTHLY_CAP` | a number | **set before enabling scans** | `0` = no platform ceiling |
| `API_PRICES` | from Cloud Billing | decision | unset = costs shown as unpriced |
| `RAZORPAY_*`, `CARD_PRICE_PAISE` | **empty** | no | Cashfree is deferred; Razorpay must not be configured. The guard rejects half-set Razorpay keys |
| `SENTRY_DSN` | project DSN | recommended | Admin > Operations is "critical" without it |
| `AUTONOMY_EMERGENCY_STOP` | `true` until live validation is complete | decision | holds every Google write platform-wide |
| `ADMIN_SESSION_TTL_HOURS`, `SESSION_TTL_HOURS` | `12`, `336` | defaults | |
| `FLOWQR_API_PORT`, `FLOWQR_*_MEM` | `18000`, memory ceilings | defaults | the loopback port the existing Caddy proxies to; container limits for the shared server |

## Things that are NOT variables here

Redis and PostgreSQL addresses (internal Compose networking, `redis:6379` and `db:5432`); there is no file or media storage setting (photos and logos live in PostgreSQL); there is no separate Celery broker variable (Celery uses the Redis instance). Payment provider settings do not exist for Cashfree yet.
