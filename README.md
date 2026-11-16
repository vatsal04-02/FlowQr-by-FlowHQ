# FlowQR by FlowHQ

**AI-powered reputation & review management for local businesses**: unique QR/NFC review cards, an AI writing assistant for customers, Google Business Profile review sync, and human-approved AI reply drafts. Multi-tenant (one platform → many businesses → many locations → many cards), built for Indian SMBs first (INR, `+91` phone formats, English/Hindi/Hinglish).

> Status: feature-complete MVP+ (auth, multi-tenancy + RLS, QR/NFC cards, public AI assistant, Google sync/replies/profile management, Razorpay billing, platform admin). **Integrations with Google, Gemini and Razorpay are fully coded and tested against labelled fakes, but not against the real services** (no credentials were available). Exact PASS / BLOCKED / NOT TESTED list: [docs/CHECKLIST.md](docs/CHECKLIST.md).

## Two operating modes

| Mode | What works | Needs |
|---|---|---|
| **A. Manual review link** | Cards, public landing page, AI writing assistant, scan analytics | Nothing from Google. Owner pastes their Google review link. |
| **B. Connected Google** | + review sync, reviews inbox, AI reply drafts, approve & publish | Google OAuth client **and** Google-approved Business Profile API access |

Without Google credentials the app shows an explicit **"Configuration pending"** state. It never fakes a connection.

## Domains

| Host | Serves |
|---|---|
| `flowqr.co.in` | marketing site (home, pricing) |
| `app.flowqr.co.in` | customer dashboard + platform admin console (+ same-origin `/api`) |
| `api.flowqr.co.in` | API for Razorpay webhooks / integrations |
| `go.flowqr.co.in` | permanent QR/NFC card URLs `/c/{token}` only |

## Architecture (modular monolith)

```
Browser ──► Caddy (TLS) ──► Next.js (UI + /api proxy) ──► FastAPI ──► PostgreSQL (RLS)
                                                          │  ▲
                                                          ▼  │
                                                Celery worker/beat ◄──► Redis
                                                          │
                                         Google OAuth / Business Profile · Gemini
```

```
backend/            FastAPI, SQLAlchemy 2, Alembic, Celery
  app/api/v1/       routers: auth, tenants(+staff), locations, cards, admin, public, google, reviews, analytics
  app/core/         config, db (+RLS context), security (Argon2id, Fernet), deps (auth/CSRF/tenant), rate limit
  app/models/       Tenant, User, Membership, Location, GoogleConnection/Location, Review, ReplyDraft/Log,
                    QRCard, CardBatch, CardAssignment, ScanEvent, AIGenerationLog, Subscription, AuditLog ...
  app/services/     cards, qr, ai (provider abstraction + Gemini), google (provider interface + HTTP impl), sync
  app/workers/      Celery app + tasks
  alembic/          migrations (0001 schema · 0002 RLS + grants · 0003 card code sequence)
  tests/            58 tests (incl. cross-tenant + raw-SQL RLS tests)
frontend/           Next.js 15 (App Router), TypeScript, Tailwind
  src/app/          pages (landing, auth, onboarding, dashboard, reviews, cards, google, ... admin, c/[token])
  src/components/   ui kit, charts (accessible SVG), AppShell
db/init/            creates the non-superuser runtime role (so RLS is enforced)
deploy/             Caddyfile, backup.sh, restore.sh
docs/               ARCHITECTURE, DATABASE, API, DEPLOYMENT, SECURITY, CHECKLIST, ART_DIRECTION_AND_UI_AUDIT (design system + route-by-route screenshots)
e2e/                Playwright smoke test; demo-data seed, product-screenshot capture and UI sweep (see the audit doc)
```

## Quick start with Docker (recommended)

```bash
cp .env.example .env
# fill in the secrets (Razorpay/Google/Gemini keys are optional: features show 'configuration pending' without them) (commands are in .env.example):
openssl rand -hex 32                                   # -> SECRET_KEY
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # -> TOKEN_ENCRYPTION_KEY
# also set POSTGRES_PASSWORD and APP_DB_PASSWORD (letters/digits), and PLATFORM_ADMIN_EMAILS=you@yourdomain.in
docker compose up --build
```

Open http://localhost:3000. Register with the email you put in `PLATFORM_ADMIN_EMAILS` to become a **FlowHQ platform admin** (this unlocks **Platform admin** → card inventory). Register any other email to act as a business owner.

Services: `db` (Postgres 16), `redis`, `migrate` (one-shot Alembic), `api` (:8000, loopback only), `worker` + `beat` (Celery), `frontend` (:3000, loopback only).

## Local development without Docker

Requires Python 3.12+, Node 20+, PostgreSQL 16, Redis 7.

```bash
# 1) Database roles (runtime role must NOT be a superuser, otherwise RLS is bypassed)
sudo -u postgres psql <<'SQL'
CREATE ROLE flowqr LOGIN PASSWORD 'flowqr_dev' CREATEDB;
CREATE ROLE flowqr_app LOGIN PASSWORD 'flowqr_app_dev' NOSUPERUSER NOBYPASSRLS;
CREATE DATABASE flowqr OWNER flowqr;
CREATE DATABASE flowqr_test OWNER flowqr;
SQL

# 2) Backend
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cat > .env <<'ENV'
DATABASE_URL=postgresql+psycopg://flowqr_app:flowqr_app_dev@localhost:5432/flowqr
MIGRATION_DATABASE_URL=postgresql+psycopg://flowqr:flowqr_dev@localhost:5432/flowqr
TOKEN_ENCRYPTION_KEY=<generated Fernet key>
PLATFORM_ADMIN_EMAILS=you@example.com
ENV
alembic upgrade head
uvicorn app.main:app --reload --port 8000            # API docs: http://localhost:8000/api/docs
celery -A app.workers.celery_app worker -l INFO       # optional: background sync
celery -A app.workers.celery_app beat -l INFO         # optional: periodic sync

# 3) Frontend (new terminal)
cd frontend
npm install
BACKEND_URL=http://localhost:8000 npm run dev         # http://localhost:3000
```

## Tests

```bash
cd backend && . .venv/bin/activate && pytest -q       # 139 tests; needs the flowqr_test database above + Postgres running
cd frontend && npx tsc --noEmit && npm run build      # typecheck + production build
```

Backend tests rebuild the schema from the real migrations, then cover auth, CSRF, rate limiting, tenant isolation (HTTP **and** raw SQL under RLS), card generation/assignment/redirects, QR decode round-trip (via OpenCV), public AI assistant guardrails, Google OAuth/state validation, token encryption, review sync (idempotency, backoff, rate-limit, revocation), reply approval workflow, and analytics.

### End-to-end smoke test (browser)

With API and frontend running and `PLATFORM_ADMIN_EMAILS=admin@flowhq-dev.example.com` set:

```bash
npm i --no-save playwright && npx playwright install chromium   # one-time
node e2e/smoke.js     # registers a business, onboards, assigns a card, opens the public mobile page, screenshots to e2e/shots/
node e2e/qr-and-access.js   # QR design/export, pause/resume, destination edits, old codes staying alive, staff location access, Google states (needs the running docker stack; creates and removes a ZZ-E2E business)
```

## Key product rules (enforced in code)

- Every card has its own unguessable token (`secrets.token_urlsafe(18)`, 144 bits) and a printed code (`FQR-0001`). QR and NFC share the same permanent URL; the **Google review link behind it is editable** without replacing a card.
- The public page never auto-posts, never asks for or filters by rating, never routes unhappy customers elsewhere; AI output is labelled and editable; the AI is instructed to preserve meaning and outputs that balloon in length are rejected.
- Replies always need a human to approve. Flagged reviews (medical, legal, threat, accusation) need an explicit acknowledgement. A reply is shown as **published only after Google confirms**.
- Billing: Razorpay subscriptions (₹399 / ₹799 / ₹1,499, configurable trial). Paid status comes only from Razorpay (signature-verified + confirmed via API/webhook). Physical-card purchases are a separate payment kind.
- Analytics keep *scans*, *landing visits*, *clicks to Google* and *synced reviews* separate; a click is never counted as a review.

## Documentation

[Architecture](docs/ARCHITECTURE.md) · [Database](docs/DATABASE.md) · [API reference](docs/API.md) · [Deployment](docs/DEPLOYMENT.md) · [Security checklist](docs/SECURITY.md) · [Implementation checklist](docs/CHECKLIST.md) · [**Staging readiness**](docs/STAGING_READINESS.md) · [Google setup & approval](docs/GOOGLE_SETUP.md)

---
FlowQR is a product of FlowHQ and is not affiliated with, endorsed by, or sponsored by Google. Google and Google Business Profile are trademarks of Google LLC.
