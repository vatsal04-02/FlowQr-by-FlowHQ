# Phase 2 final acceptance (2026-11-15)

## Verdict

**Phase 2 is NOT accepted. Phase 3 has NOT been started.**

Every piece of Phase 2 work that could be finished without something only the owner can provide **is finished and tested**. What remains is blocked by external dependencies (an authorised Google test profile, a Places key and verified pricing, a real server and domain, a real SMTP provider, owner decisions on commercial numbers, a legal review). Those cannot be produced by building more code, and several of them are exactly the evidence the brief says may never be faked. Per the brief ("if an external dependency is unavailable, complete all independent work, document the blocker and STOP before Phase 3"), this is where work stops.

**Release status: Development Complete — External Validation Pending.** Not "Staging Validated" (a staging stack passed all its checks, but on one laptop with a private certificate authority, not on a real host, and with no real integration), and not "Production Ready" (gates 4, 7, 8, 9, 10, 12, 13, 14, 15 and 16 of `docs/PRODUCTION_DEPLOYMENT.md` are unmet). `backend/app/release_gates.json` was **not** edited: only a person does that, with dated evidence.

Statuses used: **PASS**, **FAIL**, **BLOCKED — external dependency**, **NOT APPLICABLE**. A test double never counts as a real integration result.

## 1. The seven items that need actual evidence (Part C)

| # | Item | Status | What exists, and what is missing |
|---|---|---|---|
| 1 | Google write validation | **BLOCKED — external dependency** | No authorised test Business Profile has been named. The runbook (`docs/LIVE_VALIDATION_RUNBOOK.md`), the dry-run-by-default `google-write-test` command, the three-act authorisation, the evidence log template and every double-based test are ready. **No live write, post, photo, reply, read-back, emergency-stop or retry run against Google has ever been performed; the evidence log is empty.** One read-only live check was recorded earlier (`docs/LAUNCH_REPORT.md`) |
| 2 | Real Places scan | **BLOCKED — external dependency** | No Places key may be used: the only key in the development environment was pasted into a chat and is marked for rotation (`SECURITY_AUDIT.md` finding 7), and staging must have its own key. No verified Places pricing (`API_PRICES` unset), no approved map allowances (maps are off by design). Quota, budget, failure and retry behaviour are tested **with doubles only**. No request was consumed and no cost was calculated from a real scan |
| 3 | Staging deployment | **split** | **3a. Local staging rehearsal: PASS.** Production overlay, `APP_ENV=staging` strict guard, own database, volumes and secrets, API + worker + beat + Redis + PostgreSQL + frontend + Caddy with HTTPS (internal CA), health and readiness, persistent volumes, logs scanned. 40 route and TLS checks, 33-step smoke, 18-step browser run. **3b. Staging on a real host with a real domain, real certificates, real SMTP and real monitoring: BLOCKED — external dependency** (no server, domain or DNS exists) |
| 4 | Complete security audit | **split** | **4a. Internal audit: PASS** (`docs/PHASE_2_SECURITY_AUDIT.md`): every area in the brief covered, 5 findings fixed with regression tests (one High), 5 accepted or owner decisions, three systematic controls added (route manifest, role sweep, database sweep). **4b. Independent penetration test of a deployed server and a second factor for administrators: BLOCKED — external dependency / owner decision.** The audit states that it is not an independent test |
| 5 | Migration upgrade and restore rehearsal | **PASS** with stated limits | 0025 to 0030 on a restored copy of real development data (row counts preserved), downgrade and re-upgrade, services boot on it; staging backup (encrypted, off-site copy) restored into an isolated database with identical checksums and a working application. **Not covered:** paid-subscription and promo data (the dev data had none), a real off-site bucket (**BLOCKED — external dependency**), production-shaped data (no production exists) |
| 6 | Production deployment readiness | **BLOCKED — external dependency** | Procedure, gates, checks and recovery are written and mostly rehearsed locally (`PRODUCTION_DEPLOYMENT.md`). Production cannot be called ready: no server, domain, real TLS issuance, SMTP, monitoring destination, payment decision or approvals. **No deployment, migration or change to the running development stack was made** |
| 7 | Customer pilot readiness | **BLOCKED — external dependency** | Pilot plan, checklists, support, incident and cost tracking are written (`docs/CUSTOMER_PILOT_PLAN.md`). Its entry gates are unmet (real host, SMTP, backups off-site, monitoring, legal review, support person), and stage B (Google connected) cannot start until item 1 passes |

## 2. The ten Part B tasks

| # | Task | Status | Evidence |
|---|---|---|---|
| 1 | Secure and checkpoint the codebase | **PASS** | 393 uncommitted entries classified and committed in 8 reviewable commits (`docs/PHASE_2_CHECKPOINT.md`); full-history scan (27 commits) for key-shaped strings and env files found none; ignored files confirmed ignored; nothing pushed, merged, force-pushed or discarded |
| 2 | Real Google Business Profile validation | **BLOCKED — external dependency** | see item 1 above |
| 3 | Real Places API validation | **BLOCKED — external dependency** | see item 2 above |
| 4 | Staging environment | **PASS (local) / BLOCKED (real host)** | see item 3 above; `docs/STAGING_DEPLOYMENT.md`, `docs/evidence/phase2/` |
| 5 | Security audit | **PASS (internal) / BLOCKED (independent)** | see item 4 above |
| 6 | Onboarding and admin UI | **PASS** | Four-step wizard (business, location, Google choice, plan and first review page) with real plan, trial and allowance data from the account; one getting-started checklist computed by the server (the older second checklist for new accounts was removed so there is one source of truth); admin **Work queue** (failed or blocked Google changes, failed posts, approvals waiting with age, deletion requests with an overdue flag, data exports, completed deletions); **spending ceilings** per business; **platform emergency stop** button with required reason. Browser-tested on staging (18/18) and the demo stack. The Google connection and location-selection screens exist from earlier phases and are exercised only with a test double |
| 7 | Migration and backup/restore rehearsal | **PASS** with limits | see item 5; `docs/DATABASE_BACKUP_RESTORE.md` section 6 |
| 8 | Production deployment preparation | **PASS** (preparation) | `docs/PRODUCTION_DEPLOYMENT.md` updated: status table, three new gates, verification step; two deployment defects fixed (Caddy marketing routes, `NEXT_PUBLIC_SITE_URL`). Deployment itself: not performed, not approved |
| 9 | Final commercial limits and cost inputs | **PASS** (made configurable and documented) / owner inputs **BLOCKED — owner decision** | `docs/COMMERCIAL_LIMITS_AND_COSTS.md`: every number tagged confirmed, provisional, missing or decision. The search-term limit was a hardcoded constant and the Places controls were not passed through Docker Compose (so the documented environment variables silently did nothing); both fixed. Maps remain fail-closed |
| 10 | Controlled customer pilot preparation | **PASS** (documents) | `docs/CUSTOMER_PILOT_PLAN.md` |

## 3. Engineering checks

| Check | Result |
|---|---|
| Backend, full suite, fresh PostgreSQL 16, migrations from scratch, test doubles for Google, Places, payments and AI | ****1368 passed, 0 failed** (1343 before this pass; 25 added)** |
| New this pass | `test_phase2_security_audit.py` (20 tests: 4 fail on the previous code; 3 systematic controls), `test_phase2_admin_queue.py` (4), one in `test_rank_tracker.py`; `route_access_manifest.txt` pins 271 routes |
| Frontend `tsc --noEmit` | passes |
| Frontend production build (inside the Docker image, several times) | passes |
| Browser, new: `e2e/phase2-onboarding-and-queue.js` on **staging over HTTPS** | **18/18** |
| Browser, existing suites on the isolated demo stack | **`phase2-commercial` 11/11, `autonomy-control-centre` 13/13, `agent-and-posts` 31/31, `google-business-agent` 10/10; **`card-inventory` 15/16 and `qr-and-access` 22/23 have one failing step each**: both steps open pre-restructure URLs (`/cards`, `/google?error=...`) and are believed to be stale tests, **not verified against the old code**, so treat them as open; `ops.js` could not start here (no bundled Chromium) and was not run. Four legacy suites also needed a location-cap seed after the plan change (done)** |
| Staging route and TLS checks (`deploy/staging/check_routes.sh`) | 40 passed, 0 failed |
| Staging end-to-end smoke (`deploy/staging/smoke_stack.py`) | 33 passed, 0 failed |
| CI workflow (`.github/workflows/ci.yml`) | **never run** (nothing was pushed); unverified until its first run on GitHub |

What these prove: FlowQR's own logic, database enforcement, the screens, and the deployment shape on one machine. What they do **not** prove: any behaviour of Google, Places, a payment provider, an AI provider, a real network or real traffic.

## 4. What the owner can do to unblock, in the order that unblocks most

1. **Name an authorised test Business Profile** (one you own and no customer depends on) and run `docs/LIVE_VALIDATION_RUNBOOK.md` stages 1 to 4 with it. This is the single biggest blocker: without it no customer may be connected to Google writes.
2. **Create a separate staging Places key** (restricted to Places API (New) and the server, with a quota cap and budget alert), **rotate the exposed one**, and give me the verified price per SKU from your Cloud Billing page. Approve map allowances per plan in Admin > Plans.
3. **Provide a server and a domain** (four hostnames, ports 80 and 443) and an SMTP provider, so staging can run for real and `check_routes.sh`, the smoke test and the browser test can be repeated there.
4. **Decide**: second factor for administrators; free-month length; Growth and Pro location counts; seat counts; per-plan search terms; and enter the cost inputs in `COMMERCIAL_LIMITS_AND_COSTS.md` section 3.
5. **Legal review** of the privacy, terms, refund and retention pages. (This pass changed two sentences of the privacy page so that it no longer names Razorpay as the payment processor; that edit also needs the review.)
6. **Set your admin password yourself** (`python -m app.cli set-admin-password`) and approve when and how to rebuild and migrate the running development stack (take a backup first; see the warning below).
7. Push the branch so CI can run for the first time (`git push -u origin phase-2/commercial-readiness`); nothing was pushed without your say-so.

## 5. A warning about the running development stack

The running `flowqr-*` containers still run the old images and are at migration 0025: **nothing about them was changed**. But the image tags `flowqr-backend:local` and `flowqr-frontend:local` were re-pointed at Phase 2 code by a build earlier in this phase (the old images are no longer tagged). If those containers are ever *recreated* (for example `docker compose up -d` after a config change, or a Docker restart policy that recreates them), Compose will use the new images and the `migrate` service will upgrade the development database to 0030 **without asking**. A fresh backup exists from 2026-11-14 (`backups/`) and a read-only dump from 2026-11-15 (`backups/rehearsal-0025-*.sql.gz`, git-ignored); take another before touching that stack. All rehearsals in this pass used separate image tags (`staging-p2`, `demo-p2`), project names, networks and databases, and removed their temporary containers.

## 6. Why Phase 3 did not start

Part C requires every applicable engineering and deployment check to pass, and "the following require actual evidence: Google write validation, real Places scan, staging deployment, complete security audit, migration upgrade and restore rehearsal, production deployment readiness, customer pilot readiness." Of those, Google writes and the real Places scan have no evidence, staging exists only on one laptop, the audit is internal, and production and pilot readiness have unmet gates. The brief is explicit that this means: document the blocker and stop before Phase 3. Starting Phase 3 now would stack new features (competitor intelligence, local-SEO intelligence, multi-location management) on an integration surface that has never been shown to work against the services it depends on, and several of those features would add Google and Places spend while the spend controls are still unpriced. When the blockers in section 4 clear, Phase 3 can begin with `docs/PHASE_3_PRODUCT_STRATEGY.md`, which will be based on what the real Google and Places behaviour turns out to allow.
