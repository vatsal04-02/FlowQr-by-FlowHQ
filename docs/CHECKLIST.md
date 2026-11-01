# Implementation & verification status

Legend: **PASS** = executed and passed here · **BLOCKED** = needs credentials/infrastructure unavailable in the build sandbox · **NOT TESTED** = built, never executed · **NOT BUILT**.

## Automated results (this repository, this session)
| Check | Result |
|---|---|
| Backend tests (pytest, real PostgreSQL 16 + migrations from scratch) | **PASS** 139/139 |
| Tenant isolation (HTTP, all major resources) + PostgreSQL RLS raw-SQL tests | **PASS** |
| QR decode round-trip (OpenCV decodes PNG → exact card URL) | **PASS** |
| Public redirect / card resolution / fallbacks / rate limit / bot filter | **PASS** |
| Auth: Argon2id, sessions, CSRF, rate limits, reset, **email verification** | **PASS** |
| Billing: signature checks, webhook validation + idempotency, out-of-order, failed payment/grace, cancel, upgrade/downgrade, limits, trial expiry, card orders (fake Razorpay, real HMACs) | **PASS** |
| GBP management, sentiment/topics, platform admin API, auto-retry task | **PASS** |
| Frontend `tsc --noEmit` | **PASS** |
| Frontend production build (29 routes) | **PASS** |
| Browser E2E (Playwright, desktop + 390 px mobile): register → verify email → onboarding → assign card → public page → pricing/subscription/payments/analytics/profile → suspension → admin console → access denial for business users | **PASS** (`e2e/smoke.js`) |
| Live Celery worker consumed `billing_refresh`, `retry_failed_replies`, `sync_due_locations` from Redis | **PASS** |
| `docker compose config` (base + prod overlay) | **PASS** |
| Staging readiness (isolated stack, real SMTP *protocol* vs sink, config guard, card-URL audit, dependency audit) | See [STAGING_READINESS.md](STAGING_READINESS.md) |
| `caddy validate` of `deploy/Caddyfile` (real Caddy 2.8.4 binary) | **PASS** |
| Docker image builds / full `docker compose up` (8 services healthy, persistence, crash recovery, Caddy 4-domain routing) | **PASS**: see [STAGING_READINESS.md](STAGING_READINESS.md) |
| Backup/restore with real data (14-table checksum snapshot identical) | **PASS** (same-host; off-site/other-cluster restore NOT TESTED) |

## External services (never called for real)
| Integration | Status |
|---|---|
| Google OAuth + Business Profile (reviews, replies, info, hours, categories, posts, media, performance) | **BLOCKED**: needs OAuth client **and** Google-approved API access. Logic verified with a labelled fake; HTTP shapes follow Google's documented v1/v4 APIs and may need small adjustments on first contact. UI shows "Configuration pending" without credentials. |
| Gemini (review assist + reply drafts) | **BLOCKED**: needs `GEMINI_API_KEY`. Without it the public page honestly says writing help is unavailable. |
| Razorpay (subscriptions, orders, webhooks) | **BLOCKED**: needs test keys + webhook secret. Without keys the UI shows "configuration pending"; no payment is ever simulated. |
| SMTP email | **NOT TESTED** against a real server (the sender is used in tests via an in-memory outbox). |
| NFC tag writing | **NOT TESTED** (the card URL is plain NDEF text/URL; no hardware). |

## Feature status
| Area | Status |
|---|---|
| Auth, onboarding, roles, staff invites, password reset, email verification, audit logs | Built |
| Multi-tenant isolation (API + PostgreSQL RLS) | Built, tested |
| Cards: batches, unique tokens, QR PNG/SVG, ZIP, print sheet, assign/reassign/deactivate/lost, per-card analytics | Built, tested |
| Public mobile review page, EN/HI/Hinglish, no gating/auto-post | Built, tested (AI via stub) |
| Google OAuth, sync, duplicate detection, backoff/quota handling, AI replies, approval, publish, history, retry | Built, tested (fake provider) |
| GBP management: info, description, hours, categories, posts, media, performance | Built, tested (fake provider) |
| Analytics: reviews, trends, reply coverage, pending, scans/visits/clicks, locations, cards, AI usage, sentiment & topics | Built, tested |
| Billing: plans ₹399/₹799/₹1,499, trial, checkout, verify, webhooks, renewal/failed payment handling, cancel, change plan, limits, payment history, admin override | Built, tested (fake Razorpay) |
| Physical card orders (separate from subscriptions) + admin fulfilment | Built, tested |
| Platform admin console (customers, suspension, support status, subscriptions, payments, card inventory/batches/assignments, AI usage, platform stats, audit) | Built, tested |
| Deployment: Dockerfiles, compose (+prod), Caddy (4 hosts), health checks, backup/restore, `.env.example` | Built; images unbuilt |

## Known limitations / next
1. Staging deploy with Docker and real domains; first-contact adjustments for Google, Gemini and Razorpay with real credentials.
2. GST invoices/tax handling, refunds UI, dunning emails, MFA, privacy policy/terms pages (needed for Google OAuth verification).
3. Card self-activation (claim code), data-retention job for `scan_events`.
4. Frontend component tests and CI pipeline.
5. Google push notifications for new reviews (polling only today).
