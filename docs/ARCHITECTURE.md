# Architecture

## Shape
A **modular monolith**: one Next.js frontend, one FastAPI backend, one Celery worker (+ beat), PostgreSQL, Redis. No microservices.

The browser only talks to the Next.js origin. Next.js proxies `/api/*` to FastAPI (`BACKEND_URL`), so session cookies are first-party (`SameSite=Lax`), no CORS is needed in production, and no secret ever reaches the browser.

## Request lifecycle & tenancy
1. `get_auth_context` loads the server-side session from the HTTP-only cookie (SHA-256 of an opaque token is stored, so a DB leak can't be replayed). For `POST/PUT/PATCH/DELETE` it requires `X-CSRF-Token` equal to the token bound to that session.
2. `get_tenant_context` finds the user's memberships and picks the active tenant. The tenant is **never taken from a body/query parameter**; an optional `X-Tenant-Id` header only *selects among tenants the user is already a member of*.
3. It then sets `app.tenant_id` for the DB transaction. PostgreSQL **Row-Level Security** (FORCE'd, non-superuser app role) now confines the session to that tenant, even if a handler forgets a `WHERE tenant_id = ...`. With no context, tenant tables return zero rows (default deny).
4. `require_role(Role.admin)` etc. gate by Owner > Admin > Staff.
5. Public card endpoints and platform-admin endpoints run with explicit bypass and only perform narrow, token-keyed or admin-only queries. Workers use `system_session()` (bypass).

## Modules
| Module | Code | Notes |
|---|---|---|
| Auth & onboarding | `api/v1/auth.py`, `tenants.py` | Argon2id, sessions, CSRF, reset tokens, invitations, tenant creation (Owner + trial Subscription in one transaction) |
| Cards | `services/cards.py`, `qr.py`, `api/v1/cards.py`, `admin.py` | batches via DB sequence → `FQR-0001`; tokens 144-bit; QR via `segno`, error correction **H**, 4-module quiet zone; PNG/SVG, ZIP + `manifest.csv`, printable A4 sheet |
| Public landing + AI assist | `api/v1/public.py`, `services/ai/*` | scan recorded server-side; bot filter + 20 s dedupe; per-IP and per-tenant AI limits; usage logged (sizes only) |
| Google | `services/google/*`, `api/v1/google.py` | `GoogleBusinessProvider` interface; `HttpGoogleProvider` real impl; state = signed payload + nonce cookie; tokens Fernet-encrypted |
| Sync | `services/google/sync.py`, `workers/tasks.py` | idempotent upsert on `(google_location_id, external_id)`; 1/2/4 s in-request backoff; 5 min → 6 h persistent backoff; revoked → connection marked `revoked` |
| Replies | `api/v1/reviews.py`, `services/reviews.py`, `services/ai/replies.py|safety.py` | draft → approve (+ack if flagged) → publish; "published" only after Google 2xx; every attempt in `reply_logs` |
| Analytics | `api/v1/analytics.py` | tenant-timezone day buckets; bots excluded; four funnel stages kept separate |

## Provider abstractions
* **AI**: `LLMProvider.generate(system, user)`; add a provider in `services/ai/base.get_provider`. Gemini is implemented (`services/ai/gemini.py`, key sent in a header, never in a URL).
* **Google**: `GoogleBusinessProvider` protocol. Tests replace `app.services.google.get_google_provider` with a labelled fake.
* **Email**: `services/mailer.send_email` (SMTP when `SMTP_HOST` set).

## Why scans are recorded by the API, not the redirect
`/c/{token}` is a Next.js page that calls `GET /api/v1/public/c/{token}` from the visitor's browser. Link-preview bots (WhatsApp/Facebook) that don't run JS never hit the API, real browsers do; remaining bots are flagged by user-agent and excluded from analytics. The permanent card URL is `{PUBLIC_CARD_BASE_URL}/c/{token}`; changing the destination review link never changes the card URL.

## Design system
Swiss-minimal SaaS (UI/UX Pro Max guidance), white surfaces, rounded cards, subtle shadows. Blue `brand` = primary actions, orange `flow` = FlowQR accent (dark text on orange for contrast), Google-style multicolour used only as decoration and chart hues (series also differ by line style). Poppins headings / Open Sans body. 44 px touch targets, visible focus rings, `prefers-reduced-motion`, inline validation on blur + focusable error summary, charts with legend + keyboard tooltip + data-table fallback.

## Phase 2: commercial layer
* **One catalogue** (`services/plans.py`) is the specification; `billing_plans` is what runs; a test compares them. Features gate routes (`require_feature`), workers (`has(...)`) and the autonomy executor. A free card month is layered on top of a subscription at read time (`entitlements.for_tenant`), never written into it.
* **Quotas** are enforced at the backend call site by `ai_usage.quota_exceeded(db, tenant, kind)`: review generations and replies are counted separately, successes only.
* **One usage ledger per kind of cost**: AI in `ai_call_ledger`, Google in `api_usage_ledger`. `services/finance.py` reads both and the payment tables; it never invents a figure.
* **Honest status everywhere**: finance figures are actual, estimated or missing; the release ladder (`app/release_gates.json`) is edited by a person with evidence and is never computed.
