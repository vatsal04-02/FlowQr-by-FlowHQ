# Rollback and recovery

Read `DATABASE_BACKUP_RESTORE.md` first. This file answers: "a release went wrong, what do I do, and what does each option cost?" **None of the procedures below has been rehearsed against a production-sized database; they are derived from the code and the scripts and marked accordingly.**

## 1. Before you release (so that recovery is possible)

1. A backup taken **now**, encrypted, copied off-site, `status.json` ok, and **a restore of it proven in the last week** (`verify-restore.sh --from-remote`).
2. The previous images are still available: build with a release tag (`FLOWQR_TAG=2026-11-20 docker compose ... up -d --build`) and keep the previous tag's images (`docker image ls flowqr-backend`). The compose file reads `FLOWQR_TAG` for the `migrate`, `api`, `worker` and `beat` images.
3. The current revision and version recorded: `docker compose exec api alembic current` and `git rev-parse HEAD`.
4. The release is a migration-ordered one (see the table in section 3) and you know which of its migrations are safe to reverse.

## 2. Decide: roll back, restore, or fix forward

| Symptom | First move | Why |
|---|---|---|
| New code misbehaves, **schema unchanged or only expanded** | **Redeploy the previous image tag** (section 4) | the fastest and the least lossy; the database keeps everything written since |
| A migration failed halfway | **do nothing destructive.** Read `docker compose logs migrate`. PostgreSQL runs each Alembic migration in a transaction, so a failed migration normally leaves the previous revision intact: check `alembic current`, fix, re-run | do not "downgrade" a migration that never completed |
| Data is wrong or lost (bad migration logic, bad job) | **stop the writers** (`docker compose stop worker beat api`), then **restore the pre-release backup** into a *new* database first and compare before replacing anything | restoring loses every write since the backup: it is the last resort, not the first |
| An external action went wrong (a bad Google edit, a duplicate post) | **Emergency stop** (owner: Autonomy page; platform: `PUT /admin/autonomy/emergency-stop` or `AUTONOMY_EMERGENCY_STOP=true` then `docker compose up -d api worker beat`). Then fix the item in Google by hand. | stops further writes within the next job run; nothing is lost |
| Payments or webhooks misbehave | pause nothing: webhooks are idempotent and Razorpay retries. Check Admin > Billing, the `webhook_events` table, and `subscription_events`. Fix forward. | undoing a payment event locally would disagree with the provider |

## 3. Migrations: which can be reversed, and what a reversal destroys

Alembic `downgrade` exists for these, but a downgrade of the newest ones **deletes data on purpose** (it drops the tables it created). Only use it on an environment with nothing worth keeping (staging, a failed first deployment).

| Migration | Adds | Reversal | Safe after real customers use it? |
|---|---|---|---|
| 0026 reliability | publish-state columns, `ai_call_ledger`, `tenants.ai_monthly_budget_usd`, `reply_drafts.risk_level` | drops them | no: loses the AI spend ledger |
| 0027 balanced autonomy | actions, approvals, history, follow-ups, platform controls, autonomy settings | drops them (needs the history-erase flag) | **no: erases the audit history** |
| 0028 geo-grid | map tables, `agent_actions.subject_*` | drops them | no: loses map scans |
| 0029 commercial plans | quotas and limits columns, `subscription_events`, `promotional_grants`, `card_orders.offer_code`; Starter and Pro plan rows | drops the tables and columns and **deletes the Starter and Pro plan rows** | **no: any subscription on Starter or Pro would then point at a plan that no longer exists, and subscription history and free-month records are lost** |
| 0030 usage ledger | `api_usage_ledger`, AI ledger columns, `tenants.places_monthly_cap` | drops them | no: loses API usage history |

**After go-live, the rule is: restore a backup or fix forward; do not downgrade.**

**The migrations are written to be additive** (new tables, new nullable or defaulted columns), so the previous release's code should keep working against the newer schema. That is a design intent, **not proven**: prove it on staging by running the previous image against a database at the new revision (section 4, step 3) before relying on it.

## 4. Roll the application back (schema stays)

```bash
# 1. stop taking new work
docker compose exec api python -c "print('ok')"   # sanity: the stack is up
docker compose stop beat                            # no new scheduled jobs; running ones finish
# 2. redeploy the previous tag, WITHOUT re-running a downgrade
FLOWQR_TAG=<previous tag> docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --no-build --no-deps api worker frontend
FLOWQR_TAG=<previous tag> docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --no-build --no-deps beat
# 3. verify
curl -fsS https://api.<domain>/api/health ; docker compose ps ; docker compose logs --tail=50 api worker
```
Do **not** include the `migrate` service in this command (`--no-deps` and naming only the app services keeps it from running `upgrade head` with the old image, which would be a no-op at best). Then watch Admin > Operations for failing jobs for at least one full beat cycle (15 minutes).

If the previous image fails against the newer schema, you have found the limit of "additive": go to section 5.

## 5. Restore from backup (last resort)

1. **Announce** the maintenance window: restoring discards every write since the backup (reviews synced, replies sent, payments recorded locally).
2. Take a fresh backup of the *current* state first (even a broken one): `./deploy/backup.sh`. You may need it to recover the writes later.
3. `./deploy/verify-restore.sh <chosen backup>` (does not touch the live database).
4. `./deploy/restore.sh <chosen backup>` (type `yes`).
5. `docker compose run --rm migrate` runs as part of the restore; it only moves **forward**. Make sure the code you are running matches the restored revision (or is newer and expects to migrate).
6. Reconcile what the restore forgot:
   * **Payments**: Razorpay is the source of truth. Re-fetch missed events from the Razorpay dashboard (webhook deliveries can be replayed; our handler is idempotent), and compare `payments` with the dashboard.
   * **Google**: reviews re-sync on the next job; posts, photos and replies sent after the backup exist on Google but not locally. The post and reply publishers look for an existing item before creating one, so a retry will not duplicate; check Admin > Operations for stuck items.
   * **Deleted businesses** come back: re-run their deletions (`DATABASE_BACKUP_RESTORE.md` §4).
   * **Autonomy**: set the emergency stop **before** restarting the worker, review the action queue, then lift it.

## 6. Individual recovery recipes

| Problem | Recovery |
|---|---|
| Worker crashed mid-publish | nothing to do: items left `publishing` or `executing` are resolved by the 5-minute recovery jobs by **asking Google**, never by re-sending blindly. A photo is never re-sent without a person checking. |
| Redis lost | no data lost; queues empty; the beat re-schedules. Rate-limit counters reset. |
| `TOKEN_ENCRYPTION_KEY` lost | stored Google tokens are unreadable; every business reconnects Google. Prevent it: keep the key in a second secure place. |
| A business asks to be deleted but is already in a backup | deletion is complete when the backup ages out (`BACKUP_KEEP_DAYS`, remote lifecycle); say so in the privacy notice. |
| Wrong plan or allowance given to a customer | Admin > Customers > Subscription override (audited, with a note) or Admin > Plans and limits for plan-wide values. Never edit the database by hand: `subscription_events` and the audit log are the record. |
| Suspected leaked secret | rotate it (`ENVIRONMENT_VARIABLES.md` §"Rotating a secret"), then review Admin > Audit. |

## What was rehearsed on 2026-11-15, and what was not

| Procedure | Rehearsed? | Result |
|---|---|---|
| Restore a staging backup into an isolated database and run the application on it | yes | checksums identical, API, worker and beat run, a restored user signs in, reads and writes. `docs/evidence/phase2/staging-backup-restore.txt` |
| Downgrade 0030 to 0028 and upgrade again on a copy of real development data | yes | succeeded; customer tables identical afterwards; ledger, promotional-grant and subscription-history rows are **deleted by the downgrade** (as section 3 says) and plan allowances revert, so a downgrade after real sales loses history: prefer restoring the pre-release backup |
| Previous API code against the upgraded schema (rollback of code only) | started only | the 0025 API started and answered `/api/health` and `/api/v1/billing/plans` on the 0030 schema. This suggests the migrations are additive enough for "roll back the image, keep the schema", **but it was one start-up and one read, not a regression of the old code**. Until it is rehearsed on staging with the old release's own tests, treat the restore as the safe path |
| Restore from a real off-site bucket; point-in-time recovery; a production database | no | no bucket, no WAL archiving and no production exists |
| Re-applying business deletions made after the backup (section 4) | no | procedure only |
