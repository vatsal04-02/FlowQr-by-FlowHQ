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

## 8. Final verification round (2026-11-23)

**Status in one line: the screens are verified in real browsers against the real API with a fake Google; the real two-account Google test has NOT been run and cannot be run by me (section 8.4).**

### 8.1 Code scope
* Diff against `origin/release/gbp-agency`: 44 files. WhatsApp: the only file is `tests/test_whatsapp.py`, two lines, the pinned migration head 0065 to 0066. No WhatsApp application code, route, model or migration is touched.
* Migration graph checked with Alembic itself: single head `0066`, `0066.down_revision = 0065`, 63 revisions in one chain; no stale "0065 is head" pin remains in the tests.
* **Integration with the hardening branch** (`hardening/production-readiness-audit`, local, not merged): a dry-run `git merge-tree` shows `google.py`, `posts.py` and `media.py` merge automatically; **one real conflict**, `frontend/src/components/gbp/GoogleConnection.tsx`, where that branch changed `<AgencyManager />` to `<AgencyManager available={...} />` and this branch adds `<JourneyLink />` on the neighbouring line. Resolution: keep both. The hardening branch has no migration, so 0066 will not collide. An automatic merge is not proof the combination works: after merging, re-run both suites. Nothing of the hardening work is lost by this branch, which does not remove or rewrite any of it.

### 8.2 Browser verification (real Chromium, real Next.js app, real API and database, fake Google)
`e2e/agency-self-service.js` with `e2e/agency-rig/rig_api.py` (the rig runs the real app and replaces only Google; it is test tooling and is never deployed). **122 checks, 0 failed**, at desktop 1440x900, tablet 820x1180 and phone 390x844. Covered: not started; Google sign-in and return to the guided page; identity shown; location choice and mapping gates; permission-by-permission consent (reading locked on, nothing else pre-ticked, Approve only after the explicit agreement); the eight stages; acceptance pending (stage 6 in progress, nothing after it done, not "Connected"); connected (seven done, sync honestly "On hold"); blocked; failed; expired; flag off; not opened by an operator; Stop and Start again; the existing Locations & Google page and its "Guided setup" entry; the operator list (loading, filtering, empty); operator detail and Check again; unauthorized access (a platform admin who is not a listed operator sees "Not available" and the API answers 404; an ordinary customer sees "Platform admins only" and 404); no sideways scroll; no uncaught page errors; no token strings in any page.

Problems the browser found, now fixed and covered:
1. The Connected sentence was printed twice (server detail plus a client note). Fixed with `extraNote` (unit-tested) and a browser check that it appears once.
2. The "Google account connected" toast fired twice. Fixed with a once-per-arrival guard; browser check.
3. Panel titles repeated the state headline. Retitled.
4. The operator list hid businesses that had not yet reached an authorization (waiting for the customer, or blocked). It now lists every Google connection.
5. "Check again" was offered in the operator detail where nothing can be retried (a failed business). It is now disabled.
6. The state headline is now a real heading (accessibility).

Not covered: a real phone, Safari/Firefox, a screen-reader pass, dark mode. Screenshots I actually looked at: `phone-05-connected`, `desktop-04-acceptance-pending`, `tablet-15-operator-list`; the rest were checked by assertions only. The operator table scrolls sideways on tablet and phone by design (11 columns).

### 8.3 Google API contract
Requests built by the real `HttpAgencyClient`, captured on a mock transport (not sent to Google):
```
POST https://mybusinessaccountmanagement.googleapis.com/v1/locations/222/admins   (Bearer: customer token)
     {"account":"accounts/114863040359228435467","role":"MANAGER"}
GET  https://mybusinessaccountmanagement.googleapis.com/v1/accounts/114863040359228435467/invitations   (Bearer: agency token)
POST https://mybusinessaccountmanagement.googleapis.com/v1/accounts/114863040359228435467/invitations/77:accept   (Bearer: agency token, empty body)
```
* v1 Account Management host and path; no v4 endpoint is used for invitations. `account` is the full `accounts/{digits}` resource name; `role` is `MANAGER`; there is no `admin` or `adminName` in the group request (Google: `account` wins if both are set). A placeholder such as `LocationGroupID`, a non-numeric id or an empty value is refused before any request exists (tested).
* The responses in that capture are the mock's, not Google's.
* Google's reference names the field `admin`; its conceptual page uses `adminName` and shows `"account": "LocationGroupID"`. The code follows the reference. Only a live call can settle which one Google accepts.

### 8.4 Real two-account test: NOT RUN
I cannot do it and I did not fake it. It needs (a) an interactive Google sign-in and consent screen for Account A, which I may not perform, and (b) a dedicated FlowHQ-owned Business Profile and Account B on an installation I am allowed to use. I did not use the production database, the production agency login, the live test tenant or any customer profile. So there is **no real invitation response, no real acceptance response, no real manager-access verification, no real review sync and no real revocation result** to report. Inventing them would be exactly the simulation this work must not present as success. The human steps are in the runbook, section 7.

### 8.5 Customer protection: what is and is not evidenced
* Server-side enforcement of every category: tested (`action_not_consented`, audited) and wired into the reply, post, photo and profile-edit paths. Unticked means denied.
* Consent stores actor, e-mail snapshot, timestamp, wording version and hash, categories, and the tenant/location/connection mapping. After Stop the authorization is no longer open and the token resolver refuses it (tested).
* Separate manager-addition notice: sent as soon as FlowHQ's acceptance is recorded; a 48-hour overdue alert exists. Verified only through the test outbox, not real SMTP.
* Offboarding: removal is attempted at once and retried hourly; deadline seven business days; an alert fires two days before it. Whether Google lets a Manager remove itself is undocumented (live-test item); the customer can always remove FlowQR in Google.
* Secrets in logs: by code review the added log lines carry only exception class names and counts. A scan of the rig's log found nothing, **but that log was empty (warning level), so it is not evidence**. A real check needs info-level logs on a live run.

### 8.6 Policy and release gate
Unchanged and tested: internal-only grants, operator allowlist (404 for others), operations off by default, project-model gate, no operator consent. Passing technical tests is not Google policy approval; `GOOGLE_AGENCY_POLICY_REFERENCE` stays empty and must not be invented.

### 8.7 Project and OAuth identity per operation (design; real values to be recorded in the live run)
| Operation | Google identity | API project |
|---|---|---|
| Sign-in, consent, account and location discovery, create invitation, list or withdraw a pending invitation | Account A (customer) | FlowQR's OAuth client (`GOOGLE_CLIENT_ID`), model `flowhq_own_project` |
| Invitation discovery and accept, group membership check, location listing, review sync after the switch, self-removal | Account B (FlowHQ agency login in `google_agency_accounts`) | the same project |
| Revoke the customer's sign-in | Account A's token at Google's revoke endpoint | the same project |
The actual project number and client id are not known to me here and must be recorded from the live run.
