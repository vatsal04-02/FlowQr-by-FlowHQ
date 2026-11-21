# Managing client Google accounts: options after GBP-01

Written 2026-11-21 as the follow-up to `GBP_FUNCTIONAL_AUDIT.md` finding GBP-01. **This is an engineering reading of Google's published policy, not Google's answer and not legal advice. Nothing here says Google has approved any of these models; only Google can confirm which is acceptable for FlowQR.** Quotes come from `developers.google.com/my-business/content/policies` as read on 2026-11-21 and must be re-read on the page before anyone relies on them.

> **Update 2026-11-21:** Option B has since been built behind a switch that is off and has never been run against Google. See sections 7 to 10 for what exists, every unverified point, the questions for Google, and the no-client-token alternative.
>
> **Correction 2026-11-21 (later):** the first build invited **one person's e-mail**. The intended architecture is **delegation to FlowQR's Business Group (a LocationGroup)**. Section 11 describes the corrected design and replaces the statements in sections 7 to 10 that say otherwise; the individual invitation is kept only as a documented fallback.

## 1. What the policy says that matters here

| Clause (as read) | Meaning for FlowQR |
|---|---|
| "You cannot allow agencies, end-clients, or other third parties to use your Business Profile project." / "You cannot provide indirect access to your Business Profile project." | Your project may not be handed to other parties, for example by letting a client's own scripts or an agency call Google through it. |
| Your own programmatic use is allowed; automatic or programmatic use by agencies or end-clients must run under **their own** project. | A party that is itself the agency, using **its own** approved project, is within the rule. |
| Use the APIs for "listings that you either own or are authorized to manage on behalf of the business owner." | Managing a client is expressly contemplated, with authorization. |
| "If you respond to reviews on behalf of your end-client, you must receive their authorization first." Automatic replies, Q&A, listing creation or edits need "the user's prior specific and express consent." | Written, specific authorization before replies and edits. |
| Notify the end-client of account changes (for example adding a manager) within 48 hours, in a notice separate from Google's own. Give a quick, easy way to stop; seven business days to let them disassociate; then remove the tool's permissions. | This is the **agency-as-manager** model written into the policy. |
| Tool providers cannot build APIs that let clients reach the Business Profile APIs through scripts. | FlowQR must not expose Google calls to clients' own automation. |
| Stored API content: temporary, limited, "no more than 30 calendar days", not manipulated or aggregated. | Applies to every model below (GBP-02). |

The policy does not say outright whether a multi-customer **tool** that each owner authorises with OAuth may use one shared project. That is the question for Google (section 5).

## 2. What FlowQR does today

1. **Self-service owners (OAuth).** Each owner signs in to Google and authorises FlowQR's single project (`api/v1/google.py`). Needs Google's confirmation (GBP-01).
2. **Admin-managed businesses.** A FlowQR administrator sets up a business, its locations and its Google *review link*, assigns cards, and records an offline agreement (`docs/ADMIN_MANAGED_BUSINESSES.md`, table `tenant_agreements`). **This path makes no Google Business Profile API call at all** (a search of `admin_businesses.py` finds no Google use). Cards, scans, review pages, analytics and billing do not depend on Google sync.
3. **No pass-through.** The only public API keys in FlowQR belong to the WhatsApp integrations API (customers, enquiries, bookings, visits); no endpoint lets a client script reach Google through FlowQR. Keep it that way.

## 3. The options

### Option A. Keep self-service OAuth under FlowQR's one project (today's design)
* **Needs:** Google's written confirmation that a multi-business tool authorised by each owner is permitted, and whatever approval or agreement they require; the production project approved (GBP-03); the 30-day storage redesign (GBP-02).
* **Pros:** best experience; no manager invitation; owners stay in control.
* **Cons:** this is exactly the clause in doubt. **Do not onboard real customers to it until Google answers.**

### Option B. FlowQR acts as the agency: clients add FlowQR as a manager
* **How it works:** FlowQR (the company) has its own Google account(s) and its own approved project. Each client adds FlowQR's account as a **Manager** (or Owner) on its Business Profile in Google. FlowQR then reads and, with the client's approval, changes those listings **as the agency, under its own project**: the policy's "your own use" and "authorized to manage on behalf of the business owner".
* **Needs (all buildable):**
  1. Written client authorization before any reply, post or edit (extend `tenant_agreements`: capture it from the client, not only from a FlowQR administrator; the table's own comment notes it is "not the shopkeeper personally accepting").
  2. A **separate** notice to the client within 48 hours of FlowQR being added as manager (a dedicated email, not Google's).
  3. A quick, easy stop for the client, and removal of FlowQR's manager permission within seven business days of notice, with a visible deadline for staff.
  4. The 30-day storage rule (GBP-02).
  5. FlowQR's own project approved by Google (GBP-03).
* **Pros:** matches the policy's explicit agency provisions; fits the new "your marketing team of AI agents" positioning (FlowQR runs the profile for the client); no client OAuth into a shared project.
* **Cons:** clients must add a manager in Google (support load); FlowQR becomes accountable as the agency; one set of FlowQR accounts is a concentration risk (use MFA and a dedicated account, never a person's personal one).
* **Still not proven:** whether Google is content with FlowQR running automation for many clients through one agency account at volume. Ask (section 5).

### Option C. Each client brings its own Google Cloud project
* Not realistic. The policy says end-clients cannot be made to apply for their own project and such applications are denied. **Do not build this.**

### Option D. Assist-only mode (no Google API)
* FlowQR drafts replies, posts and profile changes; the **owner copies and publishes them on Google** (or uses Google's own screens). FlowQR makes no Google API call for these.
* **Needs:** a copy-and-open-Google flow, and the same honesty in the UI. Reviews would be entered into FlowQR by the owner (paste) or not stored at all.
* **Pros:** no Google policy question, ready quickly, compatible with everything FlowQR already does (QR cards, review pages, analytics of scans, billing, WhatsApp).
* **Cons:** less automatic; no live review inbox.

## 4. Recommendation (for the owner and counsel to decide)

1. **Now:** run **Option D** for self-service customers and **the existing admin-managed path** for clients FlowQR looks after. Turn Google sync **off** for real customers. Everything else FlowQR sells already works without it.
2. **In parallel:** send Google the question in section 5 and record the answer.
3. **If Google confirms A:** keep OAuth, finish GBP-02 and GBP-03, then enable.
4. **If Google says A is not allowed but the agency route is:** build **Option B**; the admin-managed businesses feature is the starting point because it already has a business, a Launch plan, an administrator workflow and an agreement table.
5. **Whatever the answer:** fix retention (GBP-02), keep human approval of every public action, keep the emergency stop on, and never expose Google calls to clients' own scripts.

## 5. Question to send Google (draft; fill the bracketed facts)

Send through the Business Profile API support channel used for the access request. Keep the reply in writing and record it in this repository.

> **Subject: Business Profile API: multi-business tool and agency use, request for confirmation**
>
> Project number: [OWNER INPUT REQUIRED]. Company: [OWNER INPUT REQUIRED]. Product: FlowQR (flowqr.site), a tool for local businesses to manage Google reviews and their profile, with AI-drafted replies and posts that a person approves before anything is published.
>
> 1. **Shared project.** Each business owner signs in with their own Google account and authorises FlowQR for their own locations (scope business.manage). FlowQR then calls the API from one Cloud project on their behalf, with a person's approval for every reply, post and edit. The owners do not receive API access and cannot run their own scripts through our project. Is this model permitted under "You cannot allow agencies, end-clients, or other third parties to use your Business Profile project" and "You cannot provide indirect access"? If an additional approval or agreement is needed for a tool provider, what is it?
> 2. **Agency model.** For clients we manage, the client adds our company Google account as a manager of their profile and we act as their agency under our own project. Please confirm that this is permitted, and whether any limit applies to the number of locations managed from one agency account.
> 3. **Stored content.** The policy limits storing API content to temporary, limited storage (no more than 30 calendar days) and says it cannot be manipulated or aggregated. Our product shows owners their reviews, a daily performance chart and totals. What may we keep, for how long, and may we keep our own counters (for example "replies sent this month") that do not contain Google content?
> 4. **Automatic replies.** We offer optional template thank-you replies to 4 and 5 star reviews, using text the owner approved and a recorded, location-specific consent. Is this acceptable under the "prior specific and express consent" rule?
> 5. **Branding.** Our site shows illustrative screens of how a profile looks and the Google "G". Please confirm the permitted use.
>
> Evidence available on request: our data inventory, retention settings, the consent record, and the list of what each connection can do.

## 6. Work list by option

| Work | A | B | D |
|---|---|---|---|
| Google's written answer (section 5) | required | required | not needed |
| Production Google project approved and recorded (GBP-03) | yes | yes | no |
| Short-lived Google content plus own counters (GBP-02) | yes | yes | not needed (no Google content stored) |
| Client's written authorization before replies, posts and edits | yes (owner approves in the app) | **yes, separate record from the client** | not needed (owner publishes) |
| 48-hour separate notice when FlowQR is added as manager | no | **yes** | no |
| Client stop, and manager removal within seven business days | disconnect exists | **new: deadline tracking** | no |
| Copy-and-open-Google flow | no | no | **yes** |
| Keep no pass-through API for Google | yes | yes | yes |

This file does not decide the model. It exists so the decision can be made quickly once Google answers.

---

## 7. Update 2026-11-21: Option B is now built, behind a switch that is OFF

Built on branch `audit/security-privacy-gbp`, **not committed, not deployed, never run against Google.** Everything below was tested only against a fake Google (`backend/tests/fake_agency_google.py`) and against a mock HTTP transport that pins each request to Google's reference (`tests/test_google_agency_client.py`). **No test touches the real API and none can.** Whether Google behaves as its reference says is exactly what the manual runbook is for: `docs/runbooks/GOOGLE_AGENCY_TWO_ACCOUNT_TEST.md`.

**What it does.** A client signs in to Google and picks a location as before. A new card on *Locations & Google* shows the consent text and asks the client to agree. Only then does FlowQR invite its manager as **Manager** (never Owner: neither invite function has a role parameter), using the client's token: by default **FlowQR's Business Group** (`accounts/114863040359228435467`, section 11), or, only as a documented fallback, one agency login's e-mail. The agency Google user accepts with its own token, and the location is checked to be listed for it (under the group, in group mode). Only after that does the connection switch to `agency_account` mode, and only after the switch is the client's token revoked at Google. From then on every Google action (reviews, replies, posts, photos, performance) gets its token from the same function as before (`tokens.get_access_token`), which now returns the agency token for such a connection.

| Part | Where |
|---|---|
| Switch and settings | `GOOGLE_AGENCY_MANAGER_ENABLED` (default **false**), `AGENCY_TOKEN_ENCRYPTION_KEY` (its own key; the production guard refuses the switch if it is missing, invalid, or equal to `TOKEN_ENCRYPTION_KEY` or `SECRET_KEY`), `GOOGLE_AGENCY_NOTICE_HOURS` (48), `GOOGLE_AGENCY_REMOVAL_BUSINESS_DAYS` (7), `GOOGLE_AGENCY_VERIFY_INTERVAL_HOURS` (6), `GOOGLE_AGENCY_VISIBILITY_WAIT_HOURS` (48), `GOOGLE_AGENCY_LOCATION_GROUP_ID`, `GOOGLE_AGENCY_INDIVIDUAL_FALLBACK` (**false**), `GOOGLE_AGENCY_MAX_LOCATIONS_PER_ACCOUNT` (**0 = unknown, not unlimited**) |
| Google calls | `services/google/agency_client.py`: interface, real client, factory. Test double: `tests/fake_agency_google.py` |
| The flow | `services/google/agency.py`: a resumable state machine, every step committed and safe to repeat |
| Data (migrations 0061 and 0062, additive) | `google_agency_accounts` (platform-only, own-key tokens); `google_agency_authorizations` (per location: consent version, hash, time and who; invite, accept, verify, switch, notice, removal and loss dates; status); `google_connections.auth_mode` and `agency_account_id`; `google_locations.client_google_account_name`; **0062:** `target_type`, `target_account_name` and `receiving_account_name` on each authorization, `location_group_name` on each agency login |
| Routes | `GET /google/agency/status`, `POST /google/agency/consent`, `POST /google/agency/connections/{id}/advance` ("Check again"), `POST /google/agency/connections/{id}/stop`. The first three answer 404 with the switch off. `stop` always works |
| Background | `flowqr.agency_housekeeping`, hourly: finishes removals, retries a client-token revoke, sends and chases the notice, re-checks access. Obligations run even with the switch off |
| Screen | `frontend/src/components/gbp/AgencyManager.tsx`, rendered only when the status route exists |
| CLI | `google-agency-auth-url`, `google-agency-register`, `google-agency-status` |

**The rules it keeps.**
* Nothing is sent to Google without a stored consent for that exact wording (version and hash recorded). A missing or old version is refused with 422.
* Before the switch, every failure (invite refused, accept refused, location not visible) leaves the connection and the client's token exactly as they were. A step that cannot finish without a person becomes `needs_attention`, is **not** retried automatically, and a person is told. "Check again" resumes at the step that stopped.
* One connection switches only when **all** of its selected locations are verified, so no location loses access half-way.
* If Google does not confirm the token revoke, the encrypted client token is kept and the revoke retried; a person is alerted after 24 hours.
* The separate notice to the client is sent when FlowQR becomes a manager, the date is recorded, and a person is alerted (once a day) if it is more than `GOOGLE_AGENCY_NOTICE_HOURS` late.
* "Stop FlowQR managing my profile" stops all work at once (connection ended, locations deselected), then removes FlowQR from Google, retried until done, with the deadline recorded and a person alerted two days before it. Disconnecting in the existing screen, or deleting the business, does the same.
* If the client removes FlowQR in Google, a permission error asks Google once whether FlowQR can still see the location (one 403 alone proves nothing). If not, the connection is marked revoked, all work for that client stops, and a person is told. The periodic check finds it too. No call is made against that profile afterwards (tested by counting calls).
* Approvals are unchanged: only the token source changed. A reply draft nobody approved is still refused in agency mode (tested).
* Several agency logins are supported; each connection records which one it uses, and a new client goes to the least loaded login that has room under its cap.

**Storage and the 30-day rule (GBP-02).** No retention job for Google content exists yet (`GOOGLE_DATA_RETENTION_FINDINGS.md`, decision D3, still open), so there is no existing logic to attach to. The new tables hold FlowQR's own control record only: consent, dates, status, and Google **identifiers** (`locations/{id}`, the admin resource name, the account name the location is listed under). They hold no review, reply, post, photo or metric, and no token (the one token store, `google_agency_accounts`, is encrypted with its own key). Whether Google counts those identifiers as "Content" is part of question 3 in section 9. The existing GBP-02 problem (stored reviews and metrics) is **not** fixed by this work.

**What this does not change.** Option A (client OAuth under FlowQR's one project) is untouched and still needs Google's answer (GBP-01). Option B shifts which login acts; it does not by itself answer whether Google accepts one agency account serving many clients, which is question 2 below.

## 8. What is still unverified (every `TODO(verify)` in the code)

Read from Google's reference on 2026-11-21: the invite, accept, list-invitations, list-admins and delete calls exist as described in `agency_client.py`. The reference does **not** say (rows 1 to 5 were written for the individual invitation; section 11.7 adds the group-specific ones and says which of these still apply):

| # | Unverified | Where in the code | What the code does meanwhile | How it gets answered |
|---|---|---|---|---|
| 1 | Under which account a location is listed for the agency login after accepting (its own account, a location group, the client's account) | `agency_client.list_visible_locations`, `agency._visible_account` | Reads the account name Google actually lists it under and stores it (`agency_account_name`); the v4 reviews, posts and media paths need `accounts/{a}/locations/{l}`. If no account lists it, **it is not treated as visible and nothing switches** | Runbook step 4 |
| 2 | Whether a manager may remove **itself** (`locations.admins.delete` as the agency login) | `agency_client.remove_manager`, `agency.remove_self` | On 403 it checks whether the location is already invisible (then done); otherwise reports `removal_refused`, keeps retrying, alerts a person near the deadline, and the notice already tells the client how to remove FlowQR in Google | Runbook step 9 |
| 3 | The exact status and reason for a duplicate invitation | `agency._step_invite` (409) | Looks for an existing invitation first; treats 409 as "already invited" | Runbook step 7 |
| 4 | Whether `admins.list` returns the invitee's e-mail (the reference says `admin` is "only needed during creation") | `AdminEntry.email`, `agency._step_invite`, `remove_self` | If absent, duplicate detection relies on Google's refusal, and removal relies on the name stored from the invite response | Runbook step 7 |
| 5 | Which account is the `parent` for `invitations.list`, its paging, the `Invitation.state` field, and the syntax of its `filter` | `agency_client.list_pending_invitations` | Asks every account the login lists (403 and 404 skipped), reads only `name` and `targetLocation.locationName`, sends no filter | Runbook step 4 |
| 6 | How many locations one agency account may manage | `GOOGLE_AGENCY_MAX_LOCATIONS_PER_ACCOUNT`, `google_agency_accounts.max_locations`, `agency.pick_account_id` | **0 means unknown.** No limit is assumed; a cap is applied only if set from a written Google answer | Question 2 below |
| 7 | The exact format of `targetLocation.locationName` | `agency_client.location_key` | Compares by the last path segment, so `locations/1` and `accounts/9/locations/1` match | Runbook step 4 |
| 8 | Business-day count is Monday to Friday; public holidays are not excluded | `agency.add_business_days` | The recorded deadline can only be earlier than a holiday-aware count, so FlowQR errs towards removing itself sooner | Counsel |
| 9 | Whether the policy's 48-hour and seven-business-day figures are still current wording | `GOOGLE_AGENCY_NOTICE_HOURS`, `..._REMOVAL_BUSINESS_DAYS` | Read from `GOOGLE_DATA_RETENTION_FINDINGS.md` and section 1 above | Re-read the policy page before go-live |

## 9. Questions for Google (add to the draft in section 5)

1. **Shared project (unchanged, still the blocker).** Is one FlowQR Cloud project, used by owners who each authorise it (Option A), allowed, or must clients be on the agency route?
2. **Agency account scale.** May one agency Google account manage hundreds or thousands of locations for unrelated clients? Is there a limit on locations or on managers per account, and does using one account for automation at that volume put the account at risk?
3. **How a location appears after acceptance, and what counts as "Content".** After an agency login accepts a manager invitation, under which account does the location appear for that login, and which API call lists it? Are resource identifiers and our own counters "Content" under the storage limit?
4. **Self-removal and invitations.** May a manager remove itself through `locations.admins.delete`? What does Google return for a duplicate invitation? Does `locations.admins.list` return invitee e-mails?
5. **LocationGroup delegation.** May FlowQR's Business Group be invited as Manager by many unrelated clients? Where does that invitation appear (whose `invitations.list`), and which user may accept it?
6. **Group access paths.** After acceptance, does the group list the location under `accounts/{group}/locations`, and do the v4 reviews, posts and media calls accept `accounts/{group}/locations/{id}`? Does `locations.admins.list` return `Admin.account` for a group admin?

## 10. The alternative with no client token at all: the client adds FlowQR in Google

The client can skip FlowQR's invite entirely: in Google Business Profile, **People and access, Add**, they enter the FlowQR agency e-mail (or, with group delegation, FlowQR's Business Group) and choose **Manager**. No client OAuth token ever reaches FlowQR's project, so there is nothing to revoke and no `business.manage` grant from the client to explain.

**Not built.** Most of the work already exists and would be reused as it is: the agency login accepts the pending invitation (`_step_accept`), is checked to see the location (`_step_verify`), the notice, stop, loss detection and storage rules all apply unchanged. What is missing is (a) a way for the client to say which location they added FlowQR to, which cannot come from the client's own OAuth listing (there is none), so it would come from the **agency login's** own list of pending invitations and visible locations, matched to the business by an administrator or by a code the client enters; and (b) the consent step without a Google sign-in, tied to the signed-in FlowQR user. Cost: the client does one more manual step in Google. Benefit: the strongest answer to "indirect access through your project", because the client never authorises our project at all. Worth choosing if Google's answer to question 1 is no.

</content>

## 11. Correction 2026-11-21: delegate to FlowQR's Business Group, not to one person's e-mail

### 11.1 What the first build did
`agency._step_invite` sent `{"admin": <agency e-mail>, "role": "MANAGER"}`: **target A, an individual agency e-mail.** That was a fair reading of the first brief. FlowQR has since set up its Google Business Profile organisation (accountNumber `5234249121`, API resource name `accounts/110178313486978980497`) and Location Group (accountNumber `5488245563`, API resource name `accounts/114863040359228435467`), and the intended architecture is **group-level delegation** to that group. The individual path stays only as a documented fallback (section 11.9). These are identifiers, not secrets. **Correction (2026-11-21, after the first real read-only API check):** the owner first reported the short accountNumber references; the API's resource names are the long ones above, and `accounts/<accountNumber>` is 404. The resource names were confirmed by a real `accounts.list` with the agency token.

### 11.2 User-level versus group-level delegation

| | Individual (fallback) | LocationGroup (intended) |
|---|---|---|
| What the client invites | one Google login, by e-mail: `Admin.admin` | FlowQR's Business Group: `Admin.account = accounts/114863040359228435467` |
| Who gets access | that one person | every member of the group, as far as the group's role allows |
| Who accepts | the invited person | the Location Group's administrator, with their own credentials (documented); which kinds of administrator qualify is not |
| Staff changes | a new login means a new invitation to every client | add or remove a member of FlowQR's group; no client does anything |
| Offboarding | access ends only if that login is removed from every client | removing the person from the group ends their access to all clients at once |
| How accepted access shows in Google's admin list | by the person's **name** (the e-mail only while the invitation is pending, as documented) | by `Admin.account` (**assumed** to be returned, TODO(verify)) |
| If a login is compromised | its clients | **every client of the group**, so membership needs review and MFA (11.8) |
| Recorded in FlowQR | `target_type = individual_agency_user`, no group | `target_type = flowhq_location_group`, `target_account_name = accounts/114863040359228435467` |

When both `account` and `admin` are sent, Google says `account` takes precedence and the e-mail is ignored. So the group call has **no e-mail parameter at all** and refuses anything that is not a numeric account id before a request exists: a mistake can never be hidden by Google ignoring half of it.

### 11.3 What Google's pages say (read 2026-11-21, in three rounds) and what they do not
**Where the invitation sequence is documented.** The merchant-invites, administrator-lists, administrator-accepts sequence for a Location Group is on **transfer-locations**, under "Transferring to a location group". The **manage-locations** page documents what a Location Group is and how to verify (`accounts.list`, then list the account's locations); it does not describe the invitation. Both were read in full.

**Documented by Google**
* **The sequence** (transfer-locations): (1) `locations.admins.create`, "with the merchant OAuth credentials", with the `account` field set to the location group account ID and "the appropriate role"; (2) "the location group administrator's credentials" call `accounts.invitations.list` "passing the location group's account ID as the `parent` argument" and find the invitation for the target location; (3) `accounts.invitations.accept`; (4) the destination account's credentials call `accounts.locations.list` and the location appears. **The page is written for an ownership transfer.** FlowQR never transfers anything.
* **A Location Group** (manage-locations): "A location group is used to manage a group of individual locations." "When you add personal accounts and user groups to a location group, they inherit the location group's permissions." "A personal account that belongs to an organization or user group isn't eligible to directly own a location or location group." "It's best not to add personal accounts to a location group. Instead, grant user groups access directly."
* **Verification** (manage-locations): call `accounts.list`; "the response includes an account `name` and a `type`, such as `LOCATION_GROUP`"; then `GET https://mybusinessbusinessinformation.googleapis.com/v1/{accountId}/locations`.
* **Account types** (Account reference): `PERSONAL`, `LOCATION_GROUP` ("A group of Locations"), `USER_GROUP`, `ORGANIZATION` ("An organization representing a company"). `PERSONAL` and `ORGANIZATION` cannot be created through the API. The organisation and the group are different accounts with different IDs.
* `Admin.account` ("Used when calling locations.admins.create to invite a LocationGroup as an admin", format `accounts/{account}`); when `account` and `admin` are both set, `account` wins and the e-mail is ignored.
* `accounts.invitations.list`: `GET /v1/accounts/{id}/invitations`, "pending for the account", at most 1000, `filter` on `Invitation.target_type` (no syntax). An `Invitation` has **no `state` and no `inviter`**. `accounts.invitations.accept`: empty body, scope `business.manage`, no role or account type named.
* `Admin.admin` on a GET "returns the email address if the invitation is still pending, and otherwise the user's first and last names."
* Probation (transfer-locations): "users added as an owner or manager are limited for 7 days and can't transfer primary ownership of a profile".

**Inconsistencies inside Google's own pages.** The manage-admins example sends a bare `"LocationGroupID"` where the Admin reference says `accounts/{account}`; and its individual example uses `adminName` where the reference field is `admin`. The code follows the reference.

**Not documented** (so not assumed): that the same sequence holds for a **Manager** invitation rather than an ownership transfer; which kinds of administrator may accept; whether being listed by `accounts.list` is enough to read the group's invitations; whether a Manager group lists the location; the v4 account path for a group; limits.

### 11.4 The six things the state machine now keeps apart
| Concept | Field | Set when, from what |
|---|---|---|
| Invitation target resource | `target_type`, `target_account_name` | at consent, from the agency login chosen |
| Agency Google **user** identity | `agency_account_id` (the `google_agency_accounts` row, e-mail and tokens under their own key) | at consent |
| LocationGroup resource ID | `target_account_name`, and `google_agency_accounts.location_group_name` | at registration (`google-agency-register --location-group-id`, default `GOOGLE_AGENCY_LOCATION_GROUP_ID`) |
| Receiving invitation account ID | `receiving_account_name` | **read from Google** when the pending invitation is found, never assumed |
| Accepted manager resource | `admin_resource_name` (`locations/{id}/admins/{admin}`) | from the invite answer; what removal deletes |
| Verified location access | `verified_at`, `agency_account_name` | only when the **group's own** location list shows the location under the group's account |

### 11.5 The group flow, against Google's documented sequence
0. **Pre-flight, before the merchant's token is touched.** The agency Google user's own `accounts.list` must contain `accounts/114863040359228435467` typed `LOCATION_GROUP`. Not listed means the user is not an administrator of the group; typed `ORGANIZATION` means the id is the organisation's; anything else is unconfirmed. In each case the authorization becomes `needs_attention`, a person is alerted, **nothing is sent to Google**, and Check again resumes once it is fixed.
1. **Consent** by the client in FlowQR, stored with version, hash, time and person.
2. **Create** with the **merchant's** token: `POST locations/{id}/admins {"account": "accounts/114863040359228435467", "role": "MANAGER"}`. No e-mail. The merchant's token also does a duplicate-guard read of the location's admin list at this step, and, if the client stops before acceptance, withdraws the invitation; the end revoke is the last use. It is **never** used to list invitations, accept, or list the group's locations.
3. **List** the invitation with the **group administrator's** token: `GET accounts/114863040359228435467/invitations`, the group as `parent`. **Only that list is read.** Searching every account the user can see exists as a diagnostic (`GOOGLE_AGENCY_INVITATION_DISCOVERY`), **off by default**: when the invitation is not in the group's list the authorization waits and then needs a person, and nothing is accepted from anywhere else. A refusal on the group's list means `group_access_missing`.
4. **Accept** with the same administrator's token.
5. **Verify** with the group's credentials: `accounts/114863040359228435467/locations` must contain the location **under the group's account**; and the location's admin list must not show the group pending or with a role other than Manager (an unreadable admin list does not block).
6. **Switch** only when **every selected location** is verified for the same login and the same group; `google_account_name` is re-pointed to the group account (TODO(verify), G6). **Then** the merchant's token is revoked, unless another FlowQR connection (any business) still runs on a token of the **same Google user**: then it is kept, encrypted, and revoked later, because revoking a grant may affect that user's other tokens (G16). That wait is deliberate and raises no alert.
7. **Unchanged:** the notice, stop, removal, loss detection (one group-wide listing per check), consent and audit records. If the agency user loses group membership, no client is marked lost; a person is alerted once a day.
8. **Nothing in this flow transfers ownership, requests an Owner role, or uses the organisation id.** Tests enforce each.

**Found and fixed in this review: a cross-client leak.** The "refresh locations" button called the same discovery as the first connection, and in agency mode the token it used is the agency user's, which sees **every client of FlowQR's group**. A refresh would have copied other businesses' names and addresses into this business's records and overwritten its own location's title and address. Reproduced with a test first, then fixed: an agency-managed connection now refuses to re-list (`409 managed_by_flowqr`) and makes no Google call. Nothing else in the code lists accounts or locations with a stored connection token for a business (the operator tools `google-smoke` and `google-readiness` do, and are not customer-facing).

### 11.6 Answers to the review questions: what is known, what is assumed

| Question | Answer | Status |
|---|---|---|
| Which account owns the pending invitation? | Documented (transfer-locations): the **Location Group**: the administrator lists invitations with the group as `parent`. Implemented that way only. | Documented; real test still needed (G2) |
| Where does it appear? | In `accounts/114863040359228435467/invitations`, with `targetLocation.locationName`. | Documented; real test still needed (G2) |
| Which authorised user accepts? | "The location group administrator", with their own credentials. FlowQR uses the agency Google user and refuses to start unless that user's own `accounts.list` shows the group. | Documented; which kinds of administrator qualify is not (G3) |
| How does the agency user's OAuth identity reach the invited group? | By already administering the group (directly or, as Google recommends, through a user group). A person arranges that in Google; FlowQR cannot. Checked by the pre-flight. | Partly documented (G4) |
| How is the resulting visibility verified? | The group's credentials call `accounts.locations.list` on the group: the location must appear under it. | Documented; real test still needed (G5) |
| Can the group list **and manage** the location after acceptance? | List: shown by that call. Manage: the admin list showing the group as Manager and not pending is the evidence the role was granted; real write ability is proved only by one approved edit (runbook step 5.5). No automated test writes. | Partly unverified |
| Are individual and group acceptance identical? | **Not assumed.** Different list, different accepting user, different way of recognising the admin, different verification listing. | Handled |

### 11.7 Verification matrix
Three questions for every row, kept separate on purpose. **A row is never marked real-tested because Google documents it, or because a mock passes.** Nothing in column 4 has been run against Google; the whole of column 4 is what the manual two-account runbook is for.

| # | Behaviour | 1. Documented by Google | 2. Implemented and mock-tested | 3. Real two-account test still required |
|---|---|---|---|---|
| G1 | Form of `account` in the create request | **Inconsistent across pages:** `accounts/{account}` (Admin reference) versus a bare id (manage-admins example) | Reference form sent, exact body pinned (`{"account": "accounts/114863040359228435467", "role": "MANAGER"}`, no `admin`); a bare id is normalised; anything else refused before a request exists | **Yes**: does Google accept `accounts/114863040359228435467` |
| G2 | Whose invitation list holds a group invitation | **Yes** (transfer-locations): the Location Group, as `parent` of `accounts.invitations.list` | Group parent only; the search across every account is a diagnostic, off by default; a "lands elsewhere" invitation stalls instead of being accepted | **Yes**: the page describes an ownership transfer; confirm it is the same for a Manager invitation |
| G3 | Who may accept for the group | **Yes, in outline:** "the location group administrator" with their credentials. Which administrators qualify is not stated | The agency Google user accepts with its own token; the merchant's token and a non-administrator's cannot proceed; wrong identity stops before any invitation | **Yes**: direct administrator versus user-group member |
| G4 | How the agency user's identity reaches the group | **Partly:** members inherit the group's permissions; user groups recommended; `accounts.list` returns the account with its `type`. Not stated: that being listed lets a user read the group's invitations | Pre-flight: the user's own `accounts.list` must show the group typed `LOCATION_GROUP` before any invitation or merchant call | **Yes**: does the real `accounts.list` for `vatsal@flowhq.co.in` include the group |
| G5 | The accepted location appears under the group | **Yes** (transfer-locations, manage-locations): the group's credentials list the location | `accounts/{group}/locations` required and checked under the group's account; a location visible only elsewhere does not count | **Yes**: documented for a transfer; confirm for a Manager invitation |
| G6 | The v4 reviews, posts and media paths accept `accounts/{group}/locations/{id}` | No | `google_account_name` is set to the group account; mock only | **Yes** (runbook 5.2) |
| G7 | `locations.admins.list` returns `Admin.account` for a group admin | The `account` field exists; that list answers include it is not stated | Used for duplicate detection and removal lookup; absence falls back to Google's refusal and the stored name | **Yes** |
| G8 | Who may delete the group's admin entry | No | Tries with the agency user's token; on 403 checks whether the group still lists the location; else `removal_refused`, retries, alerts | **Yes** |
| G9 | What the organisation (`accounts/110178313486978980497`; accountNumber `5234249121`) contributes | Types are distinct; "a location group in the organization" is mentioned; nothing on listing paths | **Never used to call Google.** Refused as a group id (registration, pre-flight, production guard); the type check catches an organisation id too | **Yes**: which account actually lists the location |
| G10 | Pending, expired, withdrawn invitations | **Yes:** an `Invitation` has no `state` and no `inviter` | Not listed means wait, then `needs_attention`; visibility settles the "already accepted" case | Observe |
| G11 | How many locations a group or its members may manage | No | `max_locations` per login and a config cap; **0 means unknown** | Question 2 to Google |
| G12 | Status Google returns for a duplicate invitation | No | Reads the admin list first; treats 409 as already invited | **Yes** |
| G13 | Terms prompt for an invited group | Only for invited **users** ("they will be prompted to agree to the terms") | Nothing assumed | **Yes** |
| G14 | Seven-day limit on newly added owners and managers | **Yes**, stated for transferring primary ownership; whether it limits managing is not | Not applicable: FlowQR never transfers | Observe what is blocked in the first seven days |
| G15 | Whether an invited **person** inside an organisation may be a manager | For owners: "can't be a member of an organization account or user group"; for managers not stated | Applies to the individual fallback only | Only if the fallback is ever used |
| G16 | Whether revoking one refresh token ends the same Google user's other tokens for FlowQR's project | Not in the pages read | The merchant's token is kept while another connection runs on the same Google user, then revoked | Cannot be settled by reading; the guard stays |
| G17 | `accounts.list` returns `type` for a group | **Yes** (manage-locations and the Account reference) | The pre-flight requires `LOCATION_GROUP`; a missing or other type stops safely | Confirm the real value |

Still open from section 8 and unchanged: the business-day count (8), the currency of the 48-hour and seven-business-day figures (9), and rows 1 to 7 as they apply to the individual fallback.

### 11.8 What group delegation changes for governance (owner decisions, not code)
* **Anyone in the group can act on every client.** Keep a written list of the members, require MFA for all of them, and review it on a schedule.
* Use a **dedicated agency Google user** for FlowQR's automation, a member of the group, never a person's own account.
* Write the offboarding step: removing a person from the group ends their access to all clients at once. That is the main benefit over individual invitations.
* FlowQR staff in the group can open client profiles in Google. That is a disclosure matter for the privacy documents and the data inventory (counsel).
* Keep the group and organisation IDs in configuration (`GOOGLE_AGENCY_LOCATION_GROUP_ID`), not in code.
* None of this answers whether Google accepts one agency group serving many unrelated clients. That remains questions 2 and 5 in section 9. **No Google policy approval is claimed.**

### 11.9 The individual fallback
Kept for two documented cases: Google refusing group invitations (G1 to G4), and the period before the group is usable. It runs **only** when `GOOGLE_AGENCY_INDIVIDUAL_FALLBACK=true` **and** no group-capable agency login has room; a login that belongs to a group is always preferred, even with the fallback on. With the fallback off and no group login, a client's consent is refused with "FlowQR cannot take this on right now" and nothing is sent. Limits: an accepted person appears by name, so duplicate detection by e-mail only works while the invitation is pending; and access depends on one login. Records of that path are marked `individual_agency_user`.

### 11.10 What is tested, and what that proves (updated after the second review)
Mocked tests cover: the group invitation and its exact request (account resource, role, no `admin`), no e-mail ever sent in group mode, duplicate group invitations, listing the group's invitations, accepting, visibility under the group (and not as an individual), wrong or missing group access (no membership, listed under another account, still pending, wrong role, wrong account in Google's answer, access lost midway), group removal, tenant isolation, the feature switch off, and that the connection is never switched or the client's token revoked before every selected location is verified. They prove the code does what Google's **pages** say. They do not prove Google behaves as the pages say, and they say nothing where the pages are silent: only `docs/runbooks/GOOGLE_AGENCY_TWO_ACCOUNT_TEST.md`, run by a person, can answer that.

Added in the second review: the merchant's token is used only for the invitation step (and its withdrawal and final revoke) and never to list, accept or verify; the group administrator's token lists with the group as parent and accepts; the group's credentials list the accepted location; a different Google user, or one that is not an administrator, cannot complete the process and nothing reaches Google; the organisation id is refused as the group; an id that `accounts.list` does not type as a Location Group is refused; the invitation is looked for only where Google documents it; nothing switches until the group lists the location, even when the admin list already says Manager; the merchant's token is kept while another connection uses the same Google user; no ownership is transferred or requested; and the cross-client leak above cannot recur.


## 12. Addendum 2026-11-21: a client who ALREADY added FlowQR's group, and proving the API access first

Situation: the client approved the group's management request in Business Profile Manager, so the location is listed under `accounts/114863040359228435467`, but the FlowQR connection still runs on the client's own Google login. Website visibility is **not** evidence that the API reaches it.

* **Read-only proof first.** `python -m app.cli google-agency-check` (services/google/agency_check.py) makes only reads with the stored agency token: identity (Google's own answer, never the label), `accounts.list` (the group listed and typed LOCATION_GROUP), the group's locations (counted, never named), the client's location id under the group, a review page at `accounts/<group>/locations/<id>`, and which FlowQR business holds that location. Registration takes `--expect-email`: Google's answer must match or nothing is stored and the sign-in is revoked. **Until this has been run with the real token every one of these is MOCK TESTED ONLY.**
* **No second invitation.** The old order was invite (with the CLIENT's token) then accept then verify. For a location already listed under the group that sent another invitation, depended on Google returning `Admin.account` (TODO(verify)), and used the client's token for a write. With `GOOGLE_AGENCY_ADOPT_EXISTING_ACCESS` (default off) the location is verified from the group with the agency token only and nothing is sent. A location that is not listed is invited exactly as before. The consent, the separate notice and verify-then-switch are unchanged. **New refusal:** if another business already holds an open authorization for the same Google location the flow stops (`location_claimed`) and alerts a person; the database's own one-open-authorization rule is per FlowQR location row and could not see this.
* **Rollback.** The client's token used to be revoked at once, so a switch could not be undone. `GOOGLE_AGENCY_CLIENT_TOKEN_KEEP_HOURS` (default 0 = as before) keeps it, encrypted and unused, for that long; `google-agency-rollback` then returns the connection to the client's own login after proving that token still works. The consent wording states the keep window when it is set. Rolling back does not remove FlowQR's group in Google.
* **Stopping an adopted location.** A location adopted from existing access has no manager-entry name from an invitation. If a list cannot name it, the old code reported the removal as DONE without asking Google anything. It now stays `stopping` (a person is alerted near the deadline) unless the agency login really can no longer see the location.
* **Still unverified (add to section 8):** that `accounts/<group>/locations` lists a location a client added through a management request (not an invitation); that `accounts/<group>/locations/<id>/reviews` (v4) answers for a group account; whether a manager may read the admin list; the real date the client's approval took effect (the notice clock starts when FlowQR records it).
