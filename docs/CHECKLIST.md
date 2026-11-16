# Implementation & verification status

Legend: **PASS** = executed and passed here · **BLOCKED** = needs credentials/infrastructure unavailable in the build sandbox · **NOT TESTED** = built, never executed · **NOT BUILT**.

## Latest verification pass (2026-11-10, local Docker stack)
| Check | Result |
|---|---|
| Backend tests (pytest, PostgreSQL 16, migrations rebuilt from scratch) | **PASS** 729/729 |
| Migrations 0012-0015: fresh database, upgrade with existing data, downgrade, re-upgrade, model drift (temporary script, removed after the run) | **PASS** 28/28 checks |
| Frontend `tsc --noEmit` and production build (incl. the new `/qr` page) | **PASS** |
| Browser E2E `e2e/qr-and-access.js` (Chromium): Google connect redirect and connection states, QR design, logo upload, PNG/SVG/PDF downloads, bulk export, card pause/resume, destination editing, new code + old code alive, typed-word deactivation, staff location assignment, location-deactivation warning | **PASS** 23/23 |
| Live checks through the Next.js proxy against the running API (temporary script) | **PASS** 35/35 |
| Docker: `db`, `redis`, `api`, `worker`, `beat`, `frontend` healthy on schema 0015; existing local data unchanged | **PASS** |
| Celery worker ran `sync_due_locations`, `retry_failed_replies`, `purge_review_sessions`, `billing_refresh`; beat running | **PASS** |
| QR files read back by two independent decoders (ZXing, OpenCV ArUco) in PNG, SVG and PDF | **PASS** (rendered files only; see [QR_RELIABILITY.md](QR_RELIABILITY.md)) |
| Google contract tests (mocked HTTP transport, no network) | **PASS**; prove the code matches Google's documentation, nothing more |
| Google live: OAuth refresh-token exchange | **PASS** |
| Google live: any Business Profile read or write | **BLOCKED**: all four APIs return HTTP 403 `SERVICE_DISABLED` on the Cloud project ([GOOGLE_API_AUDIT.md](GOOGLE_API_AUDIT.md)) |
| `e2e/smoke.js` (older browser smoke test) | **NOT RE-RUN** in this pass |
| QR codes on printed paper / physical phones | **NOT TESTED** |

## Automated results (earlier sessions)
| Check | Result |
|---|---|
| Backend tests (pytest, real PostgreSQL 16 + migrations from scratch) | **PASS** 139/139 |
| Tenant isolation (HTTP, all major resources) + PostgreSQL RLS raw-SQL tests | **PASS** |
| QR decode round-trip (ZXing and OpenCV ArUco decode PNG → exact card URL) | **PASS** |
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
| Google OAuth | Real client configured locally; token refresh **verified live** 2026-11-10. Browser consent flow not re-tested in this pass. |
| Google Business Profile (reviews, replies, info, hours, categories, posts, media, performance) | **BLOCKED**: the four APIs are not enabled on the Cloud project (live HTTP 403 `SERVICE_DISABLED`), and Google's access approval is unknown until they are. Request/response shapes audited against Google's reference and pinned by mocked contract tests. **No successful read or write has ever been made.** Steps: [GOOGLE_SETUP.md](GOOGLE_SETUP.md). |
| Gemini (review assist + reply drafts) | **BLOCKED**: needs `GEMINI_API_KEY`. Without it the public page honestly says writing help is unavailable. |
| Razorpay (subscriptions, orders, webhooks) | **BLOCKED**: needs test keys + webhook secret. Without keys the UI shows "configuration pending"; no payment is ever simulated. |
| SMTP email | **NOT TESTED** against a real server (the sender is used in tests via an in-memory outbox). |
| NFC tag writing | **NOT TESTED** (the card URL is plain NDEF text/URL; no hardware). |

## Feature status
| Area | Status |
|---|---|
| Auth, onboarding, roles, staff invites, password reset, email verification, audit logs | Built |
| Multi-tenant isolation (API + PostgreSQL RLS) | Built, tested |
| Cards: batches, unique tokens, QR PNG/SVG/PDF, ZIP, print sheet, assign/reassign/pause/resume/deactivate/lost, per-card analytics incl. unique scans | Built, tested |
| QR design (colours, logo, caption, size, margin, error correction) with decode check; tenant bulk export | Built, tested |
| QR permanence: editable destinations, earlier campaign codes stay alive as aliases, explicit typed-word deactivation, confirmation before deactivating a location with live codes | Built, tested (backend + browser) |
| Location-level permissions for staff (API, analytics, background reply retry) + assignment UI | Built, tested (backend + browser) |
| Public mobile review page, EN/HI/Hinglish, no gating/auto-post | Built, tested (AI via stub) |
| Google OAuth, sync, duplicate detection, backoff/quota handling, AI replies, approval, publish, history, retry; rejected-reply handling; distinct "API disabled" / "awaiting approval" / "reconnect" states | Built, tested (fake provider and mocked HTTP) |
| GBP management: info, description, hours, categories, posts, media, performance | Built, tested (fake provider) |
| Analytics: reviews, trends, reply coverage, pending, scans/visits/clicks, locations, cards, AI usage, sentiment & topics | Built, tested |
| Billing: plans ₹399/₹799/₹1,499, trial, checkout, verify, webhooks, renewal/failed payment handling, cancel, change plan, limits, payment history, admin override | Built, tested (fake Razorpay) |
| Physical card orders (separate from subscriptions) + admin fulfilment | Built, tested |
| Platform admin console (customers, suspension, support status, subscriptions, payments, card inventory/batches/assignments, AI usage, platform stats, audit) | Built, tested |
| Deployment: Dockerfiles, compose (+prod), Caddy (4 hosts), health checks, backup/restore, `.env.example` | Built; images unbuilt |

## Known limitations / next
0. **Manual steps before Google can be called working:** enable the four APIs in Cloud Console, submit/confirm the Business Profile API access request, run `python -m app.cli google-smoke --connection <id>`, then do the first reply, post and profile edit by hand on a test location. Press **Re-check** on the Google connection page to refresh the stored state of the existing local connection.
0. Print a QR test sheet and scan it with real phones; decide whether the default code colour should become pure black (see QR_RELIABILITY.md, section 3).
0. Run `e2e/smoke.js` again; it was not part of this pass.
1. Staging deploy with Docker and real domains; first-contact adjustments for Google, Gemini and Razorpay with real credentials.
2. GST invoices/tax handling, refunds UI, dunning emails, MFA, privacy policy/terms pages (needed for Google OAuth verification).
3. Card self-activation (claim code), data-retention job for `scan_events`.
4. Frontend component tests and CI pipeline.
5. Google push notifications for new reviews (polling only today).
