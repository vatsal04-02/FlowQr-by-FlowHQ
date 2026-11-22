# Agency self-service onboarding: implementation

Branch `feature/agency-self-service-onboarding`, from `origin/release/gbp-agency` @ `0604555` (backend image `prod-10bcbbe` / migration 0065 were the last deployed). Local only: not pushed, not merged, not deployed. See the architecture, test matrix and runbook alongside.

## 1. Verified against the code first

| Claim in the brief | Found |
|---|---|
| Agency Manager backend and protections exist | Yes: `services/google/agency.py` (consent, invite with the customer's token, accept with the agency token, verify under the Location Group, switch, stop, loss detection, notices), `agency_client.py`, `agency_audit.py`, per-use gate `resolve_agency_access` |
| Separate agency identity and key | Yes: `google_agency_accounts`, `AGENCY_TOKEN_ENCRYPTION_KEY`, platform-only row-level security |
| Operator allowlist | Yes: `GOOGLE_AGENCY_OPERATOR_EMAILS`, `/agency-ops/*` |
| Group id not hard-coded | Correct: read from `GOOGLE_AGENCY_LOCATION_GROUP_ID` / the agency account row. The literal appears only in help text, comments, an error-message example and test fixtures, never in logic |
| Frontend | Existed: a consent panel (`AgencyManager.tsx`) and no operator screen, no unified journey, no per-permission consent, no first sync, no customer notices beyond "manager added" |

So most of the supported workflow already existed. This work builds the customer journey and operator surface around it, closes the gaps below, and fixes four defects found on the way.

## 2. What was built

**Backend**
* `alembic/versions/0066_google_agency_self_service.py` (additive): `consent_actions`, `notices_sent`, `initial_sync_enqueued_at` on `google_agency_authorizations`.
* `services/google/agency_journey.py` (new, read-only): the 13 states, eight stages, mapping checks, timeline; customer view and operator view.
* `services/google/agency.py`: permission categories (`ACTION_CATEGORIES`, `normalize_actions`, `permits`); `action=` enforcement in `resolve_agency_access`; `connection_lock`; per-business isolation in the hourly job; `enqueue_initial_sync` (Celery only, once); `send_customer_notice` (stop requested / removed / lost / failed); `finish_client_oauth` (revoke the customer's Google sign-in once FlowQR has left).
* `get_access_token(..., action=)` wired at reply publishing, post/photo publishing, the profile editor and the governed post/photo screens.
* `api/v1/google_agency.py`: `GET /google/agency/journey`, `POST /google/agency/journey/start`; rate limits on the earlier consent/advance routes.
* `api/v1/google.py`: `google.connect_started` audit; `return_to=journey` (fixed allow-list, cookie) so Google returns to the guided page; disconnect keeps the encrypted sign-in only while an unfinished withdrawal needs it.
* `api/v1/agency_ops.py`: `GET /agency-ops/journeys` (filter by state/tenant), `GET /agency-ops/journeys/{id}`, `POST /agency-ops/journeys/{id}/advance`.
* `core/config.py`: `GOOGLE_AGENCY_SELF_SERVICE_ENABLED` and its start-up guard; `deploy/vps/docker-compose.vps.yml` lists it so it can reach the app; `docs/ENVIRONMENT_VARIABLES.md`.

**Frontend**
* `/gbp/connect` (`AgencyJourney.tsx`): the customer's Google connection page: connect button and connected identity, discovered locations and choice (with mapping to their own FlowQR location), the permission list with an explicit agreement, the eight-stage progress in the wording of the brief, blocked/failed/expired explanations, mapping checks ("how we checked this is your profile"), invitation/acceptance/verification dates, the separate-notice status, sync status and last success, history, and Stop / Reconnect / Check again. It polls only while FlowQR or Google is working.
* `/admin/agency` (`AgencyOperator.tsx`, entry in the admin nav): table of every business with state, customer Google status, invited/accepted/verified, consent, last sync and failures, issue and revocation, and a detail dialog with the mapping checks, failure codes, notices and audit history.
* `lib/agency-journey.ts`: pure helpers (tested).
* An entry point ("Guided setup") on the existing Locations & Google page, shown only when the server has the feature on.

## 3. Defects found and fixed in existing behavior

1. A failure recorded by an onboarding step (expired customer sign-in, Google refusal) was never committed, so the next look still showed the old state.
2. The hourly job looped over businesses without isolating errors: one exception stopped the rest.
3. No guard against two workers advancing the same connection (two clicks, a retry and the hourly job could each send an invitation).
4. After "Stop FlowQR managing my profile" the customer's encrypted Google sign-in stayed stored and valid (only the older "Disconnect" route revoked it).

## 4. Deliberately unchanged

Owner-OAuth connections, selection and syncing; scheduled sync; reviews, payments, QR/NFC, analytics; WhatsApp. The only WhatsApp file touched is `tests/test_whatsapp.py`, to move its pinned migration head from 0065 to 0066 (as every migration release does). The customer's own mapping is not switched merely because an invitation succeeded: the switch still needs verified access *and* operations enabled.

## 5. Decisions the brief left open

* **Consent before selection or after?** After selection: the stored consent is per Google location, so the location must be known. The page shows the exact location(s) being approved.
* **"Policy response not a prerequisite."** Implemented without it, and still gated by the existing controls (internal-only grant, operations switch, project model, Google's API approval). A closed gate is shown as BLOCKED with the reason; none is bypassed.
* **CONNECTED means access verified, not "syncing".** With operations off the sync stage is shown as on hold.
* **Operator screen needs two things:** a platform-admin login for the admin shell, and a listed operator e-mail for the API (404 otherwise).
* **One authorization per Google location** across all businesses is enforced (platform-wide unique rule plus explicit check).

## 6. Not done / limits

* **No real-Google run.** Every automated test uses the in-memory fake. The acceptance criterion in the brief ("do not call it complete if any stage is simulated or only mock-tested") is **not met**; see the test matrix and runbook §3.
* The operator account is not registered here (a person does it; the operator must not be added to a customer business).
* The journey screens were type-checked, built and their logic unit-tested, but **not looked at in a browser** in this session.
* Not tested: a live Celery worker and Redis (the queue path and lock are tested with stand-ins), SMTP delivery of the notices (tested via the test outbox).
* `agency_client` fields for the individual-user fallback still follow the reference; the conceptual doc differs (architecture §10).

## 7. Test results (2026-11-23, isolated throwaway Postgres, fake Google only)

| Suite | Result |
|---|---|
| Backend, full (`pytest tests`, 29 min) | 3466 passed, 1 failed: `test_route_access_manifest_has_not_drifted` (the five new routes were not yet in the pinned manifest). Manifest regenerated after reviewing the diff (exactly: 3 operator routes, 1 member route, 1 admin-only route) and that test re-run: passed. No other test failed. |
| New module `test_agency_self_service.py` | 45 passed |
| Existing agency suites (`test_google_agency*.py`, migrations 0037/0065) | 257 passed, unchanged except two deliberate expectation changes (stop-before-invite now also revokes the stopped connection's own Google sign-in; migration head pins 0065 → 0066) |
| Frontend `npm test` | 137 passed (128 before + 9 new) |
| `tsc --noEmit` | clean |
| `next build` | succeeds; `/gbp/connect` and `/admin/agency` built |

Not run: browser look at the new screens; bandit / pip-audit / secret scan on this branch (no dependency changed).
