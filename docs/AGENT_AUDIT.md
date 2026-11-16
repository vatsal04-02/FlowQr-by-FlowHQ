# FlowQR: Autonomous AI Growth Agent: Engineering Audit

Audit date: 2026-11-15. Repository state: branch `feature/growth-platform`, HEAD `1118cd7` plus uncommitted work. Migrations at head `0025` when audited; **`0026` added by Phase 0** (see the Phase 0 section). The findings below describe the code **as audited**; the Phase 0 section says which of them were fixed.

## How to read this report

Every finding carries an **evidence tag**:

| Tag | Meaning |
|---|---|
| **[LIVE]** | A real external call is on record: rows in the running local database, or the dated live smoke result in `docs/LAUNCH_REPORT.md`. |
| **[TEST]** | An automated test exists. All of them use fakes or `httpx.MockTransport`. **I did not execute the test suite in this audit** (it rebuilds a `flowqr_test` database; the compose database port is not published). A [TEST] tag means "a mocked test covers this", never "Google accepted it". |
| **[CODE]** | Read in the source only. |

Method: read the implementation (not the UI), then queried **aggregate counts** from the local database (no customer text, no tokens) to see what the scheduler has actually done. Not inspected in depth: frontend screens, `services/media.py`, `workers/monitor.py`, `services/ops.py`, billing and entitlements, `ai/quality.py`, `ai/intelligence.py`, `api/v1/auth_google.py`.

## Phase 0: Production Reliability Foundation. Results (2026-11-15)

**Status: code complete and verified by the full automated suite (1064 passed, 0 failed). Every Google interaction in those tests is MOCKED. No live Google write has been performed, so no write feature is claimed to work against Google.** Phase 1 (Balanced Autonomy) follows below.

Evidence tags used below: **[MOCKED]** = automated test against a test double (proves FlowQR's own logic, nothing about Google). **[DB]** = real PostgreSQL, real migrations, real RLS (also in the tests). **[LIVE]** = a real Google call, on record. There is no [LIVE] entry in this section.

### Acceptance criteria

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1a | A controlled live-write test exists for replies, posts, photos and profile updates, restricted to an authorised test profile | **Ready, not yet run** | `python -m app.cli google-write-test` (`app/ops_cli.py: google_write_test`). A real write needs **three deliberate confirmations**: env `FLOWQR_LIVE_WRITE_AUTHORIZED=<location>` set by a person, `--confirm-location`, and `--confirm-title` (the profile's real title, printed from Google before anything is sent). Dry run by default. [MOCKED] `tests/test_phase0_google_write_test.py` (15 tests): every missing confirmation refuses with zero writes. |
| 1b | Every write is verified by reading the resource back from Google | **Implemented** | post: list shows it with the same text, then delete and list again. photo: read the media item back, delete, confirm gone. profile: description read back on two separate reads, original restored, restore read back. reply: review read back and the reply compared, reply deleted (`reviews.deleteReply`, new `delete_reply` in `provider.py`), confirm gone. A step is `PASS` only if it matched; the JSON report marks each step `verified_by_read_back`. [MOCKED] a Google that returns 200 but does not persist is reported FAIL (post, profile, reply cases), and a restore that does not stick prints "restore it by hand". |
| 1c | A mocked run can never be mistaken for a live one | **Done** | The report says `"mode": "mocked"` and prints "MOCKED: not evidence about Google". Only the real provider path writes `"mode": "live"`. |
| 2a | Atomic publishing state **before** the Google call | **Done** [MOCKED][DB] | `services/agent/posts.py: publish`: claim (`status=publishing`, `attempts`, `publishing_started_at`, `publish_token`) is **committed before** `create_post`. Test: a different DB session reads `publishing` while Google is being called. |
| 2b | Idempotency protection | **Done** [MOCKED][DB] | Google's create has no idempotency key, so: *look before create*. Any retry (`first_attempt_at` set) reads `list_posts` and adopts a post with the same text created since the first attempt (`find_on_google`); never adopts a REJECTED post, an older post, or one owned by another FlowQR post. New unique index `uq_scheduled_posts_google_name` (one Google post name per location). |
| 2c | Crash recovery | **Done** [MOCKED][DB] | `posts.recover_stuck` + Celery `flowqr.recover_stuck_posts` (every 5 min, `celery_app.py`). Crash after Google created the post -> adopted, not re-sent. Crash before -> re-queued, sent exactly once. Google unreadable -> left alone (never re-sent on a guess). Attempt limit -> `failed`, not a loop. Disconnected location -> `failed`. Every outcome is audited. |
| 2d | No duplicates after retries or restarts | **Done** [MOCKED][DB] | Ambiguous failure (Google created it, response lost) then retry; owner Retry after a final failure; two identical-text posts; scheduled job run twice. `tests/test_phase0_post_publishing.py` (17 tests). |
| 3a | Shared AI starter-text pool removed | **Done** | Deleted: `GET /public/reviews/{id}/starter`, the pool/cooldown code, `generate_starter`, `validate_starter` and their prompts, the frontend fetch (`ReviewLanding.tsx`), the preview label (`LandingFrame.tsx`) and the copy strings. Opening the page makes **no model call** and sends **no pre-written text**. [MOCKED] `tests/test_phase0_review_generation.py`. |
| 3b | Suggestions only from the customer's own experience | **Done** [MOCKED] | `/generate` refuses empty input (422) and asks one question for vague input without calling the model; the prompt contains only `<customer_answers>`; a draft that invents facts is rejected and never stored. |
| 3c | Customer editing and final control preserved; handoff unchanged | **Done** [MOCKED] | The stored final text is the customer's edit, kept apart from the AI text. `/submit` still answers 409 `direct_unavailable`; a config flag alone cannot enable direct submission. No automatic submission was added. |
| 4a | Every model call recorded: input/output tokens, model, task, tenant, estimated USD, status | **Done** [DB] | New table `ai_call_ledger` (one row per `generate()` call, written in its own transaction so a rolled-back request keeps its cost). `services/ai_usage.py: MeteredProvider`. Calls blocked by a budget are recorded too (`status=blocked`, zero cost). |
| 4b | All five original call sites and the dashboard/agent calls covered | **Done** | 11 call sites wrapped: `reviews.py` (reply draft), `posts.py` (post draft, ideas), `agent.py` (task draft, description), `tenants.py`, `public.py`, `review_public.py`, `review_growth.py`, `agent/plan.py` (daily agent replies and posts). Test `test_every_model_call_site_goes_through_the_meter` fails the build if any `get_provider()` call is not wrapped. Also fixed: `log_generation` calls that used to drop token counts (the live DB showed 0 tokens for reply and post drafts). |
| 4c | Per-business monthly budgets and a platform hard limit | **Done** [DB] | `tenants.ai_monthly_budget_usd` (per business) or `AI_TENANT_MONTHLY_BUDGET_USD` (default); `AI_TENANT_MONTHLY_TOKEN_BUDGET`; `AI_PLATFORM_HARD_LIMIT_USD`; `AI_PLATFORM_MONTHLY_TOKEN_LIMIT`. Visible in the ops dashboard (`ai_limits`). All **off (0) by default**: nothing is enforced until you set them. |
| 4d | Nonessential generation stops when limits are reached | **Done** [DB] | Customer-facing review writing and the review-risk check are *essential* (stop only at the platform hard limit). Drafts, posts and the agent stop at the business budget and at the platform soft line (`AI_PLATFORM_SOFT_PCT`, default 90%). Owner endpoints answer **402** with the reason. |
| 4e | Never silently bypassed, including on retries | **Done** [DB] | The check sits **inside the provider wrapper**, before every `generate()`. A rewrite or second attempt is a new call and is checked again; the pre-check adds the call's own worst case (estimated input + `max_tokens`), so one call cannot cross a limit. A USD limit with **no price configured fails closed** (`budget_unpriced`) instead of silently not working. Budget codes never pause AI for everyone. |
| 5a | Sensitive reviews, threats, privacy issues and high-risk complaints are escalated | **Done** [MOCKED] | `services/ai/safety.py: assess_risk` (level low / medium / high): new reasons `privacy` (phone, email, Aadhaar/PAN-shaped numbers, "without consent"...), `self_harm`, `hostile_tone`, `detailed_complaint`; **every 1-2 star review is now `low_rating`** (before, only when another flag also matched). Stored as `reply_drafts.risk_level`; high or medium needs the owner to acknowledge before approval. |
| 5b | Not only flagged keywords | **Done** [MOCKED] | Structural signals (rating, length, shouting, personal data) **and** an AI safety read (`services/ai/risk.py`). Test: a calm threat with no flagged word (`"We know where you live..."`) scores *low* on rules alone and *high* with the AI check. The AI can only raise a level, never lower it; review text is wrapped as data; an AI failure or budget stop never makes a review look safer (a 3-star review becomes medium; a 5-star one is "not AI-checked"). |
| 5c | Ordinary low-risk reviews can later be configured for automatic replies | **Prepared, not enabled** | `safety.eligible_for_auto_reply(risk)`: only LOW risk, no reasons, and (by default) AI-checked. **Nothing automatic was added**; `auto_publish` is still always false (`autonomy.py`). |
| 6 | Regression tests; mocked clearly separated from live | **Done** | See below. Each new test file's docstring states what is mocked. |

### Exact files changed

Backend, **added (7):** `alembic/versions/0026_phase0_reliability.py`, `app/services/ai/risk.py`, and the tests `tests/test_phase0_post_publishing.py`, `test_phase0_ai_cost.py`, `test_phase0_review_safety.py`, `test_phase0_review_generation.py`, `test_phase0_google_write_test.py`.

Backend, **modified (28):** `app/api/v1/{agent,posts,public,review_growth,review_public,reviews,tenants}.py`, `app/core/config.py`, `app/models/{__init__,agent,business,platform,tenancy}.py`, `app/ops_cli.py`, `app/schemas/reviews.py`, `app/services/agent/{plan,posts,autonomy}.py`, `app/services/ai/{review_generate,safety}.py`, `app/services/{ai_usage,ops}.py`, `app/services/google/provider.py`, `app/workers/{celery_app,tasks}.py`, and the tests `tests/{conftest,test_autonomy,test_review_starter,test_ops_cli}.py`.

Frontend (3): `src/components/public/ReviewLanding.tsx`, `src/components/review-growth/LandingFrame.tsx`, `src/lib/review-growth.ts`. Infrastructure and docs: `docker-compose.yml` (passes the new AI limit variables to the containers), `.env.example`, this file.

### Database migration `0026_phase0_reliability`

* `scheduled_posts`: `publishing_started_at`, `first_attempt_at`, `publish_token`; unique partial index `uq_scheduled_posts_google_name (google_location_id, google_post_name)`; partial index for stuck-post lookup.
* `ai_call_ledger` (new): per-call tokens, model, task, tenant, cost, status; RLS enabled **and forced**; app role gets `SELECT, INSERT` only (append-only). Deliberately **no foreign key** to `tenants`, so spend history survives a deleted business.
* `tenants.ai_monthly_budget_usd` (nullable); `reply_drafts.risk_level`.
* **Verified:** applied from scratch by the test suite; **and on a copy of the real local database** (revision 0025, 3 scheduled posts, 2 reply drafts, 5 tenants, 964 reviews): upgrade, `downgrade -1`, upgrade again all succeeded, row counts unchanged, RLS on. The copy was in a throwaway container and has been deleted. **The running local stack is still on 0025**: it has not been migrated or rebuilt (see blockers).

### Tests executed

Run in Docker (`flowqr-test` image, throwaway PostgreSQL 16, migrations rebuilt from scratch, Google and the AI **mocked**):

| Run | Result |
|---|---|
| Baseline, untouched copy of the code, before any change | **995 passed, 0 failed** (8m26s) |
| After Phase 0, full suite | **1064 passed, 0 failed** (9m08s) |

New: **95 tests** (post publishing 17, AI cost 21, review safety 32, review generation 10, write-test tool 15). Removed: **26 test cases**, the whole shared-starter feature's tests (`test_review_starter.py` keeps the one-tap, refine and Google-link tests). Changed on purpose (3): `test_autonomy.py` (a low-star review now needs the flag acknowledged before approval), `test_ops_cli.py` x2 (the write test now needs the extra confirmations). The frontend type-check (`tsc --noEmit`) passes. **No browser (e2e) tests were run.**

### Live Google write results

**None performed.** No authorised test Business Profile was designated, and writing to the connected profile (which is a real business's) without explicit authorisation is exactly what this phase forbids. The state of the local stack: 2 active Google connections, `api_access=approved`, so a live run is feasible as soon as a test profile is named. Runbook:

```
# 1. dry run (sends nothing, prints exactly what would be sent)
docker compose exec api python -m app.cli google-write-test --connection <connection-id> --location locations/<N> --post --photo --profile --reply-review <review-id> --reply-text "<test reply>"
# 2. the live run, only on a profile you have said is a TEST profile
FLOWQR_LIVE_WRITE_AUTHORIZED=locations/<N> docker compose exec -e FLOWQR_LIVE_WRITE_AUTHORIZED api python -m app.cli google-write-test --connection <id> --location locations/<N> \
    --post --photo --profile --reply-review <id> --reply-text "<text>" --execute --confirm-location locations/<N> --confirm-title "<exact title the dry run printed>" --report /tmp/write-test.json
```
Record the report here with the date and the profile (by name). Until then these remain **unverified against Google**: reply publishing, post publishing, photo upload, profile edits, `deleteReply`, and the new post crash-recovery against Google's real `localPosts` behaviour (in particular whether `createTime` and `summary` come back exactly as the matching assumes).

### Behaviour owners will notice

* Every 1-2 star review needs the owner to **acknowledge a flag** before approving a reply, even with no flagged word.
* New reasons shown on drafts: privacy, self-harm, hostile tone, long complaint, and the AI-found ones.
* When a budget is reached, AI drafting returns **HTTP 402 with the reason**, not a generic failure.
* The review page no longer pre-fills any text. The box starts empty; the draft appears from the customer's own stars, topics or words.

### Remaining blockers

1. **An authorised test Business Profile** (and a review on it, for the reply step) to run the live write test. Nothing in section 1b can be called live-verified before that.
2. **AI per-token prices** (`AI_PRICE_IN_PER_MTOK` / `AI_PRICE_OUT_PER_MTOK`) and the limits themselves (`AI_PLATFORM_HARD_LIMIT_USD`, `AI_TENANT_MONTHLY_BUDGET_USD`) are **not set**. With them unset, calls are recorded (tokens) but cost is `NULL` and **nothing is stopped**. The ops dashboard shows "No platform hard limit" until they are set. I did not invent prices.
3. **The running stack still has the old code.** Rebuild and migrate the backend (`docker compose build api worker beat && docker compose up -d`, the `migrate` service applies 0026). The new beat entry (stuck-post recovery) and the ledger only exist after that.
4. **Two model variants are not exercised live:** the AI review-risk call has never run against real Gemini (only scripted); budget behaviour with Gemini's real token counts and thinking-token billing is unmeasured. The risk call adds one small model call per drafted reply (`AI_REVIEW_RISK_CHECK=false` turns it off).
5. **Known gap, unchanged:** drafting is still once a day, `auto_publish` is still always false, rank data is still not connected to decisions. These are Phase 1+ and were not touched.

---

## Phase 1: Balanced Autonomy Policy and Execution Engine. Results (2026-11-15)

**Status: foundation implemented and verified by automated tests (full suite 1190 passed, 0 failed). Every Google interaction and every ranking measurement in those tests is a TEST DOUBLE. No autonomous or approved write has been executed against real Google, so FlowQR does NOT claim autonomous execution works. Autonomy is OFF for every business until its owner switches it on, and nothing in this phase adds unrestricted publishing: replies, Google Posts and photos still use their Phase 0 approval-gated paths (`auto_publish` is still always false).**

Evidence tags as in Phase 0: **[MOCKED]** a test double stands in for Google or Places (proves FlowQR's own logic only), **[DB]** real PostgreSQL, real migrations, real row-level security and the real append-only trigger, **[LIVE]** a real Google call on record. There is **no [LIVE] entry in this section**.

### Architecture

```
 proposer (Local SEO scan, daily plan, owner request)
        |   no level / risk / authorization parameter exists on this call
        v
 executor.propose  --> autonomy_policy.classify   (pure code: the ONLY place a level is decided)
        |             autonomy_policy.validate_proposal  (verified source, current value, evidence)
        |             learning.suppression               (do not repeat what did not help)
        v
 agent_actions (pending_approval | approved | blocked)  +  agent_intervention_events (hash-chained, append-only)
        |
        |  Level 1 + owner switched autonomy on  ->  authorized by policy
        |  Level 2 + owner pre-authorized THIS type ->  authorized by pre-authorization
        |  otherwise / Level 3 (always)           ->  a person decides: executor.decide (owner only for Level 3)
        v
 executor.execute  (the ONLY path that writes a profile field to Google)
   claim -> read live -> re-verify -> write -> read back independently -> compare -> record
        |
        v
 learning: baseline BEFORE the write, follow-ups at 7 / 14 / 28 days -> improved / declined / unchanged / unknown
        -> priorities and suppression for the next scan
```

The model never sees or sets any of this. A draft written by Gemini is just a `proposed` value; its level comes from the action *type* and the *values* (`classify` can only escalate: it never lowers a level), and an API request cannot carry a level (`extra="forbid"`, tested).

### The policy (`services/agent/autonomy_policy.py`, published at `GET /agent/policy`)

| Level | Who authorizes | Action types |
|---|---|---|
| **1: autonomous** | The policy, **only if the owner turned autonomy on** for the business (default off) | Ranking/keyword monitoring, SEO analysis and reporting, profile-completeness analysis, internal planning, ranking trend analysis and alerts *(internal: no Google write)*; **description improvement from verified, owner-approved facts**; spelling/format/wording correction (safe changes only: no new words, numbers or links); service-description improvement |
| **2: conditionally autonomous** | A person, **unless the owner pre-authorized that exact action type** (then the policy, with verified source data) | Regular opening hours; services (add/change); adding a **missing** website or phone from the business record; **adding** a secondary category; publishing approved content; uploading a genuine photo from the approved library |
| **3: owner authorization** | The **owner, every time**. It cannot be pre-authorized (the settings API refuses it, and the engine ignores it if the data says otherwise) | Business name; primary category; address/location; important attributes; service area; **changing** an existing primary phone or website; removing significant information; regulated or sensitive claims |

Escalation rules in code (`classify`): a contact update where Google already has a value becomes *change an existing primary contact* (L3); removing a field, shrinking the description by more than 40%, dropping a day from the hours, or removing a secondary category becomes *significant removal* (L3); description text containing a regulated claim (cure, treat, diagnose, guarantee, certified, licensed, ...) on a health business becomes *sensitive claim* (L3). Malformed values are a `PolicyError`, never a guess.

**Evidence and fact validation** (`validate_proposal`): every proposal stores the current value, the proposed value, the verified source (business knowledge, the business record, owner input or the Google profile; owner input must name the person who entered it), the evidence, the reason, the risk, the required authorization level and an expected outcome that **never promises ranking**. A missing, empty, conflicting or unsupported fact **blocks** the proposal (status `blocked`, reasons recorded) and nothing can execute it. Nothing is invented: the engine only mentions a search term the business verifiably is or does.

**Approvals** (`agent_action_approvals`): `pending_approval -> approved | rejected | expired -> executing -> executed | failed`, plus `invalidated`, `blocked`, `canceled`. An approval stores who, when, the decision, the basis (`owner`, `level1_policy`, `preauthorization`), an expiry (72 h for a person, 24 h for automatic authorization), and a **scope hash** over (action type, field, location, exact value hash, the Google value it was proposed against, the facts it relied on). Execution recomputes the hash: an approval authorizes **that exact change and nothing else**, so editing the stored value after approval, or approving action A and running action B, does nothing. A rejection needs a reason. If the Google value, the business facts or the policy level changed after approval, the action is **invalidated** instead of executed.

**The execution engine** (`services/agent/executor.py: execute`), in order, every time: lock the row and read it fresh; emergency stop (hold); tenant / location / connection ownership; business active and plan includes profile management; an authorization that is valid, unexpired and matching its scope hash; autonomy still on, not suspended, the type still allowed, Level < 3; per-business daily limit; read the live profile from Google; already applied? (invalidate, never write twice); Google value unchanged since proposal; verified facts unchanged; policy level not increased; evidence still sufficient; Google edit rate limit; ranking baseline; **atomic claim (`executing`) committed before Google is touched**; the write; **an independent read-back**; compare. **A request Google accepted is never a success by itself**: if the read-back does not show the value, the action is `failed` with `read_back_mismatch`. Temporary errors (429/5xx/network) retry with back-off (max 4 attempts); an ambiguous failure is resolved by reading Google first (adopt, never re-send); permanent errors fail at once. Concurrency: a partial unique index allows **one in-flight write per location and field**, a second worker gets `location_field_busy`; an idempotency key stops duplicate proposals; a crash mid-write is resolved by `recover_stuck` (read Google, verify or requeue, never a blind rewrite).

**Intervention history** (`agent_intervention_events`, `services/agent/history.py`): per action, every step (proposed, policy_classified, approved/rejected/auto_authorized, baseline_measured, executing, google_write, read_back, verified/failed, follow-ups, evaluated), each with actor, time and data. The application's database role has **SELECT and INSERT only**; a trigger refuses UPDATE, DELETE and TRUNCATE even for the table owner; each event carries a sha256 of its content chained to the previous event, and `history.verify` detects edits or gaps even if the trigger were bypassed. The only exception is deleting a whole business (a transaction-local flag that `account.delete_tenant` sets), so data-deletion rights still work. Shown with an integrity check at `GET /agent/actions/{id}`.

**Ranking feedback loop** (`services/agent/learning.py`): for ranking-relevant actions the tracked search terms are measured **before the write** (a check under 7 days old is reused at no cost; otherwise one Places call per term inside the business's monthly allowance; whatever cannot be measured is recorded as unavailable and never blocks the action), then re-measured at **7, 14 and 28 days**. Each term is compared as improved / declined / unchanged (a move under 3 positions is noise) / **unknown** (a failed measurement is never read as a rank; "not in the first 20" is a real result). Every result carries the note "observed after the change, not proof that the change caused it". Effect on later behaviour: a change followed by a decline is not re-proposed by the agent for 45 days; two changes with no observed movement pause that kind of change for 60 days; two failures or a recent rejection pause it for 30 / 14 days; the priority of that kind of change is lowered after an improvement and raised after "no movement". A person can still ask for a paused change. **Rank data now changes decisions:** the optimizer gets a `visibility` check, the health score a `visibility` component (weight 10), the daily plan a `visibility` task, and the SEO scan proposes a description change for measured-weak terms (all only when measurements exist; without them nothing new appears).

**Emergency controls:** per-business switch (`PUT /agent/autonomy-settings`, owner only; switching off also **returns already-authorized pending actions to a person**), per-action-type permission (`auto` / `ask` / `off`), per-business daily limit (default 3 autonomous changes), **platform-wide emergency stop** (env `AUTONOMY_EMERGENCY_STOP` or `PUT /admin/autonomy/emergency-stop`, platform admin, reason required, audited) which holds profile writes **and** scheduled posts, photos and reply retries without losing them, **automatic suspension** after 3 consecutive failed executions (the owner must resume), per-business and platform AI budgets (Phase 0 `MeteredProvider`; the scan stops before any model call) and the Places monthly cap, all audit-logged.

### Acceptance against the brief

| Requirement | Status | Evidence |
|---|---|---|
| Central policy classifies every proposed action; AI cannot override | **Done** [MOCKED][DB] | `autonomy_policy.py`; no level parameter on `propose`/`classify`; property test that `classify` never lowers a level; API rejects `level`, `policy_level`, `authorization`, `status`, `risk` (422) |
| Level 1 / 2 / 3 per the brief | **Done**, with the limits listed under "Known limitations" | every action type has a test (`test_phase1_policy.py`) |
| Evidence and fact validation, never invent, insufficient evidence blocks | **Done** [MOCKED] | missing, empty, conflicting and unsupported facts, unsupported fields, a type the owner switched off |
| Structured approval workflow, immutable history, revalidation | **Done** [MOCKED][DB] | approve/reject/expire/execute, scope tamper, Google value changed, facts changed, policy escalated, approval of A never runs B |
| One safe execution engine with read-back | **Done**, **against a test double only** | `executor.execute`; read-back mismatch, lost response, retry, permanent refusal, concurrency, duplicates |
| Intervention history protected | **Done** [DB] | role cannot UPDATE/DELETE; trigger refuses even the owner role; hash chain detects bypass; deleting a business erases its history |
| Ranking feedback loop | **Done** [MOCKED] | baseline before the write, 7/14/28 day follow-ups, verdicts, suppression, priorities, rank data changes optimizer/plan/health/scan |
| Emergency controls | **Done** [MOCKED][DB] | see tests below |
| Live proof that autonomous execution works | **NOT DONE** | needs an authorized test profile |

### Database migration `0027_balanced_autonomy`

New tables (all with row-level security **enabled and forced**, default deny): `agent_actions` (status check; partial unique idempotency index over live statuses; partial unique in-flight index `(google_location_id, field_key) WHERE status='executing'`), `agent_action_approvals`, `agent_intervention_events` (append-only: SELECT/INSERT grants only, trigger blocks UPDATE/DELETE/TRUNCATE), `agent_rank_followups` (unique per action and day offset), `platform_controls` (the runtime emergency stop). `agent_settings` gains `autonomy_enabled` (default **false**), `autonomy_permissions`, `autonomy_permissions_by/at`, `autonomy_daily_limit` (3), `autonomy_suspended_at/reason`, `autonomy_failure_streak`. Applied from scratch by the test suite on PostgreSQL 16. **Not yet applied to the running local database** (still revision 0025): see blockers. A `downgrade` exists and was written to drop the history table through the documented purge flag.

### Exact files changed (Phase 1)

Backend, **added (11):** `alembic/versions/0027_balanced_autonomy.py`, `app/models/autonomy.py`, `app/services/agent/{autonomy_policy,history,controls,learning,executor,seo_engine}.py`, `app/api/v1/autonomy_actions.py`, `tests/test_phase1_policy.py`, `tests/test_phase1_executor.py`.

Backend, **modified (11):** `app/main.py` (router), `app/core/config.py` (7 `autonomy_*` settings), `app/models/{__init__,agent}.py`, `app/services/account.py` (history purge flag when a business is deleted), `app/services/agent/{plan,optimizer,health,autonomy}.py`, `app/api/v1/agent.py` (rank data into the optimizer; the description approval now goes through the executor), `app/workers/{tasks,celery_app}.py` (4 jobs; emergency stop holds the three publishers), and `tests/test_autonomy.py` (low-star drafts need the flag acknowledged; changed in Phase 0).

Infrastructure: `docker-compose.yml` and `.env.example` (the `AUTONOMY_*` variables).

New API (all tenant-scoped; roles enforced server-side): `GET /agent/policy`, `GET/POST /agent/actions`, `GET /agent/actions/{id}`, `POST .../approve | reject | cancel`, `POST /agent/actions/scan`, `GET/PUT /agent/autonomy-settings` (PUT owner only), `POST /agent/autonomy-settings/resume` (owner only), `GET/PUT /admin/autonomy/emergency-stop` (platform admin). New Celery jobs: `autonomy_execute` (2 min), `autonomy_housekeeping` (5 min: expire, recover stuck), `autonomy_followups` (hourly), `autonomy_scan` (6 h; only for businesses with autonomy on).

### Tests executed

Run in Docker (`flowqr-test` image, throwaway PostgreSQL 16, migrations rebuilt from scratch, Google, Places and the AI **mocked**):

| Run | Result |
|---|---|
| Phase 0 end state, full suite | 1064 passed, 0 failed |
| Phase 1 policy tests (`test_phase1_policy.py`) | **54 passed** |
| Phase 1 executor, approval, history, feedback and API tests (`test_phase1_executor.py`) | **72 passed** |
| After Phase 1, full suite | **1190 passed, 0 failed** (1064 + 126 new) |

What the new tests cover, by the brief's list: **every classification** (all 22 types, escalations, never-lowers property); **missing or conflicting facts** (empty knowledge, tenant-record conflict, malformed values); **unauthorized actions** (Level 3 by an admin or staff, Level 2 without a pre-authorization, a pre-authorization for a different type, `auto` written to a Level 3 type, unapproved actions never write); **expired approvals** (at execution time and by the expiry job); **Google value changed after approval**; **facts changed after approval**; **approval scope tampering**; **tenant isolation** (API 404, row-level security on all four new tables, a mismatched action/location/tenant is blocked, feedback never crosses businesses); **concurrent execution** (two real threads: one write, the second gets `not_approved`/`location_field_busy`); **duplicate prevention** (same proposal, executed twice, same field in flight, lost response adopted not re-sent); **Google failure and retry** (503 retried with back-off, permanent 403, read failure before the write); **read-back mismatch** (a 200 that changes nothing is `failed`); **emergency stop** (env and runtime, held not lost, publishers held, lifted -> runs); **budget exhaustion** (AI budget stops the scan before a model call, Places cap gives "unavailable" and the action still runs); **autonomy off stops pending jobs**; **automatic suspension after repeated failures**; **intervention history integrity** (UPDATE, DELETE, TRUNCATE refused, app role has no privilege, hash-chain detects a bypass, deleting the business erases it); **the feedback loop** (baseline before write, 7/14/28, improved/declined/unchanged/unknown, a failed measurement is not a rank, giving up on unmeasurable follow-ups, suppression, priorities, rank data changes the optimizer, plan, health score and scan); and one end-to-end **mocked** cycle (scan -> policy -> execute -> read-back).

Fixed during testing (real defects found by these tests): a duplicate-proposal handler that returned an unsaved object on **any** integrity error (now re-raised unless a real duplicate exists); the in-flight claim error escaped its handler because the history write flushes first; a person's request was swallowed by an earlier **blocked** agent proposal for the same change; the emergency-stop response read back before flushing; the execution lock trusted a session's cached copy of the row.

### Live Google execution evidence

**None.** No authorized test profile was provided; writing to the connected (real) profile is forbidden by the constraints of this work. Therefore: **it is not claimed that autonomous execution works.** What is established: FlowQR's policy, approval, claim, verification, history and emergency logic behave as specified against a test double and a real database. What is **not** established: that Google's `locations.patch` accepts these field masks for this account, that a read immediately after a write returns the new value (eventual consistency), that `profile.hours`/`categories` read-back compare equal to what is sent, and what Google does when a profile is under review. The existing live runbook (Phase 0) exercises the profile description write; extend it before enabling Level 2.

### Known limitations (stated, not hidden)

1. **Not every classified type can be written.** Google's API as integrated here writes only description, hours, primary and additional categories, phone and website. **Name, address, attributes, service area and services are classified (Level 3 / 2) but NOT writable**: a proposal for them is recorded as `blocked` with "cannot write ... a person can change it in Google Business Profile".
2. **Posts, photos and replies are classified Level 2 but are not routed through the executor.** They keep their Phase 0 approval-gated, claim-before-publish paths. No autonomous publishing exists.
3. **Owner edits made directly in the profile editor (`gbp.py`) do not go through the executor**: they are the owner acting in person and are not in the intervention history.
4. **Geographic comparison is limited.** Only a single-centre ranking exists (no geo-grid), so "geographic visibility" means the one measured point. A geo-grid is a separate piece of work.
5. **Keyword discovery** is not part of this phase: the engine uses the search terms the owner tracks.
6. **No frontend** was built for autonomy settings, the action queue or the history. The API is complete; the owner cannot yet switch autonomy on from the dashboard. (This is a safe default: autonomy cannot be enabled by accident.)
7. The 7/14/28 day follow-ups use the same single point; results are observations, **never causal claims**.

### Remaining blockers

1. **An authorized test Business Profile** to run the live execution test. Until then every execution result is [MOCKED].
2. **The running stack is on the old code and migration 0025.** Rebuild and migrate (`docker compose build api worker beat && docker compose up -d`) to get 0026 and 0027. Not done: it was not asked for.
3. A decision on **owner-facing UI** for autonomy (settings, queue, history) before any business can use this.
4. **AI prices and limits** (Phase 0 blocker 2) are still unset, so budget stops are not enforced in production until configured.
5. Extend the live write-test runbook to hours, categories, phone and website, and run it on the test profile before any Level 2 pre-authorization is offered to owners.

---

## Phase 1.5: Geo-grid ranking, unified Google execution, Autonomy control centre. Results (2026-11-15)

**Status: all six workstreams are built and verified by automated tests (full backend suite: 1267 passed, 0 failed) and by browser tests against an isolated demo stack. Every Google and Places interaction in those tests is a TEST DOUBLE or a SEEDED database row. No live Google write or live Places scan has been run. FlowQR is NOT claimed to be production-ready for autonomous Google writes: that claim needs the evidence log in `docs/LIVE_VALIDATION_RUNBOOK.md` section 9 to be filled in on an authorised test profile.**

Evidence tags: **[MOCKED]** test double (proves FlowQR's logic only), **[DB]** real PostgreSQL, migrations, RLS and triggers, **[BROWSER]** the real UI in Chromium against a real local stack with seeded data and no Google call, **[LIVE]** a real Google call. There is no [LIVE] entry here.

### 1. Geo-grid ranking

| Requirement | Status | Evidence |
|---|---|---|
| Configurable grid | **Done** | 3x3, 5x5 or 7x7 squares at 250 m to 10 km spacing, centred on the business or on chosen coordinates; or the owner's own points (validated: real, distinct, within 50 km). The resolved coordinates are stored with a hash so history stays comparable. [MOCKED][DB] |
| Multiple coordinates per business and keyword | **Done** | several maps per location; every tracked search term is scanned over every map; one `rank_grid_scans` row per (map, term, run) and one `rank_grid_points` row per coordinate. |
| Historical results, significant-change detection | **Done** | each scan is compared with the previous scan of the **same points** (hash match) and the same term. Significant = top-3 coverage moved 15+ points, or average position 2+, or 30%+ of points moved 3+ positions. A point that failed in either scan is `unknown`, never a decline; a scan with under 80% of points measured is not compared. The wording is "observed", never "caused". [MOCKED] |
| Heat-map data for the frontend | **Done** | `GET /gbp/{loc}/rank/grids/{id}/heatmap`: one cell per point (rank, bucket, error), bounds, legend, scan summary, change. Drawn in `GeoGrid.tsx` (colour is never the only signal: every circle shows its number). [BROWSER] |
| Plan-based limits | **Done** | `settings.rank_grid_plan_limits` by plan code (trial 2 maps / 9 points / 150 searches a month, growth 3 / 25 / 400, multi 6 / 49 / 2000; a plan not listed has none, e.g. essential gets 402). **These numbers are my defaults, not a pricing decision: set them to your plan design.** |
| Places API cost controls | **Done** | every point = one billed search, counted per business per month; a scan that does not fit the allowance is refused **before any search** ("Nothing was spent"); a 429/503 mid-scan stops buying the rest; optional **platform-wide** monthly cap; optional price per call for estimated spend; 6 scans/hour/business and 30/hour/IP; automatic weekly re-scans only when the whole scan fits, max 3 per run. The key never appears in any response (tested). |

Migration `0028`: `rank_grids`, `rank_grid_scans`, `rank_grid_points` (RLS enabled and forced).

### 2. Unified Google execution

One engine, no parallel path. `services/agent/content_exec.py` makes posts, photos and replies **actions** in the same `agent_actions` table with the same policy, approval record, platform emergency stop, claim, independent read-back and hash-chained history as profile edits. **It does not replace the existing publishers**: `agent/posts.publish`, `media.publish` and `reviews.publish_draft` still do the sending, and `content_exec.govern` decides whether they may run, claims the item, then verifies with a separate read.

| Path | Now goes through the engine | Policy |
|---|---|---|
| Scheduled and "publish now" posts, owner retry | yes (`api/v1/posts.py`, `publish_due_posts`) | `publish_content`, Level 2, person-only |
| Scheduled photos | yes (`publish_due_media`) | `upload_photo`, Level 2, person-only |
| Review replies (publish, auto-retry job) | yes (`api/v1/reviews.py`, `retry_failed_replies`) | `reply_publish`, Level 2, person-only |
| Owner's profile editor (`PATCH /gbp/{loc}/info`) | yes: `executor.owner_edit`, one action per field, judged against what Google holds **now** | by type: description L1, hours/categories L2, replacing a phone or website or changing the main category **L3, owner only** |
| Direct post create/edit/delete, direct photo add/delete | yes (`gbp.py::_governed`) | `publish_content`, `content_edit`, `content_delete`, `upload_photo` |
| Crash recovery | yes (`content_exec.recover_stuck`, in `autonomy_housekeeping`) | looks, never re-sends blindly; a photo is never re-sent without a person checking |

Rules: public content is `person_only` (Level 2 but **cannot be pre-authorised** and is never run by policy, even if autonomy is on and the raw data says "auto"); nothing is sent without a person's approval on the row; idempotency by content+approver+approval time (a double click sends once) and by the in-flight unique index; a business that is suspended or has asked to be deleted sends nothing; platform emergency stop holds all of it (nothing lost); failures of governed publishing do **not** count toward autonomy's automatic suspension. **"Executed" means the publisher succeeded AND a separate read of Google shows the item**; if the read does not show it, the **action** is `failed` ("Sent, but not confirmed") while the owner-facing row keeps Google's own answer, so the owner is not misled either way. Existing owner-facing statuses, messages and approval flows are unchanged (the full prior suite passes).

Migration `0028` adds `agent_actions.subject_type/subject_id`. The profile-field executor ignores such actions and vice versa.

### 3. Autonomy control centre (`AI > Autonomy`, owners and admins)

`GET /agent/control-centre` (one read) feeds `components/autonomy/*`: the master switch with a plain-language confirmation of what turning it on allows; **owner emergency stop** (`POST /agent/autonomy-settings/stop`: off + suspended + everything authorised by standing policy goes back to a person immediately; person-approved items untouched; resume is deliberate); **Needs you** (before/after, level, who decides, approve/reject with a required reason, Level 3 owner-only); **Activity** (confirmed changes); **Problems** (failed, blocked, stopped, expired, with the reason); a full **record** per action (authorisation, every step, history-integrity check); **Permissions** (per type: Ask me / Do it / Never; Level 3 and public content show as locked); **Usage** (AI drafts, AI spend and budget, tokens, map searches, ranking checks, daily autonomy limit, estimated Google spend when priced). Mobile: phone layout, no horizontal scroll, tabs scroll. Found and fixed by the browser test: the page used to flash to a skeleton after every action and lose the open tab and dialog.

Platform-admin emergency stop is unchanged (`PUT /admin/autonomy/emergency-stop`).

### 4. Live-validation preparation

`docs/LIVE_VALIDATION_RUNBOOK.md`: evidence tags, hard rules, preconditions, five stages, stop and rollback, and the **evidence log to fill in** with the exact criteria for "production-ready". New command `python -m app.cli autonomy-live-test` runs profile-change/restore and post/delete **through the governed engine** with the same three confirmations as `google-write-test` (dry run by default; env var, `--confirm-location`, `--confirm-title`), requires each step to be `executed` with a matching read-back **and an intact history chain**, and says `"mode": "mocked"` when run against a double. [MOCKED]

### 5. Data retention

`docs/DATA_RETENTION.md`. Findings fixed: the owner data export **omitted every autonomy table** (now included, without secrets); history had **no time limit** (now erased as whole records after 730 days, maps after 400, both configurable, `0` = keep; never touches live work or actions with follow-ups still due; counts-only audit entry); business deletion erasing history is now tested for every new table; a business that asked to be deleted no longer sends anything to Google during its grace period. Open decisions for a lawyer are listed in section 6 of that document.

### Migrations

`0028_geo_grid_unified_execution`: `rank_grids`, `rank_grid_scans`, `rank_grid_points` (RLS enabled and forced, app role SELECT/INSERT/UPDATE/DELETE); `agent_actions.subject_type`, `subject_id` + index; `DELETE` on `agent_actions` for the app role (retention) which still cannot remove history without the transaction-local erase flag. Applied from scratch by the test suite and to the isolated demo stack (head `0028`). **Not applied to the original running stack** (`flowqr-*`, still older).

### Exact files changed in Phase 1.5

Backend **added (10):** `alembic/versions/0028_geo_grid_unified_execution.py`, `app/models/rank_grid.py`, `app/services/rank_grid.py`, `app/api/v1/rank_grid.py`, `app/services/agent/content_exec.py`, `app/services/agent/retention.py`, tests `test_phase15_geogrid.py` (29), `test_phase15_governed.py` (31), `test_phase15_retention_and_live_prep.py` (14).
Backend **modified (17):** `app/api/v1/{autonomy_actions,gbp,posts,reviews}.py`, `app/cli.py`, `app/core/config.py`, `app/main.py`, `app/models/{__init__,autonomy}.py`, `app/ops_cli.py`, `app/services/account.py`, `app/services/agent/{autonomy_policy,executor}.py`, `app/workers/{celery_app,tasks}.py`, tests `test_gbp.py`, `test_phase0_post_publishing.py`, `test_phase1_policy.py` (changed on purpose: a profile edit is now one governed write per field; test posts carry the approval a real post has; the policy table lists the new types).
Frontend **added (6):** `app/(app)/ai/autonomy/page.tsx`, `components/autonomy/{Actions,ControlCentre,PermissionsUsage}.tsx`, `components/gbp/GeoGrid.tsx`, `lib/autonomy.ts`. **Modified (2):** `lib/nav.ts`, `app/(app)/gbp/rank/page.tsx`.
E2E: `e2e/autonomy-control-centre.js` (new), `e2e/agent-and-posts.js` (rail list, autonomy rule wording, cleanup SQL). Docs and config: `docs/DATA_RETENTION.md`, `docs/LIVE_VALIDATION_RUNBOOK.md`, this file, `docker-compose.yml`, `.env.example`.

New settings: `RANK_PLATFORM_MONTHLY_CAP`, `RANK_COST_PER_CALL_USD`, `AUTONOMY_HISTORY_RETENTION_DAYS`, `RANK_GRID_RETENTION_DAYS` (+ `rank_grid_plan_limits`, `rank_grid_*` in `config.py`). New jobs: `check_rank_grids` (6 h), `autonomy_retention` (daily).

### Tests executed

| Run | Result |
|---|---|
| Backend, Phase 1 end state | 1190 passed |
| Backend, after Phase 1.5 (full regression, fresh PostgreSQL 16, migrations from scratch) | **1267 passed, 0 failed** |
| Frontend `tsc --noEmit` | passes, no errors |
| Frontend production build (`next build` inside the Docker image) | passes (first attempt failed once on a transient Google Fonts fetch, unrelated; retry passed) |
| Browser: `e2e/autonomy-control-centre.js` (new) | **13/13**, including phone width and the honest failure when Google cannot be reached |
| Browser: `e2e/agent-and-posts.js` (existing) | **31/31** (two expectations updated, see files) |

New backend tests: **75** in three files (geo-grid 29, governed publishing and owner edits 31, retention, offboarding and live-test tooling 15), plus new parametrised policy cases. The first full run had one failure caused by my new tests leaving tracked search terms in the shared test database; fixed in the tests, rerun clean. Mocked vs live: every new test file's docstring says what is mocked; none is evidence about Google or Places.

Defects found by this phase's tests and fixed: a person's description was rejected for lack of "business knowledge" and for being under the agent's minimum length (owner-typed text is now held to Google's limits and the business's own prohibited claims only); the control centre lost its tab and open dialog after each action; the claim error for a busy field would have escaped; map copy said "square" for circles.

### Known limitations (Phase 1.5)

1. **Nothing is live-verified.** Whether Google's APIs accept, normalise and read back each field and post as the engine assumes is exactly what the runbook is for.
2. **Replies:** the read-back looks for the reply on the review in the first 3 pages (150 reviews) of Google's newest-first list; an older review would be reported "not confirmed" even if it worked.
3. **Photos** are confirmed by Google returning the media item; whether it is publicly visible is Google's processing and is reported as such, not as failure.
4. Geo-grid points are Google Places text searches biased to a circle; this is a measurement, not what every phone sees. Map defaults, plan numbers and the per-point radius are my choices and unvalidated against real Places behaviour and cost.
5. The control centre has no UI to *request* a profile change or create a post (those stay in Business info, Posts and Photos); it governs, shows and controls. The geo-grid has no address search for choosing custom points (latitude/longitude text input only).
6. The AI spend ledger survives business deletion (pseudonymous tenant id); see `DATA_RETENTION.md` section 6.
7. Hash chain proves internal consistency, not protection against the database owner rewriting the whole chain (external anchoring is described, not built).
8. A hand-written `DELETE` of a Google location that has autonomy history is refused by the database by design.
9. The original running stack and its database are untouched and still on old code and migrations.

### Acceptance criteria

| # | Criterion | Met? |
|---|---|---|
| 1 | Configurable geo-grid, multi-coordinate, history, significant-change detection, heat-map data, plan limits, cost controls | **Yes** (mocked + browser) |
| 2 | Posts, photos, replies and eligible profile edits under the central policy and execution engine, with idempotency, read-back and history, no parallel publisher | **Yes** (mocked) |
| 3 | Mobile-friendly control centre with all eight capabilities | **Yes** (browser) |
| 4 | Runbook, mocked vs live distinguished, no writes to customer profiles | **Yes** (prepared; not run) |
| 5 | Retention and offboarding reviewed, mechanism built, open legal decisions listed | **Yes** |
| 6 | Full backend regression, type-check, production build, browser tests | **Yes** |
| 7 | **Real Google execution and read-back demonstrated** | **NO. Blocked on an authorised test profile.** Until then FlowQR is not claimed production-ready. |

### Remaining blockers

1. An **authorised test Business Profile** and a person to run `LIVE_VALIDATION_RUNBOOK.md` and fill in its evidence log.
2. A **Places API key** (for stage 5) and real prices; AI prices and budgets (Phase 0 blocker).
3. **Rebuild and migrate the original stack** to get 0026 to 0028.
4. Decisions: map plan limits, retention periods, and the legal questions in `DATA_RETENTION.md`.

---

## Verdict (one paragraph)

FlowQR today is a **well-built, approval-gated assistant, not an autonomous agent.** The schedule runs by itself (collect → analyse → draft), reads are verified against real Google, and a real Places-based rank measurement has been run live. But: **nothing public is ever executed without a person's approval, by deliberate policy** (`autonomy.py`, `agent.py:472-475`); **rank data is not connected to any decision** (the agent, optimizer, plan and health score never read it); there is **no keyword discovery, no geo-grid, no intervention history and no post-change measurement**; and **no Google write (reply, post, photo, profile edit) has ever been executed live.** The "Collect → Analyse → Decide → Execute → Verify → Measure → Adapt" cycle is complete only for *Collect → Analyse → Draft*, and partial for *Verify*.

---

## 1. Fully implemented and verified

| # | Feature | Evidence |
|---|---|---|
| 1.1 | **Token encryption and refresh.** Fernet at rest for access and refresh tokens; refresh on expiry; `invalid_grant` marks the connection revoked. | [CODE] `core/security.py:59` `TokenCipher`; `services/google/tokens.py` `get_access_token`, `store_tokens`, `mark_revoked`. [LIVE] refresh with the business scope passed in the read-only smoke (`docs/LAUNCH_REPORT.md:17`, 2026-11-12). [TEST] `tests/test_google_contract.py`. |
| 1.2 | **Review detection (read).** Sync every 30 min, idempotent upsert on (location, Google review id), back-off on 429/5xx, REJECTED replies not shown as public. | [CODE] `services/google/sync.py` `sync_google_location`, `upsert_review`, `with_backoff`; beat `sync-due-google-locations` (`workers/celery_app.py:12`). [LIVE] DB: 964 reviews synced, both selected locations `last_sync_status=ok`, latest 2026-11-15 07:19 UTC. |
| 1.3 | **Scheduled collection and plan.** Beat → `flowqr.daily_agent` (every 30 min, per tenant after 06:00 local, once per day) → `snapshots.refresh` → `plan.run_plan`. Failure of one tenant is isolated and recorded. | [CODE] `workers/tasks.py:170-205`; `services/agent/plan.py:162-313`. [LIVE] DB: **15 `daily_plan` runs, all `ok`**, last 2026-11-14 06:45; 1 `refresh_google` run; 2 snapshots with profile and performance data, no snapshot errors. |
| 1.4 | **Live rank measurement (manual).** Official Places API (New) text search biased to a circle around the location; position among the first 20 results; "not found" is never a made-up number; failed checks stored as `error`; monthly cap 300 per tenant. | [CODE] `services/rank.py` `PlacesClient.search`, `check_keyword`; `models/rank.py`; `api/v1/rank.py` (`GET /gbp/{id}/rank`, `POST .../keywords`, `POST .../check`, `GET .../keywords/{kid}/history`). [LIVE] `RANK_PROVIDER=google_places`, key set; DB: **2 `rank_checks`, status `ok`, source `manual`** (rank 1 then 4 of 20 results, centre lat/lng stored). [TEST] `tests/test_rank_tracker.py` (15 tests, FakePlaces and MockTransport). |
| 1.5 | **Tenant isolation.** Postgres row-level security with default deny; policy on `tenant_id` or an explicit bypass setting; app connects as a non-superuser; rank tables are covered (migration `0023`). Workers use `system_session()` (bypass) with explicit tenant filters. | [CODE] `core/db.py:1-63`; `alembic/versions/0002_rls_and_grants.py`, `0023_local_rank_tracking.py`. [TEST] `test_auth_and_tenancy.py`, `test_rank_tracker.py::test_another_business_cannot_see_spend_or_delete`. |
| 1.6 | **Customer review acquisition rules.** Handoff only: FlowQR copies the customer's own final text and opens Google's own review page; FlowQR never submits a review. No rating gating. Request wording is checked at save for incentives or "only if happy". The "direct" provider is a documented non-implemented stub (`implemented = False`). | [CODE] `services/review_submit/base.py`, `handoff.py`, `google_direct.py`; `api/v1/request_templates.py:24-29`; `api/v1/review_public.py` (`/generate`, `/approve`, `/handoff`; `final_text` is the customer's confirmed wording); `services/ai/review_generate.py` (generated only from `<customer_answers>`, rules + fact-check, `NEEDS_MORE` when too vague). [TEST] `test_review_submit.py`, `test_review_rating.py`, `test_review_depth.py` (exist; not run). |
| 1.7 | **Verification discipline for what exists.** A reply is "published" only after Google returns it; a post only after Google returns a post name; a profile description only if Google's re-read shows it. Rejected replies are corrected back to `failed`. | [CODE] `services/reviews.py:publish_draft`, `sync.py:_reconcile_drafts`, `agent/plan.py:execute_profile_description` (442-446), `agent/posts.py:publish`. |

## 2. Implemented but not verified (live)

All of these have mocked tests but **no live Google execution on record**. `docs/LAUNCH_REPORT.md:18` says so explicitly ("Live Google, WRITES … NOT VERIFIED"). The database agrees: `reply_logs` is empty, no `scheduled_posts` row is `published`, no `scheduled_media` rows exist.

| # | Feature | Where | Notes |
|---|---|---|---|
| 2.1 | Publish a review reply (human-approved) | `services/reviews.py:publish_draft`; `PUT …/reviews/{id}/reply` in `provider.py:326`; `api/v1/reviews.py:216,235` | Strong design: `publishing` state committed **before** the Google call; reply call is an upsert (PUT) so a retry cannot duplicate. [TEST] `test_google_and_reviews.py`, `test_google_contract.py` (MockTransport). |
| 2.2 | Retry failed replies | `workers/tasks.py:63-110` `retry_failed_replies` (every 15 min) | Only human-approved drafts, transient errors only, `skip_locked`, max 4 attempts. [TEST] mocked. |
| 2.3 | Publish Google Posts (scheduled) | `agent/posts.py:publish`; `workers/tasks.py:133-167` (every 60 s); `provider.py:410` `create_post` | Retries with exponential back-off (5 min × 2ⁿ), `MAX_ATTEMPTS`, 10 edits/min/location limit. **See 5.1 for an idempotency gap.** [TEST] `test_google_business_agent.py`. |
| 2.4 | Photo upload and processing re-check | `services/media.py` (not read in depth); `workers/tasks.py:252-300`; `provider.py:461` | [TEST] mocked. |
| 2.5 | Write a profile description (approved) | `agent/plan.py:426-447` `execute_profile_description` → `provider.update_location` (`provider.py:352`) | Verifies by comparing Google's returned description. Safety check at approval (`api/v1/agent.py:293`). Smoke skipped `locations.patch validateOnly`. |
| 2.6 | Profile edits by the owner (hours, categories, phone, website) | `api/v1/gbp.py`; `provider.update_location` | Read-merge-write for categories and phone, as Google requires. [TEST] `test_gbp.py` (FakeGbpProvider). |
| 2.7 | **Scheduled rank re-check** | `workers/tasks.py:304-340` `check_ranks` (every 6 h); `rank.due_keywords` | Respects plan feature, cap, 40 calls per run. [TEST] `test_scheduled_task_checks_only_what_is_due`. **[LIVE] none**: no `source='auto'` row exists yet (both live checks were manual and still inside the 7-day window). |

## 3. Partially implemented

| # | Feature | What exists | What is missing |
|---|---|---|---|
| 3.1 | **Keyword discovery** | Google's own monthly *search-keyword impressions* are fetched (`provider.py:484`) into each snapshot (`snapshots.py:90-99`, top 25) and used as **hints** in description and post prompts (`optimizer.search_terms_line`). | Rank keywords are **manual only**, max 10 per location (`api/v1/rank.py:50-68`, `rank.MAX_KEYWORDS_PER_LOCATION`). Nothing proposes or adds keywords from Google's terms, categories, services or city. No competitor or suggestion source. |
| 3.2 | **Location-based ranking** | One centre (`GoogleLocation.lat/lng`, one is populated of two selected locations; `_ensure_center` fetches it via Places) and a 3 km radius bias. | **No geo-grid**: no multi-point measurement, no per-area rank. Single-point proxy only (the code and UI say so honestly: `rank.NOTE`). |
| 3.3 | **Historical ranking data** | `rank_checks` rows with rank, results seen, top-10 competitors (name, rating, review count), error, source, centre; history endpoint (limit ≤ 100); "change vs previous" in `keyword_out`. | No trend analysis, no alerts on drops, no comparison against competitors over time. |
| 3.4 | **Profile completeness analysis** | `agent/optimizer.py:30-136` (description length and quality problems, categories presence and count, services vs business brain, hours, holiday hours, phone, website, name rules, photo types, post freshness); `snapshots.profile_completeness`; `health.compute` (6 weighted components, visible formula, daily `HealthSnapshot`). | **Attributes are never read or written** (`get_location_details` readMask, `provider.py:338`, has no `attributes`). Category analysis only checks "has a primary / has extras", not fit against search terms or competitors. No Q&A, products/menu, service area. |
| 3.5 | **Ranking weaknesses → decisions** | The daily plan produces fact-based tasks: unanswered reviews, missing description or fields, stale photos or posts, repetitive posts, a ≥20 % fall in customer actions (`plan.py:84-291`). | **None of it uses rank data** (see 4.2). The only "SEO" decision is "improve the description". Tasks say plainly "this is a comparison, not a diagnosis" (good). |
| 3.6 | **New-review handling** | New reviews are detected within 30 min (1.2). Drafting: `plan.generate` creates reply tasks (≤5 per run, reviews ≤90 days old) and, **only if `auto_draft_replies` is on (default off; 0 of 5 tenants have it on)**, drafts them. | Drafting happens at most **once per day** (after 06:00 local), not when the review arrives. |
| 3.7 | **Contextual Gemini replies** | `services/ai/replies.py`: grounded in the business knowledge base, language detection, recent replies to avoid echo, sentiment-specific guidance, two-layer safety (`agent/safety.check_text`) + quality scoring, one guided retry, refusal if safety fails twice. [TEST] `test_ai_gemini.py`, `test_agent.py` (scripted model). | Single model for every task (no routing, see 3.9). |
| 3.8 | **Escalation of sensitive reviews** | `ai/safety.py:assess_review` keyword flags (medical, legal, threat, accusation; English, Hindi, Hinglish) set `requires_human_handling`; shown in the approval queue. | Keyword-regex only. `low_rating` is added **only when another flag already matched** (`safety.py:46-47`): a 1-star review with no flagged word is not escalated. Harmless today (a human approves everything) but must be fixed before any auto-reply exists. |
| 3.9 | **Gemini model routing and token usage** | Provider abstraction (`ai/base.py`); Gemini provider with retry, quota detection, running token totals (`gemini.py`, `usageMetadata`). One model from env (code default `gemini-3.5-flash`; the running container uses `gemini-3.5-flash-lite`), thinking level `minimal`. | **No routing** by task. **Token usage is not recorded for the agent's own drafts**: `plan.py:355,419`, `reviews.py:149,163`, `posts.py:213,217`, `tenants.py:118` call `log_generation` without `usage=`. **[LIVE] DB:** `post_draft` 3 rows and `reply_draft` 2 rows have 0 with token counts, while `review_generate` (10 ok rows) does. Live Gemini also hit failures: `review_generate` shows 9 errors (credits exhausted ×6, rate limited ×3). |
| 3.10 | **Cost limits** | Per-tenant monthly AI *call* quota by plan (`ai_usage.quota_exceeded`); per-tenant monthly rank cap (300); per-IP / per-tenant rate limits on public AI and checks; AI health pause on credit/quota errors (`ai/health.py`). | Quota counts **calls, not tokens or dollars**. Platform budget is **alert-only** and **unset** (`AI_MONTHLY_BUDGET_USD=0`, `services/ops.py:193-200`): no hard stop. |
| 3.11 | **Google OAuth and permissions** | Offline access, forced consent, scope check (`has_business_scope`), `ACCESS_TOKEN_SCOPE_INSUFFICIENT` mapping, quota-zero ≙ "awaiting approval" detection, per-connection `api_access` state. | Refresh has no row lock: concurrent refreshes are possible (low risk: Google refresh tokens do not rotate). |
| 3.12 | **Audit log and action verification** | `audit()` on reply approve and publish attempt, rank add/remove/check, description write, settings, posts; `ReplyLog` for each publish attempt; `AgentTaskEvent` state history. Verification-before-"done" is real (1.7). | No audit event for *scheduled* executions of rank (`check_ranks` writes rank rows only); no unified "what the agent changed and why" ledger (see 4.5). |

## 4. Missing

| # | Missing capability | Evidence it is absent |
|---|---|---|
| 4.1 | **Geo-grid ranking** | No grid code or model anywhere (`grep -i grid` in `app/` returns nothing). |
| 4.2 | **Rank → optimization link.** | `RankCheck` / `RankKeyword` are referenced only by `services/rank.py`, `api/v1/rank.py`, `workers/tasks.py:check_ranks` and `services/ops.py` (counts). Not by `agent/plan.py`, `optimizer.py`, `health.py`, `ai/intelligence.py`, or any prompt. |
| 4.3 | **Autonomous execution of any public action.** | `autonomy.py:5-8,87` (`auto_publish` is always `False`; "There is no switch that turns this off"); `api/v1/agent.py:472-475`; the only autosettings are `auto_draft_replies` and `auto_draft_posts`, both drafts only (`models/agent.py:45-47`). The only agent-driven Google write is the description, and only after approval. |
| 4.4 | **Profile writes for services and attributes.** | `update_location` supports `description, hours, primary_category, additional_categories, phone, website` only (`provider.py:352-389`); the optimizer says services "can't be edited through FlowQR yet" (`optimizer.py:85`). `autonomy.py:30` claims the agent can "read … attributes": the code does not (see 5.3). |
| 4.5 | **Intervention history and post-change measurement.** | No table linking an executed change to before/after state and to later rank or performance. `ai/outcomes.py` records generated-draft outcomes; I found no link to rank or Google performance. No re-measurement scheduled after an action. |
| 4.6 | **Adapt step.** | Nothing feeds observed results back into task priority or action choice. |
| 4.7 | **Verified live writes** | See section 2. |
| 4.8 | **Token- or dollar-based cost cap; per-task model routing.** | See 3.9 and 3.10. |
| 4.9 | **Drafting triggered by a newly synced review** (instead of once a day). | `sync.py` does not enqueue drafting. |

## 5. Broken, misleading or unsafe

> **Phase 0 status of these findings (details in the Phase 0 section above):** 5.1 post duplicate risk **fixed** [MOCKED]; 5.2 cost metering **fixed** (per-call ledger, budgets: off until you set limits and prices); 5.3 attributes claim **corrected** (`autonomy.py` now says attributes are not read); 5.4 shared starter pool **removed**; 5.5 low-rating escalation **fixed**; 5.6 operational, unchanged. Nothing below is verified against live Google writes.

| # | Finding | Where | Severity |
|---|---|---|---|
| 5.1 | **Google Posts can be published twice after a crash.** `publish()` calls `move(post, "publishing")` but does **not commit** before `provider.create_post`; the worker commits after. If the process dies after Google creates the post but before the commit, the row stays `scheduled` and is created again. `localPosts` create is a POST (not idempotent). There is **no recovery job for posts stuck in `publishing`** (replies have one). Photos "mirror" this design (`tasks.py:252`; `media.py` not read). The reply path does it correctly. | `services/agent/posts.py` `publish` (≈ line 245), `workers/tasks.py:133-167` | **High** before any autonomy; low probability today. |
| 5.2 | **Cost and usage are under-reported.** Agent and dashboard drafts store no token counts (3.9); quota counts calls; platform budget unset. | `ai_usage.py`, `plan.py`, `reviews.py`, `posts.py` | **Medium**. Cost limits are blind for the agent's own calls. |
| 5.3 | **Documentation claims more than the code does.** The autonomy matrix says the agent can read profile *attributes*; no code reads them. | `services/agent/autonomy.py:30` vs `provider.py:338` | **Medium** (honesty). |
| 5.4 | **Pre-filled review "starter" text policy risk.** `GET /r/{id}/starter` serves an AI-written, *pre-filled* opening to **every** customer before they type anything, from a small **shared pool per business** (`STARTER_POOL`). It is built from business details (no visit facts) and flagged editable with a note, but many customers can receive and post near-identical text. That conflicts with the "only from genuine customer-provided experience" requirement and risks Google's fake-engagement detection. | `api/v1/review_public.py:394-441` | **Medium–High** (policy). DB shows it has run live (2 ok, 2 rejected, 1 error). Decide before scale. |
| 5.5 | **Low-rating escalation gap** (3.8). | `ai/safety.py:46-47` | Low today; **blocker** for auto-reply. |
| 5.6 | **Live Gemini ran out of credits / was rate limited** (9 errors of 19 `review_generate` calls). Operational, but it means AI was unavailable for real customers at times. | DB `ai_generation_logs`; `ai/health.py` pause works | Operational. |

---

## 6. Safety and compliance: what checks out

* **Never claims rankings.** `rank.NOTE`, optimizer copy ("FlowQR will not claim any change in ranking"), health formula text. No invented rank: "not found" is stored as `NULL`, failures as `status='error'`. [CODE]+[LIVE]
* **No scraping.** Rank uses the official Places API (New); the key is sent as a header and never returned (`test_the_key_never_appears_in_any_response`). [CODE]/[TEST]
* **Replies:** prompt forbids invented facts, medical confirmation, incentives; output checked for invented prices/offers, health claims, prohibited phrases (`agent/safety.py`). [CODE]/[TEST]
* **Business name rule:** the optimizer never suggests adding keywords to the name. [CODE]
* **Reviews:** no gating, no incentives, no submission on a customer's behalf. [CODE]
* **Rate limiting:** 10 edits/min/location for posts and description (`gbp-edit:{id}`), photo upload 60/h, plan run 6/h, rank check 20/h/tenant. Replies have **no** equivalent per-location publish limit (only the approval step and 15-min retry job). [CODE]
* **Idempotency:** task dedupe via a partial unique index (`uq_agent_tasks_open_dedupe`), reply drafts idempotent via PUT upsert; posts are the exception (5.1). [CODE]

---

## 7. Prioritized implementation plan

Principles: extend the existing modules (`services/rank.py`, `agent/plan.py`, `agent/optimizer.py`, `AgentTask`, `AgentSettings`); add no parallel system. Every step keeps "never invent data, never claim rankings, verify against Google before reporting done."

### Phase 0: make the foundation trustworthy (before any autonomy)
> **Done in code on 2026-11-15** except step 1 (the live write test: tool ready, not yet run) and the live part of step 3 (prices and limits are not configured). See the Phase 0 section at the top. Step 4 (`autonomy.py` claim) was done too.

1. **Live-verify the Google writes** on an authorized profile with a throwaway test: one reply, one post (then delete), one `locations.patch` with `validateOnly` then a real harmless change, one photo. Record dated results in `docs/LAUNCH_REPORT.md`. *Gate: no auto-execution is enabled until this passes.*
2. **Fix post idempotency (5.1):** commit `publishing` before the Google call; add a recovery job like `retry_failed_replies`; before re-creating a stuck post, `list_posts` and match on summary and time. Same review for `media.py`.
3. **Fix metering (5.2):** pass `usage=provider.usage` at the five `log_generation` sites; add a token/dollar monthly cap per tenant to `quota_exceeded`; set `AI_MONTHLY_BUDGET_USD` and make the platform budget a hard stop.
4. **Correct `autonomy.py:30`** (remove "attributes", or implement the read in step 1 of Phase 1).
5. **Decide the starter-pool policy (5.4):** remove it, or generate per-customer from nothing but the business facts with a de-duplication check.

### Phase 1: autonomous Local SEO and ranking maintenance (highest priority)
1. **Keyword engine** (extend `rank.py`, add a `source` column to `rank_keywords`: `manual|google_terms|category|service|agent`): propose keywords from (a) Google search terms already in `GbpSnapshot.performance.keywords`, (b) the primary category + services in the business knowledge base + city, (c) the owner's list. Adding a tracked keyword spends only the tenant's own capped Places quota, so it is a safe **auto** action; cap at the existing 10 (raise per plan).
2. **Geo-grid** (new `grid_id`/`point` fields on `rank_checks` or a small `rank_grid` table): 3×3 or 5×5 points around the location, weekly, top N keywords, strict per-point cost accounting against `rank_monthly_check_cap`. Endpoint `GET /gbp/{id}/rank/grid`. Keep the "measured proxy, not what every person sees" note.
3. **Rank-aware analysis** (extend `optimizer.py`, new task kind `seo_fix` in `plan.generate`): deterministic rules with the rank rows as evidence: tracked keyword *not found* or down ≥ 3 places; competitors with more reviews/rating in `top_results`; category not matching the intent of a high-impression term; description lacks a genuinely applicable term; no recent post. Each task cites the `RankCheck` ids it used.
4. **Safe auto-execution tier** (`AgentSettings.autonomy_level` + a per-action allowlist, default **off**): execute without approval only when the value comes from **verified tenant facts** (business knowledge base or tenant record) and passes `check_text`, and only for *reversible, low-risk* fields (e.g. missing phone/website from the tenant record, holiday hours the owner entered, additional categories from an owner-approved list). Always: `validateOnly` first, `gbp-edit` rate limit, idempotency key = task id, audit entry, **re-read from Google and compare** before marking done. Everything else stays approval-gated.
5. **Intervention history** (new `agent_interventions` table: tenant, location, task, field, before/after from Google's re-read, executed_at, verified_at).
6. **Measure** (new Celery task `measure_interventions`): re-run the affected keywords at +7/+14/+28 days and store the *observed change* against the baseline and against untouched keywords. Report as "observed after", never "caused by", never as a guarantee.
7. **Adapt:** deterministic re-prioritisation from measured outcomes (deprioritise action types that show no change). No ML.

### Phase 2: autonomous review replies (needs a policy decision)
`autonomy.py` states auto-publish "cannot be switched off", so this phase **changes a stated product rule**: update that copy and the UI first.
1. Trigger drafting when sync finds a new review (not once a day).
2. Opt-in `auto_publish_replies`, low-risk only: rating ≥ 4 with text, no `assess_review` flag, passes `check_text`, quality score ≥ threshold, language match; daily cap, per-location publish rate limit, a short delay window with owner veto, kill switch, full audit.
3. **Fix 3.8 first:** any rating ≤ 3 or any flag escalates; add `low_rating` without needing another flag.
4. Escalation, AI failure and Google rejection all fall back to the existing approval queue. Reuse `publish_draft` (already idempotent).

### Phase 3: autonomous Google Posts
Auto-publish only posts built from approved knowledge-base offers with valid dates, within a daily cap, de-duplicated against recent posts, after Phase 0 fixes 1 and 2.

### Phase 4: AI routing, cost and monitoring
Route by task (cheap model for classification/flags, stronger for descriptions); record tokens everywhere; verify configured model IDs against the live API; alerts for refresh failures, quota, credit exhaustion and cost spikes (extend `services/ops.py` and `workers/monitor.py`).

### Test plan for "live autonomous execution" (do not claim before this passes)
For each autonomous action on an **authorized** profile: (1) dry run with `validateOnly` where available, (2) execute once, (3) re-read from Google and diff, (4) confirm the audit and intervention rows, (5) confirm no duplicate on a forced retry, (6) rank re-measure at +7 days.

## 8. What I did not do

* Did not run the pytest suite (it drops and rebuilds a `flowqr_test` schema; running it in the compose stack needs a test database and credentials I did not create).
* Did not execute any Google write, any Gemini call or any Places call.
* Did not read `services/media.py`, `workers/monitor.py`, `services/ops.py`, billing/entitlements, `ai/quality.py`, `ai/intelligence.py`, `auth_google.py` or the frontend beyond route names.
* Database queries were read-only aggregates against the local `flowqr` database; no review text, tokens or personal data were read.
