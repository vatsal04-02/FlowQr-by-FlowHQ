# Phase 2 evidence (2026-11-15)

Raw output of the rehearsals and checks cited by `docs/PHASE_2_FINAL_ACCEPTANCE.md`. Nothing here is edited except two things: scratch-folder paths were replaced by `<scratch>`, and this note. All of it was produced on **one developer PC** (Windows, Docker Desktop). None of it is evidence about Google, Places, Razorpay/Cashfree or a public server.

| File | What it is |
|---|---|
| `migration-upgrade-0025-to-0030.txt` | A read-only `pg_dump` of the running development database (revision 0025, 47 tables, real rows: 6 users, 5 businesses, 964 reviews, 1,236 audit rows) restored into a throwaway PostgreSQL 16 and migrated to 0030 with the Phase 2 code. Row counts of every pre-existing table are compared |
| `row-counts-before-0025.txt`, `row-counts-after-0030.txt` | The counts behind the comparison (only `billing_plans` changed: 3 to 5 rows, as designed) |
| `migration-downgrade-and-boot.txt` | The same copy downgraded 0030 to 0028 and upgraded again (customer tables identical), then API, worker and beat started on it as the non-superuser application role. **Its `plans: 404` line is a typo in the check's URL (`/api/billing/plans` instead of `/api/v1/billing/plans`); it is not an application error.** The correct URL was checked by hand straight afterwards (below) |
| `staging-backup-restore.txt` | Encrypted backup of the **staging** database, restored into an isolated PostgreSQL: checksums of 14 key tables identical; API, worker and beat run on the copy; a restored owner signs in, reads their data, writes, and the plan limit is still enforced |
| `staging-routes-and-tls.txt` | `deploy/staging/check_routes.sh` against the staging Caddy over HTTPS (internal CA): 40 checks, 0 failures |
| `staging-smoke.txt` | `deploy/staging/smoke_stack.py`: registration, verification, onboarding, staff invitation, password reset, card batch and scan, over HTTPS and through the SMTP sink: 33 passed, 0 failed |
| `staging-browser.txt` | `e2e/phase2-onboarding-and-queue.js` in Chromium against staging: 18/18 |
| `route-access-matrix.txt` | Every API route and its access level at the time of the audit (a copy of the manifest the tests pin: `backend/tests/route_access_manifest.txt`; 271 rows: level, method, path) |

## Checked by hand, not captured in a file

* The **previous** release's API code (copied out of the running development container, migration 0025) was started against the **upgraded** 0030 schema: `/api/health` 200 and `/api/v1/billing/plans` 200 with the new plans. So the migrations are additive enough that the old API image can run on the new schema; this matters for the rollback order in `docs/ROLLBACK_AND_RECOVERY.md`. It was only a start-up and one read, not a full regression of the old code.
* A spoofed `X-Forwarded-For` / `X-Real-IP` on 16 login attempts through the staging Caddy did not evade the per-address rate limit (5 x 401, then 11 x 429).
* The staging API, worker, beat, frontend and Caddy logs after the smoke and browser runs were searched for passwords, tokens, keys and tracebacks: only URL paths such as `/auth/password-reset/request` and Caddy's own "installing root certificate (you might be prompted for password)" notice matched; no secret value; 0 tracebacks. (Taken before the access-log redaction fix (audit finding F4) was built into the image, so OAuth `code=` values would have shown in the API access log; no OAuth flow ran in staging.)
