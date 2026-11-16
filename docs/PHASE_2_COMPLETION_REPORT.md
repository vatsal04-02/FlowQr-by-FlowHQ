# Phase 2 completion report

Branch `phase-2/commercial-readiness`, 2026-11-15. Starting point and method: `docs/PHASE_2_AUDIT.md`.

## Final release status

**Development Complete — External Validation Pending.**

Not "Staging Validated" (a local staging passed its checks on 2026-11-15, see the addendum, but no staging exists on a real host with real integrations) and not "Production Ready" (no live Google write, no live Places scan and no live payment has ever been performed, and several owner decisions are open). The same status is on `GET /admin/release-gates` (`backend/app/release_gates.json`), where each rung can only be marked passed with a date and evidence.

## Addendum, 2026-11-15: completion pass

Done after the report above was first written. The acceptance decision is in **`docs/PHASE_2_FINAL_ACCEPTANCE.md`** (Phase 2 not accepted; Phase 3 not started; external blockers listed). In short:

* **Checkpoint.** All Phases 0 to 2 work (393 uncommitted entries) is committed on `phase-2/commercial-readiness` in reviewable commits, tagged `phase-2-checkpoint`, nothing pushed (`docs/PHASE_2_CHECKPOINT.md`). Several statements above said work was "uncommitted"; that is no longer true.
* **Security audit** (`docs/PHASE_2_SECURITY_AUDIT.md`): replaces "Partly. Targeted work, not a re-audit" for Milestone 3 with an internal audit of all areas. One **High** finding fixed: a sign-up with an administrator address became an administrator without verifying the mailbox. Also fixed: 14-day administrator sessions, OAuth codes in access logs. Three systematic controls added (route access manifest, role sweep, database sweep).
* **Staging.** A local staging stack was built and tested (HTTPS through Caddy's internal CA, production overlay, strict guard). It found **two defects the unit suite could not**: the marketing host redirected every marketing page but two to the app domain and could not call its own API (pricing page would have shown "Talk to us for pricing"), and canonical links, sitemap and social cards would have used `localhost` (`NEXT_PUBLIC_SITE_URL` was never passed to the build). Both fixed.
* **Migration and restore rehearsal.** 0025 to 0030 on a restored copy of the real development database (row counts of all 47 existing tables preserved), downgrade and re-upgrade, services boot; staging backup restored into an isolated database with identical checksums (`docs/evidence/phase2/`). Milestone 5's "nothing rehearsed" is superseded for everything that can be done on one machine.
* **Milestones 6 and 7** (see the table below, which still shows the earlier result): now also a **four-step onboarding wizard** with real plan and trial data and first-review-page creation, **one** getting-started checklist (the older duplicate for new accounts was removed), admin **Work queue**, per-business **spending ceilings** (the API existed; there was no screen, although Finance said there was), and the **platform emergency stop** button (the API existed; there was no screen).
* **Commercial inputs** (`docs/COMMERCIAL_LIMITS_AND_COSTS.md`): the number of search terms per location was a hardcoded constant and most Places controls were not passed through Docker Compose, so the environment variables the documentation described did nothing; both fixed. The payment provider decision (Cashfree, deferred) is recorded; the customer-facing billing text and the privacy page no longer name Razorpay.
* **Corrections to the table of "Known issues" below:** the Razorpay plan-id problem for existing subscribers is moot until a provider is integrated; "rebuilt onboarding wizard", "admin views for failed Google actions, pending approvals, data export and deletion status" are done.
* **Tests.** Backend ****1368 passed, 0 failed** (1343 before this pass; 25 added)**; new browser suite 18/18 on staging; existing suites on the demo stack: **`phase2-commercial` 11/11, `autonomy-control-centre` 13/13, `agent-and-posts` 31/31, `google-business-agent` 10/10; **`card-inventory` 15/16 and `qr-and-access` 22/23 have one failing step each**: both steps open pre-restructure URLs (`/cards`, `/google?error=...`) and are believed to be stale tests, **not verified against the old code**, so treat them as open; `ops.js` could not start here (no bundled Chromium) and was not run. Four legacy suites also needed a location-cap seed after the plan change (done)**.
* **Still true and still blocking:** no live Google write, no live Places scan, no live payment, no real staging host, CI never run, owner decisions open.

## Scope: what was and was not done

Milestones were done in the order that protects the product. Honest per-milestone result:

| # | Milestone | Result |
|---|---|---|
| 0 | Audit and baseline | **Done.** `docs/PHASE_2_AUDIT.md`. Baseline was the Phase 1.5 suite (1267 passed) |
| 1 | Plans, entitlements, lifecycle, promo, bundles, refunds | **Done** (mocked): see below |
| 2 | Usage, cost and budget management | **Done** (mocked): see below |
| 3 | Security | **Partly.** Targeted work and checks, **not a re-audit** (details below) |
| 4 | Real Google and Places validation | **Blocked** (no credentials or test profile). Release-gate record and a status model added; the command and runbook from Phase 1.5 are unchanged and **still only ever run against a test double** |
| 5 | Deployment and DevOps | **Documents written from the real repo; nothing deployed or rehearsed.** Readiness endpoint and CI workflow added (**the workflow has never run**) |
| 6 | Onboarding and dashboard | **Partly.** Getting-started checklist from real data, Google-permission explanation, plan/free-month/allowance display. **Not done:** a rebuilt multi-step onboarding wizard, a dashboard redesign, saved onboarding drafts |
| 7 | Operations and administration | **Partly.** Plans and limits, Finance and usage, budgets, release ladder. **Not done:** admin views for failed Google actions, pending approvals, data export and deletion status, and support playbooks as UI (the existing Operations page covers jobs, health and Google status) |
| 8 | Commercial and financial visibility | **Done** (backend and admin UI), with missing inputs shown as missing |

## What was implemented

**Plans and entitlements.** Starter ₹499, Growth ₹799, Pro ₹1,499 exactly as confirmed (`services/plans.py` is the specification, `billing_plans` is what runs, a test compares them). Review generations and AI replies are **separate allowances** (200/200, 400/400, 800/800; a plan with 400 and 400 has 800 operations), counted from successful generations only, enforced at every backend call site (`ai_usage.quota_exceeded(db, tenant, kind)`). Posts, descriptions, the growth agent and the safety read draw on neither allowance: they follow their plan feature and the USD budgets. Every paid area is a feature key checked by routes, scheduled jobs and the autonomy executor: `keyword_tracking`, `geo_ranking`, `autonomy`, `growth_agent`, `profile_optimizer`, `gbp_posts`, `multi_location`, and so on. A standing authorisation is only honoured while the plan includes `autonomy`; a change a named person approved still runs after a downgrade. Downgrading or cancelling removes access, never data (tested). The old Essential and Multi plans are retired but kept for existing subscribers; existing subscriptions were grandfathered (limits not reduced, old combined allowance split in half).

**Map allowances: fail closed.** The 150/400/2000 searches and the grid and point limits are **no longer in code**. Every plan ships with them unset, and maps stay off (`reason: not_configured`, a 402 explaining the allowances "have not been set yet") until a platform admin sets all three numbers in **Admin > Plans and limits** (audited, with a note, optionally applied to existing subscribers). A half-configured plan is an unconfigured plan.

**Lifecycle and history.** `subscription_events` (append-only) records trial, activation, renewal, plan change, scheduled plan change, failed payment, past-due, cancel request, cancellation, expiry, refund, promotional grant/end/revocation and admin overrides, with source and reference. `GET /billing/subscription/history` for owners and admins.

**Cards and the free month.** The two bundles are priced as bundles (1 card ₹800, 2 cards ₹1,000), recorded as **one-time revenue**. A paid card order creates a `promotional_grants` row: one month of Growth as free access layered on the entitlements at read time (the subscription row is untouched), never counted as MRR, ended by a daily job, revoked if the card payment is refunded, idempotent across duplicate payment events, one per business by default. Choosing a plan during the free month schedules the first charge for the day it ends and only on the customer's own explicit checkout; nothing is charged automatically.

**Payments.** The existing signed, idempotent Razorpay webhook handler now also processes refunds (partial and full, idempotent per refund id); a refund never cancels a subscription by itself. No provider was chosen or changed.

**Usage and cost.** `api_usage_ledger` (migration 0030) records every Google Places search (one row per map point, not per scan) and every Business Profile write the engine makes, with the operation, feature, units, status ok/error/refused and an idempotency key so a retry cannot count twice. Prices come from `API_PRICES` (empty by default); **an unpriced call is stored with a NULL cost and `priced=false`, counted and flagged, never recorded as free**. The AI ledger gained location, actor, request id, retry count, cached tokens and feature. Refusals (plan allowance, platform cap, a business ceiling) are recorded in their own transaction. An admin can set a per-business Places ceiling and AI dollar budget (`PUT /admin/tenants/{id}/budgets`, audited). **Admin > Finance and usage** shows spend by feature, operation and business, failed and refused calls, and says how many calls had no price.

**Finance.** MRR counts only active subscriptions paid through the provider at list price; trials, the free card month and comped subscriptions are shown separately; card revenue is one-time and never in MRR/ARR; each figure is labelled actual, estimated or missing; **a margin is shown only when every variable-cost input exists** (otherwise the page lists what is missing, never a partial sum as if complete); lifetime value is "missing" until churn is actually observed. Card manufacturing cost (about ₹75 per card) is carried as a **provisional** input and labelled so.

**Onboarding and experience.** A "Getting started" checklist on the overview, computed only from real records (location, review link, Google connection with a chosen location, campaign, assigned card, plan or free period, notification choice, autonomy), with optional steps marked, plan-locked steps showing which plan adds them, and a path for a business with no Google profile. The onboarding Google step now explains in plain language what connecting allows and that signing in with Google is separate. The plan page shows the two allowances, the free month and the history; the card order dialog shows the two packs.

**Operations.** `GET /api/ready` (database, Redis and migration revision; statuses only; deliberately independent of the worker). A CI workflow (`.github/workflows/ci.yml`). Five deployment documents and an environment-variable reference.

**Security work done** (Milestone 3, targeted): plan gating moved from the UI to the backend for every Growth feature (a Starter business cannot reach them through the API: tested route by route); standing autonomy authorisation requires the plan feature at proposal and at execution; tenant-isolation tests for everything new (billing history, promotional grants, usage ledger, card orders, plan data, release record); admin-only checks; the new ledgers are append-only for the application role; a grep review found no token or secret logged, OAuth state is signed and nonce-bound to the browser, no key-shaped string or env file is tracked, and the browser bundle receives no secret. **Not done:** a fresh penetration-style audit of authentication, sessions, rate limits and OAuth refresh handling (`docs/SECURITY_AUDIT.md` from earlier phases still stands; I did not re-run it beyond the existing tests).

## Migrations created

* `0029_commercial_plans`: plan allowances and limits columns, Starter/Pro rows, retired plans, grandfathering of existing subscriptions, `subscription_events`, `promotional_grants`, `card_orders.offer_code`.
* `0030_usage_ledger`: `api_usage_ledger`, AI ledger columns, `tenants.places_monthly_cap`.

Both were applied from scratch by the test suite and to an empty isolated demo stack (head `0030`). **Neither has been applied to a database holding real data, and the running local stack was not migrated.** Reversing 0029 or 0030 deletes data by design (`docs/ROLLBACK_AND_RECOVERY.md` §3).

## Tests run, with actual results

| Check | Result |
|---|---|
| Backend, full regression, fresh PostgreSQL 16, migrations from scratch (Google, Places, Razorpay, AI are test doubles) | **1343 passed, 0 failed** (Phase 1.5 baseline was 1267). An earlier run during this phase failed one test, the security audit's "every non-public route refuses anonymous requests", because of the new public `/api/ready` endpoint; I added it to that test's reviewed allowlist with the reason written down and added a test pinning that it discloses only statuses |
| New Phase 2 backend tests | 74 in four files (plans and billing 33, usage and finance 19, ops/onboarding/isolation/readiness 18, autonomy plan 4 incl. one for Business Profile usage rows); the rest of the increase over 1267 is the migrated existing tests |
| Existing tests changed on purpose | the retired plan codes became Starter/Pro; the trial/Growth plan now includes ONE location so many test helpers raise only the test business's location cap (`make_business`); the shared AI allowance test now exercises the generations allowance; map-allowance tests set allowances on the plan like an admin does; `/api/ready` was added to the reviewed public-route allowlist with the reason written down. **No assertion about security, tenancy, approvals or authorisation was weakened.** One earlier test file left rows in the shared test database and broke an older test; fixed in my test |
| Frontend `tsc --noEmit` | passes |
| Frontend production build (`next build` inside the Docker image, three times during this phase) | passes; one earlier build failed once on a transient Google Fonts fetch in an earlier phase, and not again |
| Browser `e2e/phase2-commercial.js` (new) | **11/11** (plans, allowances, free month, history, Starter gate, getting started, Google explanation, admin Plans, Release status, Finance) |
| Browser `e2e/autonomy-control-centre.js` | **13/13** (seed updated: the test business is given approved map allowances; usage rows renamed) |
| Browser `e2e/agent-and-posts.js` | **31/31** (seed updated: the test business is given a higher location cap) |

All browser tests run against an **isolated demo stack** with seeded data and no Google, Places or Razorpay call. They prove the screens and server rules, not the services.

## Verified with test doubles / against real services / not tested

| | |
|---|---|
| **Verified with doubles** | everything above: plan rules, quotas, gating, history, promo, refunds, usage ledger, budgets, finance arithmetic, onboarding, readiness, isolation; the Phase 1 and 1.5 autonomy engine (policy, approvals, execution, read-back, history, retention, maps, governed publishing) |
| **Verified against real APIs** | only the read-only live Google check recorded in `docs/LAUNCH_REPORT.md` (earlier phase). **Nothing in Phase 2 was verified against a real API.** Razorpay was never contacted |
| **Not tested at all** | real Google writes (profile, posts, photos, replies), real Places scans and their real cost, real Razorpay checkout, subscriptions, refunds and webhooks, real SMTP, a migration over real data, a restore from a production backup, the CI workflow, rollback, behaviour under load |

## Known issues and limitations

1. **Nothing external has been validated**; see the release ladder.
2. Several numbers are **my assumptions** until the owner decides: Growth includes **one** location ("No by default" for multi-location), Pro allows **ten** (carried from the old Multi plan), staff seats 3/10/50 carried over, Starter keeps manual profile editing while Posts and Photos start at Growth, "one month" is 30 days, and a second card order does **not** earn a second free month.
3. The Razorpay-side plan objects are created lazily on first checkout with the new prices; **existing Razorpay plan ids for Essential/Multi continue to bill the old amounts** for existing subscribers until moved. No migration of live Razorpay subscriptions was designed or run.
4. Finance figures are only as good as the inputs: no hosting, support, fee, card-cost or marketing figure is configured, so no margin, CAC or LTV can be shown yet. API prices are unset, so cost totals show $0 with unpriced counts.
5. Onboarding is a checklist, not a rewritten wizard; no saved onboarding drafts; no duplicate-business/location detection beyond what existed; Google "multiple locations" and "account already connected" paths use the existing connection screens.
6. Admin views for failed Google actions, approvals, export/deletion status and support playbooks were not built.
7. Quotas count generation logs in the application database, not a transactional counter: two simultaneous requests can both pass at the boundary by one operation (the AI USD budgets have the same property, documented earlier).
8. `.github/workflows/ci.yml` has never run; the Postgres service role setup in it mirrors `db/init/01-app-role.sh` but is unverified.
9. The CI, staging and production documents describe procedures that were not rehearsed.
10. Two empty directories named `pytest.ini;C:` and `requirements-dev.txt;C:` (dated 12 Nov) sit in `backend/`; they pre-date this phase and are harmless.

## External dependencies and owner decisions

| Needed | Status |
|---|---|
| Authorised Google test Business Profile | not provided |
| Real Places API key and prices (`API_PRICES`) | not provided |
| Final map allowances (set in Admin > Plans and limits) | **not approved; maps are off until then** |
| Promo month length, one grant per business, location caps, seat limits, Starter feature set | assumed; need confirmation |
| Cost inputs: card unit and fulfilment cost, hosting, support, payment fee, marketing spend, USD/INR rate | not provided; finance shows missing |
| Legal review of retention periods and policy pages | not obtained |
| Approval and a plan to migrate the running stack and any real database (including moving live Razorpay subscribers to the new plan ids) | not provided |
| Payment provider: Razorpay is wired and untested live; whether it is the right provider (current India fees, subscription e-mandate support, webhook guarantees) was **not** validated | open |

## Deployment readiness

Procedures exist (`PRODUCTION_DEPLOYMENT.md`, `STAGING_DEPLOYMENT.md`, `DATABASE_BACKUP_RESTORE.md`, `ROLLBACK_AND_RECOVERY.md`, `ENVIRONMENT_VARIABLES.md`). Release gates 4, 7, 8, 9, 10 and 12 in `PRODUCTION_DEPLOYMENT.md` §2 are **not met**.

## Production blockers

1. Real Google validation (runbook stages 1 to 4) on an authorised test profile.
2. Real Places validation and measured costs, then `API_PRICES` and the platform cap set.
3. A staging environment on this code, upgraded from a restored copy of production-shaped data.
4. Razorpay end to end in test mode, then live; decision on migrating existing subscribers.
5. Owner decisions in the table above; legal review.
6. CI run green on GitHub; rollback rehearsed.

## Recommended next actions

1. Commit Phases 0 to 2 as a checkpoint on this branch (349 files were uncommitted when Phase 2 began).
2. Name a test Business Profile and run `docs/LIVE_VALIDATION_RUNBOOK.md`; fill in its evidence log and `backend/app/release_gates.json`.
3. Decide the map allowances and the open numbers; set them in Admin > Plans and limits.
4. Stand up staging from `STAGING_DEPLOYMENT.md` and rehearse a migration from a restored backup.
5. Then build what Phase 2 left: the onboarding wizard, the remaining admin views, a security re-audit of authentication and sessions.

## Files changed in Phase 2

**Backend added:** `alembic/versions/0029_commercial_plans.py`, `0030_usage_ledger.py`; `app/services/{plans,usage,finance,onboarding}.py`; `app/release_gates.json`; tests `test_phase2_plans.py`, `test_phase2_usage_and_finance.py`, `test_phase2_ops_and_isolation.py`, `test_phase2_autonomy_plan.py`.
**Backend modified:** `app/core/config.py`, `app/main.py`, `app/models/{__init__,billing,platform,tenancy}.py`, `app/schemas/{admin,billing}.py`, `app/services/{ai_usage,billing,entitlements,rank,rank_grid}.py`, `app/services/agent/{executor,content_exec,plan}.py`, `app/workers/tasks.py`, `app/api/v1/{admin,agent,autonomy_actions,billing,public,posts,rank,rank_grid,review_public,reviews,tenants,workspace}.py`; tests `conftest.py`, `test_admin.py`, `test_billing.py`, `test_config_guard.py`, `test_phase15_geogrid.py`, `test_public_ai.py`, `test_review_context.py`, `test_review_growth.py`, `test_security_audit.py`, `test_trial_expiry_safety.py`.
**Frontend added:** `app/(admin)/admin/{plans,finance}/page.tsx`, `components/overview/GettingStarted.tsx`. **Modified:** `lib/{plans,types,billing,autonomy}.ts`, `components/{PlanCards,AdminShell}.tsx`, `components/autonomy/PermissionsUsage.tsx`, `components/gbp/GeoGrid.tsx`, `app/onboarding/page.tsx`, `app/(app)/overview/page.tsx`, `app/(app)/settings/billing/{page,payments/page}.tsx`, `app/(admin)/admin/customers/[id]/page.tsx`.
**E2E:** `e2e/phase2-commercial.js` (new), `e2e/autonomy-control-centre.js`, `e2e/agent-and-posts.js`.
**Docs:** `PHASE_2_AUDIT.md`, `PHASE_2_COMPLETION_REPORT.md`, `PRODUCTION_DEPLOYMENT.md`, `STAGING_DEPLOYMENT.md`, `DATABASE_BACKUP_RESTORE.md`, `ROLLBACK_AND_RECOVERY.md`, `ENVIRONMENT_VARIABLES.md`, additions to `API.md`, `DATABASE.md`, `ARCHITECTURE.md`. **CI:** `.github/workflows/ci.yml`.
