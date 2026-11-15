# Staging deployment

Staging is where every migration and every release is proven **before** production. It runs the same images and the same `docker-compose.prod.yml` overlay as production (hardened config guard on, real TLS), with its own project name, database, volumes and `.env.staging`. The older evidence is in `docs/STAGING_READINESS.md` (2026-11-01, migrations to 0024). **That report predates migrations 0026 to 0030; this file is the current procedure.**

## 0. Status

| Item | State |
|---|---|
| Procedure and scripts (`deploy/staging/*`) | exist and were run for the 0024-era build |
| A staging environment on the current code (0030) | **not built.** The throwaway test stack used for Phase 2 is not staging: it has no TLS, no real SMTP, no real integrations. |
| "Staging validated" for any Phase 2 change | **no** |

## 1. Create the environment

```bash
git clone <your repo URL> flowqr-staging && cd flowqr-staging
git checkout phase-2/commercial-readiness        # or the release tag under test
deploy/staging/make-env.sh staging.yourdomain.in  # writes .env.staging (mode 600, fresh random secrets, refuses to overwrite)
$EDITOR .env.staging   # real staging SMTP, rzp_test_ Razorpay keys + webhook secret, GEMINI_API_KEY, Google OAuth client for the staging redirect URI,
                       # PLATFORM_ADMIN_EMAILS, ACME_EMAIL, and the Phase 2 inputs in docs/ENVIRONMENT_VARIABLES.md (API_PRICES etc.)
```

Use **test-mode Razorpay keys, a separate Google Cloud OAuth client and a separate Places key** for staging, never the production ones.

## 2. Start

```bash
C="docker compose -p flowqr-staging --env-file .env.staging -f docker-compose.yml -f docker-compose.prod.yml"
$C up -d --build
$C ps                                   # db, redis, api, worker, beat, frontend, caddy healthy; migrate = Exited (0)
$C exec api alembic current             # must print 0030 (head)
curl -fsS https://api.staging.yourdomain.in/api/health
$C exec api python -m app.cli preflight --smtp-test you@yourdomain.in
```

The `migrate` service runs `alembic upgrade head` as the table owner before the API starts; on staging that is the point (this is where a migration meets realistic data).

## 3. Proving a migration on staging (the order that matters)

1. **Restore production's latest verified backup into staging** (`deploy/restore.sh`, see `DATABASE_BACKUP_RESTORE.md` §4) so staging holds production-shaped data at production's current revision. Never copy production's `.env` or secrets.
2. `$C exec api alembic current` must equal the revision production reports. If it does not, stop: you are not testing the real upgrade.
3. `$C run --rm migrate` applies every pending migration. Read the output; each should say `Running upgrade`.
4. `deploy/staging/snapshot.sh` before and after (it prints row counts and checksums of the key tables): counts must not drop; the tables a migration claims to leave alone must have identical checksums.
5. `$C exec api alembic downgrade -1 && $C exec api alembic upgrade head` for the newest migration, to prove the downgrade path exists **and** to learn what it loses (see `ROLLBACK_AND_RECOVERY.md` §3: some downgrades delete data by design).
6. Run the checks below.

## 4. Checks to run on staging

| Check | Command | What a pass means |
|---|---|---|
| Routes, TLS, headers | `deploy/staging/check_routes.sh` | the four domains route correctly, HSTS and security headers present |
| End-to-end flows | `python deploy/staging/smoke_stack.py` | register, onboard, card scan, public page, export, deletion |
| Billing webhooks | `deploy/staging/seed_billing.sh && deploy/staging/run_webhook_scenarios.sh` | signed events are processed once; bad signatures are refused; duplicates change nothing |
| After a restore | `python deploy/staging/post_restore_check.py` | data and RLS survived |
| Unit and integration | `cd backend && pytest -q` (in the test image against a throwaway Postgres; see `docs/PHASE_2_COMPLETION_REPORT.md` for the exact command) | the suite is green on this revision |
| Browser | `node e2e/autonomy-control-centre.js`, `node e2e/agent-and-posts.js` (`BASE_URL` = staging, use a test business) | the screens work against real services |
| Worker and scheduler | Admin > Operations | worker heartbeat fresh, no failing jobs, backup fresh |
| Live Google | `docs/LIVE_VALIDATION_RUNBOOK.md` | **only with an authorised test profile** |

## 5. Release status ladder

A change is only as validated as the highest rung it has actually passed. Record the rung in the release notes; never skip one in wording.

1. **Unit tested** (pytest, test doubles)
2. **Integration tested with doubles** (browser tests with seeded data)
3. **Staging validated** (sections 2 to 4 on current code, with test-mode Razorpay)
4. **Tested against real Google** (runbook stages 1 to 4, an authorised test profile)
5. **Tested against real Places** (runbook stage 5)
6. **Approved for production** (a named person, after 1 to 5 and the migration rehearsal)

## 6. Stop and clean up

`$C down` keeps data. `$C down -v` **destroys the staging database and certificates** (irreversible; fine for staging, never for production).
