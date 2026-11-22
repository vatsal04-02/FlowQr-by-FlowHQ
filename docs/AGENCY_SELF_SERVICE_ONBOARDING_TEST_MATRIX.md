# Agency self-service onboarding: test matrix

**Read this first.** Every automated test below runs against an **in-memory fake of Google** (`tests/fake_agency_google.py`). They prove that FlowQR's code does the right thing given what Google's documentation says. They do **not** prove that Google behaves that way. **No stage of this journey has been run against real Google**: that needs a dedicated test Business Profile and two people signed in to Google (runbook §3). The right-hand column says so for every row.

Test file: `backend/tests/test_agency_self_service.py` (45 tests), plus the existing agency suites (`test_google_agency*.py`, 257 tests, all still green) and `frontend/tests/agency-journey.test.mjs` (9 tests). Results are in the implementation document.

| # | Brief item | Automated test (fake Google) | Real Google |
|---|---|---|---|
| 1 | Customer registration | `make_business` in every test; `test_one_google_sign_in_one_agreement_then_everything_follows_over_the_real_routes` starts from a new business | existing sign-up, not re-tested live |
| 2 | Google OAuth | same end-to-end test: `POST /google/connect`, real `/google/callback`, state cookie, scope check; `test_a_started_but_unfinished_google_sign_in_is_oauth_pending_then_clears` | **not run** |
| 3 | One-time consent | the consent screen is Google's own; FlowQR records only that the sign-in completed with `business.manage` (existing `test_google_and_reviews.py`) | **not run** (human) |
| 4 | Account discovery | end-to-end test (accounts/111) | **not run** |
| 5 | Location discovery | end-to-end test lists both locations; `…no_locations_says_so…` | **not run** |
| 6 | Location selection and mapping | end-to-end test maps to the business's own FlowQR location; `…selected_location_waits_for_the_customers_own_agreement…` | **not run** |
| 7 | Merchant-side manager invitation | `…journey_reaches_connected_only_through_real_records…` (customer's token, `account`=group, role MANAGER, no e-mail, never Owner) | **not run** |
| 8 | Agency-side acceptance | same test (agency token accepts); `…invitation_google_has_not_yet_delivered…`; `…each_stage_is_reported_as_it_happens…` | **not run** |
| 9 | Agency access verification | `…never_becomes_visible_never_becomes_connected`, `…access_to_a_different_place_is_not_accepted…` (listing under the group, place id, role) | **not run** |
| 10 | Correct tenant mapping | `mapping` checks asserted in the end-to-end test; `…same_google_location_cannot_be_mapped_to_two_businesses`; existing `test_google_agency_resolution.py` | **not run** |
| 11 | Initial review sync | `…operations_on_the_connection_moves_and_the_first_sync_is_queued_once` | **not run** |
| 12 | Pagination | `…first_sync_pages_through_google_de_duplicates…` (two pages, a repeated review stored once, agency token only) | **not run** |
| 13 | Scheduled follow-up sync | existing `sync_due_locations` / `due_locations` tests; second run in the pagination test creates nothing new. A real hourly schedule on a switched connection is **not** separately tested | **not run** |
| 14 | Expired customer token | `…expired_customer_sign_in_is_expired…` (state EXPIRED, nothing sent, customer told once) | **not run** |
| 15 | Expired/revoked agency token | `…expired_or_revoked_agency_login_pauses_onboarding…` (nothing sent, row marked revoked, never CONNECTED) | **not run** |
| 16 | Duplicate connection | `…same_google_location_cannot_be_mapped…`, `…second_attempt_for_the_same_location_creates_one…` | **not run** |
| 17 | Wrong agency identity | `…wrong_google_identity_can_never_accept`; registration with the wrong e-mail is refused and revoked (existing `test_google_agency_registration.py`) | **not run** |
| 18 | Revoked authorization | `…removal_by_the_customer_in_google_is_detected…`, `…business_the_operator_has_not_opened…` (grant revoked) and existing resolution tests | **not run** |
| 19 | Customer disconnection | `…customer_can_stop_and_everything_afterwards_is_refused`, `…stopping_an_invitation_that_was_never_accepted…` (notices once each; OAuth revoked after) | **not run** |
| 20 | Cross-tenant attempts | `…another_business_sees_nothing_of_this_one…`, `…journey_never_carries_a_token…` | n/a |
| 21 | Unauthorized operator attempts | `…only_a_listed_signed_in_operator_reaches_the_operator_screens`, `…operator_can_retry_but_gives_no_consent…` | n/a |
| 22 | Reconnection | `…customer_can_reconnect_and_start_again_after_stopping` | **not run** |

Additional properties tested: flag off ⇒ routes 404 and old page unchanged; config guard; consent needs agreement, current wording and known categories; categories stored, audited and **enforced** (`action_not_consented`); legacy rows keep their meaning; only an admin can consent; BLOCKED states (API not approved, not opened, no agency login, no group access, location identity mismatch); a failed step is persisted; one broken business does not stop the others; the per-connection lock; rate limit; open-redirect guard on the return path; migration 0066 shape.

## What a live test must still confirm (nothing here can)

1. Google accepts `{"account": "accounts/<group>", "role": "MANAGER"}` on `locations.admins.create` (the reference says so; the conceptual page uses different field names).
2. Where the group invitation appears for the agency user, and that `invitations:accept` works with the agency user's token for a LocationGroup.
3. That the location is then listed under the group, with the same place id.
4. Whether a Manager can delete its own admin entry, and what `admins.list` returns for a group.
5. That the customer's OAuth revocation does not disturb other FlowQR connections of the same Google user.
6. Business Profile API quota/approval for FlowHQ's project (an unapproved project shows as BLOCKED `api_not_approved`).
