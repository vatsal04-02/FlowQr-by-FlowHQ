# Agency self-service onboarding: release candidate and deployment plan

Written for the person who approves the deployment. **Nothing in this document has been executed against production.** Every command run on the VPS while preparing it was read-only (`docker ps`, `psql select`, `pg_dump --schema-only`, file listings).

## 1. The release candidate

| | |
|---|---|
| Branch | `integration/agency-self-service-on-43539cc` (local; not pushed) |
| Contains | exactly what production runs (`5ec9e93` = Local SEO V2 + production hardening) **plus** `feature/agency-self-service-onboarding` (`d382fb7`) |
| Agency migration | **renumbered 0066 to 0067** (production's 0066 is `0066_seo_engine_v2`); down_revision 0066; additive; three nullable/defaulted columns |
| Not included | `18d0161` and `8931233` (newer SEO V2 commits that are not deployed), `monitoring/sync-error-critical` (not deployed, see 3.3) |
| Feature flag | `GOOGLE_AGENCY_SELF_SERVICE_ENABLED`, default **false**; with it false the new routes answer 404 and every screen behaves as before |

## 2. Why the first approved commit could not be deployed (recap)

`d382fb7` was built on `release/gbp-agency`, before Local SEO V2 existed, and also called its migration 0066. Deploying it would have (a) left production's database at `0066` so Alembic would have skipped the agency migration and the three columns would never exist, and (b) replaced the running code with a tree lacking SEO V2 and the hardening work. The integration fixes both.

## 3. Findings you asked for

### 3.1 Where `prod-43539cc` came from
`43539cc` is a merge commit by the repository owner's account on 2026-11-23 01:58 IST: `hardening/production-readiness-audit` (tip `0540577`) merged into `feature/local-seo-engine-v2`. The image was built on the VPS and the containers created at 21:01 UTC on 22 Nov by the Local SEO V2 work (its release script, `release2.sh`, is in that session's scratchpad). It therefore contains: Local SEO V2 (migration 0066 and its services, dashboard and live-test tooling) and all of the hardening branch (sync hardening, held-post fairness, form fix, cross-tenant sweep, release-candidate package).

**Production has moved since.** At my second read the containers ran `prod-5ec9e93` (up about 12 minutes), i.e. `43539cc` plus the SEO V2 dashboard frontend changes and a guarded live-test CLI (`faae177`, `5ec9e93`); no migration. The SEO V2 branch has since gained `18d0161` and `8931233`, not yet deployed. So **another session is actively deploying to the same VPS and Vercel project.** The candidate was re-merged onto `5ec9e93` for that reason.

### 3.2 Why `.env.production` names a different image from the running containers
The env file holds `FLOWQR_TAG=prod-10bcbbe` (last written 22 Nov 17:10 UTC). The SEO V2 release script deploys with an **inline override**: `FLOWQR_TAG=$NEW docker compose ... up -d --no-deps api worker beat` (and `FLOWQR_TAG=$OLD ...` for its rollback). Docker Compose gives a shell variable precedence over `--env-file`, so the containers run the new image while the file still says the old one. The containers' labels confirm they were created from `/opt/flowqr/docker-compose.yml` + `deploy/vps/docker-compose.vps.yml` + `.env.production`.

Why this matters:
* Any later `docker compose up` that does not repeat the override (a routine recreate, or someone following the older runbooks) would silently **roll production back to `prod-10bcbbe`**, which has no SEO V2 code but would sit on a 0066 database; `/api/ready` returns 503 when the database head and image head differ, so it would also take the API down.
* Therefore this release **writes the tag into `.env.production`** (after a backup of the file) instead of using an inline override, and the overlay change is installed the same way.

### 3.3 Are the monitoring improvements included?
**No.** `monitoring/sync-error-critical` (`788cb9c`) is not an ancestor of `43539cc` or `5ec9e93`, so it is not in the running image. It adds (a) a backend change so a location failing to sync for 6 hours or more is reported as critical however few locations exist (`services/ops.py` plus a test) and (b) `deploy/vps/heartbeat-ping.sh`, an independent heartbeat script, plus evidence files. It **merges into this candidate without conflicts** (tested with `git merge-tree`). It is deliberately left out so this release contains one change. Decide separately whether to ship it with, before or after this release.

## 4. Migration evidence

Test database: a **schema-only** dump of production (read-only `pg_dump --schema-only --no-owner` over SSH; 118 tables, no data), restored into a throwaway database, stamped `0066`, with one synthetic existing authorization row added, then the candidate's real Alembic scripts run.

| Step | Result |
|---|---|
| Before | alembic `0066`; the three columns absent (0 of 3); 1 existing authorization row |
| `alembic heads` | single head `0067` |
| `alembic upgrade head` | success; `alembic current` = `0067` |
| After | `consent_actions jsonb NULL`, `notices_sent jsonb NOT NULL default '{}'`, `initial_sync_enqueued_at timestamptz NULL` |
| Existing row | survived unchanged; `consent_actions` NULL (meaning: recorded under the earlier wording), `notices_sent {}`, `initial_sync_enqueued_at` NULL |
| Drift check | production-derived schema vs a fresh `alembic upgrade head` of the candidate: identical columns, defaults, indexes, constraint names, RLS flags, policies and grants (3,121 catalog lines each; the only text differences were five partial-index conditions and some CHECK constraints printed with two equivalent spellings of the same expression, verified to vanish when normalised) |
| Chain | one linear chain, no revision id used twice; `0067.down_revision = 0066`; tests `test_migration_0067.py` (3) also prove downgrade drops exactly the three columns, keeps rows, and upgrade restores them |

## 5. Test results for the candidate (final tree, all on throwaway databases, Google replaced by a fake)

| Check | Result |
|---|---|
| Backend, full suite (`pytest tests`, 29 min) | **3602 passed, 0 failed** (SEO V2's and the hardening branch's tests are included and pass) |
| New and changed agency tests | `test_agency_self_service.py` 45, `test_migration_0067.py` 3, route manifest unchanged by the merge (both sides' routes were already present) |
| Frontend `npm test` | **141 passed** (138 agency + SEO V2 + hardening) |
| `tsc --noEmit` | clean |
| `next build` | compiles; `/gbp/connect`, `/admin/agency`, `/seo/*` all built |
| Browser (real Chromium, real app and API, fake Google) | **122 of 122**, desktop 1440, tablet 820, phone 390, on the final merged tree |
| Migration on a production-schema copy at 0066 | passed (section 4) |
| Not run | SEO V2's own browser script (hard-wired to another session's containers and ports; I did not touch them); a real Google run; any production smoke test |

Differences from the previous candidate: backend 3467 to 3602 (the SEO V2 and hardening tests are now in the tree), frontend 138 to 141.

## 6. Proposed deployment sequence

Preconditions, re-read **on the day** (production is a moving target):
1. On the VPS: `docker ps` image tags, `alembic_version`, `.env.production` tag, md5 of the overlay (expected `ba9863a3717f` before the change) and of the base compose (`5f7044c5b7eb`, never replaced).
2. `git fetch`; if `feature/local-seo-engine-v2`, `hardening/*` or anything else has been deployed since `5ec9e93`, **stop and re-merge**; re-run the suites.
3. Agree a short freeze with whoever else deploys (the SEO V2 session), because both use the same host, the same compose project and the same Vercel project.

Backend (one person, one terminal, scripts run as files with `</dev/null`):
4. Back up: copy `.env.production` and `deploy/vps/docker-compose.vps.yml` to `backups/…pre-agency-<ts>` and take a redacted dump with the existing `redacted-dump.sh` pipeline. Abort if it fails.
5. Build the image on the VPS from `git archive <final SHA> backend` and tag it `flowqr-backend:prod-<sha>`. The previous running image stays on the host as the rollback target.
6. Install the overlay with the one added line (md5 will change from `ba9863a3717f`; keep the old file as `.prev`). **Do not copy the base `docker-compose.yml`** (the repository's copy differs from the VPS's; that difference predates this work).
7. Write `FLOWQR_TAG=prod-<sha>` into `.env.production` (this also repairs the stale tag).
8. **Validate with the real guard before touching running containers**: `compose run --rm --no-deps -T api python -c "import app.main"` using both compose files. A refusal means restore the file and stop (a refused configuration took the API down for minutes on 22 Nov).
9. Migrate and recreate back to back with both compose files: `compose run --rm --no-deps -T migrate`, then `compose up -d --no-deps api worker beat`. Expect alembic `0067`. Verify `/api/ready` 200 locally and publicly, `docker port` shows `172.17.0.1:18000`, the three containers healthy.
10. Fingerprint check: row counts of users, tenants, memberships, qr_cards, subscriptions, audit_logs equal before and after; Google sync status of every location unchanged and still running; one Cashfree webhook-free read check; QR redirect check.
11. Flags inside the running container must read: `GOOGLE_AGENCY_SELF_SERVICE_ENABLED=false` (new), the agency switches exactly as they were (manager true, operations true, internal-only true, operators list unchanged), SEO V2 customer writes unchanged and closed, WhatsApp unchanged, emergency stop unchanged.

Frontend:
12. Deploy with the established CLI recipe only: a temp directory containing `frontend/` from `git archive <final SHA>` and `.vercel/project.json`, `vercel --prod`. **Never push** `claude/admiring-edison-e9a7s3` or any branch that Vercel auto-publishes. The current production deployment is `flowqr-ehw0i39vl` (created 03:33 IST on 23 Nov); record it as the frontend rollback target at deploy time.
13. Smoke the live site: `/`, `/login`, `/gbp/locations`, `/seo`, `/admin` as an admin; `/gbp/connect` should say guided connection is not available (flag off); `/admin/agency` should say not available to a non-operator.

Turning the feature on (a **separate, second** approval):
14. Operator account registered through normal sign-up, verified, no membership in a customer business.
15. Set `GOOGLE_AGENCY_SELF_SERVICE_ENABLED=true` in `.env.production`, validate with the guard, recreate api only. `INTERNAL_ONLY` stays true, so only a business an operator has opened can start; Geeta's and every customer's connection stays untouched.
16. The real two-account Google test on a dedicated FlowHQ-owned profile (runbook section 7). Until it passes with Google's own confirmation, the integration is reported as not verified.

## 7. Rollback
**Important, verified in the code:** `/api/ready` compares the database revision with the image's head by strict equality (`services/ops.py check_migrations`). An older image started on a database at `0067` reports "critical" and the API answers 503. So an image-only rollback is **not** enough once 0067 has been applied.

* **Backend rollback (the tested route):** (1) with the candidate image still on the host, run `alembic downgrade 0066` through the migrate service (tested: drops exactly the three new columns and nothing else; if the feature has been used, the consent categories and notice log in those columns are lost, so take a dump first), (2) set `FLOWQR_TAG` back to the previous image in `.env.production` (today `prod-5ec9e93`), restore the overlay `.prev`, (3) `compose up -d --no-deps api worker beat` with both files, (4) confirm `/api/ready` 200 and `docker port` shows `172.17.0.1:18000`.
* If the downgrade is not wanted: keep the candidate image running with `GOOGLE_AGENCY_SELF_SERVICE_ENABLED=false`. That is the lowest-risk "off": the routes answer 404 and nothing else differs from production today.
* **Frontend rollback:** promote the recorded previous production deployment (`flowqr-ehw0i39vl` as of this writing); the new pages are inert while the flag is off.
* Data safety: nothing in this release changes or deletes an existing row; the flag-off path adds one audit entry type (`google.connect_started`) when a customer presses Connect Google, nothing else.

## 8. Open items for you
* Confirm who else deploys (the SEO V2 session) and agree the freeze.
* Decide on the monitoring branch (3.3).
* Decide whether the later SEO V2 commits (`18d0161`, `8931233`) should ship first; if they do, this candidate must be re-merged.
