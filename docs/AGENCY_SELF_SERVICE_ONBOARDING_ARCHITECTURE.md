# Agency self-service onboarding: architecture

Branch `feature/agency-self-service-onboarding` (from `origin/release/gbp-agency` @ 0604555). Migration 0067 (on top of Local SEO V2's 0066). Feature flag `GOOGLE_AGENCY_SELF_SERVICE_ENABLED` (off by default). Not deployed.

## 1. What this is, and what it is not

The customer connects Google once, chooses a location, agrees once (to the wording and to each permission category), and FlowQR then does the rest: invites FlowHQ's business group as **Manager** with the customer's own credentials, accepts with FlowHQ's own agency login, checks real access, maps and records everything, and starts synchronization. Each stage is shown from the records, never from hope.

It adds **no new Google call and no new permission**. The steps already existed in `services/google/agency.py` (consent → invite → accept → verify → switch → stop). This work adds the customer journey around them, the per-category consent and its enforcement, the operator screen, the notices, the revocation of the customer's OAuth after a stop, and four robustness fixes (§8).

## 2. Two Google identities, never mixed

| | Customer (merchant) | FlowHQ agency |
|---|---|---|
| Who | the business owner's own Google account | FlowHQ's own login (registered once by a person, `google-agency-register`) |
| Table | `google_connections` (key `TOKEN_ENCRYPTION_KEY`) | `google_agency_accounts` (separate key `AGENCY_TOKEN_ENCRYPTION_KEY`, platform-only row-level security) |
| Used for | discover accounts and locations; list admins; **create the Manager invitation**; withdraw a pending invitation; revoke | list pending invitations; **accept**; verify the location is listed under the group; sync reviews after the switch; remove itself |
| Never used for | accepting, verifying | anything for a business without an active, mapped, consented authorization |

`resolve_agency_access` is the single gate for every use of the agency login: one active authorization for exactly this tenant, connection, agency login and Google location; the location under the group the authorization names; no other business with an open authorization for the same Google location; operator grant while internal-only; and now the permission category the business agreed to. It fails closed and audits each refusal. Tokens are never sent to the browser, logged, or put in the audit log.

## 3. The journey and its states

The state is **derived on every read** (`services/google/agency_journey.py`) from records that already exist, so it cannot drift from them. Every change of an authorization's status is also written to `audit_logs` by `agency_audit.py` (`google.agency.transition`, in the same transaction), and the journey's timeline reads that log. The pre-authorization events (`google.connect_started`, `google.connect`, `google.select_locations`, `google.agency.consent`) are audit entries too.

| State | Evidence |
|---|---|
| NOT_STARTED | no live connection and no recent sign-in attempt |
| CUSTOMER_OAUTH_PENDING | `google.connect_started` in the last 15 min with no completed connection after it |
| LOCATION_SELECTION_PENDING | connection active, locations discovered, none selected (or none found: said so) |
| CUSTOMER_CONSENT_PENDING | a location selected and mapped to the business's own FlowQR location; no authorization yet |
| MANAGER_INVITE_CREATING | authorization `consented` (consent stored, nothing at Google yet) |
| MANAGER_INVITE_PENDING | `invited`, invitation not yet visible to the agency login (`invitation_name` empty) |
| AGENCY_ACCEPTANCE_PENDING | `invited`, invitation found, acceptance not recorded |
| ACCESS_VERIFICATION_PENDING | `accepted` (`accepted_at` set), the location not yet listed under the group |
| CONNECTED | `verified` or `active`: the location was **listed under the group by the agency login** (and, for a group, the admin entry is not pending and the role is Manager) |
| FAILED | `failed` / `withdrawn` |
| REVOKED | `stopping` / `stopped` / `cancelled` / `lost` |
| EXPIRED | the customer's sign-in was refused (`client_token_invalid`, connection `revoked`) or the invitation never appeared (`invitation_not_found`) |
| BLOCKED | a rule or setting, not an error: business not opened by an operator, Google has not approved the API project, no agency login, location already claimed, group access missing, wrong group type, unexpected role, place-id mismatch |

Mapping notes. `needs_attention` is shown as the step it is waiting in (a person at FlowQR has been alerted) unless its code is a block or an expiry. With several locations the connection shows the most pressing state, else the *least advanced* one.

Eight stages are reported, each `done | current | waiting | pending | blocked | failed`, with the customer's wording: Connecting Google account · Finding your business locations · Selecting business location · Approving FlowQR as your Manager · Requesting FlowHQ manager access · Accepting agency invitation · Verifying access · Synchronizing reviews. A stage is `done` only when its own evidence exists (`accepted_at`, `verified_at`, a successful sync at or after `switched_at`).

**Sync stage honesty.** With `GOOGLE_AGENCY_OPERATIONS_ENABLED` off, onboarding ends at *access verified*: the state is CONNECTED but the sync stage is `blocked` with the reason, and the customer's own sign-in keeps syncing exactly as before. Nothing says "synchronizing" unless it is.

## 4. Sequence (all stages mapped to code)

1. `POST /google/connect?return_to=journey` → audit `google.connect_started`, Google's consent screen (the customer acknowledges it once).
2. `GET /google/callback` → exchange code, **business.manage scope required**, store encrypted tokens, discover accounts/locations, land on `/gbp/connect` (fixed allow-list; the value is never used as an address).
3. `PUT /google/connections/{id}/selection` → choose the location and map it to the business's own FlowQR location (existing).
4. `POST /google/agency/journey/start` (admin only, verified e-mail, 10/hour): stores consent (wording version + hash, who, when, **categories**), refuses a location another business holds, then `advance_connection`:
   - `_group_preflight`: the agency login must list the FlowQR group typed LOCATION_GROUP before the customer's token is used for anything;
   - invite with the **customer's token**: `POST locations/{id}/admins {"account": "accounts/<group>", "role": "MANAGER"}`;
   - accept with the **agency token**: `invitations.list` on the group, `:accept`;
   - verify: location listed under the group, place id equal, admin entry not pending and Manager;
   - switch (only if operations are on): connection to `agency_account`, customer token revoked at Google, then the first sync is queued once.
5. Hourly `flowqr.agency_housekeeping` continues anything waiting (growing pauses), re-verifies access every 6 h, sends notices, finishes removals. Recurring review sync is the existing `sync_due_locations` schedule.

## 5. Consent

Specific and separate from the OAuth callback. The customer ticks each category; reading is always included, the rest are opt-in: `read_reviews`, `reply_to_reviews`, `publish_posts` (posts and photos), `edit_profile`. Stored in `consent_actions`; the agreement itself is audited. **Enforced**: `get_access_token(..., action=)` is passed at reply publishing, post and photo publishing, the profile editor and the governed post/photo screens; an agency connection refuses a category not agreed (`action_not_consented`, audited). `NULL` = recorded under the earlier wording (covered all four, each still needing the customer's approval). Public actions still need the customer's approval inside FlowQR; the categories are an additional ceiling.

## 6. Notices

| Notice | When | Once-only record |
|---|---|---|
| Manager added (separate from Google's) | at acceptance, due within `GOOGLE_AGENCY_NOTICE_HOURS` (48); overdue alert to staff | `notice_sent_at` |
| Stopped | on the customer's stop request | `notices_sent.stop_requested` |
| Removed (exclusive control again) | when FlowQR has removed itself | `notices_sent.removed` |
| Access lost | when FlowQR's access is found removed in Google | `notices_sent.lost` |
| Could not be set up | when onboarding fails | `notices_sent.failed` |

## 7. Disconnect and revocation

`POST /google/agency/connections/{id}/stop` (works with the feature off): all work stops at once, the connection is marked disconnected, selection cleared, FlowQR removes itself as Manager (withdraws a pending invitation with the customer's token), retried hourly and alerted two days before the deadline (`GOOGLE_AGENCY_REMOVAL_BUSINESS_DAYS`, 7). **New:** once nothing is still `stopping`, the customer's own Google sign-in is revoked at Google and the stored copy dropped (`finish_client_oauth`); `DELETE /google/connections/{id}` keeps the encrypted sign-in only while an unfinished withdrawal still needs it. A stopped authorization is not "open", so a later reconnect starts a fresh, audited one. Reviews already synced follow the existing retention rules (30-day redaction when retention is on).

## 8. Robustness changes to existing behavior

1. A failure recorded by an onboarding step (expired sign-in, refusal) was **not committed** and was lost; `_drive` now commits after each step.
2. The hourly job isolates each business (`try/except` + rollback per connection), so one broken business cannot stop the others.
3. `connection_lock` (short Redis lock) so two clicks, a retry and the hourly job cannot each invite. Without Redis the steps are still individually idempotent (each lists what Google already holds first).
4. After a stop, the customer's OAuth is revoked at Google (it was previously left stored).

## 9. Security properties

OAuth `state` is signed and bound to browser cookie, tenant and user; the callback requires the same session user and an admin membership; scope `business.manage` is verified; redirect URI is configured server-side (exact match at Google). Tenant isolation by row-level security plus explicit tenant checks; operator endpoints answer 404 to anyone not in `GOOGLE_AGENCY_OPERATOR_EMAILS` (verified e-mail, no tenant membership needed or granted); the operator can retry but **cannot record consent**. Rate limits: start 10/h/tenant, consent 10/h, advance 30/h, operator retry 60/h. No password is ever requested; no token, e-mail body or Google content is logged or returned.

## 10. Google documentation basis (read 2026-11-23)

* OAuth setup: merchant signs in once and acknowledges the consent dialog; the platform caches credentials; **the invitation is created with the merchant's cached credentials; it is accepted with the management user's cached credentials**; Google e-mails the merchant on add/remove; merchants can revoke at any time; resellers must use the partner's own app name/logo or a separate Cloud project. This is the flow implemented.
* Reference `Admin`: `admin` (invitee e-mail), `account` (`accounts/{account}`, used to invite a LocationGroup; wins over `admin` if both are set), `role` (required), `pendingInvitation` (output only). The code sends exactly these.
* **Documentation inconsistency, not resolved:** the conceptual *manage-admins* page shows `adminName` and `"account": "LocationGroupID"`; the reference shows `admin` and `accounts/{account}`. The reference form is sent. If a live test shows Google rejecting it, the failure is recorded and surfaced as `invite_refused`; nothing is simulated.
* Not documented anywhere and therefore live-test items: where a group invitation appears for acceptance, whether a Manager may remove itself, whether `list` returns the invitee e-mail (see `agency_client.py` `TODO(verify)`).
* Policy restrictions kept: FlowHQ operates through its own approved project and agency login; the project and its credentials are never exposed to customers; no OAuth/consent step is bypassed; no action is automated without the customer's express, categorized authorization; Google content retention applies; FlowQR does not present itself as Google.

## 11. Known limits

* Nothing in this branch has been exercised against real Google (§ test matrix). The first live run is a human-assisted two-account test (runbook).
* The path is **internal-only in production** (`GOOGLE_AGENCY_INTERNAL_ONLY`): a business is BLOCKED (`not_opened_for_business`) until an operator opens it. Opening it to the public is a separate decision (Google's answer on shared-project, multi-business use is still unresolved) and is not made here.
* Google offers no webhook for invitations: acceptance and visibility are polled (pauses grow to `GOOGLE_AGENCY_POLL_MINUTES`).
* A manager removing itself (`admins.delete` with the agency token) is undocumented; if Google refuses, a person must remove FlowQR, and the customer can always remove it in Google.

## 12. Verification status and the integration note (final round)

* The architecture above is implemented and tested against an in-memory Google and, for the screens, in real browsers. It has not been exercised against real Google. Section 11 lists what a live run must still confirm; the runbook, section 7, is the procedure.
* The Google request contract (v1 `locations/{id}/admins` with `{"account": "accounts/{id}", "role": "MANAGER"}`; accept at `accounts/{a}/invitations/{i}:accept` with the agency token) was confirmed from the code's own requests on a mock transport, not from Google.
* Operator list: `GET /agency-ops/journeys` now returns every Google connection (including those waiting on the customer or held back by a rule), because a business that is blocked before any authorization exists is exactly what an operator needs to see.
* Merging with `hardening/production-readiness-audit` produces one small textual conflict in `GoogleConnection.tsx` (keep `<AgencyManager available=... />` and `<JourneyLink />`); the other overlapping files merge automatically; re-run both suites after merging.
