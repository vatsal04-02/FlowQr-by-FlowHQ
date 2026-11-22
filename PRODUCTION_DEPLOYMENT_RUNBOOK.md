# FlowQR production deployment runbook

For the release of branch `hardening/production-readiness-audit` (and the template for later releases). Written 2026-11-22 from the repository's own runbooks (`docs/runbooks/GOOGLE_AGENCY_RELEASE_AND_ROLLBACK.md`,
`docs/ROLLBACK_AND_RECOVERY.md`, `docs/DATABASE_BACKUP_RESTORE.md`, `deploy/vps/*`) and what the audit rehearsed locally. **Nothing in this file has been run on the production server by the audit.**
Everything that needs a person's approval says so. Placeholders are in `<angle brackets>`; no secret belongs in this file.

## 0. This release in one paragraph

6 backend and 4 frontend source files changed, plus tests and scripts. **No migration (`alembic` stays at `0065`), no environment variable, no dependency, no URL change.** One extra boolean (`agency_available`)
in `GET /google/status`. Fixes: a stuck "running" sync state, scheduled posts/photos starved by a suspended business, a form crash in the New campaign dialog, two small page defects, blank reply drafts.
Because there is no migration, the 20 to 30 second public 503 that happened when the head changed under a running image (recorded in the agency runbook) **should not occur**; verify that it does not.

## 1. Never do these

* Never recreate a container before the real startup guard has accepted the configuration in a throwaway container (section 3, step 4). A guard refusal took the public API down for 3 to 5 minutes on 2026-11-22.
* Never run compose with one file. Production is always **both** files: `docker compose -p flowqr-production --env-file .env.production -f docker-compose.yml -f deploy/vps/docker-compose.vps.yml <command>`. With only the base file the API loses its private port (`172.17.0.1:18000`) and the shared proxy answers 503.
* Never `docker compose down -v` (deletes the database volume). Never overwrite or commit `.env.production`.
* Never edit an applied migration. Schema changes are new migrations, backed up and rehearsed first.
* Never switch on the agency switches, public third-party access, or set `GOOGLE_AGENCY_POLICY_REFERENCE` without Google's written answer. Never invent one.
* Never test on a customer's Google profile, and never start a real Cashfree transaction as a test.
* Never run Vercel commands from a folder that is not linked to the project. Never use `git push --force`.
* Do not touch the neighbouring applications on the shared server (n8n, Grist, the clinic app, the Caddy that owns ports 80 and 443).

## 2. Before the release (all must be true, with evidence attached to the release note)

| # | Gate | How to check | Result at the audit |
|---|---|---|---|
| 1 | Release content approved by you | Read `PRODUCTION_READINESS_AUDIT.md` sections 6 and 10 | awaiting your approval |
| 2 | Branch is based on what is live, and nobody else's work is overwritten | `git fetch origin; git log --oneline origin/release/gbp-agency -3`; compare with the live image tag; merge, never force | `origin/release/gbp-agency` is `0604555` (6dc3739 + 11 marketing commits). Decide how to combine. |
| 3 | Backend suite green on this exact revision | 8-shard Linux run (`PRODUCTION_TEST_MATRIX.md` header) | 3,445 passed, 0 failed |
| 4 | Frontend `tsc`, `npm test`, `npm run build` | `cd frontend; npx tsc --noEmit; npm test; npm run build` | clean, 131/131 |
| 5 | Browser journeys | `node e2e/production-audit-journeys.js` against a local stack | 40/40 |
| 6 | Backup taken now, encrypted, restore proven | section 3 step 2 | repeat on the day |
| 7 | Off-site copy exists | `cat backups/status.json` shows `"offsite": true` | **Not met until you configure a destination (section 8)** |
| 8 | Previous images and previous Vercel deployment id recorded | `docker image ls flowqr-backend`; Vercel dashboard | record on the day |
| 9 | `AUTONOMY_EMERGENCY_STOP` and the safeguards unchanged | read `.env.production` flags, **not** secrets | record on the day |

## 3. Release steps

Run as the deploy user in `/opt/flowqr`. Run any script as a file with `</dev/null` (a piped `docker exec` can swallow stdin). Record each output.

1. **Record the starting state** (read-only):
   `docker compose -p flowqr-production --env-file .env.production -f docker-compose.yml -f deploy/vps/docker-compose.vps.yml ps`
   `... exec -T api alembic current` (expect `0065`), `docker port flowqr-production-api-1` (expect `172.17.0.1:18000`), `curl -fsS https://api.flowqr.site/api/ready`.
   Save the running image tag, the md5 of both compose files, and a fingerprint (row counts of users, tenants, memberships, qr_cards, subscriptions, reviews, audit_logs).
2. **Protect.** `./deploy/backup.sh` then `cat backups/status.json` (`ok:true`, `encrypted:true`; `offsite:true` once configured), then `./deploy/verify-restore.sh` (add `--from-remote` once off-site exists). A manual pre-release dump is also kept 14 days by `prune-manual-dumps.sh`.
3. **Build** the backend image from a clean archive of the approved commit, never from a working tree: extract it (`git archive <commit> | tar -x -C <clean dir>`), then `docker build -t flowqr-backend:prod-<short-sha> <clean dir>/backend` (the build context is the `backend` folder; the base image is Python 3.13). Build locally and `docker save`/`docker load` it on the server if the server should not pull from PyPI. Confirm the image id is identical locally and on the server.
4. **Validate the configuration with the real startup guard, in a throwaway container, before any container is touched:**
   `FLOWQR_TAG=prod-<short-sha> docker compose -p flowqr-production --env-file .env.production -f docker-compose.yml -f deploy/vps/docker-compose.vps.yml run --rm --no-deps -T api python -c "import app.main"`
   It must exit 0 with no "Unsafe production configuration" text. (`compose config` only renders YAML and does not run the guard.) If it refuses, **stop**: nothing has changed.
5. **Migration step** (a no-op for this release, run it anyway so the procedure is the same every time): `... run --rm --no-deps -T migrate`. Expect no new revision; `alembic current` still `0065`. If it prints anything unexpected, stop and use section 5.
6. **Recreate** api, worker and beat together, both compose files, `--no-deps`:
   `FLOWQR_TAG=prod-<short-sha> docker compose -p flowqr-production --env-file .env.production -f docker-compose.yml -f deploy/vps/docker-compose.vps.yml up -d --no-deps api worker beat`
   Then at once: `docker port flowqr-production-api-1` must show `172.17.0.1:18000`; `curl -fsS https://api.flowqr.site/api/ready` must return `{"ready":true,...}`; the env diff against the recorded one must be the image tag only; the compose files' md5 must be unchanged.
7. **Frontend** (Vercel). A push of a non-production branch creates a **Preview** only (corrected in the agency runbook; if in doubt, do not push). Production is published with the CLI from a temporary folder that contains a clean `git archive <commit> frontend` plus the project's `.vercel/project.json`: `npx --yes vercel@latest --prod`. Record the new deployment id and keep the previous one as the rollback target. Confirm the aliases still point at `www.flowqr.site` and `flowqr.site`.
8. **Run the smoke tests (section 4).** Only then tell customers or announce anything.

## 4. Post-deployment smoke tests

All read-only or on a disposable business you created for the purpose.

| # | Check | Expected |
|---|---|---|
| 1 | `curl -fsS https://api.flowqr.site/api/health` and `/api/ready` | 200; `{"ready":true,"checks":{"database":"ok","redis":"ok","migrations":"ok"}}` |
| 2 | `curl -sI https://www.flowqr.site/`, `https://flowqr.site/`, `https://go.flowqr.site/` | 200; 308 to www; 302 to www |
| 3 | `curl -s -o /dev/null -w '%{http_code}' https://api.flowqr.site/api/docs` and `/api/v1/agency-ops/tenants` | 404 and 401 |
| 4 | `docker compose ... ps` | api, worker, beat, db, redis healthy; no container restarting |
| 5 | `... logs --since 10m api worker beat > release.log 2>&1; grep -c -i -e Traceback -e Unsafe -e ERROR release.log` | 0 (or explained) |
| 6 | Admin > Operations | every check green; "Scheduled jobs" lists the jobs and none failing; heartbeat under a minute old; backup panel as expected |
| 7 | Sign in as yourself; open Home, Reviews, Campaigns, Locations | pages load; Locations makes no failing request (browser console) |
| 8 | Create a campaign through the dialog | no console error (this was the React #185 fault) |
| 9 | Scan a real printed card (or the QR of a campaign) with a phone | the review page of the right business opens; an NFC tap opens the same page |
| 10 | **F-01 check:** no location stuck "running": `... exec -T db psql -U flowqr -d flowqr -c "SELECT set_config('app.bypass_rls','on',false); SELECT count(*) FROM google_locations WHERE last_sync_status='running' AND updated_at < now() - interval '30 minutes';"` | 0 |
| 11 | **F-01 check:** both customer locations synced after the release | Admin > Operations, or `SELECT title, last_sync_status, last_synced_at FROM google_locations WHERE selected;` shows `ok` and a time within the last hour |
| 12 | **F-02 check:** nothing overdue is waiting without a reason | `SELECT tenant_id, count(*) FROM scheduled_posts WHERE status='scheduled' AND scheduled_for < now() - interval '1 hour' GROUP BY 1;` (same `set_config` line first) should be empty, or only businesses that are suspended or deleting |
| 13 | Agency still locked | `SELECT count(*) FROM google_agency_tenant_grants WHERE revoked_at IS NULL;` unchanged from the recorded value; flags unchanged |
| 14 | WhatsApp untouched | the WhatsApp menu and its flags are exactly as before (this release does not touch them) |

If any of 1 to 5 fails, roll back immediately (section 5). If 6 to 14 show a defect, decide between rollback and fix-forward; the code in this release is additive, so a rollback loses nothing.

## 5. Rollback

| Situation | Action | Notes |
|---|---|---|
| Backend misbehaves | `FLOWQR_TAG=<previous tag> docker compose -p flowqr-production --env-file .env.production -f docker-compose.yml -f deploy/vps/docker-compose.vps.yml up -d --no-deps api worker beat`, then the checks in step 6 | **Both files, `--no-deps`.** This release has no migration, so the schema stays. Previous images stay on the server: keep at least the last two. |
| Frontend misbehaves | Promote or alias the recorded previous Vercel deployment to `www.flowqr.site` and `flowqr.site` | The new frontend needs nothing from the new backend except an optional boolean, so either side can be rolled back alone. |
| A configuration change was refused by the guard and the API is down | Put the previous `.env.production` back (the one recorded in step 1), validate with the throwaway guard, then recreate | Do not "try" values on the running stack. |
| A migration was involved (a future release) | Do nothing destructive. Read `... logs migrate`; Alembic runs each migration in a transaction, so a failed one normally leaves the previous revision. Roll the image back first; downgrade only if the previous image cannot run on the new schema | See `docs/ROLLBACK_AND_RECOVERY.md` section 3 for which downgrades delete data. |
| Agency path must stop | Set `GOOGLE_AGENCY_MANAGER_ENABLED=false` and `GOOGLE_AGENCY_OPERATIONS_ENABLED=false`, validate with the guard, recreate api, worker, beat. Or the operator closes the business's grant (`python -m app.cli google-agency-revoke-grant ...`), or the client presses "Stop FlowQR managing my profile" | The stored agency login and client tokens are not removed. A connection returns to the client's own login with `google-agency-rollback` while the client token is still held. |
| An outgoing Google action went wrong | Emergency stop: platform `AUTONOMY_EMERGENCY_STOP=true` (validate, recreate) or the admin endpoint `PUT /admin/autonomy/emergency-stop` | Posts stay scheduled and publish when lifted. |

## 6. Recovery

| Disaster | Procedure |
|---|---|
| Bad data or a bad job | Stop the writers (`stop worker beat api`). Restore the latest good backup into a **new** database, compare with the live one, and only then decide what to move. Never restore over the live database. |
| Database volume lost | Provision the stack with the same compose files, restore `backups/*.sql.gz.enc` (decrypt with the passphrase from your off-server copy), start only `db`, run `verify-restore.sh` logic by hand (tables, `alembic current`, RLS policy count), then start `migrate`, `api`, `worker`, `beat`. **After any restore, run the Google-content retention job before serving traffic** (the backup is redacted but the rule is the rule: `docs/audits/GOOGLE_RETENTION_ARCHITECTURE.md`). |
| Server lost | Rebuild from this repository, `docs/PRODUCTION_SECRETS_RECOVERY.md` (the secrets you must have kept off the server), the latest **off-site** backup, DNS and the shared proxy's two site blocks (`deploy/vps/Caddyfile.flowqr-*`). **Without an off-site copy this is not recoverable.** |
| Lost the backup passphrase | The backups cannot be opened. Keep a copy in a password manager. |

The restore mechanics were rehearsed on 2026-11-22 against a throwaway database: a real `backup.sh` run (redacted, AES-256, sha256, read-back) and `verify-restore.sh --from-remote` (118 tables, migration `0065`, 96 RLS policies, row counts equal), and a corrupted copy was refused by all three integrity layers (`docs/evidence/production-audit-2026-11-22/backup-restore-rehearsal.txt`).

## 7. Monitoring and alerts

* **Admin > Operations** shows database, Redis, migrations, heartbeat, per-job failures, failed work (replies, posts, photos, **location syncs in error**), Google access, AI limits, subscriptions, retention, backup. `ops_watch` runs every 15 minutes and e-mails platform admins when a check newly turns critical: this needs working SMTP, so test one alert e-mail.
* **A location in error** now shows a plain sentence and a back-off time (5 minutes doubling to 6 hours). It recovers by itself when the cause is gone. Celery still reports the job as "succeeded": trust the Operations page, not the worker log line.
* **Error reporting** (`SENTRY_DSN`) was reported unset; set it and confirm a test event arrives.
* **Nightly backup** alerts by e-mail whenever the result is not fully safe. **Until an off-site destination exists it is never fully safe, so expect that alert every night.**

## 8. Gates that need you (not done, not claimed)

1. **Off-site backup.** Choose a destination (an S3-compatible bucket, an `rclone` remote, or another host). Put `BACKUP_REMOTE=...` in `/opt/flowqr/.env.backup`, keep the passphrase (`/opt/flowqr/.backup.pass`) in a password manager. Run `./deploy/backup.sh` (expect `offsite=true`), then `./deploy/verify-restore.sh --from-remote`. Confirm the nightly cron exists (`deploy/vps/install-backup-schedule.sh`, once, as the deploy user). Set the remote store's own retention at or below the local `BACKUP_KEEP_DAYS` (the Google-content storage limit applies to it).
2. **Operator activation.** The allowlisted operator registers at the sign-up page and verifies the mailbox. Then `python -m app.cli google-agency-grant --tenant-id <tenant> --operator <operator address> --note "<why>"` (or the API with their session). Then the **client's own administrator** opens the consent screen and agrees. Only then check access with the agency token. Record who did what and when from the audit log. Do not create any of these on someone's behalf.
3. **Google's written answer** on third-party agency use (`docs/audits/GOOGLE_QUESTIONS_TO_SUBMIT.md`, not sent). Until it exists, internal-only stays on and nothing here changes.
4. **Live checks you can authorise:** `python -m app.cli google-smoke` (read-only) on an authorised account; a Cashfree sandbox checkout with your credentials; a real mailbox for verification, reset and invitation e-mails.
5. **Decisions:** an operator screen (audit O-1); the foreign-key index migration `0066` (O-4: indexes created `CONCURRENTLY`, one reviewed migration, backed up first); Sentry (O-6).

## 9. Approval record (fill in before step 1)

| Item | Entry |
|---|---|
| Commit and image tag to release | |
| Rollback image tag and Vercel deployment | |
| Migration | none (head stays `0065`) |
| Environment changes | none |
| Backup file and restore proof | |
| Approved by, date, time | |
