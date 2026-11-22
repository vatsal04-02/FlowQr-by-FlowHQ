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
2. Apply migration 0066 (additive; no row rewritten). Take a backup first (`/opt/flowqr/backups`). Rollback of the code is safe with 0066 applied (new columns are ignored by the old image).
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

Set the flag false (validate, then recreate the API). Revert the image to the previous tag. Migration 0066 stays (harmless). Existing authorizations, customer connections, syncs and notices are untouched by a rollback.

## 6. What needs a human or credentials

| Item | Who |
|---|---|
| Register and verify the operator account | the operator |
| Real two-account test on a dedicated test profile | a person with both Google logins |
| Decide whether to open the path beyond internal operators (needs Google's written answer) | the owner |
| Set the new flag in the VPS `.env`, validate, deploy | the owner / deploy |
| Send the questions to Google (`docs/audits/GOOGLE_QUESTIONS_TO_SUBMIT.md`, not sent) | the owner |
| Off-site backup, SMTP for notices in production | the owner |
