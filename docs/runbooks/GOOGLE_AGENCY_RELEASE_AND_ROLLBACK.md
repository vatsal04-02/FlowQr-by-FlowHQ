# RUNBOOK: Google agency migration, release record, deployment and rollback

Branch `release/gbp-agency` (local worktree `wt-release`), based on production's source tip `1bd1062`. **Nothing in this document has been run against production except the read-only checks listed under "Production state".** All agency switches default **off**; Google policy clearance for the shared-project agency model is **not established** (`docs/audits/GOOGLE_AGENCY_POLICY_STATUS.md`), so enabling anything is out of scope for this release.

## 1. Baseline and reconciliation record (2026-11-21)

| Worktree / branch | Head | Uncommitted | What it held |
|---|---|---|---|
| `wt-audit` / `audit/security-privacy-gbp` | `425ee2d` | 47 files | Agency code through migration 0062: OAuth state, identity guard, `--listen`, `google-agency-check`, adopt-existing, keep window, rollback, resource-name correction. Full backend suite there: 3301 passed, 2 skipped. |
| `wt-onboard` / `feature/gbp-agency-onboarding` | `425ee2d` | 46 files | An earlier snapshot of the same uncommitted tree plus onboarding: migration 0063, scope and replay protection, `GOOGLE_AGENCY_OPERATIONS_ENABLED` / policy reference, dashboard states, audit listener. |

Both were left **untouched** (no reset, clean, overwrite or force-push). They share no common commit for their uncommitted changes, so the merge was done by diff: `diff` of every shared file showed that each side's changes were separate hunks. Result in `wt-release`:

* `agency.py`: onboarding's file as the base (it has the dashboard, scope, replay, operations gate), plus every audit-only hunk (OAuth state and identity guard, adopt-existing, claimed-by-another-tenant guard, keep window, rollback, unknown-admin-name handling).
* `config.py`: audit file plus onboarding's four settings and the policy-reference guard. `fake_agency_google.py`: audit file plus onboarding's place-id support.
* Frontend `AgencyManager.tsx`, `agency-ui.ts` and their tests: onboarding's (a superset).
* Tests: onboarding's migration-head assertions (0063). One audit test, "a second business cannot take over a location another business already holds", was rewritten: the stronger consent-time refusal (onboarding's platform-wide unique index) now fires first, and the old later check is kept and tested as defence in depth.
* **Deliberately not carried over:** the three audit commits' legal drafts, public legal pages, `package.json` changes and the unrelated audit fixes (`1bd1062..425ee2d`). They are not part of this migration and the user did not ask for them.

Migrations: `0060` (production) -> `0061` -> `0062` -> `0063`, one head. No migration was renumbered. 0061 and 0062 were never applied anywhere except local throwaway databases; 0063 was written on top of 0062.

## 2. What the three migrations do (all additive)

| | Adds | Existing rows | Reversible |
|---|---|---|---|
| 0061 | tables `google_agency_accounts` (platform-only, own encryption key) and `google_agency_authorizations`; `google_connections.auth_mode` (default `client_token`), `agency_account_id`, `agency_switched_at`; `google_locations.client_google_account_name` | every connection becomes `client_token` (what it already was) | `downgrade` drops them; tested round trip |
| 0062 | `google_agency_accounts.location_group_name`; authorization `target_type`, `target_account_name`, `receiving_account_name` | existing authorizations (none in production) default to the individual target | tested round trip |
| 0063 | authorization `google_location_resource`, `invite_scope`, `consent_request_id`, `last_polled_at`; status `withdrawn`; a partial UNIQUE index (one open authorization per Google location across all businesses) | back-fills the resource from the location row; the index cannot fail on production because there are **no** authorizations there | tested round trip; downgrade maps `withdrawn` to `cancelled` |

Checked for production: no customer token column is touched; `google_connections` gets columns with a constant default (no table rewrite on PostgreSQL 16); the unique index is created on an empty table; RLS and grants are covered by the migration tests (the application role cannot read the platform-only table).

## 3. Production state (read-only, 2026-11-21)

* VPS containers: api, worker, beat on image `prod-72bd037`, healthy; db and redis healthy. `alembic_version` = **0060**.
* No agency table or column exists in production (a query for `google_connections.auth_mode` fails with "column does not exist", as expected).
* The Geeta location resource is held by exactly **one** FlowQR connection: tenant `e9e744ec` (redacted), connection active, location selected, last sync ok, 482 reviews. No other tenant holds it.
* Backups present: `/opt/flowqr/backups/pre-whatsapp3-20261121025552.dump` and the env/compose copies of that release.
* Disk 50% used.

## 4. Evidence from the isolated end-to-end run (real Google reads only)

Run on a throwaway copy of the local agency database (upgraded to 0063), the real agency token, with every Google write method blocked in code. Counts and codes only; no review content was printed or kept (the copy was dropped afterwards).

* Flow: consent, then the adopt-existing path used only `list_accounts`, `list_admins`, `list_group_locations` (all GET) and reached `active`. No write attempted; the client's own token was kept, not revoked.
* Resolver: tenant, group and location resource all matched.
* Reviews through the agency login: sync 1 = 482 reviews over 10 pages (production holds 482 for the same location); sync 2 = 0 new, 0 updated, 1 page, 0 duplicates.
* Isolation: another tenant on the same agency login was refused for its own location (`no_mapping`), for the client's location and the reverse (`tenant_mismatch`); its sync sent no request and stored 0 reviews.
* Audit trail: `google.agency.used` recorded for the client's tenant; `google.agency.resolution_denied` recorded for each refusal.
* `google-agency-check` with `--connection-id`: all seven checks PASS, including the tenant mapping (it was SKIP before).

This is evidence that the code and the API work. It is **not** Google's approval of the model.

## 5. Deployment steps (NOT executed; for a person to approve)

Only after the full suites in section 7 are green and the owner approves schema changes. With all agency switches off nothing in the product changes for any customer, so there is no urgency.

1. Fetch and confirm production's source tip is still `1bd1062` (others deploy from the same branch). Rebase or merge if not, and rerun the suites.
2. Back up (on the VPS, as `flowqr`): a database dump to `/opt/flowqr/backups/pre-agency-<UTC timestamp>.dump`, and copies of `.env.production`, `docker-compose.yml` and `deploy/vps/docker-compose.vps.yml`. Confirm the dump restores (`deploy/verify-restore.sh`).
3. Build and tag the backend image `prod-<short sha>` from this branch.
4. Run the migration as the table owner: `docker compose -p flowqr-production --env-file .env.production -f docker-compose.yml -f deploy/vps/docker-compose.vps.yml run --rm --no-deps -T migrate`. Expect 0061, 0062, 0063 and `alembic current` = 0063.
5. Recreate `api worker beat` with **both** compose files and `--no-deps` (one file alone drops the API off Caddy). Check `docker port flowqr-production-api-1` shows `172.17.0.1:18000` and `https://api.flowqr.site/api/ready` is 200.
6. Compare data fingerprints (users, tenants, memberships, QR cards, subscriptions, audit rows) before and after, and the env diff (the image tag only).
7. Do **not** add any agency variable to `deploy/vps/docker-compose.vps.yml`: they therefore cannot reach the application, which keeps every agency path off even if `.env.production` is edited.
8. Frontend: pushing this branch creates a Vercel **Preview** only (corrected: see section 8); production is published with the CLI from a clean archive. The agency screen renders nothing unless the server's status route answers, and with the backend flags off it answers 404, so the visible app is unchanged. Verify `www.flowqr.site` after the build and keep `flowqr-brpitfyq6` as the rollback target.

## 6. Safeguards that must not change

`AUTONOMY_EMERGENCY_STOP=true`, `REGISTRATION_MODE=allowlist`, `GOOGLE_AGENCY_MANAGER_ENABLED=false`, `GOOGLE_AGENCY_OPERATIONS_ENABLED=false`, no `GOOGLE_AGENCY_POLICY_REFERENCE`. In production the start-up guard refuses operations without the reference, and `operations_enabled()` answers no at run time without it.

## 7. Rollback

| Situation | Action |
|---|---|
| Backend release misbehaves | `FLOWQR_TAG=prod-72bd037`, then `up -d --no-deps api worker beat` with both compose files. The 0061-0063 columns and tables are additive and ignored by the older image, so the schema can stay. |
| Schema must go (not needed for safety) | `alembic downgrade 0060` as the owner after the older image is running. It drops only the agency tables and columns. Restore from the pre-release dump only if a downgrade fails. |
| Frontend | Vercel promote/alias `flowqr-brpitfyq6` (the build before this branch). |
| Agency path misbehaves (it is off) | Keep or set `GOOGLE_AGENCY_MANAGER_ENABLED=false`: every agency connection then fails closed (`GoogleAgencyUnavailable`) without changing stored state; flipping it back resumes. |
| A connection must return to the client's own login | `python -m app.cli google-agency-rollback --connection-id <id>` while the client's token is still held (`GOOGLE_AGENCY_CLIENT_TOKEN_KEEP_HOURS` > 0), or have the client reconnect Google. The owner-OAuth route is untouched and stays the default. |
| Wrong tenant mapping | Set that authorization to `cancelled` (`UPDATE google_agency_authorizations SET status='cancelled', failure_code='manual_unmap' WHERE id=...`), return the connection to `client_token`, and ask the client to reconnect. The resolver already refuses a mismatched tenant. |
| Duplicate location mapping | The database refuses a second open authorization per location; if two businesses claim one location, a person decides who owns it (`location_claimed` alert) and cancels the other. |
| Agency token refresh fails / login revoked | The agency account is marked `revoked`, every client on it pauses (no Google call), an alert is sent; re-register with `google-agency-register --listen --expect-email`. Client connections are not changed. |
| Failed background jobs | Housekeeping retries with backoff; a failed sync records the resolution code on the location (`last_sync_error`) and sends nothing to Google. |
| Google API errors / quota | Existing handling is unchanged: 429 and 5xx back off, "not approved" is recorded as awaiting approval, 403 on an agency connection triggers the lost-access check. |

Do not remove the old agency account `apigbp@gmail.com` or any client token until the new path has been proven in production and a rollback period has passed.

## 8. Deployment record (2026-11-21 evening, IST 23:30 to 00:10)

Executed under the owner's directive of 2026-11-21 (deploy the compatible, non-activating changes; keep every agency switch off). Source commit `6d61d85` (tests-only commit `a7637f7` follows it; the image holds the same application code).

| Step | Evidence |
|---|---|
| Pre-checks | tag `prod-72bd037`, alembic 0060, compose md5 `5f7044c5` / `6e958cac`, no other deployment running, disk 50% |
| Backup | `/opt/flowqr/backups/pre-agency-20261121180610.dump` (782 KB), `env.production.`, `docker-compose.yml.` and `docker-compose.vps.yml.pre-agency-20261121180610`; the dump restored cleanly into a throwaway database |
| Rehearsal | on that restore, inside the VPS db container: upgrade 0060 to 0064, row counts identical, 2 of 2 connections `client_token`, 0 agency rows, every review stamped; downgrade to 0060 removed the agency tables, row counts identical; upgrade again to 0064; database dropped |
| Image | `flowqr-backend:prod-6d61d85`, built from a clean `git archive`, id `08013831d322` identical locally and on the VPS |
| Migration | `run --rm --no-deps -T migrate` as the table owner; alembic = **0064** |
| Recreate | `up -d --no-deps api worker beat` with both compose files; `/api/ready` 200 on `172.17.0.1:18000`; port 172.17.0.1:18000 present; compose files byte-identical; env diff = `FLOWQR_TAG` only |
| Frontend | Vercel production `flowqr-64e2pa1gc` (CLI recipe from `git archive a7637f7 frontend`), aliased to www.flowqr.site and flowqr.site; rollback target `flowqr-brpitfyq6` |

**Interruption to report.** `/api/ready` also checks that the database is at the migration head the running image expects, so between the migration finishing and the new containers starting, the public API answered **503** (a few minutes by my reckoning; a script mistake of mine, the compose `run` consumed the rest of the script from stdin, lengthened it). Existing sessions and cards were not changed. A future deploy should recreate the containers in the same command that follows the migration, or run the migration last-moment with `up -d` doing both (the `migrate` service is a dependency of api).

**After:** row counts identical to before (users 4, tenants 5, memberships 4, qr_cards 10, subscriptions 5, audit_logs 170, reviews 483, google_connections 2 with 2 refresh tokens, google_locations 2); the running api container reports `app_env=production`, `autonomy_emergency_stop=True`, `registration_mode=allowlist`, `google_agency_manager_enabled=False`, `google_agency_operations_enabled=False`, empty policy reference, `google_content_retention_enabled=False`; beat schedule now lists `google-content-retention` (does nothing while off); 0 error lines in api, worker and beat logs; card host `go.flowqr.site` still answers 302.

**Domains.** Production deployment before: `flowqr-brpitfyq6` (target production, aliases www.flowqr.site, flowqr.site, flowqr-gold.vercel.app). Pushing a non-production branch creates a **Preview** only (an earlier line in section 5 that said a push publishes a production build was wrong). `app.flowqr.co.in` was not assigned to anything: `flowqr.co.in` does not exist in DNS (NXDOMAIN from 8.8.8.8), is not among the three domains in the Vercel account (flowqr.site, flowhq.co.in, geetakrishnaphysiotherapy.co.in), and production's `FRONTEND_URL` is `https://flowqr.site`. It is not a failure of this release; the domain was never set up. No DNS or Vercel domain was changed.

## 9. Retention release and activation record (2026-11-21 evening, UTC 19:15 to 19:40)

Backend image `flowqr-backend:prod-31d1ccf` (source commit `31d1ccf`, branch `release/gbp-agency`; id `9706bc73f13a`, identical locally and on the VPS). **No migration** (head stays 0064). Rollback targets still on the server: `prod-6d61d85` and `prod-72bd037`.

| Step | Evidence |
|---|---|
| Backup | `/opt/flowqr/backups/pre-retention-20261121193257.dump` (800 KB), `env.production.pre-retention-` and `docker-compose.vps.yml.pre-retention-` copies |
| Overlay | `deploy/vps/docker-compose.vps.yml` gained exactly four lines (the `GOOGLE_CONTENT_*` variables, defaults off/30/redact/false); the base `docker-compose.yml` md5 `5f7044c5` is unchanged; the overlay is now md5 `bd72cf75` |
| Deploy script | run as a **file** with `</dev/null` on every compose call (the earlier stdin problem), recreate api/worker/beat with both compose files; `/api/ready` 200 after ~15 s, public 200 immediately (no 503 window this time), port 172.17.0.1:18000 present |
| Dry runs in production (counts only) | now, +1, +7 days: 0 everywhere. **+31 days: 483 reviews, 1 snapshot, 3,560 metric rows, 1 draft would expire** (the oldest stored record is dated 2026-11-15, so nothing is past 30 days before **2026-12-15**) |
| Activation | `.env.production` gained `GOOGLE_CONTENT_RETENTION_ENABLED=true`, `GOOGLE_CONTENT_RETENTION_DAYS=30`, `GOOGLE_CONTENT_RETENTION_ACTION=redact` (no other line changed); api, worker, beat recreated |
| Running state | api and worker report retention on, 30 days, redact, delete-on-disconnect false, agency manager and operations false, project model empty, `autonomy_emergency_stop=True`, `registration_mode=allowlist` |
| Scheduler | beat lists `google-content-retention` (86400 s); the job was sent through the broker and **the worker ran it** (`succeeded`, audit entry `retention.google_content_run` with counts all 0 and errors `[]`); Admin > Operations check `google_retention` = ok |
| Deleted so far | **nothing**: no record is older than 30 days yet. That is the truthful state, not a failure. The mechanism was proven on a throwaway copy of the real client's 482 reviews with the job's own look-ahead (text, names and reply copy: 412, 482, 482 before, 0 after; ratings kept; second run finds nothing; a real read-only sync did not refill them) |

**Not done, needs a person:** the daily pruning of manual dumps. `deploy/prune-manual-dumps.sh` is installed on the VPS and its dry run works (0 dumps older than 30 days), but installing the cron entry was denied by the sandbox. Run once on the VPS as `flowqr`: `( crontab -l; echo '20 3 * * * BACKUP_DIR=/opt/flowqr/backups /opt/flowqr/deploy/prune-manual-dumps.sh >> /opt/flowqr/backups/prune.log 2>&1' ) | crontab -`.

**Roll back retention:** set `GOOGLE_CONTENT_RETENTION_ENABLED=false` in `.env.production` and recreate api, worker and beat with both compose files (the job then does nothing). Anything already redacted cannot be restored from Google by the sync (by design); restore from a dump if ever needed.

## 10. Internal agency activation and backup compliance (2026-11-22, UTC 10:40 to 10:55)

Backend image `flowqr-backend:prod-2945623` (id `859b1b946253`, identical locally and on the VPS; source `release/gbp-agency` at 2945623, later commits are docs). **No migration** (head 0064). Rollback targets on the server: `prod-31d1ccf`, `prod-6d61d85`, `prod-72bd037`.

| Step | Evidence |
|---|---|
| Backups first | env, overlay and `backup.sh` copies `*.pre-internal-20261122104043`, and a database copy `pre-internal-20261122104043.sql.gz` made with the NEW redacted-dump pipeline (it also proved that pipeline works on production) |
| Overlay | the agency variables (all default off) and the `GOOGLE_CONTENT_*` ones are passed through; base compose md5 `5f7044c5` unchanged |
| Agency key | `AGENCY_TOKEN_ENCRYPTION_KEY` generated on the server, never printed, different from the customer token key |
| **Interruption (mine)** | the first recreate set `GOOGLE_AGENCY_ADOPT_EXISTING_ACCESS=true` while the manager switch was still off; the production start-up guard correctly refused to start the API (`Unsafe production configuration`), and the public API answered 503 for roughly 3 to 5 minutes until I corrected the setting. `docker compose config` only renders the compose file, it does not run the application's guard. **Since then every configuration change is validated with the real guard first** (`compose run --rm --no-deps -T api python -c "import app.main"`) and the environment file is restored if it refuses (`enable_agency.sh`) |
| Agency login | brought into production with `google-agency-import-login` (token piped over ssh from the isolated database, never printed, re-encrypted with the production key; Google confirmed it belongs to `vatsal@flowhq.co.in`; the original login and every customer token were not touched or revoked) |
| Real read-only check in production | `google-agency-check` all 7 PASS: identity, `accounts/114863040359228435467` typed LOCATION_GROUP, 1 location in the group, exactly one title match `locations/726682899335438012`, review read (50 on the first page, none shown), tenant mapping to business `e9e744ec` (mode `client_token`, active) |
| Switches | guard accepted the configuration in a throwaway container, then api, worker and beat were recreated: manager on, operations on, project model `flowhq_own_project`, **internal-only on with one operator**, adopt-existing on, client-token keep window 720 h, individual fallback off, no policy reference (none exists) |
| Running state (inside the api container) | the flags above, `google_content_retention_enabled=True`, `autonomy_emergency_stop=True`, `registration_mode=allowlist`, `operations_enabled()` = True; `google-agency-activation-check` = **READY, 16 of 16 PASS** |
| Operator rule | `is_operator`: `vatsal@flowhq.co.in` (any case) True; a customer address, another FlowHQ address, None and empty False; the unauthenticated status route answers 401 |
| Not done on purpose | no consent or authorization exists (0 authorizations), so **nothing has been switched**: Geeta's live connection still runs on its owner token. Switching it, or any client, is an operator action that records the client's consent, and nothing automatic does it |
| Backups | the real nightly job ran through the redacted pipeline: encrypted backup written, status ok, scratch database dropped, manual-dump pruning ran (0 older than 14 days); the newest encrypted backup was decrypted and restored into a throwaway database and matched live (users 4, tenants 5, reviews 483, connections 2, agency accounts 1); that database was dropped. The script exits non-zero while `BACKUP_REMOTE` is unset (no off-site copy) as it always has, and sent its usual alert e-mail |

**An operator cannot use the screen yet:** `vatsal@flowhq.co.in` has no account in production (checked read-only: no user, no membership of tenant `e9e744ec`). `REGISTRATION_MODE=allowlist` stays on, so adding that address to the allowlist and registering/inviting it into the tenant is a person's action (not done here). Until then agency operations cannot be started from the app, which is the safe state.

**Roll back the agency path:** set `GOOGLE_AGENCY_MANAGER_ENABLED=false` and `GOOGLE_AGENCY_OPERATIONS_ENABLED=false` in `.env.production`, validate with the guard, recreate api, worker and beat with both compose files. The stored agency login stays encrypted and unused. To remove it entirely: `UPDATE google_agency_accounts SET status='revoked'` (never delete the Google login itself without a decision).

## 11. Operator onboarding, grants and verified off-site backups (2026-11-22, UTC 11:00 to 11:45)

Backend image `flowqr-backend:prod-10bcbbe` (id `4b0911d02d7b`, identical locally and on the VPS), migration **0065**. Rollback images on the server: `prod-2945623`, `prod-31d1ccf`, `prod-6d61d85`, `prod-72bd037`.

**Who does what (the design that replaces "the operator consents").** A FlowHQ **operator** (a listed address in `GOOGLE_AGENCY_OPERATOR_EMAILS`, no business role, no membership in any business) can open or close the agency path for one business (`/api/v1/agency-ops/...` or `google-agency-grant` / `google-agency-revoke-grant`): that is a **grant**, recorded with the operator, business and time in a platform-only table. The **client's own administrator** then gives the consent (the existing screen, `/google/agency/consent`), recorded with the client's identity, location, version and time. Without a grant a business gets 404 on every agency route and the service refuses to record a consent; closing the grant stops every later use of the agency login for that business (`tenant_not_granted`) without touching the client's own authorization or token. The operator never sees a token, a review or any Google content.

| Step | Evidence |
|---|---|
| Backup first | env and `backup.sh` copies `*.pre-grants-20261122114007` and a database copy `pre-grants-20261122114007.sql.gz` through the redacted pipeline |
| Guard | the NEW image accepted the production configuration in a throwaway container before any running container was touched |
| Migration and recreate | `run --rm --no-deps -T migrate` then `up -d --no-deps api worker beat` back to back: alembic **0065**, `/api/ready` 200 locally after ~15 s; the **public** endpoint answered 503 for roughly 20 to 30 s after the recreate (Caddy's upstream check lags a few seconds behind), then 200 |
| Production state | `google_agency_tenant_grants` exists with 0 rows; unauthenticated `/agency-ops/tenants` = 401; the grant command with a non-operator address FAILS and writes nothing; readiness check READY; tenant `e9e744ec` path open = **False**; flags unchanged (manager, operations, internal-only, retention on; emergency stop on; allowlist); 0 error lines in api, worker, beat |
| Registration allowlist | `vatsal@flowhq.co.in` added with `python -m app.cli registration --add` (note "FlowHQ internal agency operator"): the address may now register, a stranger may not; `REGISTRATION_MODE=allowlist` unchanged; **no account was created**: the person registers and verifies the address themselves |
| Not done on purpose | no grant and no consent were recorded: a grant attributed to an operator who has not acted, or a consent nobody gave, would be a fabrication |
| Off-site backups | the code path is now verified: upload, **read back and compare sha256** before `offsite` is marked true, remote pruning to the same retention (directory, ssh and rclone destinations; for S3 set a lifecycle rule), status file field `offsite_verified_at`, non-zero exit and the existing alert e-mail on any failure. Tested on the VPS against a throwaway directory destination (mechanism only, same server, NOT off-site): upload verified, an unreachable destination failed loudly, the destination copy restored into an isolated database equal to live (117 tables, 4 users, 483 reviews). **No real off-site destination is configured**, so off-site backup is **not operational** |

**To finish (people):** (1) `vatsal@flowhq.co.in` registers at the sign-up page and verifies the address. (2) That operator opens the path for the client: `python -m app.cli google-agency-grant --tenant-id e9e744ec-c3ef-42b7-99c3-1720adea64a6 --operator vatsal@flowhq.co.in --note "..."` (or the API with their session). (3) The client's own administrator of that business opens the consent screen and agrees (or declines); only then does the flow check access with the agency token and, if the client has not been invited, invite the group, and the revoke-the-client-token step is held back by the 720-hour keep window. (4) An off-site destination (see below). **Revoke:** the operator closes the grant (immediate stop of use), or the client presses "Stop FlowQR managing my profile".

**Off-site destination, what is needed:** one of `user@host:/path` (ssh key for the backup user; the destination should be a different machine), `s3://bucket/prefix` (credentials via the AWS CLI environment; a lifecycle rule expiring objects after `BACKUP_KEEP_DAYS` days) or `rclone:remote:path`. Set `BACKUP_REMOTE` in `/opt/flowqr/.env.backup` (the nightly job reads it). The backup is already encrypted before it leaves; the passphrase file must also be kept off the server.
