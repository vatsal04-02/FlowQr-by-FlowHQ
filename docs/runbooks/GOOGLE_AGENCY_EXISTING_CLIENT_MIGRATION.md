# RUNBOOK: prove the agency login's real API access, then move an existing client (Geeta Krishna Physiotherapy)

**Scope: existing agency access and the one existing client only.** Automated onboarding is a separate workstream and is not touched here. **A person runs the live steps, after approving them.** Nothing in the automated tests makes a live Google call.

Written 2026-11-21. Code: `app/services/google/agency.py` (the flow), `agency_check.py` (the read-only check), `app/cli.py` (commands).

## What is already true (and what is not)

| | |
|---|---|
| Agency Google identity | `vatsal@flowhq.co.in` (the dedicated FlowHQ agency login) |
| Organisation (API resource name) | `accounts/110178313486978980497` (accountNumber `5234249121`). **Never** a group id. FlowQR never calls Google with it; it only exists so a wrong group id can be refused. |
| Location Group (API resource name) | `accounts/114863040359228435467` (accountNumber `5488245563`, a display reference only) |
| Seen in Business Profile Manager (website) | yes: the client's listing is in the FlowHQ group, verified |
| Seen through Google's **API** with the agency token | **NOT YET PROVEN.** Seeing it in the website proves nothing about the API. That is what step 3 checks. |

## accountNumber versus API resource name (found by the first real check, 2026-11-21)

Business Profile Manager shows each account's **accountNumber**, a short display reference (10 digits seen). The API names an account `accounts/{account_id}` with a much longer id (21 digits seen). They are different values and **`accounts/<accountNumber>` is 404 at the API**.

| Account | accountNumber (display only) | API resource name (use this) |
|---|---|---|
| FlowHQ Location Group | `5488245563` | `accounts/114863040359228435467` |
| FlowHQ Organisation | `5234249121` | `accounts/110178313486978980497` |
| Geeta Krishna Physiotherapy (location) | not applicable | `locations/726682899335438012` |

Evidence, REAL (a read-only run on 2026-11-21 with the agency token; GET requests only): `accounts.list` returned both resource names above with their types and accountNumbers; the group's locations list contained Geeta's location; `locations/726682899335438012/admins` showed the group as MANAGER; a review read through `accounts/114863040359228435467/locations/726682899335438012/reviews` worked. The regression tests in `tests/test_google_agency_resource_names.py` use a MOCK shaped like those responses; they prove this code's behaviour, not Google's.

What the code does about it: `google-agency-check` recognises a short accountNumber, names the resource Google returned for it (it never works one out or guesses), and says so; `google-agency-register` and `google-agency-status` warn about a value that looks like an accountNumber. Configuration and the database accept any `accounts/<digits>` name, so the complete names are stored unchanged. To correct a row that stored the short number, re-run `google-agency-register` with the resource name, or update `location_group_name` on that one row to the resource name, then re-run `google-agency-check`.

## 0. Rules for this runbook

* **Local, throwaway database only** for steps 1 to 4. Never the dev database (`flowqr`, at migration 0036) and never production. Production is at migration **0060**; this branch needs **0061 and 0062** there first, which is a separate, approved release (not part of this runbook).
* Do **not** turn `GOOGLE_AGENCY_MANAGER_ENABLED` on anywhere for the check. The check command does not need the switch and writes nothing.
* No token is ever printed by any command here. Do not paste a token, the agency key, or the OAuth client secret into chat.
* Do not revoke any Google credential, delete any connection or transfer ownership at any point.

## 1. A throwaway database at migration 0062

From `backend/` of this branch (`audit/security-privacy-gbp`):

1. Create an empty database named `flowqr_agency_check` in your local Postgres (any name that is not `flowqr`).
2. Point `DATABASE_URL` and `MIGRATION_DATABASE_URL` at it (the app role and the table-owner role, as in your local `.env`, but with this database name), then `alembic upgrade head`. The head must be `0062`.

## 2. Register `vatsal@flowhq.co.in`, with the identity guard

1. Generate the agency key and keep it out of the repo and chat: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Set it as `AGENCY_TOKEN_ENCRYPTION_KEY` in that shell only. It must differ from `TOKEN_ENCRYPTION_KEY` and `SECRET_KEY`.
2. Set `GOOGLE_AGENCY_LOCATION_GROUP_ID=accounts/114863040359228435467` and `GOOGLE_AGENCY_ORGANIZATION_ID=accounts/110178313486978980497` in that shell (the complete resource names, never the short numbers). Use the existing OAuth client (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and a `GOOGLE_REDIRECT_URI` that is one of the three registered redirect URIs). Do not create a new project or client.
3. **Use `--listen` (step 4).** The manual route (`google-agency-auth-url`, then copying `code` and `state` from the browser) is kept but is **not reliable on a machine where FlowQR's own stack is running**: Google redirects to `http://localhost:3000/api/v1/google/callback`, which there is FlowQR's *customer* callback. It rejects the agency state on purpose, never uses the code, and sends the browser on to `/gbp/locations`, which sends a signed-out visitor to `/login`. The code and state then exist only inside that one redirected request, and the app's access log redacts them, so they cannot be recovered. (This is what happened on 2026-11-21.) If you do use the manual route: open the address **while signed in as `vatsal@flowhq.co.in`**, approve. Follow section 2 of `GOOGLE_AGENCY_TWO_ACCOUNT_TEST.md` for how the code is read from the redirect (the app's own callback rejects it on purpose; the code stays in the address bar or the Network tab). **The address now carries a random, signed, single-use `state`** (valid for 15 minutes; the old fixed word `agency-registration` is refused): take **both** `code=` and `state=` from the redirect, and sign in in a private window as `vatsal@flowhq.co.in` only. The address asks for `business.manage` (plus `openid email`, only to read who signed in) and sets `include_granted_scopes=false`.
4. **Recommended:** stop FlowQR's local frontend so port 3000 is free (`docker stop flowqr-frontend-1`), then run the register command with `--listen`. It binds the port first, prints the sign-in address, waits, receives Google's redirect itself and registers in the same process, so **nothing is copied**:
   `docker run --rm --network flowqr-testnet -p 127.0.0.1:3000:3000 --env-file <env file> -v <backend>:/app -w /app -e PYTHONPATH=/app flowqr-test:latest python -m app.cli google-agency-register --listen --listen-host 0.0.0.0 --label flowhq-agency --expect-email vatsal@flowhq.co.in --location-group-id accounts/114863040359228435467`
   The port is published to `127.0.0.1` only, the listener serves one exact path, accepts only the state this command just issued, writes no log line and shows the browser nothing secret. Restart the frontend afterwards (`docker start flowqr-frontend-1`).
   **Manual alternative:** `python -m app.cli google-agency-register --label flowhq-agency --expect-email vatsal@flowhq.co.in --state <state> --code <code>`. **`--expect-email` and `--state` are both required.** A state that is not one this installation issued, is expired or was already used stops the command **before the Google code is spent**.
   **`--expect-email` is the guard:** Google's own answer (userinfo for the token) must be that address, or **nothing is stored and the sign-in is revoked**. Signing in as `apigbp@gmail.com`, a client or a personal account by mistake therefore cannot become the agency login. The label is only a name.
5. `python -m app.cli google-agency-status` must show `flowhq-agency  vatsal@flowhq.co.in  active  group: accounts/114863040359228435467`.

## 3. The read-only API check (this is the success criterion)

First find the client's Google location id (a person runs this, **read-only**, against production; it changes nothing):

```sql
SELECT t.id AS tenant_id, c.id AS connection_id, c.status, (c.refresh_token_encrypted IS NOT NULL) AS client_token_held, gl.google_location_name, gl.google_account_name, gl.selected
FROM google_locations gl JOIN google_connections c ON c.id = gl.connection_id JOIN tenants t ON t.id = gl.tenant_id
WHERE t.name ILIKE '%geeta%';
```

(Run it as the table owner with row-level security bypassed, as your other read-only checks are. Production has no `auth_mode` column yet, because 0061 is not there.)

Then, in the local shell of step 2, find the client's location **by its title** (this reads the group's list with the agency token and names only the one location that matches; if none or more than one matches it fails and names nobody):

```
python -m app.cli google-agency-check --expect-email vatsal@flowhq.co.in --title "Geeta Krishna Physiotherapy"
```

Then confirm the id it printed against the production query above, with the id itself:

```
python -m app.cli google-agency-check --expect-email vatsal@flowhq.co.in --location locations/<ID FROM THE QUERY>
```

It makes only reads, and prints one line per link, **PASS / FAIL / SKIP**:

| Line | What it proves |
|---|---|
| `identity` | the stored login is the expected account **and** Google, asked with its token right now, says so |
| `accounts.list` | `accounts/114863040359228435467` is listed for the agency token and typed `LOCATION_GROUP` (not the organisation, not a personal account) |
| `group locations` | `accounts/114863040359228435467/locations` answers; the group's other clients are **counted, never named** |
| `location match` | the client's location id is listed under the group's own account |
| `location read` | a review page is readable at `accounts/114863040359228435467/locations/<id>`: the very path the review sync uses |
| `tenant mapping` | skipped on a throwaway database (the client is not in it); on a database that holds the connection it names the one business and connection, and **fails if two businesses hold the location** |

`READ-ONLY CHECK PASSED` means the agency token reads the client's location through the group. Anything else says which link is missing; the usual causes are in the table below. **Record every line in the migration record**, including a failure: it is a finding.

| Result | Meaning and next step |
|---|---|
| `identity` FAIL | wrong Google account registered. Re-register with `--expect-email`. |
| `accounts.list` FAIL "not a member or administrator" | the agency user is not on the group in Google. Add `vatsal@flowhq.co.in` (or a user group it is in) as an owner/manager of the Location Group, then re-run. |
| `accounts.list` FAIL "typed ORGANIZATION" / "organisation" | the id used is the organisation's. Use the Location Group's resource name `accounts/114863040359228435467`. |
| `group locations` or `location read` FAIL with 403 | the API refuses the group path even though the website shows it. Stop and record the exact status. |
| `location match` FAIL "NOT listed" | the group does not list the client's location through the API. Do not migrate. |
| any FAIL with "not approved" | the Cloud project's Business Profile API access is not approved or the API is disabled. |
| any FAIL with "rate limit" | wait a few minutes and re-run. |

## 4. After the check passes: what migration will do (NOT part of this runbook; needs approval and a production release)

The existing connection runs on the client's own Google login. The code now supports moving it **without sending Google any invitation**:

* `GOOGLE_AGENCY_ADOPT_EXISTING_ACCESS=true` (with `GOOGLE_AGENCY_MANAGER_ENABLED`, the agency key and the group id): for a client whose location is **already listed under the group**, FlowQR verifies it from the group using the **agency token only**. It sends nothing to Google and does not use the client's token before the switch. A location that is **not** listed is invited as before.
* The client must still press **agree** in the app (the stored, hashed consent). The separate notice e-mail goes out as for any client.
* The switch happens only when every selected location is verified under the group; a refusal anywhere leaves the connection and the client's token exactly as they were.
* **Rollback window:** `GOOGLE_AGENCY_CLIENT_TOKEN_KEEP_HOURS=168` keeps the client's own token (encrypted, unused) for 7 days after the switch. Inside it, `python -m app.cli google-agency-rollback --connection-id <id>` puts the connection back on the client's own login, after proving that token still works. The consent wording then says the login is kept for that long. With the default `0` the token is revoked at once and cannot be rolled back (the client would have to reconnect Google).
* The client's own token is also kept while **another** FlowQR connection still depends on the same Google user.
* Rolling back does **not** remove FlowQR's group from the client's listing in Google. Removing it is a separate decision (the client's **Stop** button, or Google's People and access).

**Notice date caveat:** FlowQR actually became a manager when the client approved the group's request, before this migration. The stored "accepted" date for an adopted location is the date FlowQR recorded the access, so the notice e-mail may be later than the 48 hours Google's policy expects. Decide whether that is acceptable (or send a manual notice first) before migrating.

**Environment:** a setting reaches the app on the VPS only if it is listed in `deploy/vps/docker-compose.vps.yml`. None of the agency settings is listed there yet.
