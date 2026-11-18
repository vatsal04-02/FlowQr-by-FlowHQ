# Admin-managed businesses: release preparation

Prepared 2026-11-18. **Status: approved for release preparation, NOT approved for production deployment.** Nothing in this document has been run against production except the read-only checks listed in section 2. Feature description: `ADMIN_MANAGED_BUSINESSES.md`.

## 1. What is being released

Branch `feature/admin-business-directory` = the release branch tip (`455f05d`) plus the admin-managed business onboarding work (commit `20e3f04`, merge `081105d`, and the follow-up that makes a deletion reason mandatory). It contains the four later improvements: the ownerless export/deletion request workflow, claim revocation with optional allowlist removal, the New business option in scan-to-assign, and the managed usage and cost page.

Against production the backend differs from what is live by this feature only. Production runs image `prod-548221c`, which is an ancestor of the branch and has **no backend difference** from the release tip, so the backend diff is exactly the feature (23 files). The live frontend (Vercel `flowqr-7331zexzb`) was built from `455f05d`; the feature adds admin-console pages only.

## 2. State of production (read-only checks, 2026-11-18)

| Item | Found |
|---|---|
| Backend image | `FLOWQR_TAG=prod-548221c`, alembic **0045** |
| Compose files in use | `/opt/flowqr/docker-compose.yml` + `/opt/flowqr/deploy/vps/docker-compose.vps.yml` |
| Safety settings | `AUTONOMY_EMERGENCY_STOP=true`, `REGISTRATION_MODE=allowlist`, `APP_ENV=production` |
| Claim settings | **absent** from the deployed compose file and from `.env.production`; the running code has no such setting. Claiming cannot be on |
| Migration 0046 | not applied (`tenants.origin`, `data_requests`, `tenant_agreements` do not exist) |
| Launch plan (`billing_plans.starter`) | active, **200 review writings, 200 replies**, 1 location, 3 staff, 400 combined |
| Size | 4 tenants, 4 users, 10 cards; 3 allowlist rows; 0 invitations |
| Platform administrators | **1** |
| Disk | 50 GB free of 96 GB |

The deployed `docker-compose.yml` differs from the repository copy in two ways: a cosmetic comment on `PREPAID_CHECKOUT_ENABLED`, and **a production-only line `TRIAL_REQUIRES_MANDATE: ${TRIAL_REQUIRES_MANDATE:-}`** (added on 2026-11-17 so trials stay cardless). The repository copy does not have that line. **Never overwrite the server's compose file with the repository copy**: doing so silently removes the passthrough and trials would revert to payment-first.

## 3. Claim invitation settings (item 6)

`CLAIM_INVITATIONS_ENABLED` defaults to `false` in code (`core/config.py`) and in the repository compose (`${CLAIM_INVITATIONS_ENABLED:-false}`). Production has no passthrough, so even setting the variable in `.env.production` would do nothing until a compose line is added. **No compose or environment change is needed or recommended for this release.** Claiming stays off by construction. To enable it later is a separate, deliberate change: add the two passthrough lines to the server's compose file by a targeted edit (not a file copy), set the variable, recreate api/worker/beat, and have the allowlist consequences reviewed first (a claim adds the address to the registration allowlist).

## 4. Migration chain

- Production: **0045**. Release branch tip: 0045 (single head). Feature branch: **0046** (single head, `0046` revises `0045`, one parent per revision, no duplicate ids; pinned by `tests/test_migration_0046.py::test_the_chain_is_one_linear_line_ending_at_0046_and_0046_hangs_off_0045`).
- Only two branches in the repository add a migration relative to the release branch: this one (`0046`) and `feature/cardless-trial` (`0039`).
- 0046 is **additive**: new nullable/defaulted columns on `tenants` and `invitations`, three new tables. No existing row is changed (`origin` defaults to `self_service`). It was exercised upgrade/downgrade in the test suite and on a database at 0045.

### 4.1 Conflict report: `feature/cardless-trial`

`feature/cardless-trial` is based on an old release commit (`a7d9224`, 78 release commits behind) and carries one migration, `0039_trial_grants`, with `down_revision = "0037"`.

Reproduced in a throwaway worktree (discarded; nothing merged):

- **Alembic:** merging it makes **two heads (`0039`, `0046`)** and a branch point at `0037` (children `0039` and `0040`). `alembic upgrade head` would refuse. It would also be wrong for production in any case: production is already at 0045, and a new revision hanging off 0037 would be a side branch.
- **Textual conflicts: 7 files**, identical with or without this feature, so this feature adds none: `backend/app/api/v1/billing.py`, `backend/app/core/config.py`, `backend/app/models/__init__.py`, `backend/tests/test_migration_0037.py`, `frontend/src/app/(app)/settings/billing/page.tsx`, `frontend/src/lib/billing.ts`, `frontend/src/lib/types.ts`.
- **Semantic overlap to review by hand** (merged cleanly as text, but both change them): `backend/app/api/v1/admin.py`, `backend/app/api/v1/tenants.py`, `backend/app/services/entitlements.py`, `backend/app/schemas/admin.py`, `frontend/src/app/(admin)/admin/customers/[id]/page.tsx` (the trial adds a Free trial card, this feature adds business panels). The two are compatible in intent: an admin-created business gets **no trial** and never touches the trial ledger.

**Recommended resolution (not performed):** do not merge blindly. When the trial branch is brought in: (1) merge the release branch into it first and resolve the 7 conflicts there; (2) renumber its migration to the next free number on top of the then-current head (`0047_trial_grants`, `down_revision = "0046"` if this feature is already released, otherwise `"0045"` and renumber this feature instead; whichever ships second takes the next number); (3) update `tests/test_migration_graph.py` (it asserts the parent is `0037` or `0038`) and the head pins in `tests/test_migration_0037/0040/0041/0042.py`; (4) re-run the full suite including the export drift test for its new tenant tables; (5) its backfill command stays an explicit operator step. Whoever ships second must re-read production's `alembic_version` first.

## 5. Security review findings

| # | Area | Finding | Status |
|---|---|---|---|
| 1 | Ownerless deletion: reason | A deletion had a typed name and acknowledgement but **no mandatory reason** | **Fixed**: `reason` (at least 10 characters) is required by the API and the form; it is stored in the request, its event and the audit entry that survives the business |
| 2 | Single-administrator deletion | One administrator logs, verifies and executes | Mitigated, not removed: verification against the record, 14-day cooling-off, typed exact name, reason, acknowledgement, 5 attempts an hour, full audit. Production has one administrator, so a second-person rule cannot be enforced. Recommended: do not delete any business during the first weeks; review requests weekly |
| 3 | Deletion never automatic | The request does not set `deletion_scheduled_for`, so the daily job cannot pick the business up | Verified by test |
| 4 | Identity verification | Callback, WhatsApp and email checks must use the number or address already on the record; details from the request do not count; no contact on record means that method is refused | Verified by test. An administrator's judgement is still the control |
| 5 | Export | Same ZIP as an owner's, no secrets, generated only after verification, nothing sent by the system, every generation audited | Verified |
| 6 | Claim after request | A claim stops every step (the owner has the real tools) | Verified by test |
| 7 | Deletion and the printed cards | Cards return to stock as unassigned, never to another business | Verified by test |
| 8 | RLS and isolation | `data_requests` and `data_request_events` are platform-only (bypass context only) with forced RLS; no DELETE on either; events insert-only; `tenant_agreements` insert-only; a business session sees none | Verified by test and in the table-protection audit |
| 9 | Access control | 19 new routes, all `platform-admin`, in the reviewed route manifest; anonymous and business owners refused on each with no state change | Verified |
| 10 | Offline agreement | Stored statement says it is **not** the shopkeeper's personal acceptance and **not** an 18+ confirmation; no consent, age or terms field is written by the admin path; audit says `personal_acceptance: false`; the form and page repeat the wording | Verified (code read and tests) |
| 11 | Managed Launch access | Subscription `manual`, plan `starter`, no provider, no trial dates; quotas come from the production Launch plan row (200 and 200); enforced by the existing counters; revoke stops AI only, cards keep working | Verified (tests, and production plan row read) |
| 12 | AI cost monitoring | Usage and cost page uses recorded per-call cost; never guesses; unpriced calls are counted and shown; production has no per-token prices configured, so only recorded costs will appear until `AI_PRICE_IN_PER_MTOK` / `AI_PRICE_OUT_PER_MTOK` are set | Behaves as designed; set prices to get a complete figure |
| 13 | Claim invitations | Off; token stored only as a hash; link shown once; accept refused if the business has an owner; allowlist addition audited; removal on revoke only when this claim created the entry and nothing else needs it | Verified |
| 14 | Application rollback | An old image cannot run migrations on a 0046 database (see section 8) | Documented; rollback uses `--no-deps` |

Residual risks: items 2 and 4 above (judgement of one administrator); `TERMS_VERSION` text needs legal confirmation; ownerless businesses have no self-service privacy path other than this workflow.

## 6. Prerequisites (all must be true before any production step)

1. **Explicit user approval to deploy** (each of: backend, migration, frontend). Approval to prepare is not approval to deploy.
2. `git fetch`; the feature branch contains the current `origin/release/ui-premium` tip (re-merge if it moved; the release branch is very busy).
3. Full backend suite, frontend unit tests, `tsc --noEmit` and `next build` all green on the exact commit to be released; the working tree is clean and the commit is the one that is built.
4. Re-read production: `FLOWQR_TAG`, `alembic_version`, running image, compose label, and that no other session is deploying (they deploy to the same VPS).
5. Backups taken and verified (section 7). 50 GB free is ample.
6. A rehearsal of 0046 on a restored copy of the dump (throwaway database, deleted afterwards) succeeded, including `alembic downgrade 0045` and re-upgrade.
7. No admin-managed business, QR batch or assignment is created as part of the deployment. First use is a separate approved step; the controlled physical QR/NFC test needs its own approval.
8. Claim invitations stay disabled; autonomy emergency stop stays `true`; payment settings unchanged.

## 7. Backups (before touching anything)

On the VPS, in `/opt/flowqr`, with a timestamp `TS=$(date -u +%Y%m%d%H%M%S)`:

1. Database, custom-format dump: `docker exec flowqr-production-db-1 pg_dump -U <owner> -d <db> -Fc > backups/pre-admin-managed-$TS.dump` (credentials come from the container environment; do not print them). Check it is readable and non-trivial: `pg_restore -l backups/pre-admin-managed-$TS.dump | head` and `ls -l`.
2. Environment and compose: `cp -p .env.production backups/env.production.pre-admin-managed-$TS` and `cp -p docker-compose.yml backups/docker-compose.yml.pre-admin-managed-$TS` (mode 600 for the env copy).
3. Record: current tag (`prod-548221c`), alembic `0045`, row counts of tenants, users, memberships, subscriptions, qr_cards, card_assignments, scan_events, audit_logs, and an md5 fingerprint of tenants/users/subscriptions/qr_cards, to compare after.
4. The nightly encrypted backup (`deploy/backup.sh`) is a separate, off-server copy; confirm the latest ran.

## 8. Rollback plan

**Application rollback (the normal one, no data change):**

1. `FLOWQR_TAG=prod-548221c` in `.env.production`.
2. Recreate with **both** compose files and **`--no-deps`**: `docker compose -p flowqr-production --env-file .env.production -f docker-compose.yml -f deploy/vps/docker-compose.vps.yml up -d --no-deps api worker beat`.
   **Do not run `migrate` with the old image.** Verified: the old code's `alembic upgrade head` against a 0046 database fails with `Can't locate revision identified by '0046'`, and because `api` depends on `migrate` completing, a plain `up` without `--no-deps` would leave the API down.
3. Check `docker port flowqr-production-api-1` shows `172.17.0.1:18000`, `https://api.flowqr.site/api/ready` is 200.
4. Frontend: re-promote Vercel `flowqr-7331zexzb` (the pre-release build).

Why this is safe: 0046 only adds columns with defaults and new tables. Verified with the production code (`548221c`) against a 0046 database: it reads tenants, subscriptions, cards and invitations normally, and creating a tenant and an invitation works and takes the column defaults (`origin = self_service`, `allowlist_entry_id` empty). Businesses created by the new code remain valid (ownerless, with a manual subscription) under old code; they just show without the new panels.

**Schema rollback (only if the schema itself must go; destroys data):** run `alembic downgrade 0045` with the **new** image (it has the 0046 file), as the table owner. It drops `tenant_agreements`, `data_requests`, `data_request_events`, `invitations.allowlist_entry_id` and the four `tenants` columns, **including any recorded agreements, requests and the `origin` marker**. Before it: `\copy` those tables out, and confirm no data request is open. Not needed for an application rollback.

**Full restore (last resort):** `deploy/restore.sh` with the pre-deployment backup. DESTRUCTIVE: everything written after the backup is lost (customer scans, reviews, payments). Stop api/worker/beat first, restore, set the old tag, start with `--no-deps`. Use `deploy/verify-restore.sh` first.

**Rollback triggers:** API not ready within 2 minutes of recreate; migration error; row counts or fingerprints differ from step 7.3; any 5xx on `/api/v1/c/`-style public scan routes or `go.flowqr.site` redirects; an unexpected change in `AUTONOMY_EMERGENCY_STOP`, registration mode or claim setting.

## 9. Exact production deployment sequence (when approved)

Backend first, frontend second. The new frontend calls new admin endpoints; the old frontend works on the new backend, not the other way round.

1. **Local, on the release commit:** fetch; merge the release tip; run the full backend suite, `npm test`, `tsc --noEmit`, `next build`; confirm `git status` is clean; note the commit SHA `<sha>`.
2. **Read-only pre-checks on the VPS:** tag, `alembic_version`, compose label, `docker ps`, that no other deployment is in progress, free disk.
3. **Backups** (section 7).
4. **Rehearse** 0046 on a restored copy of the dump in a throwaway database; run `upgrade`, `downgrade 0045`, `upgrade`; compare fingerprints; delete the copy.
5. **Build and ship the image:** `docker build -t flowqr-backend:prod-<sha> ./backend` from a clean `git archive <sha>` of the release commit; `docker save | ssh ... docker load`; confirm the image id on the server.
6. **Do not touch `docker-compose.yml` on the server.**
7. **Switch the tag:** edit only `FLOWQR_TAG` in `.env.production`.
8. **Recreate** with both compose files: `up -d api worker beat` (the `migrate` service runs automatically as the table owner and applies `0045 -> 0046`; watch the migrate container's logs, expect `0045 -> 0046`).
9. **Verify:** `/api/ready` 200; `docker port flowqr-production-api-1` has `172.17.0.1:18000`; `alembic_version = 0046`; row counts and fingerprints identical to the record; env unchanged (`AUTONOMY_EMERGENCY_STOP=true`, `REGISTRATION_MODE=allowlist`, claim setting still absent); `python -c "from app.core.config import settings; print(settings.claim_invitations_enabled)"` in the api container prints `False`; unauthenticated `GET /api/v1/admin/managed-usage` is 401/403; a public card address (`go.flowqr.site/...`) still redirects as before; worker and beat running.
10. **Frontend:** export the same commit with `git archive <sha> frontend`, copy `frontend/.vercel`, `vercel --prod`; verify the site, `/login`, and (as the platform administrator, no data created) the Businesses page, Usage and cost page and an existing business's detail page load without console errors.
11. **Stop.** Record the new tag, rollback targets (`prod-548221c`, Vercel `flowqr-7331zexzb`) and backup file names in the release notes. Creating the first managed business, setting AI prices, enabling claiming and the physical QR/NFC test are separate decisions, each needing the owner's go-ahead.

## 10. Remaining risks

1. The release branch is busy; a deploy from a stale merge can drop another session's work: re-fetch immediately before building.
2. The server compose file is **not** the repository copy; overwriting it removes `TRIAL_REQUIRES_MANDATE`.
3. A single platform administrator: no second-person approval is possible on deletion.
4. `feature/cardless-trial` will fork the migration chain if merged as is (section 4.1).
5. AI prices are not configured in production, so cost is shown only where a cost was recorded.
6. Rolling back the schema destroys recorded agreements and data requests.
7. Production data used for a rehearsal is real customer data: use a throwaway database on a trusted machine and delete it.
