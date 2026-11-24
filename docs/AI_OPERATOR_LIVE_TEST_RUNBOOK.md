# Isolated live write test on FlowHQ's own Google profile (NOT run, needs approval)

Nothing in this runbook has been executed. It needs the operator's explicit approval for the production steps in section 3. Customer writes stay disabled throughout (`GOOGLE_THIRD_PARTY_API_RESTRICTIONS.md`).

## 1. Prove the profile is ours before anything is allowlisted

What the database already shows (read-only, 2026-11-23): the Google location `locations/6589197820321114990` ("FlowHQ", Gomti Nagar, Lucknow) is selected on the business `FlowHQ` (`d56f7f58-9a9d-4e36-a587-2e01aae5c36d`), whose only member is the operator, through the Google account `flowhqofficial@gmail.com` (`accounts/113219783325743340638`); FlowHQ's agency login was accepted as Manager of it. **That shows who connected it, not who owns it.** A person must confirm, in Google Business Profile, all of:

* [ ] the profile is **verified** and its **Primary owner** is a FlowHQ-controlled account (Settings, People and access);
* [ ] no customer, and no other business, is an owner or manager of it;
* [ ] the profile is not a customer's listing used for testing (it is the FlowHQ office listing).

If any box fails, stop. Do not allowlist.

One more check: the gate matches by location **name**, and an old disconnected row for the same location exists under another test business (`Isolation Test Co`, deselected, connection disconnected). It cannot sync or write today. Ask the owner to delete that stale row before the test so the allowlist can only ever apply to FlowHQ's own business.

## 2. The change to test (safe and reversible)

Two changes, each with before and after, each reversible by the owner:

1. **Holiday hours** (a V2 field behind the gate): one closed day far in the future, for example 2027-01-26. Reverse it by deleting that special-hours entry in Google Business Profile. FlowQr has no undo by design: it never changes Google's data back by itself.
2. **Description** (the legacy path): approve an improved description, then approve a second change back to the previous text. The previous text is kept as the first change's BEFORE.

No price, name, address, category or contact detail is touched.

## 3. Production steps (each needs approval; none done)

1. Deploy this branch (backend, then frontend) the usual way. The backend has no migration.
2. `SEO_V2_*` settings do **not** reach the containers today: they are in neither `docker-compose.yml` nor `deploy/vps/docker-compose.vps.yml`. Add to the overlay: `SEO_V2_TEST_LOCATION_NAMES: ${SEO_V2_TEST_LOCATION_NAMES:-}` (and leave `SEO_V2_CUSTOMER_WRITES_ENABLED` unset, which means false).
3. In `.env.production` set `SEO_V2_TEST_LOCATION_NAMES=locations/6589197820321114990` (this one id, nothing else). Run the real startup guard, then recreate api, worker and beat with both compose files.
4. Confirm: `GET /seo/v2/overview` for FlowHQ shows the gate `allowed: true, test_profile: true, customer_writes: false`; for any other business `allowed: false`.

## 4. The test, and the evidence to keep

1. As the FlowHQ owner: Pending changes, prepare the holiday-hours change, read BEFORE and AFTER, approve.
2. Evidence: the action row (`GET /agent/actions/{id}`) with `status executed` and `verified_at`; `history_integrity` true; the dry-run result (`validation`); Google's own page showing the entry; the separate notice e-mail; a screenshot of the card.
3. Repeat for the description, then approve the change back.
4. Reverse the holiday hours by hand in Google. Confirm FlowQr then shows "Google changed this" and does not propose over it.
5. Record the results in `LOCAL_SEO_ENGINE_V2_TEST_MATRIX.md`. A passing run proves those operations for that profile only; it does not make customer writes permissible.

## 5. Stop conditions

Any write that Google refuses, any read-back that does not match, any change on a profile other than the allowlisted one: stop, set `SEO_V2_TEST_LOCATION_NAMES` empty, recreate, and report. The platform emergency stop (`AUTONOMY_EMERGENCY_STOP`) also holds every execution.
