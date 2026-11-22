# Agency self-service onboarding: runbook

Everything here is for a **person**. Nothing in this branch has been deployed, enabled, or run against real Google. No production variable has been changed.

## 1. Switches (all off by default)

| Variable | Needed for |
|---|---|
| `GOOGLE_AGENCY_MANAGER_ENABLED` | the whole agency path (already on in production) |
| `GOOGLE_AGENCY_SELF_SERVICE_ENABLED` | the guided screens and `/google/agency/journey*` (new; refused at start-up without the one above) |
| `GOOGLE_AGENCY_OPERATIONS_ENABLED` + `GOOGLE_AGENCY_PROJECT_MODEL=flowhq_own_project` (+ internal decision or policy reference) | the switch onto the agency login and agency-token sync. Off = onboarding ends at "access verified" |
| `GOOGLE_AGENCY_INTERNAL_ONLY` + `GOOGLE_AGENCY_OPERATOR_EMAILS` | production today: a business must first be opened by an operator |

The new variable is already listed in `deploy/vps/docker-compose.vps.yml` (an unlisted variable never reaches the app).

## 2. Before enabling anywhere

1. **Validate the setting with the real guard first** (a refusal makes the API 503): `docker compose ... run --rm --no-deps -T api python -c "import app.main"`.
2. Apply migration 0067 (additive; no row rewritten). Take a backup first (`/opt/flowqr/backups`). Rollback of the code is safe with 0067 applied (new columns are ignored by the old image).
3. Run `python -m app.cli google-agency-activation-check` and confirm READY.
4. **Operator account.** The operator registers through the normal sign-up (`REGISTRATION_MODE=allowlist` means the address must be allowed first), verifies the e-mail, and signs in. The operator needs **no membership in any customer business** and must not be given one. The screen is `/admin/agency` (a platform admin who is also in `GOOGLE_AGENCY_OPERATOR_EMAILS`). *Pending in the latest report; a person must do it.*
5. Confirm the agency login is registered and active (`google-agency-status`), with `GOOGLE_AGENCY_LOCATION_GROUP_ID` set to the long `accounts/<digits>` resource name (not the short account number).

## 3. First live test (the only way to prove Google behaves as documented)

Use **a dedicated test Business Profile** and two controlled Google accounts: a *test owner* who owns it, and FlowHQ's agency login. Never a customer. Follow `docs/runbooks/GOOGLE_AGENCY_TWO_ACCOUNT_TEST.md` for the account set-up, on a non-production environment with its own database, then walk the journey in the browser:

1. Sign up a throwaway business; open `/gbp/connect`. Expect NOT_STARTED. Press Connect Google.
2. Sign in as the test owner and acknowledge Google's consent screen. Expect to land on `/gbp/connect`, state LOCATION_SELECTION_PENDING, the profile listed.
3. Choose the location, map it. Expect CUSTOMER_CONSENT_PENDING and **no invitation yet** (check Google's People and access).
4. Tick categories, agree, Approve. Expect MANAGER_INVITE_PENDING / AGENCY_ACCEPTANCE_PENDING and, in Google's People and access, the business group pending then accepted. Google e-mails the owner; FlowQR's separate e-mail follows.
5. Expect ACCESS_VERIFICATION_PENDING then CONNECTED, and the "How we checked" list all ticked.
6. With operations on in the test environment: expect the first sync queued, then the sync stage `done`.
7. Press Stop. Expect REVOKED, FlowQR gone from People and access, the "stopped" and "removed" e-mails, and the test owner's Google sign-in revoked.
8. Record what Google did differently from the documentation in `GOOGLE_CLIENT_ACCOUNT_OPTIONS.md` section 8 (the `TODO(verify)` items).

## 4. Operating it

* **Operator screen** `/admin/agency`: filter by state; Open shows steps, mapping checks, consent, failure code, attempts, next attempt, notices, sync and the audit history. "Check again" retries only; it records no consent.
* **BLOCKED** is not an error. `not_opened_for_business`: open the business (`google-agency-grant` or the grant endpoint) after confirming the customer. `api_not_approved`: Google's approval, nothing to retry. `group_access_missing` / `group_is_organisation`: fix the agency login's membership/group id, then Check again.
* **Stuck** (`needs_attention`) alerts the platform admins by e-mail. Do not edit rows by hand; use Check again.
* **Customer asks to stop**: they use the button. If removal by API is refused (403), remove FlowQR in Google (People and access) before the deadline in the alert.
* **Kill switch**: `GOOGLE_AGENCY_SELF_SERVICE_ENABLED=false` hides the journey; `GOOGLE_AGENCY_MANAGER_ENABLED=false` stops every agency-mode connection (fail closed). Stop and removal keep working.

## 5. Rollback

Set the flag false (validate, then recreate the API). Revert the image to the previous tag. Migration 0067 stays (harmless). Existing authorizations, customer connections, syncs and notices are untouched by a rollback.

## 6. What needs a human or credentials

| Item | Who |
|---|---|
| Register and verify the operator account | the operator |
| Real two-account test on a dedicated test profile | a person with both Google logins |
| Decide whether to open the path beyond internal operators (needs Google's written answer) | the owner |
| Set the new flag in the VPS `.env`, validate, deploy | the owner / deploy |
| Send the questions to Google (`docs/audits/GOOGLE_QUESTIONS_TO_SUBMIT.md`, not sent) | the owner |
| Off-site backup, SMTP for notices in production | the owner |

## 7. The real two-account test: exactly what a person must do

Nothing below has been done. I did not use production, the production agency login, tenant e9e744ec or any customer profile.

**Set-up (a person)**
1. A dedicated FlowHQ-owned Business Profile, owned or managed by **Account A** (a Google account used only for this test). Never a customer's profile.
2. **Account B** is the FlowHQ agency login. It must be an administrator of the FlowQR Location Group and be registered on a **non-production** installation with its own database and its own `AGENCY_TOKEN_ENCRYPTION_KEY` (`python -m app.cli google-agency-register --listen --expect-email <B>`; registration needs B's interactive sign-in, so only the person holding B can do it).
3. On that installation set `GOOGLE_AGENCY_MANAGER_ENABLED=true`, `GOOGLE_AGENCY_SELF_SERVICE_ENABLED=true`, `GOOGLE_AGENCY_LOCATION_GROUP_ID=accounts/<long id from accounts.list>`; for step 12 also `GOOGLE_AGENCY_OPERATIONS_ENABLED=true` with `GOOGLE_AGENCY_PROJECT_MODEL=flowhq_own_project` and the internal decision. Validate first with `python -c "import app.main"`.
4. The operator account registers through normal sign-up and verifies its e-mail, with no membership in the test business, and is listed in `GOOGLE_AGENCY_OPERATOR_EMAILS`.

**Run (Account A in a browser; capture evidence as you go)**
For each step write down the time, which Google identity and which OAuth client made the call, and the sanitized request and response (remove tokens, e-mail addresses and ids you do not want published).
1. Sign up a throwaway business, open `/gbp/connect`, press Connect Google, sign in as A, acknowledge Google's consent.
2. Confirm A's accounts and the test location are listed; choose it and map it.
3. Tick permissions, agree, Approve. Capture the `locations.admins.create` response (expect `pendingInvitation: true`, `account` = the group).
4. In Google (People and access) the group is pending. Capture `invitations.list` for the group as B.
5. Capture the `:accept` response, then `locations.admins.list` (Manager, not pending) and the group's location list showing the exact location with the same place id.
6. Only then should the page read Connected. If it reads Connected earlier, that is a bug.
7. With operations on: capture the first sync (number of reviews, pages, duplicates) and a second sync (no new rows).
8. Press Stop. Capture the removal call and its response, A's token revocation, and a final `locations.list` as B showing the location is gone. If Google refuses the self-removal (403), remove B in Google by hand and record that.
9. Check the two e-mails to A (Google's, and FlowQR's separate one) and their times.

**Then record** every difference from the documentation in `docs/audits/GOOGLE_CLIENT_ACCOUNT_OPTIONS.md` section 8 and in this test matrix. Until this is done, the journey is "built and mock-tested", not "complete".
