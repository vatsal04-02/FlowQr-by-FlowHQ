# Local SEO engine: Milestone 1 audit, gap analysis and implementation roadmap

Audit date: 2026-11-17 (local time; the machine's UTC date was still 2026-11-16 during the audit). Branch `phase-2/commercial-readiness`, working tree clean at the start. **Nothing was changed in the application, database, configuration, Google account or any deployment to produce this report.** The only files written are this document and the two AEO/GEO planning documents from the earlier task (untracked).

How the evidence was gathered:

| Label | Meaning |
|---|---|
| **Code** | Read in this repository. |
| **Dev DB** | Read-only `SELECT` of metadata on the local development database (`flowqr-db-1`, Alembic `0036`). No token, secret, review text or personal field was read or is reproduced. |
| **Tests** | Ran the existing automated tests in the project's Docker harness on this branch (§9). |
| **Google docs** | Read on developers.google.com or support.google.com on 2026-11-17. Quotes are short and verbatim. |
| **Not verified** | Could not be established. Named, never assumed. |

---

## 0. The three things you should read first

1. **The dev stack on this machine can write to real clinic Google profiles right now.** `flowqr-worker-1` and `flowqr-beat-1` are running with `AUTONOMY_EMERGENCY_STOP=false`. Two active Google connections point at what are evidently real businesses (a physiotherapy clinic with 482 synced reviews, 213 services, 47 posts, 31 photos; a dental studio with 70 reviews). All 9 tenants have `autonomy_enabled = true` and `auto_reply_enabled = true`. Template auto-replies to new 4 and 5 star reviews (newer than 2026-11-15, younger than 3 days) and Level 1 description rewrites are therefore *able* to execute against those profiles. **Nothing has: 0 replies sent by the rule, 0 published posts or photos, 0 executed profile actions, 2 reply drafts, and 3 proposed actions (1 waiting, 2 blocked).** Your brief forbids using real customer profiles as test accounts. See decision D1 (§12).
2. **The engine you describe is largely already built; the gaps are consent, compliance, a few Google operations and the customer experience.** `AgentAction` + `executor` + `autonomy_policy` already implement propose, classify, approve, execute, read back, verify, retry, dedupe, suspend, emergency-stop, tamper-evident history and 7/14/28-day rank follow-ups. Rebuilding that would violate your "do not create duplicate services or models" rule. The plan below completes and hardens it.
3. **Two Google policy findings need a decision before more is built** (D2, D3): automation that is *on by default* conflicts with Google's "prior specific and express consent" rule and with your own brief, and FlowQR stores Google content (reviews, daily metrics) far longer than the 30 days Google's policy page allows for stored content.

---

## 1. Status of every capability

Categories as you defined them: **1** fully implemented and operational · **2** implemented but not connected to live Google (or not validated live) · **3** partially implemented · **4** UI only or placeholder · **5** missing.

"Operational" is used strictly: code + tests + evidence of a real result. The tests prove the code matches Google's *documented* shapes (a mock transport); only the Dev DB and the validation documents show real Google answers.

| # | Capability | Cat. | Where | Evidence and gap |
|---|---|---|---|---|
| 1 | **Google OAuth, scopes** | **1** (dev) / **2** (prod) | `services/google/provider.py`, `api/v1/google.py`, `services/google/tokens.py`; separate sign-in client | Dev DB: 6 connection rows, 3 active, 4 with `api_access = approved` (live reads have succeeded; earliest `approved` 2026-11-11). Scopes requested: `business.manage`, `userinfo.email`, `openid`. Production OAuth client and Google verification: **Not verified**; the project's own validation file says the consent screen is in *Testing* (listed test users only; refresh tokens expire in 7 days) and that verification for real customers is **BLOCKED**. |
| 2 | **Token storage, refresh, revocation** | **1** | `services/google/tokens.py`, `core/security.py` | Refresh and access tokens are Fernet-encrypted at rest; refresh on demand; `invalid_grant` marks the connection revoked; disconnect revokes at Google (best effort), wipes tokens, deselects locations and audits it. No password is ever requested. Gap: disconnect keeps synced reviews "as history" (see policy finding P1). |
| 3 | **Business Information API (read)** | **1** (dev) | `provider.get_location_details` | Dev DB: 4 snapshots, 4 with profile info, latest 2026-11-16. Reads title, description, phone, website, primary and additional categories, regular and special hours, services, open status. **Not read:** attributes, service area, address, verification state (`metadata`), Google-suggested updates (`getGoogleUpdated`). |
| 4 | **Business Information API (write)** | **3** | `provider.update_location`, `executor` | Implemented: description, regular hours, primary/additional categories, phone, website (read-merge-write so nothing is cleared). **Live evidence only for description** (round trip on the authorised test profile, 2026-11-15). Hours, categories, phone, website, review-reply and the governed path: **NOT TESTED live** (`docs/PRODUCTION_EXTERNAL_VALIDATION.md`). Not implemented: special hours, services, attributes, service area, name, address. |
| 5 | **Google Posts** | **2 → validated on test profile** | `services/agent/posts.py`, `content_exec.py`, `publish_due_posts` | Create, read back, delete **PASS** on the test profile (2026-11-15). Approval required per post; scheduled publisher with retries and recovery. Only `STANDARD` posts; event/offer posts not implemented. |
| 6 | **Photos / media** | **2 → validated on test profile** | `provider.add_media/upload_media_bytes`, `ScheduledMedia` | Upload, read back, delete **PASS** on second run. Approval per photo. |
| 7 | **Reviews: read, sync** | **1** (dev) | `services/google/sync.py` | Dev DB: 1,034 reviews, 3 of 4 locations `last_sync_status = ok`; **one location in `error` state, cause not investigated**. Polled every 30 min (no Pub/Sub). Google's reply moderation state (`PENDING`/`REJECTED`) is honoured. |
| 8 | **Reviews: reply** | **2** | `services/reviews.py`, `auto_reply.py`, `content_exec` | **NOT TESTED live** (needs a real review from another Google account). Template auto-replies to new 4 and 5 star reviews are **on by default** by an owner decision of 2026-11-15; no AI writes them. |
| 9 | **Categories, attributes** | **3** | `provider.search_categories`, optimizer | Categories read and (code) writable. **Attributes: missing** (policy classifies them as Level 3, `writable=False`; nothing reads them). |
| 10 | **Services and descriptions** | **3** | `optimizer.py`, `autonomy_policy.py` | Services are **read** (213 on one real profile) and compared with the business knowledge base. **No write path** (`service_update` has `writable=False`); the UI tells the owner to edit them in Google. |
| 11 | **Opening and special hours** | **3** | | Regular hours: read + write. Special hours: read only (existence of upcoming holiday hours is checked); no write. Date/time-range validation: basic. |
| 12 | **Booking and action links** | **5** | | Place Actions API not called, not enabled. |
| 13 | **Verification state, Google suggested updates** | **5** | | Nothing calls the Verifications API or `getGoogleUpdated`. `metadata` is in the read mask but not surfaced. |
| 14 | **Performance API** | **1** (dev) | `provider.fetch_performance`, `snapshots.refresh`, `gbp_metrics.py`, `gbp_metric_daily` | Dev DB: 315 daily rows, 7 metrics, 2026-09-30 to 2026-11-13, for one location (the dental studio, whose sync status is `error`). Per-day storage, a 3-day lag exclusion, and "not returned" is distinct from zero. Gap: the other three locations have 0 metric rows. |
| 15 | **Places API / local rank tracking** | **1** | `services/rank.py` | Dev DB: 5 keywords, 58 checks, all `ok`, latest 2026-11-16. Position among the first 20 Places results; the UI says it is not the Maps order. Production Places key: **BLOCKED** (exposed key not rotated). Price unconfigured. |
| 16 | **Geo-grid** | **3** (deliberately off) | `services/rank_grid.py` | 1 grid, scans exist; `RANK_GRID_ENABLED=false`, no price, no platform cap, per-plan allowances unset: refuses to run. **Keep disabled** (your instruction). Billed requests per point **not confirmed** against a Google invoice. |
| 17 | **Competitor observation + history** | **1** | `services/competitors.py` | 0 pinned competitors in dev DB (feature works, tests pass); 5 per location max; data is rating, review count and position from stored Places results. **Not used by any recommendation** (checked `plan.py`, `seo_engine.py`): display-only. No competitor categories, services, website or photos (not stored). |
| 18 | **Profile health score** | **1** | `agent/health.py`, `optimizer.py` | Visible formula, missing data excluded not zeroed, daily history. Does not include attributes, services quality, special hours, verification state, booking links. |
| 19 | **Review sentiment / themes** | **1** (heuristic) | `services/insights.py` | A transparent keyword + rating rule set (EN/Hinglish/Hindi), 10 topics. Not AI. Must be labelled as a signal. |
| 20 | **AI Growth Assistant / recommendations** | **3** | `agent/plan.py`, `seo_engine.py`, `optimizer.py` | Produces tasks (reply, post, profile fix, photo, connect) with a dedupe key + partial unique index. Narrow: no keyword-opportunity discovery, no category-gap, no competitor input, no "expected benefit" text on tasks. Each optimizer check already carries six parts (state, problem, recommendation, reason, evidence, preview). |
| 21 | **Autonomous execution** | **2** (mock-tested; live partly) | `executor.py`, `autonomy_policy.py`, `models/autonomy.py` | See §3. Strong. Gaps: consent defaults, consent history, undo, services/special hours/attributes. |
| 22 | **Background jobs** | **1** | `workers/celery_app.py`, `tasks.py` | 21 scheduled tasks. See §6. |
| 23 | **Tenant isolation, RLS, audit** | **1** | migrations, `services/audit.py` | RLS `ENABLE`+`FORCE` on tenant tables; per-location staff scoping in `api/v1/seo.py`. New tables must be added to the export/deletion list (an earlier review found one missed). |
| 24 | **Plan entitlements, limits** | **1** | `services/plans.py`, `entitlements.py` | Feature keys per plan. See §10. |
| 25 | **Customer UI for all of the above** | **1/3** | `frontend/src/app/(app)/{seo,ai,settings/ai,gbp}` | GBP destination (Overview, Rankings, Performance, Profile); Tasks, Approvals, Activity under AI. Gaps in §8. |

Items a "UI-only placeholder" check turned up in this area: none for Local SEO. (The earlier audit's placeholders are WhatsApp inbox and Meta studio pages, outside this scope.)

---

## 2. Google integration blockers: verified state

| Question | State | Evidence |
|---|---|---|
| Does the OAuth client exchange tokens against live Google? | **Yes (dev project)** | `.env` has `GOOGLE_CLIENT_ID/SECRET` set; Dev DB holds working refresh tokens; connections created 2026-11-11, -13, -15 are `active`, `approved`. |
| Are the four Business Profile APIs enabled and approved on the project the dev stack uses? | **Yes for reads, as of 2026-11-16** | `api_access = approved` on 4 rows; the 2026-11-10 `SERVICE_DISABLED` result in `docs/GOOGLE_API_AUDIT.md` is **superseded** for reads (the row of 2026-11-10 is `api_disabled`; the next ones are `approved`). This is inferred from stored state, **not from a fresh `google-smoke` run today**; Milestone 2 runs it. |
| Is the *production* Google Cloud project the same one? | **Not verified** | The production OAuth client, redirect URIs, API enablement and quota (0 vs 300 QPM) can only be checked in Cloud Console by the owner. |
| Production OAuth verification | **BLOCKED / Not verified** | Consent screen in *Testing* per the project's own validation file; Google requires verification for the sensitive `business.manage` scope. |
| Real customers connected? | **No** (production has none per the project notes); the dev DB has two real-looking third-party profiles | See §0.1. |
| Writes proven live | description, post, photo, on the authorised test profile only | `docs/PRODUCTION_EXTERNAL_VALIDATION.md` |
| Writes **not** proven live | hours, categories, phone, website, review reply, governed approval path, autonomous Level 1/2, emergency stop against real Google, 28-day follow-ups | same |
| Q&A | Discontinued by Google (2025-11-03): nothing to build | `docs/GOOGLE_API_AUDIT.md` |

**Rule I will follow:** no statement that Google integration is "operational" except for the specific calls with a recorded live success above.

---

## 3. The existing autonomy engine, assessed against your brief

What is already there (Code, with tests that passed: §9):

| Your requirement | Existing mechanism | Verdict |
|---|---|---|
| Idempotency keys and action deduplication | `AgentAction.idempotency_key` with a partial unique index over live statuses; a second unique index allows **one `executing` write per location and field**; `agent_tasks` dedupe key; `_recent_action` and `learning.suppression` skip repeat proposals | **Met** |
| A failed job must not repeat the same edit | Claim is committed *before* Google is touched; retries are only for transient errors (exponential back-off, `autonomy_max_attempts=4`); a stuck `executing` row is resolved by **reading Google, never by writing again** (`recover_stuck`) | **Met** |
| Verify by Google read-back | `execute` re-reads the profile after the write, compares canonical values, and marks `failed` on a mismatch rather than claiming success | **Met** (for the fields it writes) |
| Do not revert Google's changes | The executor *invalidates* an action when the live value changed since proposal (`google_value_changed`); there is no code that restores values | **Met** and matches Google's "may not automatically revert changes made by Google" |
| Granular owner authorisation | Per-action-type permission `auto`/`ask`/`off` in `agent_settings.autonomy_permissions`; Level 3 can never be `auto`; posts/photos/replies are `person_only` | **Partly met** (see gaps) |
| Level classification can only escalate | `classify` escalates for removals, primary contact replacement, health claims; the model never supplies a level | **Met** |
| Approval scope bound to the exact value | `AgentActionApproval.scope_hash` over action, field, location, value, the Google value judged against and the facts relied on; the executor refuses on any difference | **Met** |
| Per-tenant limits and kill switch | `autonomy_daily_limit` (default 3/day), failure-streak suspension, tenant switch, **platform emergency stop** (env or runtime row) honoured by executor, content publishing, auto-reply and scheduled jobs | **Met** |
| Complete audit trail | Append-only hash-chained `agent_intervention_events` (UPDATE/DELETE refused by trigger); `audit_log` rows for settings changes | **Met** |
| Ranking follow-up without causal claims | `agent_rank_followups` day 7/14/28, outcome is "observed movement, never caused by" | **Met for rank only** |

### Gaps against your brief

| # | Gap | Detail |
|---|---|---|
| G1 | **Consent is default-on, not express opt-in** | `autonomy_enabled` and `auto_reply_enabled` default to `true` (migration 0031, owner decision 2026-11-15). Level 1 types default to `auto` (`authorization_for`: `perms.get(t, "auto" if level == 1)`), so with autonomy "on" a description rewrite proceeds without a per-type grant. Your brief and Google's policy ("prior specific and express consent") both require an explicit grant. The production emergency stop is the only reason nothing runs. |
| G2 | **No consent history** | `agent_settings` keeps only the *last* `autonomy_permissions_by/at`; each change adds an `audit_log` row (`autonomy.settings`) but with no record of **what the owner was shown**, the wording version, the scope (which location) or when it was revoked. Needs a dedicated, append-only consent record. |
| G3 | **No per-location or per-field grants** | Permissions are per tenant and per action type. A multi-location owner cannot say "allow this for branch A only". |
| G4 | **No undo** | Nothing restores a previous value. The data to do so exists (`current_value`, `base_fingerprint`). |
| G5 | **Brief's "automatic publication of approved posts and photos"** | By design these are `person_only` and cannot be pre-authorised. Approved items are *already* published by the scheduler at the due time, so "publish what I approved" works today. A standing grant to publish *without* per-item approval would reverse a deliberate policy; I read your brief as the former and need confirmation (D4). |
| G6 | **Operations not writable** | services, special hours, attributes, service area, booking links, name, address, event/offer posts |
| G7 | **No "what Google changed" view** | `getGoogleUpdated` (diffMask) unread, so a Google-initiated change (or a suggested update) is invisible and not offered for review |
| G8 | **Effect of an action on performance is not measured** | Only rank has a before/after; Google's metrics are shown but never compared around an action |

---

## 4. Google API operations: official support, verified 2026-11-17

Quotes are from Google's pages. "Impl." is what FlowQR does today.

| Operation | Official support (Google docs) | Restrictions to honour | Impl. |
|---|---|---|---|
| Description | `PATCH locations/*` `updateMask=profile`; `profile` required for non-lodging categories | Business-name and keyword-stuffing rules (support policies) | Read + write, **live PASS** |
| Regular hours | `regularHours` | | Read + write, not live-tested |
| **Special hours** | `specialHours` | "This field cannot be set without regular hours." | Read only |
| Phone, website | `phoneNumbers`, `websiteUri` | phone sub-fields must be sent together (code already merges) | Read + write, not live-tested |
| Categories | `categories` field | Update rules are on a page not yet read; code sends both sub-fields | Read + write, not live-tested |
| **Services** | `serviceItems[]` listed as "Optional"; "Duplicated service items will be removed automatically." | **No page states write support or the limits** (count, length). Must be proven with `validateOnly` before implementing. | Read only |
| **Attributes** | `getAttributes` / `updateAttributes`; `attributes.list` returns metadata per category/region | "If deprecated, updating this attribute will not result in an error, but updates will not be saved." Request shape not yet verified. | Not implemented |
| Service area, address | `serviceArea`, `storefrontAddress` | Address: no PO boxes, ≤5 lines; `latlng` "can only be updated by approved clients"; both Level 3 | Not implemented |
| Name | `title` | "Location name should reflect your business's real-world name"; no taglines, special characters | Level 3, not writable |
| **Safe test of any write** | `validateOnly=true`: "the request is validated without actually updating the location" | | **Not used yet. This is how Milestone 2 can test writes without changing a profile.** |
| **Google-initiated changes** | `getGoogleUpdated` returns `location`, `diffMask`, `pendingMask`; "To accept these changes, patch the location. To reject, patch with your preferred values." | Policy: auto-discarding suggested updates without the merchant is a violation | Not implemented |
| **Verification status** | Verifications API: `getVoiceOfMerchantState`, `verifications.list` | Verification "can only be initiated by a direct request from the owner" (policies) | Not implemented |
| **Booking / action links** | Place Actions API: `placeActionLinks` create/list/patch/delete | Separate API to enable; quota 0 until approved; type enum not yet read | Not implemented |
| Posts | `localPosts`: `STANDARD`, `EVENT`, `OFFER`, (`ALERT` COVID-only, creation disabled); CTAs `BOOK, ORDER, SHOP, LEARN_MORE, SIGN_UP, CALL`; states `LIVE/PROCESSING/REJECTED`; media `sourceUrl` only | summary length limit not on the page read | Standard posts only |
| Photos | `media`: `PHOTO` only; categories COVER, PROFILE, EXTERIOR, INTERIOR, PRODUCT, AT_WORK, FOOD_AND_DRINK, MENU, COMMON_AREA, ROOMS, TEAMS, ADDITIONAL | "minimum of 250px on the short edge, with a file size of at least 10240 bytes" (except PROFILE/COVER); descriptions can't be edited after creation | Implemented |
| Review reply | `updateReply` "only valid if the specified location is verified"; reply state returned | Authorisation required before replying for a client | Implemented |
| Performance | `fetchMultiDailyMetricsTimeSeries` metrics: `BUSINESS_IMPRESSIONS_{DESKTOP,MOBILE}_{MAPS,SEARCH}`, `CALL_CLICKS`, `WEBSITE_CLICKS`, `BUSINESS_DIRECTION_REQUESTS`, `BUSINESS_BOOKINGS`, `MESSAGING_CLICKS`, `BUSINESS_FOOD_MENU_CLICKS`; **deprecated:** `BUSINESS_CONVERSATIONS`, `BUSINESS_FOOD_ORDERS` | Impressions: "Multiple impressions by a unique user within a single day are counted as a single impression." **History limit and data delay: not stated on the pages read** (the code's 3-day lag is an assumption from earlier work). | Implemented |
| Search terms | `searchkeywords.impressions.monthly`: a `value` or a `threshold` ("below this threshold"); page size 100 | history limit not stated | Implemented |
| Notifications | Account-level Pub/Sub settings (`NotificationSetting`) | type list not read | Not implemented (30-minute polling) |
| Quotas | 300 QPM default; **"Edits: 10 per minute per Google Business Profile (cannot be increased)"**; Update Location 10,000 per day; 429 with backoff | quota 0 = not approved | Edit limit enforced locally (10/min/location) |

**Unsupported / not to be simulated:** nothing in your list is simply unavailable by API, but **services, attributes, special-hours writing, booking links and verification state are unproven for write** and must pass a `validateOnly` probe (or a read) on the authorised test profile before any code claims support. Browser automation is never used.

### Google policy requirements that bind the design (verbatim from the policies pages)

| Requirement | Quote | Where FlowQR stands |
|---|---|---|
| Express consent for automation | "you must not automate or trigger review replies, Q&As, listing creations, listing edits, or other actions without the user's prior specific and express consent." | **Default-on settings conflict** (G1) |
| No auto-revert | "You may not use the Business Profile APIs to automatically revert changes made by Google." | Compliant (no revert code); undo must only restore FlowQR's own change and only if Google's value is unchanged |
| Third-party consent for reviews | "If you respond to reviews on behalf of your end-client, you must receive their authorization first." and "Verbal consent isn't sufficient" | Template auto-reply default-on is not an explicit authorisation |
| Disconnect | "You must provide your end-client with a quick and easy way to stop use of your APIs." (seven business days, remove permissions) | Met: `DELETE /google/connections/{id}`; add a clearer "Disconnect FlowQR" control |
| **Content storage** | "You cannot pre-fetch, cache, index, or store any content provided through the Business Profile APIs ("Content") for use outside of your Business Profile project except for limited amounts of Content." Stored content "must be stored temporarily for no more than 30 calendar days" and "cannot be manipulated or aggregated in any way." | **See P1** |
| No cross-customer comparison | "You must not compare or share one customer's Business Profile-specific data with your other customers." | No such feature found; keep it that way (benchmarks must never use GBP data from other tenants) |
| Disclosure | A "Working with a third party" notice linked from a discoverable place on the website (SMB-focused third parties) | **Not verified** whether the site shows it |
| UI | Must not replicate the Business Profile look and feel | Not verified |

### Policy findings

- **P1: Content retention.** FlowQR stores Google content indefinitely: `reviews` (1,034 rows in dev, with text and reviewer names), `gbp_metric_daily` (months of history) and `google_locations`, and the disconnect route keeps reviews "as history". Google's page allows only "limited amounts" stored "temporarily for no more than 30 calendar days", "only to improve the performance of your project". The page lists no exception for reviews or metrics, and the separate Business Profile Terms (linked, **not read**) might say more. I am **not** asserting a violation; I am saying the current design is hard to reconcile with the sentence as written and that a product whose value is review history and trend charts cannot be built safely without either Google's written clarification or a redesign (derive aggregates, expire raw content at 30 days, or obtain approval). Needs D3.
- **P2: Default-on automation** (G1). Needs D2.

---

## 5. Local SEO intelligence

| Area | Today | Gap |
|---|---|---|
| Keyword discovery | Tracked terms (max 10 per location) + Google's own monthly search-term report (impressions per term; small counts shown as "below threshold") | No generation of high-intent service+place terms; no category-gap check; `seo_engine` only talks about terms the owner already tracks |
| Rank observation | Places Text Search, first 20, `languageCode` hard-coded `"en"`, 3 km bias, weekly re-check, monthly cap 300/business | Language fixed to English; no per-plan keyword number; platform cap 0 (fails open) |
| Geo-grid | Built, refuses to run until six guards pass | **Keep off.** Needs: Places price (read from Google billing), per-plan allowances, platform daily/monthly cap, a restricted production key (docs/GEO_GRID_ENABLEMENT.md) |
| Competitors | Top 10 rating/review/position per check; pin up to 5; dated snapshots; review growth only between two real observations | **No category, services, website, photo recency or profile completeness** of competitors. Those need Place Details (billed; SKU for these fields not verified here). Not scraping Maps. |
| Observed vs estimated | Labelled (`places`, `google`, `flowqr`) in `api/v1/seo.py` | Keep; every new number needs the same label |
| Performance | Daily metrics stored; 28-day vs previous 28-day totals on health | No action-anchored before/after; no handling yet of Google changing metric definitions (the deprecated metrics show it happens) |

---

## 6. Background automation

Existing (all tenant-iterating, wrapped in try/except per tenant): `sync_due_locations` (review sync, back-off), `daily_agent` (profile snapshot incl. 56 days of performance, daily plan), `autonomy_scan` (6 h), `autonomy_execute` (2 min), `autonomy_housekeeping`, `autonomy_followups`, `autonomy_retention`, `check_ranks`, `check_rank_grids`, `publish_due_posts/media`, `recover_stuck_posts`, `retry_failed_replies`, `auto_replies`, `notify_by_email`, `ops_watch`, `heartbeat`, `purge_*`.

| Required job | Status |
|---|---|
| Profile health checks | Exists (daily with the plan) |
| New review monitoring | Exists (30-minute poll) |
| Review response reminders | Partial (tasks + hourly email) |
| Performance sync | Exists inside `daily_agent`; no standalone retry/observability and covers all locations only if the plan job succeeds |
| Competitor refresh | Exists as a by-product of rank checks; no Place Details refresh |
| Ranking observations | Exists |
| Pending-optimisation reminders | Partial |
| **Profile inconsistency detection** | **Missing** (GBP vs business record vs website vs knowledge base; today only "missing phone/website" from the tenant record) |
| Per-tenant quotas | Autonomy daily limit, Places caps, auto-reply daily cap; **no cap on number of proposals per tenant** |
| Global emergency stop | Exists; hot-switchable |
| Observability | `heartbeat`, `ops_watch`, admin pages; no per-job success metrics for the new jobs |

---

## 7. Security, policy and auditability checklist

| Item | State |
|---|---|
| Token encryption, refresh, revocation | Done (Fernet; revoke on disconnect) |
| Tenant isolation and RLS | Done; every new table must have it and be in the export/deletion list |
| Explicit action permissions | Partial (G1 to G3) |
| Consent history | Missing (G2) |
| Complete action audit | Done for profile and content actions; extend to consent and undo |
| Revocation support | Disconnect works; add owner-visible "revoke a specific permission" with immediate effect on queued actions (already done by `withdraw_autonomous`) |
| Rate limits | 10/min/location edit limit enforced locally; Google 300 QPM not locally limited (sync is far below it) |
| No incentives or review gating | Enforced in code and docs (everyone gets the same Google link); keep tests |
| No fabricated review activity | Nothing fabricates; reviews only from Google |
| No ranking guarantees | `expected_outcome` "never a ranking promise" is in the model; extend to new task text |
| Data minimisation / retention vs Google | P1 |
| Google "third party" disclosure notice | Not verified |

---

## 8. Customer experience: current vs requested

Today (`frontend/src/lib/nav.ts`): **GBP** destination with Overview, Rankings (+ searches, competitors), Performance, Profile (Checklist, Info, Posts, Photos). **Reviews** has Inbox, Drafts, Insights. **AI Assistant, Tasks & Approvals, Activity** hold the approval queue and history. Settings has AI & automation (Voice, Brain, Autonomy, Usage).

Requested sections map onto what exists without new top-level pages being necessary:

| Requested | Home today | Change |
|---|---|---|
| Overview | `/seo` | Answer five questions with data we hold: Is my profile healthy (health score + checklist)? Are more people finding me (28-day vs previous 28, Google metrics with the lag excluded)? What needs attention (open tasks)? What has FlowQR improved (verified actions)? What next (next scheduled audit and top task)? |
| Google Profile | `/seo/profile` + `/gbp/info,posts,photos` | Add attributes, services, special hours, verification and "Google changed this" panes once proven |
| Reviews | `/gbp/reviews` | unchanged |
| Google Visibility | `/seo/rankings`, `/seo/performance` | merge terms, rank and views into one story; geo-grid stays hidden while disabled |
| Competitors | `/seo/rankings` strip + `/seo/competitors` | add "what they show that you don't" only from observed data |
| Optimisation Tasks | `/ai/tasks`, `/ai/approvals` | one list per location with Explain / Preview / Approve / Execute / Verify / Undo |
| Activity History | `/ai/activity` | include consent changes and undo, with the hash-chain verified badge |

All wording stays plain (Hindi/Hinglish labels follow existing language switching); charts only where they answer a question (per-day views, rank ladder, review growth); `docs/DESIGN.md` rules apply.

---

## 9. Test baseline on this branch

Ran in the project's Docker harness against the test database: `test_autonomy`, `test_phase1_policy`, `test_phase1_executor`, `test_phase15_governed`, `test_google_contract`, `test_phase2_autonomy_plan`, `test_template_auto_replies`, `test_competitors_pinned`, `test_rank_tracker`, `test_seo_metrics`.

**295 passed, 2 failed (297).**
- `test_rank_tracker::test_status_says_not_configured_...`: **passes when run alone**; fails only in the combined run, so it is **test-order-dependent state leakage**, not a product defect. To fix in Milestone 2.
- `test_seo_metrics::test_previous_period_comparison_...`: compares the **local date** (`date.today()`) with the product's **UTC** date; fails between 00:00 IST and 05:30 IST each day (it was 00:29 IST on 2026-11-17). **A test defect, not a product defect.** To fix in Milestone 2.

I did not run the full suite, frontend type-check or production build (nothing was changed). These all run at the end of each milestone.

---

## 10. Commercial readiness (recommendation only; no plan or price was changed)

Current feature keys (Verified, `services/plans.py`): Launch (`starter`, ₹499) = core + `gbp_info`, review sync, AI replies and generation; Growth (₹799) adds `gbp_posts`, `gbp_media`, `gbp_performance`, `insights`, `local_seo`, `keyword_tracking`, `geo_ranking`, `autonomy`, `ai_posts`, `profile_optimizer`, `growth_agent`; Scale (`pro`, ₹1,499) adds `multi_location`. Geo allowances unset for every plan.

| Capability | Recommended placement | Cost driver | Control |
|---|---|---|---|
| Profile audit, health score, checklist (deterministic) | Launch (read-only) and up | none | none needed |
| Google performance charts, review insights | Growth and up (as now) | Google API calls, no per-call fee found but **not verified**; do not assume free | sync interval |
| Keyword tracking | Launch: 3 terms; Growth: 10; Scale: 25 per location (proposal; today a single platform number, 10) | one Places search per check; Google's global list price is $32 per 1,000 (India price **not verified**) → about ₹3 per check | per-plan keyword number (needs a limits field), monthly cap |
| Competitor following | Growth: 5 per location (as now); extras need Place Details | Place Details (billed, not verified) | stays off until priced |
| Optimisation tasks with approval | Growth and up | AI tokens (Flash-Lite class, about $0.0004 to $0.0007 per draft) | AI budgets |
| Autonomous execution (opt-in) | Growth and up (as now), Level 2 types Scale | none beyond edits | per-type grants, daily limit |
| Posts, photos | Growth (as now), counted allowances | AI for drafts, storage for photos | per-plan monthly numbers (not configured today) |
| Geo-grid | Scale only, **off** until the six guards in `GEO_GRID_ENABLEMENT.md` are met | highest: tens of billed searches per scan | keep disabled |
| Multi-location | Scale (as now) | multiplies everything above | seats/locations |

Entitlement changes require your separate approval; none are made.

---

## 11. Implementation roadmap (controlled milestones)

Effort: engineer-weeks for one engineer, estimates ±40%. Every milestone ends with: relevant backend tests, full backend suite, frontend type-check, production build, and an integration test on the **authorised test profile or a controlled test account only**. Nothing is pushed or deployed without your approval.

### Milestone 1: Audit and gap analysis: this document (done)

### Milestone 2: Google integration readiness (about 1.5 weeks)
Goal: replace inference with proof, without changing any real profile.
1. **Read-only smoke** (`python -m app.cli google-smoke`) on the FlowHQ test connection only; record each API's result in `GOOGLE_API_AUDIT.md`.
2. **`validateOnly` write probes** for description, hours, special hours, phone, website, categories and services on the test profile (changes nothing); document which succeed and Google's limits for services and attributes.
3. **Read-only** additions: `getGoogleUpdated` (diffMask), Verifications state, attributes metadata/`getAttributes`, service area, address. Behind a feature flag; no UI claims until each has a live success.
4. Fix the two test defects (§9); add a regression test for the dev-stack safety rule below.
5. Owner checklist (cannot be done from code): Cloud Console status of consent screen, redirect URIs, enabled APIs, quota 300 vs 0 for the **production** project.
**Gate:** each operation is marked *proven live*, *validated only*, or *unsupported* in a table; nothing else is described as working.
**Files:** `services/google/provider.py`, `services/google/smoke.py`, `docs/GOOGLE_API_AUDIT.md`, `tests/test_google_contract.py` (add recorded real shapes).
**Needs from you:** D1, D4 (test profile), Cloud Console checks.

### Milestone 3: Profile optimisation engine (3 to 4 weeks)
1. One **profile audit result** per location (identity, information, completeness, reputation) on top of `optimizer.checks`, adding attributes, services detail, special hours, service area, booking links, verification state and Google-suggested updates as they prove out in M2. Reuse `optimizer.explain`; add the two missing parts to every recommendation: **expected benefit as a hypothesis** (templated, never a number, never a ranking promise) and **approval requirement** (from `autonomy_policy.classify`).
2. **Review analysis**: volume, recency, rating trend, unanswered count, themes (heuristic, labelled), response time; "response quality" only by deterministic checks (length, personalisation placeholders, prohibited-claim scan), not by AI judgement.
3. **Executor extensions** for operations M2 proved: special hours, services, then attributes, each as a new `ActionSpec` with read-back verification; services/attributes only if live-proven. No new tables: `AgentAction` is reused.
4. **Undo**: a new `undo` action that restores `current_value` for profile fields only if Google still holds exactly what FlowQR wrote (otherwise refuses: do not revert Google's changes); posts and photos undone by delete; replies by `deleteReply`. Undo is itself an owner-initiated, audited, verified action.
**Tests:** unit (policy, classification), contract (recorded real shapes), executor read-back mismatch, undo refusal when Google changed the value, dedupe, no-invention (every proposed value traces to a knowledge-base field or owner input).
**Files:** `services/agent/{optimizer,autonomy_policy,executor,plan,seo_engine}.py`, `services/google/provider.py`, `api/v1/{agent,autonomy_actions}.py`.

### Milestone 4: Local SEO intelligence (about 3 weeks)
1. **Opportunity discovery** (deterministic first): candidate terms = category + each verified service + place, filtered by Google's search-term report; surfaced as suggestions to track (the owner accepts); no new tracking without the owner. One cheap AI step only for wording (optional).
2. **Competitor gaps from stored data**: review-count and rating differences, review growth between observations, how often a competitor outranks you, *and* a Place Details snapshot for pinned competitors (category, website, rating) **only after you approve the cost** (D6). Observed vs estimated labels throughout.
3. **Performance before/after**: window comparison around a verified action (same-length windows, Google lag excluded, "the numbers moved, this does not show the change caused it"); per-metric using Google's own definitions; flags when a metric was deprecated.
4. Geo-grid untouched and off.
**Files:** `services/agent/learning.py`, `services/competitors.py`, `api/v1/seo.py`, new `services/agent/opportunities.py`, `services/gbp_metrics.py`.

### Milestone 5: Autonomous operations and consent (3 to 4 weeks)
1. **Consent model.** New `consent_grants` table (append-only, RLS): tenant, optional location, scope (action type or "reply template"), mode, exact wording and version the owner saw, granted_by, granted_at, revoked_at, revoked_by. Existing settings become derived from active grants. Defaults: **off**. A grant is required for every autonomous or standing action; Level 3 can never be granted. Revocation is immediate and withdraws queued actions (existing `withdraw_autonomous`).
2. **Migration of today's defaults** per D2 (existing tenants with defaults ON are moved to "not granted" and asked once).
3. **Scheduled jobs**: profile inconsistency detection (GBP vs business record vs knowledge base; website excluded until AEO work is scheduled), standalone performance sync with its own retry and `ops_watch` check, pending-task reminders (rate-limited), per-tenant proposal cap, job-level metrics.
4. **Next audit scheduling** recorded per location (`next_audit_at`) so the loop in your §3 has a visible next step.
5. Same-profile and same-field serialisation already exists; add a regression test for "failed job never publishes twice".
**Tests:** consent required for every autonomous path (deny by default), revocation mid-queue, grant per location, hash-chain verification, emergency stop with in-flight jobs, tenant isolation on every new table, export/deletion coverage.
**Files:** `models/autonomy.py` (+ `consent`), new migration (number chosen against the real head at the time), `services/agent/{autonomy_policy,executor,controls}.py`, `workers/tasks.py`, `services/account.py`, `services/agent/retention.py`.

### Milestone 6: Customer experience (about 3 weeks)
Overview that answers the five questions; Google Profile page with proven operations only; Visibility page merging rank, terms and views; Competitors with observed-only comparisons; one task list with Explain, Preview, Approve, Execute, Verify, Undo; Activity History including consent changes. Phone first, existing design tokens, no new top-level destinations (sections are tabs inside GBP and the existing AI tasks pages), `legacy-routes.mjs` for any moved URL. Playwright for the flows; screenshots at phone and desktop widths.

| Milestone | Effort (weeks) | Likely range |
|---|---|---|
| 2 Google readiness | 1.5 | 1 to 2.5 |
| 3 Profile engine | 3.5 | 2.5 to 5 |
| 4 Intelligence | 3 | 2 to 4.5 |
| 5 Autonomous ops and consent | 3.5 | 2.5 to 5 |
| 6 Customer experience | 3 | 2 to 4.5 |
| **Total** | **about 14.5** | **about 10 to 21** |

Not included: legal review time, Google's verification of the production OAuth app, any approvals Google imposes on Place Actions, and your own manual steps.

---

## 12. Decisions I need from you before Milestone 2

| # | Decision | My recommendation |
|---|---|---|
| **D1** | **Dev stack safety (urgent).** Real clinic profiles are connected with autonomy and auto-reply on and the emergency stop off. | Before anything else: turn the emergency stop on in the dev stack (`AUTONOMY_EMERGENCY_STOP=true` and restart api, worker, beat; or flip it at runtime from the admin endpoint) **and** disconnect the two real-clinic connections in the dev app, keeping only the FlowHQ test connection. I have **not** done either: it changes your running environment. Say the word and I will, or do it yourself. |
| **D2** | **Default-on consent.** Move automation to explicit opt-in, overriding the 2026-11-15 owner decision that switched autonomy and template replies on by default. | Yes: Google's own wording ("prior specific and express consent") and your brief both require it; template replies would be one explicit grant, off until granted. |
| **D3** | **Google's 30-day stored-content wording.** Ask Google for written clarification (and read the linked Business Profile Terms), take legal advice, or redesign to keep only derived aggregates and expire raw review text and daily rows. | Treat as a launch blocker for real customers: get clarification first; design M4/M6 so raw content can be expired without breaking the screens. |
| **D4** | **"Automatic publication of approved posts/photos".** Keep per-item approval (publishing then happens automatically at the scheduled time), or introduce a standing grant that publishes without per-item approval. | Keep per-item approval for now. |
| **D5** | **Test accounts.** Confirm the authorised FlowHQ test profile is the *only* profile live writes will ever touch, and that real-clinic connections stay read-only/disconnected while testing. | Yes. |
| **D6** | **Competitor depth.** Approve a Place Details lookup (billed, price not yet verified) for pinned competitors' category, website and photo count. | Defer until the Places SKU price is read from your Google Cloud billing page. |
| **D7** | **Cloud Console checks for production** (consent screen status, redirect URIs, enabled APIs, quota, verification). | Do these in parallel with Milestone 2; they gate any real customer. |

---

## 13. What I did not do

- No application, database, configuration, credential, plan, billing or infrastructure change; no commit, push or deploy.
- No Google call was made by me; Google statements come from documentation, and "live" statements come from existing validation documents or the local database's stored state.
- I did not run `google-smoke` (it makes real Google calls with stored tokens; reserved for Milestone 2 on the test connection).
- I did not read the separate "Business Profile Terms" page or Google's prohibited-and-restricted-content page (review solicitation rules); both are needed before M5.
- I did not run the full test suite, frontend type-check or build.
