# Production database and migrations

**Status: NOT TESTED on the production database (it does not exist yet).** What follows is what has been rehearsed on other databases and the exact procedure for the VPS. Nothing here touches the Geeta Krishna clinic database or any other database on the server: FlowQR gets its **own** PostgreSQL 16 container and volume (`flowqr-production_pgdata`).

## Migration history (head: `0031`)

| Revision | What it does | Destructive? |
|---|---|---|
| `0001` to `0025` | the schema up to the AI quality tables (earlier phases) | no |
| `0026` | Phase 0 reliability (post idempotency, AI ledger, locks) | no (additive) |
| `0027` | Balanced Autonomy: action, approval and history tables (append-only, row-level security) | no |
| `0028` | geo-grid ranking and unified execution | no |
| `0029` | commercial plans: adds Starter, Growth (updated in place) and Pro, **retires** Essential and Multi (`is_active=false`), **splits the old combined AI allowance** in half into review generations and replies for existing subscriptions, creates `subscription_events` and `promotional_grants` | **the downgrade deletes the new history and grant rows** |
| `0030` | `api_usage_ledger`, richer AI ledger columns, per-business Places cap | the downgrade drops the ledger |
| `0031` | automatic template replies: new `agent_settings` and `reply_drafts` columns; **sets `autonomy_enabled = true` for every existing row** and changes the default to on | the downgrade turns autonomy **off** for every row |

All migrations run as the table-owner role (`flowqr`), never as the application role (`flowqr_app`), which is non-superuser and non-BYPASSRLS so row-level security is real.

## What was actually rehearsed (real evidence, not claims)

| Rehearsal | Result | Where |
|---|---|---|
| **Previous schema to 0030 on a copy of real data**: a read-only dump of the development database at revision `0025` (47 tables, 6 users, 5 businesses, 964 reviews, 1,236 audit rows) restored into a throwaway PostgreSQL 16, upgraded with the Phase 2 code | reached `0030`; **every pre-existing table kept its exact row count** (only `billing_plans` changed, 3 to 5); existing subscriptions received the split allowances; new ledgers have forced RLS with `SELECT, INSERT` only for the app role | `docs/evidence/phase2/migration-upgrade-0025-to-0030.txt` |
| Downgrade `0030` to `0028` and upgrade again on that copy | customer tables identical afterwards | `docs/evidence/phase2/migration-downgrade-and-boot.txt` |
| API, worker and beat started on the upgraded copy as the non-superuser role | `/api/ready` ok, Celery connected, 0 tracebacks | same |
| **`0030` to `0031` on the real development database** (2026-11-15, after a verified backup) | succeeded; all 6 businesses kept their data; autonomy and auto-replies switched on for all 6; worker registered the new task | the session record in `docs/PHASE_2_FINAL_ACCEPTANCE.md` and the commit history |
| Migrations from scratch on a fresh PostgreSQL (every test run, 1,400+ tests, and CI) | green | CI and local runs |
| Production overlay boot on a fresh database with the strict guard | green on the local staging stack at `0030` | `docs/STAGING_DEPLOYMENT.md` |

**Not rehearsed:** an upgrade of a database holding **paid subscriptions, Razorpay ids or promotional grants** (the development data had none; the production database starts empty, so this only matters if data is ever imported), and `0031` on a production-shaped database with many businesses.

## Procedure for the VPS (the first deployment starts from an empty database)

```bash
cd /opt/flowqr
C="docker compose -p flowqr-production --env-file .env.production -f docker-compose.yml -f deploy/vps/docker-compose.vps.yml"
$C up -d db redis                      # database and Redis only; wait until healthy: $C ps
$C run --rm migrate                    # alembic upgrade head, as the table owner; read every "Running upgrade" line
$C run --rm migrate alembic current    # must print 0031 (head)
# application role and privileges: created by db/init/01-app-role.sh on the FIRST start of an empty volume; verify:
$C exec -T db psql -U flowqr -d flowqr -c "select rolname, rolsuper, rolbypassrls from pg_roles where rolname = 'flowqr_app'"   # false | false
$C up -d api worker beat
curl -fsS http://127.0.0.1:18000/api/ready      # {"ready":true,"checks":{"database":"ok","redis":"ok","migrations":"ok"}}
```

Before ANY later migration on production: backup (`docs/PRODUCTION_BACKUP_RESTORE.md`), **restore that backup into an isolated database and upgrade it first** (`deploy/verify-restore.sh`, then `alembic upgrade head` against the copy), compare row counts, only then upgrade production. Never reset or drop the production database to make a migration pass; never run `docker compose down -v` there.

## Notes for the first start

* The new-business defaults (autonomy and automatic replies **on**) come from migration `0031`'s column defaults. On an empty database no existing row is changed.
* `PLATFORM_ADMIN_EMAILS` accounts become administrators only after **email verification** (or `python -m app.cli set-admin-password`, which verifies and grants).
* Plans are seeded by `0029`: Starter ₹499, Growth ₹799, Pro ₹1,499; **map allowances are set by an administrator** (Admin > Plans) and stay off until then.
