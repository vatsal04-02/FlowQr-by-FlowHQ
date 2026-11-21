# MANUAL RUNBOOK: two-account test of the agency manager flow (LocationGroup delegation)

**Read first.** By default `GOOGLE_AGENCY_OPERATIONS_ENABLED` is **off**, and then step 4 ends at **"Access verified"** (`verified`): nothing is switched, the test owner's token is **not** revoked, and nothing in this step can happen. To run this step, set `GOOGLE_AGENCY_OPERATIONS_ENABLED=true` **in the test environment only** (the production guard that asks for `GOOGLE_AGENCY_POLICY_REFERENCE` applies in staging and production, not locally) and press **Check again**. Do not enable it anywhere else: Google's published restriction on shared-project, multi-business use is not resolved by this test.

**A person runs this, by hand, only after approving it. Nothing in the automated test suite does any of it, and nothing here may be run against a real customer.** It is the only way to learn how Google really behaves; the automated tests only prove FlowQR's code does what Google's pages say.

Written 2026-11-21 for the corrected design in `docs/audits/GOOGLE_CLIENT_ACCOUNT_OPTIONS.md` section 11: the client invites **FlowQR's Business Group** (`accounts/114863040359228435467`, in `Admin.account`), not one person's e-mail. Every step records an answer to one of the unverified points **G1 to G17** (the verification matrix, section 11.7 of that file; its last column is exactly what this runbook must settle) or to a point from its section 8. The invite, list, accept, verify sequence follows Google's **transfer-locations** page ("Transferring to a location group"), which is written for an ownership transfer: this runbook tests it for a **Manager** invitation, which Google's pages do not show. **Step 5.5 is the only step that writes to Google.**

## Approval (fill in before starting)

| | |
|---|---|
| Approved by | [OWNER INPUT REQUIRED] |
| Date | [OWNER INPUT REQUIRED] |
| Test profile (created for this test, no real customers, no real reviews to lose) | [OWNER INPUT REQUIRED] |
| Environment | local or staging. **Not production.** |
| Step 5.5 (one real reply, approved by you, deleted afterwards) approved | yes / no |

## 0. What you need

* **A test owner Google account** that owns a Business Profile location created for this test.
* **FlowQR's organisation and Business Group** as set up by the owner: organisation resource `accounts/110178313486978980497`, **Location Group resource `accounts/114863040359228435467`** (confirmed by a real `accounts.list` on 2026-11-21; the short accountNumbers `5234249121` / `5488245563` that Business Profile Manager shows are display references, not API ids). They are different accounts: **only the group id is ever invited. The organisation id is never used in a request**, and FlowQR refuses it as a group id.
* **An agency Google user** (a dedicated FlowQR account, MFA on, never a person's own) that **already administers the Location Group**, directly or, as Google recommends, through a user group. FlowQR cannot grant this and **refuses to send any invitation until the user's own `accounts.list` shows the group typed `LOCATION_GROUP`** (G4, G17). Record how the user holds that access and its role.
* FlowQR's Google Cloud project with the Business Profile APIs approved and the OAuth client working. Without approval the first call returns quota 0 and the run stops there, which is itself a result.
* A local or staging FlowQR on this branch, a mail setup or sink you can read, and a database you can query read-only.

## 1. Prepare the environment (never in production)

1. Generate the agency key and keep it out of the repo and out of chat: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. It must differ from `TOKEN_ENCRYPTION_KEY` and `SECRET_KEY`.
2. In the environment's own settings (not committed): `AGENCY_TOKEN_ENCRYPTION_KEY=<that key>`, `GOOGLE_AGENCY_MANAGER_ENABLED=true`, `GOOGLE_AGENCY_LOCATION_GROUP_ID=accounts/114863040359228435467`, `GOOGLE_AGENCY_ORGANIZATION_ID=accounts/110178313486978980497` (only so the group id can be refused if it is the organisation's), `GOOGLE_AGENCY_INDIVIDUAL_FALLBACK=false`, `GOOGLE_AGENCY_INVITATION_DISCOVERY` left unset (off), `PLATFORM_ADMIN_EMAILS=<your address>`.
3. A setting reaches the app on the VPS only if it is listed in `deploy/vps/docker-compose.vps.yml`. **This runbook does not ask you to touch production.**
4. Run the migrations to `0062`.
5. Keep `GOOGLE_AGENCY_INVITATION_DISCOVERY` **off**. It is a diagnostic for the case where the invitation is not in the group's own list; turn it on only after you have seen that happen and recorded it.

## 2. Register the agency Google user as a member of the group

1. `python -m app.cli google-agency-auth-url`. Open the printed address **while signed in to the agency Google user**, approve the Business Profile permission.
2. Google sends the browser to `GOOGLE_REDIRECT_URI`, which is FlowQR's normal Google callback. That callback **rejects this sign-in on purpose** (`invalid_state`; the code is not used) and then sends the browser on to another page, so the code does **not** stay in the address bar when something is listening there. Either stop the local frontend first (so the browser shows "can't be reached" and keeps the URL), or copy the callback request's URL from the browser's developer tools (Network, Preserve log). Take only the `code=` value and turn `%2F` into `/`. Run both CLI commands with the **same** `GOOGLE_REDIRECT_URI`: Google checks it again when the code is exchanged. Prefer the localhost redirect URI: with a production URI the code would pass through the production API's logs.
3. `python -m app.cli google-agency-register --label flowqr-agency --code <code>` (the group comes from `GOOGLE_AGENCY_LOCATION_GROUP_ID`, or pass `--location-group-id accounts/114863040359228435467`). The code is single-use. Nothing prints a token.
4. `python -m app.cli google-agency-status` must show the login with `group: accounts/114863040359228435467` and `cap: unknown (not verified)`.

**Record:** registered without error (yes/no); the agency user's role in the group **[G4]**.

## 3. The test owner connects Google the usual way

Sign up a throwaway FlowQR business, connect Google as the **test owner**, select the test location on *Locations & Google*.

## 4. Consent, group invitation, acceptance, visibility **[G1, G2, G3, G4, G5, G9, G10, G13, G17]**

1. Before pressing anything, open Google Business Profile for the test location, **People and access**: FlowQR's group is **not** listed.
2. On *Locations & Google*, read **Let FlowQR join as your Manager**, tick the box, press **Invite FlowQR as Manager**.
3. In Google's **People and access**, FlowQR's **group** appears with role **Manager** (pending, then accepted). It must **not** be Owner. **Record any terms prompt** and who sees it **[G13]**.
4. The FlowQR status should walk invited, accepted, then "FlowQR manages this profile as your Manager". Use **Check again** if it waits.
5. Read-only database check:
   `SELECT status, failure_code, target_type, target_account_name, receiving_account_name, agency_account_name, admin_resource_name, invite_sent_at, accepted_at, verified_at, switched_at, client_token_revoked_at FROM google_agency_authorizations ORDER BY created_at DESC LIMIT 5;`
   `SELECT auth_mode, status, refresh_token_encrypted IS NULL AS client_token_gone FROM google_connections ORDER BY created_at DESC LIMIT 5;`

**Record:**
* **Pre-flight (G4, G17):** it runs before the invitation. If the consent stops at `group_access_missing` or `group_type_unconfirmed` and **nothing** appears in Google's People and access, the user does not administer the group, or `accounts.list` did not type it `LOCATION_GROUP`: record exactly what `accounts.list` returned for the group (name and `type`), fix the access in Google, press **Check again**.
* Did Google accept `{"account": "accounts/114863040359228435467", "role": "MANAGER"}`? If it rejected the form, the exact status and message **[G1]**.
* `receiving_account_name`: the invitation is looked for **only** in the group's own list (`accounts/114863040359228435467/invitations`, as Google documents). It should equal the group. If the flow instead waits at `invitation_pending` and later needs attention (`invitation_not_found`), the invitation is somewhere else: record where you can see it in Google, then (and only then) enable `GOOGLE_AGENCY_INVITATION_DISCOVERY` to find out which account holds it **[G2]**.
* Whether the agency user could accept with its own token, or the flow stopped at `group_access_missing` **[G3, G4]**. If it stopped, add the user to the group in Google, press **Check again**, and record that this was needed.
* `agency_account_name`: the account under which the group lists the location. It must equal the group; if the location is only listed under the organisation or another account, nothing switches by design, and the account Google used is the answer **[G5, G9]**.
* Whether the invitation disappears from the list after accepting, and how long accept took **[G10]**.

**Pass:** status `active`, `target_type = flowhq_location_group`, `receiving_account_name` recorded, `agency_account_name = accounts/114863040359228435467`, `client_token_gone = true`, role Manager in Google.
**If it stops at "accepted" and never becomes visible under the group:** that is the "not visible" path working as designed (nothing switched, the client's token untouched). Record it. It means FlowQR cannot use this location through the group and the model needs Google's answer.

## 5. The client's token is gone, and the group does the work **[G6]**

1. In the test owner's Google Account, **Security, Third-party access**: FlowQR's project should no longer have access. **Record:** gone / still listed.
2. Trigger a sync. Reviews should still arrive. This proves the agency user can read reviews through `accounts/114863040359228435467/locations/{id}/reviews` **[G6]**. **Record** any 403 or 404 and the exact text; if the v4 path refuses the group account, the design needs another path for reviews, posts and media.
3. **Refresh must not leak.** As the test owner press **Refresh list** on *Locations & Google*: it must be refused ("FlowQR manages this profile as your Manager"). The agency user sees every client of the group, so the locations list must contain **only the test location**, with its own title and address unchanged. **Record:** refused (yes/no); anything from another business visible (must be no).
4. **The merchant's grant.** After the switch the test owner's token should be revoked **unless** the same Google user is connected to another FlowQR business, in which case FlowQR keeps it until that business no longer depends on it. **Record** which happened **[G16]**.
5. **The only write.** On a **throwaway review you created on the test profile**, draft a reply, **approve it yourself**, publish it. It must go through only after approval, exactly as before. This is the only evidence that the group can **manage**, not just list. Delete the reply on Google afterwards.

## 6. The separate notice

Within minutes the test owner's mailbox should hold **"FlowQR is now a manager of ... on Google"**, naming **FlowQR's business group (accounts/114863040359228435467)**, saying it is separate from Google, how to stop, and where to remove FlowQR in Google. **Record:** received (time), wording acceptable (yes/no), `notice_sent_at` set.

## 7. Duplicates **[G7, G12]**

1. Press **Check again** and re-submit the consent. In **People and access** there must still be exactly one FlowQR group entry.
2. Optional, only if you accept creating one: add FlowQR's group manually in Google first, then run steps 3 and 4 for a fresh location. FlowQR should adopt the existing invitation rather than send another.

**Record:** what Google returned for a duplicate (status and message, from the FlowQR log, which never contains tokens) **[G12]**; whether the location's admin list returns `account` for the group entry **[G7]** (visible in the log line of the verification step, or ask for the admin list of the location in Google's API explorer **using the test account only**).

## 8. The agency user is not in the group (negative test) **[G3, G4]**

1. Remove the agency user from the Business Group in Google.
2. Add a second test location, consent, and watch: the flow must stop at `group_access_missing` (needs attention), an alert e-mail must arrive, and **nothing** must change for the client (`auth_mode` stays `client_token`, the client token stays).
3. Add the user back, press **Check again**: it must complete without a second invitation.

**Record:** the exact error the agency user got on the group's invitation list and on accept **[G3, G4]**.

## 9. The client removes FlowQR's group **[loss detection]**

As the test owner, in **People and access**, remove FlowQR's group. Wait for the next sync, or run the hourly task by hand. FlowQR must: mark the connection revoked with "FlowQR's manager access was removed in Google", mark the authorization `lost`, e-mail the platform administrators, and make **no further Google calls** for that profile.

**Record:** how long detection took; the exact error Google returned for the first call after removal (status and reason).

## 10. Stop, and group removal **[G8]**

Re-run steps 3 and 4 so FlowQR is a manager again. Press **Stop FlowQR managing my profile** and confirm.

1. Work stops at once (no sync, nothing queued).
2. In **People and access** the group entry disappears. If it does **not** (Google answered 403), the authorization stays `stopping`, an alert is sent two days before the deadline, and the notice tells the client to remove FlowQR themselves. **Record:** removed by the agency user (yes/no) and, if no, the error **[G8]**.
3. `removal_requested_at`, `removal_deadline_at` (seven business days) and `removed_at` are recorded.

## 11. Clean up

Remove FlowQR's group from the test profile in Google if it is still there; disconnect the test business in FlowQR; delete the throwaway business; set `GOOGLE_AGENCY_MANAGER_ENABLED=false` in the test environment. Keep the agency Google user registered only if you will repeat the test.

## 12. Results

| Step | Pass / fail | What Google actually did |
|---|---|---|
| 2 register, membership role (G4) | | |
| 4 request form (G1) | | |
| 4 pre-flight `accounts.list` shows the group typed `LOCATION_GROUP` (G4, G17) | | type returned: |
| 4 which invitation list (G2), who accepted (G3) | | receiving account: |
| 4 listed under the group (G5), organisation role (G9), terms prompt (G13) | | account found: |
| 5.2 reviews via the group path (G6) | | |
| 5.3 refresh refused, no other business visible | | |
| 5.4 merchant grant revoked or deliberately kept (G16) | | |
| 5.5 approved reply published | | |
| 6 notice | | |
| 7 duplicate (G7, G12) | | |
| 8 agency user not in group (G3, G4) | | |
| 9 client removes the group | | |
| 10 stop and removal (G8) | | |

Send the filled table with Google's answers to questions 1 to 6 in section 9 of `GOOGLE_CLIENT_ACCOUNT_OPTIONS.md`. **Do not turn the switch on for real customers until section 11.7 of that file has no open row that matters and Google has answered question 1. No Google policy approval is claimed by this runbook or by the code.**

## Appendix: the individual-email fallback (only if you enable it)

Only if Google refuses group invitations. Set `GOOGLE_AGENCY_INDIVIDUAL_FALLBACK=true` and register a login **without** a group (`GOOGLE_AGENCY_LOCATION_GROUP_ID` empty). Repeat steps 3, 4, 5 and 9. Expected differences: the invitation goes to the agency user's own list; an accepted person appears in the admin list by **name**, not e-mail; `target_type = individual_agency_user`, `target_account_name` is empty. Record where the location is listed for the user after accepting (`agency_account_name`).
