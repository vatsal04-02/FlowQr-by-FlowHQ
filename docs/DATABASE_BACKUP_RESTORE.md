# Database backup and restore

The scripts are `deploy/backup.sh`, `deploy/verify-restore.sh`, `deploy/restore.sh` and `deploy/staging/snapshot.sh`. They were written and proven in earlier phases; this file is the operating procedure and records what is and is not proven.

## 1. What is protected, and what is not

| | |
|---|---|
| Logical dump | `pg_dump` of database `flowqr`, gzip, AES-256 encrypted (`openssl enc -aes-256-cbc -pbkdf2 -iter 600000`) when `BACKUP_PASSPHRASE_FILE` is set. **Without a passphrase the backup is unencrypted and the status file says so.** |
| Off-site copy | `BACKUP_REMOTE`: a mounted directory, `user@host:/path` (scp), `s3://bucket/prefix`, or `rclone:remote:path`. A backup that only lives on the server it protects is not a backup. |
| Integrity | the script gunzip-tests the archive and requires at least 20 `CREATE TABLE` statements before it reports success; the result is written to `backups/status.json`, which Admin > Operations reads and alerts on when stale (`BACKUP_MAX_AGE_HOURS`, 30). |
| Retention | local copies: `BACKUP_KEEP_DAYS` (14). **Remote retention is the remote's own lifecycle rule; set one.** Deleted data lives in backups until they age out (`docs/DATA_RETENTION.md` §5). |
| Not covered | Redis (queues and rate-limit counters only; losing it loses in-flight jobs, not data: stuck jobs are recovered by the 5-minute recovery tasks); the Caddy certificate volume (reissued automatically); `.env` and the `TOKEN_ENCRYPTION_KEY` (**keep copies separately and securely: a database restore without the key leaves every Google connection unreadable**); uploaded files that live outside the database (none today). |

## 2. Backup

```bash
# one-time
openssl rand -base64 32 > /etc/flowqr/backup.pass && chmod 600 /etc/flowqr/backup.pass     # store a COPY elsewhere, not on this server
# nightly (cron)
0 2 * * * cd /opt/flowqr && BACKUP_PASSPHRASE_FILE=/etc/flowqr/backup.pass BACKUP_REMOTE=s3://your-bucket/flowqr ./deploy/backup.sh >> backups/backup.log 2>&1
# right now, before any migration or release
BACKUP_PASSPHRASE_FILE=/etc/flowqr/backup.pass BACKUP_REMOTE=... ./deploy/backup.sh && cat backups/status.json
```
`status.json` must show `"ok": true, "encrypted": true, "offsite": true`. If any is false, stop and fix it before continuing.

## 3. Prove a backup restores (do this weekly, and before every migration)

```bash
BACKUP_PASSPHRASE_FILE=... BACKUP_REMOTE=... ./deploy/verify-restore.sh --from-remote
```
It fetches the **off-site** copy, decrypts it, restores into a throwaway PostgreSQL container, checks the schema and data are present, deletes the container, and records `restore_verified_at`. It does not touch the live database. A backup that has never been restored is a hope, not a backup: **"restore last proven <date>" must be recent before any migration is run.**

## 4. Restore (disaster recovery, or building staging from production)

```bash
# DESTRUCTIVE: replaces the current database. Stops api, worker, beat, frontend; asks you to type "yes".
BACKUP_PASSPHRASE_FILE=... ./deploy/restore.sh backups/flowqr-<stamp>.sql.gz.enc
```
It checks that decryption works **before** dropping anything, restores in one transaction (an error aborts: never a half-restored database), re-grants the app role, runs `migrate` (which upgrades a dump from an older release to head; this is also how you bring a pre-migration backup forward), and restarts the services.

After any restore: `python deploy/staging/post_restore_check.py`, then `deploy/staging/snapshot.sh` against the saved "before" snapshot, then Admin > Operations.

**Re-apply deletions made after the backup.** A restore resurrects businesses that were deleted after the backup was taken. Their deletion is recorded in the audit log (`account.deleted`), which the restore also rolls back. Keep the deletion list from the live system (or the exported audit log) and re-run the deletions after any restore; this is a data-protection obligation, not a nicety.

## 5. Point-in-time recovery

Not configured. Recovery granularity is one nightly dump (up to ~24 hours of writes lost) plus the extra backup you take before changes. If that is too coarse for paying customers, enable WAL archiving (`archive_mode`, `archive_command` to the same off-site store) or move to managed PostgreSQL with PITR. This is a decision to record, not an oversight to leave.

## 6. What is proven, and what is not

| Claim | Evidence |
|---|---|
| A real encrypted backup of the dev database was copied to a stand-in off-site folder and restored into a throwaway PostgreSQL with data intact | `docs/PRODUCTION_READINESS.md` (2026-11-15) |
| Migration 0026 applied to a copy of the real dev database, downgraded and re-applied with row counts unchanged | `docs/AGENT_AUDIT.md`, Phase 0 |
| Migrations 0027 to 0030 applied to a copy of a database that holds real data | **not done**: they were applied only to empty test databases and an empty demo stack |
| A restore from a production database to staging and an upgrade across 0026 to 0030 | **not done** (there is no production database yet and the running dev stack is still on 0025) |
| Restore tested against a real off-site bucket | **not done**: only a directory stand-in |
