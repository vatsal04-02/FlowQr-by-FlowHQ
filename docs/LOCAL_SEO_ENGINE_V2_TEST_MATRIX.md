# Local SEO engine V2: test matrix

Branch `feature/local-seo-engine-v2`. Test database: its own Postgres 16 container, schema rebuilt from migrations at the start of each run.

## What a pass means

| Label | Meaning |
|---|---|
| **Mock** | FlowQR's code against a test double of Google (`V2Google`) or a mock HTTP transport pinned to the shapes in Google's documentation. Proves FlowQR's own rules. **Not** evidence about Google. |
| **DB** | Real PostgreSQL: row-level security, constraints, migrations, state machines. |
| **Live** | Run against a real Google profile. **None has been run.** |

## Result of the whole backend suite

**3523 passed, 0 failed, 1 skipped** (33 min), final tree, own database, `deploy/` mounted. Of these, 100 are new (35 pure, 17 contract, 46 engine, 2 migration) and the existing suite is otherwise unchanged apart from the edits below.

History of the runs, for honesty: a first full run (before the migration tests were updated) had 16 failures: 11 pinned the alembic head at `0065` (expected once 0066 exists) and 5 were overlay tests that need `deploy/` mounted in my runner. Both were fixed (head pins updated as every earlier migration did; runner mount) and the suite was re-run in full. An earlier run that I interrupted was discarded because I had been editing the mounted tree during it.

The original base (`origin/release/gbp-agency` @ `0604555`) passed the engine tests before any change (192 passed in the 5 core engine files). Existing tests changed, and why:

* `test_phase1_policy.py`: the pinned action-type table. `attribute_change` moved Level 3 to Level 2 (the requested risk model: attributes are medium risk); `special_hours_update` (L2) and `category_set_update` (L3) added. This is a deliberate policy change, not a loosened check.
* Eleven `test_migration_*.py`/`test_whatsapp.py` assertions that pin the alembic head: `0065` -> `0066`, as every earlier migration did.
* `route_access_manifest.txt`: the five new routes (read = member, proposals = admin).
* The runner mounts `deploy/` read-only: five overlay tests read `../deploy/vps/docker-compose.vps.yml`; with it missing they raise `StopIteration` (environment, not code).

## Requested coverage (section 11) to tests

| # | Requested | Tests (file `::` name fragment) | Kind |
|---|---|---|---|
| 1 | Description creation and correction | existing `test_phase1_*`, `test_autonomy`; `test_the_legacy_description_path_is_not_held_by_the_v2_gate` | Mock+DB |
| 2 | Keyword relevance | `pure::test_keyword_opportunities_come_from_verified_facts...`, `..._coverage_lowers_priority...`; `engine::test_the_overview_reports_only_what_exists...` | Mock |
| 3 | Category discovery and approval | `pure::test_a_category_is_recommended_only_when_the_owners_own_words_support_it`, `..._category_changes_are_a_set_and_owner_only`, `..._categories_are_capped_and_never_untraced`; `engine::test_a_category_set_is_proposed_only_with_evidence...`; `contract::test_a_category_set_sends_primary_and_additional_together...` | Mock+DB |
| 4 | Full service-list replacement safety | `pure::test_a_plan_keeps_every_existing_service...`, `..._a_complete_list_round_trips...`, `..._dropping_an_existing_service_is_a_removal...`, `..._an_empty_service_list_can_never_be_proposed`; `engine::test_a_partial_service_list_is_never_sent...`, `..._the_scan_never_proposes_removing_anything`; `contract::test_a_service_update_sends_the_complete_list...` | Mock+DB |
| 5 | Service eligibility | `pure::test_a_locked_service_list_is_unavailable_and_an_unknown_one_is_not_assumed_editable`, `..._an_unread_service_list_is_unknown_never_empty`; `engine::test_a_locked_service_list_gets_no_proposal_and_says_so`, `..._an_unknown_eligibility_flag...`, `..._an_unread_service_list_proposes_nothing...`; `contract::test_a_missing_service_flag_is_unknown_not_true` | Mock+DB |
| 6 | Attribute discovery and updates | `pure::test_attribute_*`, `..._attributes_are_asked_never_assumed`; `engine::test_attributes_come_only_from_the_owners_answers...`, `..._googles_metadata_refuses...`, `..._the_scan_never_proposes_an_attribute...`; `contract::test_attributes_are_read...`, `..._attribute_metadata_is_requested...`, `..._update_attributes_sends_an_explicit_attribute_mask...`, `..._refuses_to_send_nothing` | Mock+DB |
| 7 | Regular hours | `pure::test_hours_support_split_periods_after_midnight...`, `..._written_hours_are_compared_only_when_every_clause_is_read_exactly`, `..._the_policy_accepts_after_midnight...`; `contract::test_after_midnight_and_midnight_closing_survive...` | Mock |
| 8 | Special hours | `pure::test_special_hours_*`, `..._existing_special_hours_are_kept...`, `..._holiday_gaps...`; `engine::test_special_hours_*`, `..._a_clashing_date...`, `..._invalid_special_hours...` | Mock+DB |
| 9 | Service areas | `pure::test_service_area_rules`, `..._a_service_area_only_comes_from_the_owner`; `engine::test_service_area_changes_keep_the_business_type...`; `contract::test_a_service_area_patch_sends...` | Mock+DB |
| 10 | Phone and website validation | `pure::test_contact_assessment_never_prefers_an_unverifiable_value`; `engine::test_a_different_phone_in_the_record_is_flagged...`; existing contact tests; `contract::test_changing_the_phone_keeps_additional_phones...` | Mock+DB |
| 11 | Owner rejection and revocation | `engine::test_the_owner_can_dismiss_a_recommendation_and_it_is_not_proposed_again`, `..._v2_changes_can_never_be_pre_authorised_or_consented_to`; existing `test_consent.py` | DB |
| 12 | Google validate-only errors | `engine::test_google_refusing_the_dry_run_blocks_the_change...`, `..._a_transient_dry_run_error_is_retried...`, `..._a_provider_that_cannot_dry_run_never_gets_an_unvalidated_v2_write`; `contract::test_a_google_validation_error_is_raised_not_swallowed`, `..._validate_changes_is_a_dry_run_that_cannot_be_sent_without_validate_only` | Mock |
| 13 | Successful writes | `engine::test_services_flow_detect_recommend_approve_validate_execute_verify`, special hours / attributes / category set / service area flows | Mock+DB |
| 14 | Failed writes and retries | `engine::test_a_failed_write_is_retried_then_succeeds_without_a_second_edit`, `..._a_write_google_accepts_but_does_not_apply...` | Mock+DB |
| 15 | Read-back verification | same; `..._the_overview_counts_a_verified_change_only_after_the_read_back`; `..._a_lost_response_is_resolved_by_reading_google...` | Mock+DB |
| 16 | Duplicate prevention | `engine::test_scanning_twice_never_duplicates_a_proposal`; `migration_0066::..._owns_its_idempotency_key` | DB |
| 17 | Concurrent scans | `engine::test_two_simultaneous_scans_of_one_location_cannot_both_propose` (advisory lock held by one session, a second real session is refused); existing in-flight-write test | DB |
| 18 | Cross-tenant isolation | `engine::test_one_business_cannot_propose_on_anothers_profile_or_see_its_v2_data` (API 404s, RLS view); existing RLS tests | DB |
| 19 | Google policy feature flag | `engine::test_with_the_gate_closed_...`, `..._the_gate_is_open_only_for_test_profiles_or_with_a_recorded_google_answer`, `..._the_start_up_guard_refuses_customer_writes...`, `..._approving_through_the_api_on_a_closed_gate...`, `..._a_recommendation_can_be_promoted_once_the_gate_opens` | Mock+DB |
| 20 | Owner changes made outside FlowQR | `engine::test_the_owner_changing_services_in_google_supersedes_the_draft...`, `..._a_change_that_google_already_shows...`, `..._fields_google_reports_as_changed_are_not_proposed_over...` | Mock+DB |

Also: notice only after a verified change and none for a failed one; the V2 scan cannot break the legacy scan; the emergency stop holds V2 execution; the migration upgrades/downgrades reversibly.

I verified two guards actually guard, by temporarily disabling each in the code and watching tests fail, then restoring the code: removing the executor's gate hold failed `test_with_the_gate_closed_...`; removing the "never write unvalidated" check failed two dry-run tests.

## Frontend

`tsc --noEmit` clean. `node --test tests/*.test.mjs`: 128 pass. Browser (`e2e/seo-v2-dashboard.js`, real Chrome, the release image against a throwaway database, **not production**): gate-closed mode 21/21, designated-test-profile mode 20/20, at 1440 and 390 px, plus loading, error, not-read and empty states. It found and fixed two real defects (V2 values printed as raw JSON on the shared approval card; the area text squeezed beside its chip at 390 px). One 'failed' row and one 'verified' row in that run are **seeded fixtures** that exercise the rendering. Signed out, production `/seo` redirects to `/login` with no overflow or console errors (desktop and mobile). **A signed-in view of production was not opened: there is no production login for this work and registration there is allowlisted.**

## Proven against a real Google profile (2026-11-22/23)

One profile only: the FlowHQ-owned test profile "FlowHQ", `locations/6589197820321114990` (owner-authorised, `hasBusinessAuthority=true`, `hasVoiceOfMerchant=true`), reached through the production deployment's stored OAuth connection. Evidence files: `docs/evidence/seo-v2-live-2026-11-23/` (API-level facts and outcomes only; no customer values). Run with image `prod-43539cc` (probes) and `prod-5ec9e93` (engine steps), in one-off containers whose own environment listed only this location in `SEO_V2_TEST_LOCATION_NAMES`.

| Operation | Result against real Google | How |
|---|---|---|
| OAuth refresh with the stored token, title guard | PASS | `google-readiness` |
| `canModifyServiceList` read | PASS: `true` | readiness + live-test refresh |
| V2 reads: service items, special hours, attributes (31 offered, 0 set), category service types (16), `getGoogleUpdated` (empty masks) | PASS | readiness |
| `validateOnly`: services body built by FlowQr (current list + one new custom item) | **Accepted by Google** | readiness |
| `validateOnly`: categories, primary + additional together | **Accepted** | readiness |
| `validateOnly`: primary category alone | **400 INVALID_ARGUMENT** (confirms the documented rule that categories cannot be updated one sub-field at a time) | readiness |
| `validateOnly`: special hours alone on a profile with no regular hours | **400** (confirms the documented precondition); regular + special hours together **accepted** | readiness |
| Engine, services: propose, owner approval, Google dry run (`validateOnly`) accepted, write, **independent read-back matched**, history chain intact, `email.sent` notice audited | **PASS** (action `35b18fbf`) | `seo-v2-live-test` |
| Engine, services: the profile read back after the write holds the new service (0 before, 1 now) | PASS | same |
| Cleanup: the profile restored to 0 services and read back | PASS, **done directly, not by the engine**: the engine refuses to empty a list by design | same |
| Engine, refused change: a custom service with a non-existent category | Google's dry run answered **400**; the engine ended `blocked / validation_failed`, never wrote, the profile read back unchanged | same (action `26ff2bc3`) |
| Final state | services and special hours identical to before the run | same |

**Not proven live, and why:**
* Special hours: the test profile has no regular opening hours, so the step correctly skipped. Only the dry-run acceptance of regular + special hours together is proven.
* Attributes and category changes: dry runs / reads only; no attribute or category was written (the test profile's categories were not changed).
* Whole-list vs merge semantics of `serviceItems`: the test started from an empty list, so it cannot distinguish them. The engine always sends the complete list, which is correct either way.
* BOOL attribute wire form, prices (Money): untested.
* The notice email: Google-side nothing; SMTP accepted it, **receipt in the mailbox was not checked**.
* Any customer profile: none was touched, by design.

**Findings from the real run (each is a defect or fact a mock could not show):**
1. The category search answered **400** for a multi-word term and, quoted, returned nothing, because Google matches the *start* of the name. This also broke the existing category picker for multi-word queries. Fixed (commit `8931233`): the first word is sent, the rest narrows the answer. Verified live only through the unquoted/quoted probes; the fix itself is contract-tested.
2. `app.cli` did not route the new command; found on the first production dry run, fixed (`18d0161`).
3. A test tenant whose trial has ended is correctly **held** (`held/plan`) with nothing written; the test needed the test tenant's trial extended (approved by the owner of the platform; original values restored and audited).
4. A refused change records `validation_failed` twice in the history (cosmetic duplicate, not fixed).

## Remains unverified

Whole-list vs merge behaviour of `serviceItems`; BOOL attribute wire form; Money (price) shape; whether Google's `validateOnly` accepts each V2 body; Google's behaviour per category; the customer-write policy question; production behaviour; the dashboard in a browser.
