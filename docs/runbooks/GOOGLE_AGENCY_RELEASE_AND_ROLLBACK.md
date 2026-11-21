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
8. Frontend: pushing this branch publishes a Vercel production build (the integration deploys every pushed branch). The agency screen renders nothing unless the server's status route answers, and with the backend flags off it answers 404, so the visible app is unchanged. Verify `www.flowqr.site` after the build and keep `flowqr-brpitfyq6` as the rollback target.

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
