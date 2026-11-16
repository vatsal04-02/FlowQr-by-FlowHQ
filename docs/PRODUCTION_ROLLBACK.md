# Production rollback and recovery

**Status: procedures written; NOT TESTED on the VPS.** The generic procedures (which migrations can be reversed and what they destroy, restoring a backup, individual recovery recipes) are in `docs/ROLLBACK_AND_RECOVERY.md`; this file is the FlowQR-on-the-shared-VPS and Vercel specifics. The first deployment starts from an empty database, so there is nothing to roll back **to** yet except "off".

## Fastest safe "off" (any time, no data loss)

1. **Hold every Google write:** set `AUTONOMY_EMERGENCY_STOP=true` in `/opt/flowqr/.env.production` and `$C up -d api worker beat` (or use Admin > Operations > Emergency stop). Held work waits; nothing is deleted. Business-level: AI > Autonomy > the switch.
2. **Take the API out of service without touching the other applications:** remove (or comment out) only the `api.flowqr.site { ... }` block in the existing Caddyfile, `caddy validate`, `caddy reload`. The clinic, n8n and Grist keep running. **Do not** stop Caddy or any container that is not in the `flowqr-production` project.
3. **Stop only FlowQR:** `docker compose -p flowqr-production --env-file .env.production -f docker-compose.yml -f deploy/vps/docker-compose.vps.yml stop` (keeps data). **Never** `down -v` in production: it deletes the database volume.

## Frontend (Vercel)

Vercel keeps every deployment: **Instant Rollback** to the previous production deployment (dashboard, or `vercel rollback`). The frontend has no database and no state, so a rollback is always safe for data. If the new frontend needs a newer API, roll the pair back together. A bad `NEXT_PUBLIC_API_URL` needs a redeploy (it is compiled in), not just a variable change.

## Backend release that goes wrong

| Symptom | Action |
|---|---|
| `migrate` exits non-zero | stop; read `$C logs migrate`; the database is unchanged by a failed migration step (each runs in a transaction); restore the pre-release backup if in doubt; do not re-run blindly |
| API unhealthy after a release | `$C logs api`; roll the **image** back (`FLOWQR_TAG=<previous>`) keeping the schema **only if** the new migration was additive (0029 to 0031 were: the previous API started on the upgraded schema in a test, one start-up and one read; not a regression run); otherwise restore |
| Data wrong or lost | stop writes (emergency stop, step 2 above), restore the last verified backup into an **isolated** database first, compare, then `deploy/restore.sh` (DESTRUCTIVE, asks for `yes`), then re-apply business deletions made after the backup |
| Secrets exposed | rotate at the provider, update `.env.production`, restart; **rotating `TOKEN_ENCRYPTION_KEY` makes stored Google tokens unreadable** (customers reconnect) |

## What a downgrade destroys

`0031` down: turns autonomy off for every row and drops the auto-reply columns; replies already sent to Google stay. `0030` down: drops the usage ledger. `0029` down: deletes subscription history and promotional grants. Prefer restoring a backup to downgrading after real activity.

## Order for a full rollback of a release

Frontend (Vercel rollback) → emergency stop → API image or restore → verify `/api/ready`, sign-in, one QR scan, Admin > Operations → lift the stop. Record what happened in the release report.
