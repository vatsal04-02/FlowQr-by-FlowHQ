# Local SEO Milestone 2: Google integration readiness (2026-11-17)

Scope approved by the owner on 2026-11-17 (D1 to D7). **Nothing was pushed or deployed. Production infrastructure, production credentials and the production OAuth configuration were not touched. No real clinic profile was read or changed after containment, and no Google profile was changed at any point.**

## 1. Containment (D1), applied before any other work

| Step | Result (checked afterwards in the development database) |
|---|---|
| Worker and beat stopped | `flowqr-worker-1` and `flowqr-beat-1` exited; they stayed stopped when Docker Desktop restarted later the same day |
| Platform emergency stop on | `platform_controls.autonomy_emergency_stop = on` (audited: `autonomy.emergency_stop_on`) |
| Autonomy and template auto-replies off for every development business | 9 of 9 businesses `autonomy_enabled = false`, `auto_reply_enabled = false` (9 `containment.automation_disabled` audit rows holding the before values) |
| The two real-clinic connections isolated | both set to `disconnected`, locations deselected, `last_error` records why, audit rows `containment.connection_isolated` hold the before state. **Tokens were retained and were NOT revoked at Google** (needs separate approval). Connection and audit records preserved. |
| Nothing queued could run | approved or executing actions: 0; approved replies: 0; scheduled or publishing posts: 0; scheduled media: 0; Celery queue length: 0 |
| Clinic profiles unmodified | 0 reply drafts sent, 0 posts published, 0 executed profile actions before and after (rows counted; no write path ran) |
| Left in place | the FlowHQ test connection is the only active Google connection. A dental-studio connection is `revoked` (no token). |

## 2. Google API operations tested (live, designated FlowHQ test profile only)

Tool: `python -m app.cli google-readiness` (`backend/app/services/google/readiness.py`). It reads, and sends **only validation patches** (`validateOnly=true`, which Google documents as "validated without actually updating"). Guards: the connection must be active; the live title must equal the expected title or only that one title read is made; before any other probe a *new-value* probe proves that `validateOnly` does not apply new values; the whole profile is hashed before and after. Evidence with no customer values: `docs/evidence/google-readiness-2026-11-17.json` (37 calls; profile identical before and after).

### Reads (HTTP 200 unless stated)

| Operation | Google's answer |
|---|---|
| OAuth refresh | token issued, `expires_in 3599s`, scope includes `business.manage` |
| `accounts.list` | 1 account |
| `locations.get` (broad mask) | returned: categories, languageCode, latlng, metadata, name, openInfo, phoneNumbers, profile, storeCode, storefrontAddress, title. **Absent on this profile: regularHours, specialHours, serviceItems, websiteUri, labels, serviceArea** (not set, not an error) |
| `reviews.list`, `localPosts.list`, `media.list` | 0, 0, 0 (the test profile has none) |
| `fetchMultiDailyMetricsTimeSeries` (7 days) | **10 of 10 metrics returned data** (BUSINESS_BOOKINGS, DIRECTION_REQUESTS, FOOD_MENU_CLICKS, the four impression metrics, CALL_CLICKS, WEBSITE_CLICKS, MESSAGING_CLICKS) |
| `searchkeywords.impressions.monthly` | 0 terms (a new low-traffic profile) |
| **`locations.getGoogleUpdated`** | `diffMask = "profile.description"`, `pendingMask = ""`: **Google's live description differs from the merchant's data on this profile.** FlowQR does not read this today; Google-initiated changes are invisible in the product |
| `getVoiceOfMerchantState` | `hasVoiceOfMerchant = true`, `hasBusinessAuthority = true` (the profile is verified and manageable) |
| `verifications.list` | returned a `verifications` field |
| `attributes` get (merchant's) | returned only `name`: none set |
| `attributes.list` metadata (primary category) | 31 attributes available. **For `parent=<location>` combined with region, language and category Google answers HTTP 400**; sending `parent` alone returns 31 (fixed in the provider, pinned by a test) |
| **Notifications API** (`notificationSetting.get`) | **403 SERVICE_DISABLED** `mybusinessnotifications.googleapis.com`: not enabled on the Cloud project |
| **Place Actions API** (`placeActionLinks.list`) | **403 SERVICE_DISABLED** `mybusinessplaceactions.googleapis.com`: not enabled on the Cloud project |

### Validation-only writes (nothing applied)

| Probe | Google's answer | What it does and does not show |
|---|---|---|
| **A NEW value (`labels`) with `validateOnly=true`** | accepted; the profile was byte-identical afterwards | proves validateOnly does not apply new values on this API |
| description, current and a NEW text | accepted | the shape is valid. **Only a real write proves it lands.** The earlier live write test (2026-11-15) did. |
| categories (current primary and additional) | accepted | |
| categories with `updateMask=categories.primaryCategory` | **400 INVALID_ARGUMENT** | consistent with Google's rule that categories are updated as a whole; the provider already sends both |
| `serviceItems` current round trip, and **adding one new free-form service** | accepted | **services are valid to write by the API's own validation.** Still no real write; no count or length limits were stated |
| `regularHours` NEW Mon to Fri | accepted | |
| `specialHours` alone | **400** (profile has no regular hours) | matches Google's "cannot be set without regular hours" |
| `regularHours` + `specialHours` together | accepted | the order FlowQR would need |
| `phoneNumbers` NEW, `websiteUri` NEW | accepted | |
| `title`, `storefrontAddress`, `openInfo` (current values) | accepted | accepted by validation does not make them FlowQR-writable: these stay Level 3 |
| `latlng` (current value) | accepted by validation | Google's doc says only approved clients may update it; **do not infer FlowQR may** |
| unknown field | 400 "Unknown name ... Cannot find field" | |
| `metadata` (output-only), `languageCode` (immutable) | 400 | matches the documentation |
| rate | the first run hit **HTTP 429 on the 11th validation request in a minute**; with a 7-second pause no 429 occurred | validation requests appear to count toward "10 edits per minute per profile". The tool now paces itself. |

### Not tested, and why
* **Real writes** (any field, post, photo, reply): not done. D5 requires explicit approval for each, with before-state, one change at a time, read-back and restore. A proposed sequence is in section 7.
* **Review replies, review sync of real reviews, Q&A (discontinued by Google)**: the test profile has no reviews.
* **Revoking the test token at Google**: would destroy the test connection; needs approval. Revocation was tested through the code and the mock (existing tests).
* **Production OAuth, production Cloud project**: owner action (section 6).

## 3. Consent and permissions (D2): implemented

* Migration `0038_consent_grants` (chain 0036 → 0037 → 0038): new table `consent_grants` (RLS forced; one row per owner agreement; the exact wording and its version, who agreed and when, who withdrew and when); a database trigger refuses DELETE and any edit except recording a revocation; a revoked row is frozen; a later grant is a new row. `agent_settings.autonomy_enabled` and `auto_reply_enabled` default to **off**, and every existing row is switched **off** (nobody silently inherits automation). Downgrade never switches anyone's automation back on.
* `services/consent.py`: scopes are derived from the policy table, so only Level 1 or 2 profile changes that the integration can write, plus the template-reply rule, are grantable: `description_improve`, `text_correction`, `hours_update`, `contact_update`, `secondary_category_update`, `reply_template`. **Level 3 changes and public content (posts, photos, AI-drafted replies, edits and deletions) cannot be consented to** and are refused with a clear message. A grant is for **one location and one action type**.
* API (`api/v1/autonomy_actions.py`): `GET /agent/consents`, `POST /agent/consents` (owner only; refused against stale wording), `POST /agent/consents/{id}/revoke`, `POST /agent/consents/revoke-all`.
* Enforcement: proposals are authorised by policy or pre-authorisation **only** where active consent exists for that location and action type (else a person decides); the executor **re-checks consent at the moment of writing** (so a revoked grant cannot be used by a job already queued); template replies need consent in both eligibility and the governed publisher; revoking returns that location's and type's queued work to "waiting for a person" at once. The emergency stop and the owner's autonomy switch still beat consent.
* Consent records are in the owner's data export (`services/account.py`).
* **Posts and photos (D4):** unchanged. Each needs a person's approval; there is no standing grant for them.
* **Not built (Milestone 6):** the owner-facing screens for granting and withdrawing. Today it is API only.

## 4. Tests

| Run | Result |
|---|---|
| `tests/test_consent.py` (new, 23 tests): default off; owner-only; Level 3 and public-content scopes refused; stale wording refused; wording and person recorded; per-type and per-location isolation; execution gated; revoke withdraws queued work; revoked consent cannot be used by an already-queued job; emergency stop holds a consented action; autonomy switch beats consent; record cannot be edited or deleted; revoked grant frozen; idempotent revoke; revoke-all; other business cannot revoke; export includes consent | passed |
| `tests/test_google_readiness.py` (new): `validateOnly` is always sent and is not a parameter; documented URLs for the new reads; attribute-metadata rule seen live; the tool stops after one read on a title mismatch; the tool refuses an isolated connection; the evidence holds no values | passed |
| Existing suites adapted to the new default (documented in each file): `test_phase1_executor` helper records consent; `test_template_auto_replies` and `test_phase15_governed` grant consent through the real endpoint; the old "on by default" tests now assert **off by default** | passed |
| Two test defects found in the audit fixed: UTC date in `test_seo_metrics`, tenant-scoped count in `test_rank_tracker` | passed |

**Full backend suite, final run: 1,750 passed, 0 failed, 0 errors** (the test run before it showed the three expected consequences of this milestone, all fixed: the two migration-chain tests pinned head 0037 and now pin 0038; the route-access manifest gained exactly four routes, reviewed: `GET /agent/consents` (member) and three owner-only POSTs). Frontend: **not changed in this milestone**, so no frontend type check or build was run for it.

## 5. Files changed

New: `backend/app/services/consent.py`, `backend/app/services/google/readiness.py`, `backend/alembic/versions/0038_consent_grants.py`, `backend/tests/test_consent.py`, `backend/tests/test_google_readiness.py`, `docs/GOOGLE_READINESS_M2.md`, `docs/GOOGLE_DATA_RETENTION_FINDINGS.md`, `docs/evidence/google-readiness-2026-11-17.json`, `docs/LOCAL_SEO_ENGINE_AUDIT_AND_ROADMAP.md` (Milestone 1), the two AEO/GEO documents (earlier task).
Changed: `backend/app/models/autonomy.py` (ConsentGrant), `backend/app/models/agent.py` (defaults off), `backend/app/models/__init__.py`, `backend/app/services/agent/executor.py`, `backend/app/services/agent/content_exec.py`, `backend/app/services/auto_reply.py`, `backend/app/services/account.py`, `backend/app/services/google/provider.py` (read-only calls and the validation-only patch), `backend/app/cli.py` (`google-readiness`), `backend/app/api/v1/autonomy_actions.py`, tests: `test_phase1_executor.py`, `test_template_auto_replies.py`, `test_phase15_governed.py`, `test_seo_metrics.py`, `test_rank_tracker.py`.
Side effects outside the repository: the development API container holds temporary copies of the changed provider, readiness and cli files (used for the live run; lost when the container is rebuilt). The migration was **not** applied to the development database.

## 6. Remaining blockers

1. **Data retention (D3), launch blocker:** `GOOGLE_DATA_RETENTION_FINDINGS.md`. FlowQR keeps reviews, daily metrics and Places coordinates far longer than the 30-day wording on Google's policy page; the page names no exception. Needs Google's written answer, legal review, or a redesign before any real customer.
2. **Production Google Cloud (D7, owner action).** Check and record in Cloud Console for the production project, without sharing secrets: OAuth consent screen publishing status (Testing means refresh tokens expire after 7 days and only listed test users can connect); the authorised redirect URI exactly `https://<APP_DOMAIN>/api/v1/google/callback` (and the separate sign-in client's); scopes (`business.manage`, `openid`, `email`); enabled APIs (Account Management, Business Information, My Business v4, Performance; **Verifications, Notifications and Place Actions were also exercised here and Notifications and Place Actions are not enabled even on the development project**); quota on each API (0 = not approved, 300 per minute = approved); OAuth app verification state for the sensitive scope, and Google's "Working with a third party" disclosure requirement. I did not read or change any production console or credential.
3. **The two clinic connections still hold tokens.** Revocation at Google needs your separate approval; until then the tokens sit encrypted in the development database.
4. **Write path proof.** Description is the only field with a live write proof (2026-11-15). Hours, phone, website, categories, services, special hours and review replies are validated only. Proposed live-write sequence (needs your approval before any step): (a) read and record the profile; (b) one real change at a time, in this order: description (restore), website, phone, regular hours, special hours, add a secondary category, add one service; (c) after each: read back, compare, restore, log; (d) posts and photo on the test profile; (e) a reply needs a real review from a second Google account.
5. **Google-initiated changes (`getGoogleUpdated`)** are visible through the API but invisible in the product; a Milestone 3 task. The test profile already shows one (`profile.description`).
6. **Notifications (Pub/Sub) and Place Actions** APIs are not enabled on the project; enabling is a Cloud Console action, plus approval for Place Actions.
7. The development stack still runs the old image (alembic 0036) with the emergency stop on. Do not restart worker or beat until you decide.

## 7. Confirmations

* No clinic profile was modified, and after containment none was contacted; the readiness tool ran only against the FlowHQ test profile (live title guard; connection id fixed on the command line).
* No Google write was made by this milestone: every patch was `validateOnly`, and the profile hash was identical before and after.
* Production infrastructure, production credentials and production OAuth configuration were untouched; no push, no deploy, no paid API expansion, no public automation activation.
