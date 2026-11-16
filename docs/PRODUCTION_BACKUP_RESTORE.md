# Production backup and restore (FlowQR on the VPS)

**Status: scripts and procedure PASS on a local staging stack; NOT TESTED on the VPS; off-site storage BLOCKED (no destination chosen).** A backup that has not been restored on the real server, from the real off-site copy, is a hope. Nothing below has been run on `201.18.202.128`.

## What is protected

* **PostgreSQL** (`flowqr-production_pgdata`): everything, **including uploaded photos and logos** (they are stored in the database, not on disk). There is no other file or media store to back up.
* **Not in the database, keep separately and securely:** `.env.production`, above all **`TOKEN_ENCRYPTION_KEY`** (without it every restored Google connection is unreadable and every customer must reconnect) and the backup passphrase. Redis holds queues and rate-limit counters only (losing it loses in-flight jobs, not data).
* The existing clinic database, n8n and Grist are **not** touched and **not** backed up by this.

## Backup (encrypted, off-site, with a status file the admin page reads)

```bash
cd /opt/flowqr
export COMPOSE="docker compose -p flowqr-production --env-file .env.production -f docker-compose.yml -f deploy/vps/docker-compose.vps.yml"
export BACKUP_DIR=/opt/flowqr/backups BACKUP_PASSPHRASE_FILE=/etc/flowqr/backup.pass BACKUP_REMOTE=<off-site destination>   # s3://..., user@host:/path, rclone:..., or a mounted directory
openssl rand -base64 32 > /etc/flowqr/backup.pass && chmod 600 /etc/flowqr/backup.pass     # once; keep a COPY OFF THIS SERVER
./deploy/backup.sh && cat $BACKUP_DIR/status.json    # must show "ok": true, "encrypted": true, "offsite": true
# nightly:  0 2 * * * cd /opt/flowqr && <the exports above> ./deploy/backup.sh >> backups/backup.log 2>&1
```

* `backup.sh` dumps with `pg_dump`, gzips, **checks the archive and requires at least 20 tables**, encrypts (AES-256, PBKDF2), proves the encrypted file decrypts, writes a SHA-256, copies off-site, and exits non-zero unless the copy is both encrypted **and** off-site (so cron mails you).
* **Retention:** local copies `BACKUP_KEEP_DAYS` (default 14). **Off-site retention is the destination's own lifecycle rule: set one.**
* **Failure alerts:** the API reads `status.json` (mounted read-only); Admin > Operations shows the backup as stale or failed after `BACKUP_MAX_AGE_HOURS` (30) and the scheduler emails platform admins about new critical items (needs SMTP and `SENTRY_DSN`/admin emails configured). Also let cron mail the non-zero exit.
* The backup must **never** live only on the same volume or disk as the database: the off-site copy is mandatory.

## Prove it restores (before go-live, then weekly and before every migration)

```bash
./deploy/verify-restore.sh --from-remote      # fetches the OFF-SITE copy, decrypts, restores into a throwaway PostgreSQL container, checks tables, migration revision and RLS policies, deletes it
```

This never touches the live database. Record the date: "restore last proven" must be recent before any migration.

## Restore (disaster recovery, DESTRUCTIVE: replaces the database; asks you to type `yes`)

```bash
BACKUP_PASSPHRASE_FILE=/etc/flowqr/backup.pass ./deploy/restore.sh backups/flowqr-<stamp>.sql.gz.enc
```

It checks decryption **before** dropping anything, restores in one transaction (an error aborts: never half-restored), re-grants the app role, runs `migrate` (so an older dump is brought forward), and restarts the services. Afterwards run `python deploy/staging/post_restore_check.py` and `deploy/staging/snapshot.sh`. **Re-apply any business deletions made after the backup** (a restore resurrects them; this is a data-protection duty). Never run it on the clinic's database: it is `docker compose`-project-scoped to `flowqr-production`.

## Evidence so far

| Test | Result |
|---|---|
| Encrypted backup of a staging database, copied to an off-site stand-in directory, restored from that copy into an isolated PostgreSQL | **PASS** (2026-11-15): 14 key tables identical in row counts and content checksums; migrations a no-op; API, worker and beat ran on the copy; a restored user signed in, read, wrote, and the plan limit was still enforced. `docs/evidence/phase2/staging-backup-restore.txt` |
| Same on the VPS, against a real off-site destination | **NOT TESTED / BLOCKED** (no server access, no destination) |
| Point-in-time recovery | **not configured**: recovery granularity is one nightly dump (up to about 24 hours of writes). If that is too coarse for paying customers, enable WAL archiving or managed PostgreSQL |
| A backup taken before every release | procedure only: `docs/PRODUCTION_DEPLOYMENT.md` section 3 |

## Disk planning

The dump of the development database (6 businesses, 964 reviews) is under 0.4 MB compressed; photos stored in the database will dominate growth. Check `docker system df` and `df -h` in the infrastructure audit and alert at 80% disk.
