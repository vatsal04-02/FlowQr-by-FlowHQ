# Phase 2 audit: starting point (Milestone 0)

Written 2026-11-15 on branch `phase-2/commercial-readiness`. Method: read the code and the existing docs, run the suites, change nothing before this was written. **Depth is stated per area** so nothing here reads as more verified than it is.

## 0. Git state (read this first)

* Branch before Phase 2: `feature/growth-platform`, HEAD `1118cd7`.
* **Phases 0, 1 and 1.5 were never committed.** The working tree carries 349 changed or new files on top of `1118cd7` (migrations 0018 to 0028, the whole autonomy engine, the control centre, the docs). There is no "Phase 1.5 checkpoint" commit to branch from. `phase-2/commercial-readiness` was created from the working tree (`git switch -c`), which keeps every uncommitted file exactly as it was. **Nothing has been committed, pushed, stashed or discarded.** Recommended before more work lands: you commit Phase 0 to 1.5 as one checkpoint on this branch so Phase 2 diffs are reviewable.
* The running local stack (`flowqr-*` containers) still runs old code. It has not been migrated and was not touched.

## 1. Baseline results (before any Phase 2 change)

These were run in the previous working session on this same tree (no file changed between that run and the branch switch). They were **not** re-run in this step; the full backend suite is re-run after each milestone below.

| Check | Result |
|---|---|
| Backend: pytest in Docker, fresh PostgreSQL 16, migrations from scratch to 0028, Google/Places/AI as test doubles | **1267 passed, 0 failed** |
| Frontend `tsc --noEmit` | passes |
| Frontend production build (`next build` in the Docker image) | passes (one earlier attempt failed on a transient Google Fonts fetch) |
| Browser: `e2e/autonomy-control-centre.js` | 13/13 (seeded data, no Google calls) |
| Browser: `e2e/agent-and-posts.js` | 31/31 (two stale expectations updated in Phase 1.5) |
| CI | **none**: no `.github`, no pipeline file. Tests run only by hand. |
| Live Google, read-only | one dated PASS (`docs/LAUNCH_REPORT.md`) |
| Live Google writes, live Places scans | **never run** |

## 2. Architecture as found

FastAPI (`backend/app/api/v1/*`) over SQLAlchemy 2 and Alembic; PostgreSQL 16 with row-level security (default deny, `app.tenant_id` / `app.bypass_rls`, forced RLS, a non-superuser app role); Redis; Celery worker and beat (`workers/tasks.py`, schedule in `workers/celery_app.py`); Next.js frontend; Caddy in production compose; Docker Compose files (`docker-compose.yml`, `.prod.yml`, `.local-tls.yml`, `.mail-sink.yml`). AI through Gemini behind a metered wrapper (`services/ai_usage.py`, ledger `ai_call_ledger`). Google Business Profile through `services/google/provider.py`; Places through `services/rank.py` and `services/rank_grid.py`. Autonomy engine: `services/agent/{autonomy_policy,executor,content_exec,history,learning,retention}.py`. Migrations: 0001 to 0028, sequential.

## 3. Status by area

| Area | Status | Evidence / depth |
|---|---|---|
| Auth, sessions, CSRF, roles, RLS tenancy | **Complete, tested** | `docs/SECURITY_AUDIT.md` (two rounds), `tests/test_security_audit.py`; I did not re-audit beyond running tests |
| Billing plumbing | **Partly complete** | Razorpay client behind an interface, checkout, verify, cancel, change-plan, payments list, card orders, signed and idempotent webhook (`webhook_events.event_id` unique), `refresh_statuses` housekeeping. Read in full: `services/billing.py`, `models/billing.py`, API list. Not exercised against real Razorpay (staging report: hosts blocked) |
| Plan catalogue | **Does not match the confirmed commercial plans** | seeded: Essential ₹399, Growth ₹799, Multi ₹1,499 (`0004`), not Starter ₹499 / Growth ₹799 / Pro ₹1,499 |
| Quotas | **Gap** | one combined counter `monthly_ai_generations` counts every AI call of every kind (`ai_usage.usage_this_month`). The commercial plan needs **separate** review-generation and reply allowances |
| Feature gating | **Partial** | `require_feature` on many routes with keys `review_sync, ai_replies, gbp_info, gbp_posts, gbp_media, gbp_performance, insights`. No keys for optimizer, growth agent, autonomy, geo-ranking, keyword tracking, multi-location. Autonomy and agent currently gate on `gbp_info` (which Starter has) |
| Subscription lifecycle | **Partial** | statuses trialing, active, past_due, halted, expired, canceled, pending; grace days; no **history** table; no refund handling beyond marking a payment refunded; no promotional-access concept |
| Card purchase | **Gap** | price is `quantity x CARD_PRICE_PAISE`, not the ₹800 (1 card) / ₹1,000 (2 cards) bundles; a card payment grants nothing; no promotional Growth month |
| AI cost ledger | **Complete for AI** | `ai_call_ledger`: tokens, model, kind, tenant, cost, status; budgets per business and platform; fails closed without prices. Missing: location, actor, request id, retry count, cached tokens, feature |
| Google / Places usage accounting | **Gap** | Places: only counts (`rank_checks`, `rank_grid_points`); no unified ledger, no price table, no refused-operation log, no Google Business API call accounting |
| Cost / margin / revenue dashboard | **Gap** | admin has AI usage and payments lists only (`admin.py`); no MRR, no margin |
| Autonomy engine | **Complete, mocked only** | Phases 1 and 1.5; **no live write ever run** |
| Retention / deletion | **Built, provisional** | `docs/DATA_RETENTION.md`; periods are settings; not legally approved |
| Operations | **Present** | `/admin/ops`, `ops_watch`, Sentry wiring (needs DSN), backups with encrypted off-site copy and a proven restore (`deploy/*.sh`, `docs/PRODUCTION_READINESS.md`) |
| Staging process | **Present, older** | `deploy/staging/*`, `docs/STAGING_READINESS.md` (2026-11-01, migrations to 0024-era). Not updated for 0026 to 0028 |
| Deployment docs | **Fragmented** | `DEPLOYMENT.md`, `PRODUCTION_READINESS.md`, `STAGING_READINESS.md`; the five documents requested in Milestone 5 do not exist |
| Onboarding | **Basic** | `/onboarding` (177 lines): business setup; no plan or promotion step, no first-campaign step, no progress save |
| Admin | **Partial** | tenants, subscriptions, payments, card orders and inventory, AI usage, audit, stats, ops. No budgets editor, no plan-limit view, no Places usage, no finance view |

## 4. Security observations (not a re-audit)

1. **No CI**: nothing stops a regression from merging. (Medium)
2. **Quota bypass by kind**: the combined counter would let one AI feature starve another; with separate allowances the enforcement must be at the backend call sites, not the UI (being fixed in M1).
3. **Plan features do not gate the autonomy engine** by plan; a Starter tenant that reaches the autonomy API is only stopped by `gbp_info` (being fixed in M1).
4. Payment-event idempotency exists for webhooks, but `payment.refunded` / `refund.*` events are not processed (M1).
5. Everything in `docs/SECURITY_AUDIT.md` still stands; open accepted items there are unchanged.

## 5. External dependencies and owner decisions (unchanged, none provided)

Authorised Google test profile; Places key and prices; **final** map allowances (the 150/400/2000 numbers in `config.py` are Phase 1.5 placeholders, to be made fail-closed in M1); legal review of retention; approval to migrate the running stack; verified payment provider (Razorpay is wired but unverified live; no claim is made here that it is the right provider; compare current fees, India subscription (e-mandate) support and webhook guarantees before committing).

New owner decisions Phase 2 surfaces (each defaults to the safest reading and is listed in the completion report): when the card's free Growth month starts (default: at payment); whether a second card order earns a second free month (default: no, one per business); Growth multi-location "no by default" (default: 1 location) and the Pro location cap (default: 10, carried from the old Multi plan); which features Starter keeps beyond the listed ones (default: manual profile editing stays, posts and photos move to Growth).

## 6. Plan

| # | Milestone | This session | Notes |
|---|---|---|---|
| 0 | Audit and baseline | **done** (this file) | |
| 1 | Plans, entitlements, lifecycle, promo, card bundles, webhooks | **implement** | migration 0029 |
| 2 | Unified usage and cost ledger, price tables, budgets, cost dashboard | **implement** | migration 0030 |
| 8 | Revenue and unit-economics metrics | **implement (backend + admin API)** | actual / estimated / missing |
| 3 | Security | targeted: tenant-isolation tests for new endpoints, plan gating of autonomy, CI | no re-audit of old areas |
| 4 | Real Google/Places validation | **blocked** on credentials; add release-gate status model | no claim |
| 5 | Deployment docs | write the five documents from the real repo files | migration to the running stack not performed |
| 6 | Onboarding / dashboard | as far as time allows; reported honestly | |
| 7 | Admin | extend with plan limits, budgets, usage, finance | |

Anything not finished is listed as not done in `docs/PHASE_2_COMPLETION_REPORT.md`.
