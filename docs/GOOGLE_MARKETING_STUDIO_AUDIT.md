# Google Marketing Studio: audit, permission report and release notes

Date: 2026-11-24. Base: production commit 8d4bc62 (migration head 0067). Branch `feature/google-marketing-studio`, local only: **not pushed, not deployed**.

## 1. What already existed (and was reused, not rebuilt)

| Need | Already in FlowQR |
|---|---|
| Google OAuth, encrypted token storage, refresh, revoke | `services/google/provider.py`, `tokens.py`, `google_connections` (Fernet-encrypted) |
| Scope `business.manage` | Requested by default (`GOOGLE_SCOPES`); checked at connect time and refused if the user unticks it |
| Posts API client | `create_post` / `update_post` / `delete_post` / `list_posts` on `mybusiness.googleapis.com/v4/.../localPosts`; STANDARD, OFFER, EVENT; CTA rules |
| Approval + schedule + retry + duplicate guard | `scheduled_posts`, `services/agent/posts.py` (claim before call, find-on-Google before retry), `content_exec.py` (policy, emergency stop, read-back, history) |
| Calendar, preview, AI single-post drafts, safety rules | `/posts`, `PostCalendar`, `PostPreview`, `safety.check_text` (no invented prices/offers, health claims) |
| Business facts, local intelligence, quotas, audit log, RLS | Business brain, `intelligence.build`, `ai_usage`, `audit`, forced row-level security |
| Background workers | Celery `publish_due_posts` (unchanged) |

Missing before this work: the **campaign layer** (brief, objective, duration, several posts at once), a **media/document library**, a **public photo address** Google can fetch, a **campaign dashboard**, and the **local SEO assistant**.

## 2. Google permission report

| Requirement | Status | Evidence |
|---|---|---|
| Google Cloud project | PARTIALLY CONFIGURED | One project, in use. Production APIs were enabled and answered real calls (2026-11-21 live tests per release notes). |
| Business Profile APIs enabled | WORKING (production) | Accounts, locations, locations read and services write verified live on the FlowHQ-owned profile (SEO V2 live test, 2026-11-23). Not re-verified today. |
| OAuth client configured | WORKING | Client id/secret/redirect set; refresh exchange works while a token is alive. |
| Required OAuth scope | WORKING | `business.manage` is the default scope; connect refuses a token without it. |
| Customer authorization | REQUIRES MANUAL ACTION | Each customer must connect and tick the permission. **The consent screen is in Testing: refresh tokens die after 7 days.** Observed today: the local dev connection's refresh failed ("authorization revoked or expired"). Production: the paying customer's connection was revoked on 2026-11-22 the same way. |
| Account / location access | WORKING for the FlowHQ test profile; BLOCKED for others until tokens stop expiring | as above |
| Local Posts API access | NOT PROVEN LIVE | `localPosts.list` has run live (read, zero posts). **No `localPosts.create` has ever been sent to live Google.** The create body matches Google's current reference (searched today; no deprecation found; Local Posts remain on the v4 surface). |
| Publishing permission | NOT PROVEN | Needs one supervised real post on a FlowHQ-owned profile. |
| Token refresh | WORKING (mocked + live while valid) | |
| Production readiness | BLOCKED on 1) publishing the OAuth app out of Testing and passing Google verification for the sensitive scope, 2) one supervised live post, 3) `API_PUBLIC_URL` for photos | |

Today's live check: `google-smoke` against the local dev connection stopped at the token refresh (expired). I did **not** touch production tokens or create any post. Nothing was published to Google by this work.

### Distinctions that matter
* An API key alone cannot publish; publishing needs the customer's OAuth token with `business.manage` and an account that manages the location.
* The Posts API takes media **only as `sourceUrl`** (a URL Google downloads). A private storage URL cannot work. Hence the public photo door below.
* Third-party (agency) management of customer profiles is still blocked on Google's written policy answer (unchanged, separate from this feature).

## 3. What was built

* **Database** (migration `0068`, additive): `marketing_campaigns`, `marketing_assets` (both with forced RLS and the tenant policy), and on `scheduled_posts`: `campaign_id`, `asset_id`, `keywords`, `suggested_for`. Posts stay in `scheduled_posts` so approval, scheduling, retries, publishing and read-back are the **same governed path** (no second publisher). `PublishingLog` = the existing `agent_actions` history, shown per post. Both new tables are in the data export and cascade-delete with the business.
* **Backend**: `services/marketing_studio.py` (campaign planning and generation, library validation, local keywords, SEO assistant), `api/v1/marketing.py` (campaigns, library, regenerate, set photo, reschedule/publish-now, overview, readiness, SEO assistant), `api/v1/marketing_public.py` (the one public door).
* **Generation**: one model call writes the campaign from the Business brain, local keywords (real city, no invention), the owner's uploaded document text (fenced as data, prompt-injection instruction), and recent posts to avoid. Every post is re-checked: Google length limit, `check_text` (no invented price/discount/booking/health claims), similarity to earlier posts, quality gate; a failing post gets one individual rewrite, else it is left out and the owner is told. Offers come only from verified offers; events only from the owner's own title and dates. Link buttons are never invented (only CALL is suggested). Posts: 3 / 5 / 8 for 7 / 15 / 30 days, one per day at most, 10:00 business time.
* **Photos**: JPG/PNG, 10 KB to 5 MB, 250 px minimum, validated like Google. Attaching one gives it an unguessable token and serves it at `API_PUBLIC_URL/api/v1/public/mm/<token>`; documents never get a public address; deleting the photo ends the address. Videos are not accepted: the Posts API supports photos only. PDFs are stored but **not read** (no PDF parser in the stack; the UI says so); Word and text are read.
* **Frontend**: `/gbp/studio` (overview strip, publishing readiness, campaigns, calendar, media library, local search ideas), `/gbp/studio/new`, `/gbp/studio/[id]` (preview, edit, regenerate, photo picker, approve and publish/schedule, reject, reschedule, publish now, per-post history, retry). Menu: GBP > Marketing Studio.
* **Not built (deliberately)**: AI-generated images (the existing rule forbids generated imagery of the premises, team or results; no image model is configured), Instagram/Facebook/etc., ranking promises.

## 4. Can FlowQR publish Google Business Profile posts right now?

**NO, not proven.** The code path is complete and tested against doubles, and reads against real Google work, but a `localPosts.create` has never run live, and customer tokens expire after 7 days while the consent screen is in Testing. Publishing is also gated by a platform-wide emergency stop that was still **on** in production as of 2026-11-23.

## 5. Tests

* Backend new: `tests/test_marketing_studio.py`, 22 tests (**mocked Google and AI**; real PostgreSQL, RLS, state machines): generation, durations, safety refusal, offers/events rules, document handling and prompt-injection fencing, upload validation, public photo door, tenant isolation (API and raw RLS), approve/publish via the governed engine, double-approve cannot double-publish, reschedule, archive, readiness, SEO assistant.
* Existing suites re-run with this change: agent, Google business agent, post publishing, GBP, account/privacy lifecycle (export drift), security audit (route manifest, RLS sweep, role sweep), hardening isolation: all pass (180 + 42 passed). **The full backend suite (about 40 minutes) has not been run.**
* Frontend: `tsc` clean, 155/155 tests (3 new), production build succeeds. **No browser run of the new pages** (needs a signed-in session with a connected Google test location).
* Not performed: any live Google post, live AI generation, mobile/visual review.

## 6. Manual actions required (yours)

1. Google Cloud Console: set the OAuth consent screen to **In production** and complete verification for the sensitive `business.manage` scope (otherwise every customer reconnects weekly).
2. Set `API_PUBLIC_URL=https://api.flowqr.site` in `.env` **and** in `deploy/vps/docker-compose.vps.yml` (env vars reach the app only if listed in the overlay).
3. After deploying, publish ONE supervised test post to the FlowHQ-owned profile (`locations/6589197820321114990`), including one with a photo; check it on Google. Until then treat publishing as unproven.
4. Decide when to lift `AUTONOMY_EMERGENCY_STOP` (it holds all publishing).
5. Customers must reconnect Google (the paid customer's connection is revoked).
6. Privacy text: post photos are served from a public URL by design; mention it in the privacy notice (lawyer review pending as for other drafts).

## 7. Deployment

* Migration `0068` (additive; downgrade provided). Required order: backup, migrate, then api/worker/beat on the new image, then frontend. Rollback: previous image (`prod-8d4bc62`) works with the 0068 schema (columns are nullable); `alembic downgrade 0067` only if needed.
* No new dependency, no new worker or schedule. One env var (`API_PUBLIC_URL`, existing name). Feature plan gate: the same `gbp_posts` feature as Posts (Growth and up).
* Pushing any branch auto-publishes the Vercel production site: **do not push this branch until you want it live.**
