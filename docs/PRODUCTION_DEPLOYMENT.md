# Production deployment

Single server (Docker Compose + Caddy). The first-time server setup, DNS, TLS, Google and Razorpay account steps are in `docs/DEPLOYMENT.md`; the old readiness list is `docs/PRODUCTION_READINESS.md`. **This file is the release procedure for the current code (migrations through 0030) and the gates that must pass first.**

## 0. Honest status

**Development Complete — External Validation Pending.** FlowQR has not been deployed to production. The running local stack (`flowqr-*` containers) is on old code at migration 0025 and was deliberately not touched. No real Google write, no real Places scan and no live payment have been performed. Do not deploy Phase 2 to paying customers until the release gates in section 2 are ticked.

### Preparation status (2026-11-15)

Everything below is **written and rehearsed locally**; none of it has been run on a production server, which does not exist yet.

| Part of the process | State |
|---|---|
| Environment configuration | Documented in `docs/ENVIRONMENT_VARIABLES.md` and `.env.example`; `deploy/staging/make-env.sh` generates fresh secrets; the strict config guard (`APP_ENV=production`) refuses development secrets, insecure cookies, localhost URLs, sink SMTP and test payment keys. **New in this pass: `NEXT_PUBLIC_SITE_URL` is a build-time setting**, set it before building the frontend |
| Migration sequence | 0025 to 0030 rehearsed on a restored copy of real development data, with downgrade and re-upgrade (`docs/evidence/phase2/`). Not rehearsed on production-shaped paid data |
| Backup procedure | `deploy/backup.sh` (encrypted, off-site, status file) and `deploy/verify-restore.sh` proven on staging with a directory as the off-site target. A real bucket or remote host is not tested. Use `BACKUP_DIR` if staging and production ever share a machine |
| Health checks | `/api/health` (process and database), **`/api/ready`** (database, Redis, migration revision: for a load balancer or the deploy script), Admin > Operations (worker, scheduler, backup, sync). All working on local staging |
| Monitoring | Sentry hooks and the Operations page exist; **no `SENTRY_DSN` is set and no alert destination is wired**: not met |
| TLS | Caddy with automatic Let's Encrypt in production (HTTP to HTTPS 308, HSTS). Rehearsed only with Caddy's internal CA on staging; **real ACME issuance has not run** (needs the four DNS records and ports 80 and 443 reachable) |
| Worker and scheduler | Separate `worker` and `beat` services, healthy on staging; beat must run **exactly once** |
| Rollback and recovery | `docs/ROLLBACK_AND_RECOVERY.md`; the restore path is rehearsed; "roll the code back, keep the schema" is plausible (the previous API started on the new schema) but not proven |
| Post-deployment verification | Section 4 below, plus `deploy/staging/check_routes.sh` (run it against the production hostnames with `RESOLVE_IP` unset and a real CA) |
| Payments | **Deferred by the owner (Cashfree, after the live website).** No payment provider is wired. Launching without self-serve payment means an administrator sets each business's plan from Admin > Customers |
| Administrator account | Must be verified before it has admin rights (new this pass). On the server: `docker compose exec api python -m app.cli set-admin-password --email <address in PLATFORM_ADMIN_EMAILS>` (verifies the address, grants the flag, signs the account out everywhere) |

## 1. Never do these

* Do not run `alembic upgrade` (or start the stack, which runs it) against a database you have not backed up **and restored to staging first**.
* Do not `docker compose down -v` on production: it deletes the database volume.
* Do not overwrite `.env`; do not commit it; do not copy it between environments.
* Do not point staging at production's Razorpay, Google or Places credentials.
* Do not write to a real customer's Google profile to "test" anything.

## 2. Release gates (all must be true)

| # | Gate | Evidence to attach to the release |
|---|---|---|
| 1 | Backend suite green on this exact revision | full pytest output, fresh PostgreSQL, migrations from scratch |
| 2 | Frontend `tsc --noEmit` and `next build` pass | outputs |
| 3 | Browser suites pass on staging | `e2e/autonomy-control-centre.js`, `e2e/agent-and-posts.js` outputs |
| 4 | Staging is on the same revision and **was upgraded from a restored copy of production data** | `alembic current` before and after; `snapshot.sh` before and after |
| 5 | Backup taken, encrypted, off-site, **restore proven this week** | `backups/status.json` |
| 6 | `preflight` passes on the production environment | output (`python -m app.cli preflight --smtp-test ... --sentry-test`) |
| 7 | **Payments:** either the chosen provider (Cashfree) is integrated, live keys and webhook set, and a real small payment and refund made end to end, **or the owner has written down that launch is without self-serve payment** (plans set by an administrator) | dashboard export, or the owner's note |
| 8 | **Live Google validation stages 1 to 4 complete** on an authorised test profile | the filled-in evidence log in `docs/LIVE_VALIDATION_RUNBOOK.md` §9 |
| 9 | Places key, `API_PRICES` and the platform cap set; map allowances approved by the owner | Admin > Plans and limits shows nothing pending |
| 10 | Owner decisions recorded (promo month length, one grant per business, retention periods) and legal review of the privacy and retention pages | written approvals |
| 11 | Sentry DSN set and a test event seen | screenshot |
| 12 | Rollback rehearsed on staging (`ROLLBACK_AND_RECOVERY.md` §4, step 3) | notes |
| 13 | **Staging on a real host**: real domain, real certificates, real SMTP, the same overlay as production, with `deploy/staging/check_routes.sh`, `smoke_stack.py` and the browser test passing there | outputs |
| 14 | Administrator account verified with a password the owner set; the second-factor decision (`PHASE_2_SECURITY_AUDIT.md` F7) recorded | owner's note |
| 15 | `NEXT_PUBLIC_SITE_URL` set to the public marketing origin **before the frontend is built**; `sitemap.xml` and the canonical link on `/pricing` show it | `curl` output |
| 16 | `RANK_PLATFORM_MONTHLY_CAP` set (0 means no platform ceiling on Google spend) | `.env` line (not the key) |

Gates 4, 7, 8, 9, 10, 12, 13, 14, 15 and 16 are **not met today**.

## 3. Deploy

```bash
cd /opt/flowqr
git fetch && git checkout <release tag>                      # never deploy an untagged branch tip
# 1. protect
BACKUP_PASSPHRASE_FILE=/etc/flowqr/backup.pass BACKUP_REMOTE=... ./deploy/backup.sh && cat backups/status.json
BACKUP_PASSPHRASE_FILE=/etc/flowqr/backup.pass BACKUP_REMOTE=... ./deploy/verify-restore.sh --from-remote
docker compose exec api alembic current > release-before.txt ; deploy/staging/snapshot.sh > snapshot-before.txt
# 2. emergency stop on, so nothing is half-way through a Google write while code changes
#    set AUTONOMY_EMERGENCY_STOP=true in .env, then:  docker compose up -d api worker beat
# 3. build and migrate (the migrate service runs `alembic upgrade head` as the table owner, then exits; api waits for it)
FLOWQR_TAG=<release tag> docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose ps                         # migrate: Exited (0); everything else: healthy
docker compose exec api alembic current   # 0030 (head)
# 4. verify (section 4), then lift the stop (AUTONOMY_EMERGENCY_STOP=false; docker compose up -d api worker beat)
```

If `migrate` exits non-zero: **stop**, read `docker compose logs migrate`, and use `ROLLBACK_AND_RECOVERY.md`. Do not re-run blindly.

## 4. Verify after deploying

1. `curl -fsS https://api.<domain>/api/health`, `curl -fsS https://api.<domain>/api/ready` (must say `"ready":true`) and `https://app.<domain>`. Then `deploy/staging/check_routes.sh` with `STAGING_DOMAIN=<domain> RESOLVE_IP=none CADDY_ROOT_CA=` (empty: trust the system certificates) from a machine that resolves the real hostnames: marketing pages stay on the marketing host, the pricing page can load the plans, the card host serves only card routes.
2. Admin > Operations: database, Redis, migrations match code, **worker and scheduler heartbeat fresh**, backup fresh, no failing jobs.
3. `deploy/staging/snapshot.sh > snapshot-after.txt; diff snapshot-before.txt snapshot-after.txt`: row counts only grow; tables a migration did not touch have identical checksums.
4. Admin > Plans and limits: Starter, Growth and Pro at ₹499 / ₹799 / ₹1,499; pending items listed (maps stay off until approved).
5. As a test business: onboard, create a QR campaign, choose a plan through Razorpay in the mode you are in, confirm it shows only after the webhook.
6. Admin > Finance and usage loads, and every missing input is shown as missing.

## 5. Running it

| Concern | Where |
|---|---|
| Health, jobs, backups, errors | Admin > Operations (`/admin/ops`), 15-minute `ops_watch` email alerts, Sentry |
| Cost and margin | Admin > Finance and usage (`/admin/finance`, `/admin/costs`) |
| A customer's plan, allowance, free month, ceilings | Admin > Customers, Admin > Plans and limits, `PUT /admin/tenants/{id}/budgets` |
| Stop all autonomous and approved writes | `PUT /admin/autonomy/emergency-stop` (needs a reason) or `AUTONOMY_EMERGENCY_STOP=true` |
| Backups | `DATABASE_BACKUP_RESTORE.md` |
| Something broke | `ROLLBACK_AND_RECOVERY.md` |
| Scaling | raise `--concurrency` on the worker; move PostgreSQL and Redis to managed services by changing `DATABASE_URL`, `MIGRATION_DATABASE_URL`, `REDIS_URL` |

## 6. Reliability features and their honest limits

| Feature | State |
|---|---|
| Health endpoint | `/api/health` (process is up). Deeper readiness (database, Redis, migration revision, heartbeat) is on Admin > Operations and `/api/ready`. |
| Worker and scheduler heartbeat, failed-job and stuck-job detection | present (Operations); stuck posts, photos, replies and autonomous actions are recovered every 5 minutes by asking Google first |
| Retries | bounded (attempts and back-off), idempotent: a post or reply is looked up on Google before it is created again; a usage row cannot be counted twice; a webhook is processed once |
| Graceful shutdown | Celery's warm shutdown on `SIGTERM` finishes the running task; each external write is claimed (committed) before the call so a crash is recoverable, not silent |
| Structured logs | JSON-style logger names per module (`flowqr.*`); Sentry for errors. No tokens or customer text are logged. A central log store is not set up. |
| Point-in-time recovery | not configured (`DATABASE_BACKUP_RESTORE.md` §5) |
| High availability | none: one server, one database. A restore is the recovery plan. |
