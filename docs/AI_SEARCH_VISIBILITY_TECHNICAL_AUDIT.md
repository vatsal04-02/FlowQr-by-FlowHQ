# AI Search Visibility: technical audit of what exists today

Audit date: 2026-11-17. Read-only. Audited from the working tree on branch `phase-2/commercial-readiness` (clean at the start of the audit; no application code, migration, dependency, environment variable, plan or infrastructure was changed to produce this document or its companion, [AI_SEARCH_VISIBILITY_FEASIBILITY.md](AI_SEARCH_VISIBILITY_FEASIBILITY.md)).

How to read the status words. They are used strictly:

| Status | Meaning |
|---|---|
| **Implemented** | Code exists, is wired into a route, job or page, and has automated tests in the repository. |
| **Implemented, not validated live** | As above, but only a mock transport or test double has ever exercised the external call. |
| **Partial** | Some of the capability exists; the missing part is named. |
| **Absent** | Searched for and not found. The search used is stated. |
| **Not verified** | Could not be established from the repository (typically production runtime state). Nothing is assumed. |

Reading code is not the same as running it. Where the repository's own documents record a live result (for example `docs/PRODUCTION_EXTERNAL_VALIDATION.md`), that is cited; nothing in this audit was run against production, Google, or any AI platform.

---

## 1. Summary

| Capability the AEO/GEO idea would build on | Status | Where |
|---|---|---|
| Local rank tracking by keyword (Google Places API (New)) | **Implemented**; live read-only calls recorded 2026-11-14; production key **blocked** (see §5) | `backend/app/services/rank.py`, `api/v1/rank.py` |
| Geo-grid rank maps | **Implemented**; switched **off** everywhere by default; one live 3x3 scan recorded | `services/rank_grid.py`, `api/v1/rank_grid.py`, `models/rank_grid.py` |
| Competitor observation and history | **Implemented** for up to 5 pinned competitors per location, from stored Places results; rating, review count, position | `services/competitors.py`, `models/competitors.py`, `api/v1/seo.py`, migration `0036` |
| Google Business Profile read/write | **Implemented, not validated live** for most calls; live post, photo and description round-trips recorded on a test profile | `services/google/provider.py`, `docs/GOOGLE_API_AUDIT.md`, `docs/PRODUCTION_EXTERNAL_VALIDATION.md` |
| Profile checklist ("health") | **Implemented** (deterministic rules, no AI) | `services/agent/optimizer.py`, `services/agent/health.py` |
| Business knowledge (what the AI may say) | **Implemented** | `models/agent.py` `BusinessKnowledge`, `services/agent/knowledge.py` |
| AI provider layer, metering, budgets | **Implemented**; Gemini benchmarked live, OpenAI-compatible endpoints supported | `services/ai/*`, `services/ai_usage.py` |
| External API usage ledger | **Implemented** | `services/usage.py`, `models/platform.py` (`ApiUsage`, `AICallLedger`) |
| Background jobs and scheduling | **Implemented** (Celery + beat) | `workers/celery_app.py`, `workers/tasks.py` |
| Plan features and allowances | **Implemented** | `services/plans.py`, `services/entitlements.py` |
| Approval workflow for changes to Google | **Implemented** | `services/agent/executor.py`, `autonomy_policy.py`, `content_exec.py` |
| Review theme extraction | **Implemented as a keyword heuristic**, not AI | `services/insights.py` |
| **Fetching or auditing a business's own website** | **Absent** | see §3 |
| **Structured data (Schema.org / JSON-LD) reading or generation** | **Absent** | see §3 |
| **Question bank / customer-question discovery** | **Absent** | see §3 |
| **Any client for ChatGPT, Google AI, Copilot or Perplexity** | **Absent** | see §3 |
| **Google Search Console or Bing Webmaster integration** | **Absent** | see §3 |
| **A way to publish to a customer's website** | **Absent** (FlowQR can write only to Google Business Profile) | see §3 |

The headline for the planning document: the Local SEO module is real and reusable for competitor data, scheduling, metering and approvals, but **everything specific to AEO and GEO (website crawling, structured data, question discovery, AI-platform querying) is new code**, not an extension of something that is nearly there.

---

## 2. Verified components, with paths

All paths are relative to the repository root.

### 2.1 Local rank tracking

| Item | Verified detail |
|---|---|
| Client | `backend/app/services/rank.py` `PlacesClient`. `POST https://places.googleapis.com/v1/places:searchText`, field mask `places.id,places.displayName,places.rating,places.userRatingCount`, `pageSize` 20, `languageCode` `"en"` (hard-coded), location bias circle of `rank_radius_m` (default 3000 m). Key is sent in a header only. |
| Meaning of a number | Position among the first 20 Places results for the text, biased to a circle. Not the order seen in Google Maps by a person. The code and UI say so (`NOTE`). |
| Storage | `rank_keywords`, `rank_checks` (`backend/app/models/rank.py`). `RankCheck.top_results` (JSONB) keeps the top 10 results as `{place_id, name, rating, reviews, is_you}` plus the business's own row if below 10. **No website URL, phone, categories or address of competitors is stored.** |
| Limits | 10 keywords per location (`RANK_MAX_KEYWORDS_PER_LOCATION`, provisional), 300 checks per business per month (`RANK_MONTHLY_CHECK_CAP`), `rank_platform_monthly_cap` (default 0 = no platform cap). |
| Schedule | `flowqr.check_ranks` every 6 hours; keywords re-checked after `RANK_AUTO_CHECK_DAYS` (7). |
| API | `backend/app/api/v1/rank.py`, `rank_grid.py`; read models in `api/v1/seo.py` (`/seo/overview`, competitors, profile). |
| Tests | `backend/tests/test_rank_tracker.py`, `test_seo_metrics.py`. |
| Live evidence | `docs/PRODUCTION_READINESS.md`: live read-only calls 2026-11-14 found a real location at position 1 for "physiotherapy". `docs/PRODUCTION_EXTERNAL_VALIDATION.md`: one real 3x3 grid scan, 18 requests (run twice by mistake), cost **unpriced**. |
| Not done | Places price not configured (`API_PRICES` empty); production Places key blocked (a key was pasted in chat and must be rotated); the number of billed requests per grid point is **not confirmed** against a Google Cloud bill. |

### 2.2 Competitors

| Item | Verified detail |
|---|---|
| Models | `PinnedCompetitor`, `CompetitorSnapshot` in `backend/app/models/competitors.py`. `PIN_LIMIT_PER_LOCATION = 5`. Snapshots are written only from the results of the business's own rank checks (`source` is constrained to `'rank_check'`), so pinning costs no extra Google call. |
| Service | `backend/app/services/competitors.py`: `pin` (only a place that has actually appeared in stored results can be pinned; back-fills up to 400 days of stored observations), `record_from_check`, `out` (series, review/rating change, how often the competitor outranks you). Absence in a check is "did not appear", never a rank. |
| UI | `frontend/src/app/(app)/seo/rankings`, `/seo/competitors`, `/seo` under the "GBP" destination in `frontend/src/lib/nav.ts`. |
| Tests | `backend/tests/test_competitors_pinned.py`. |
| Gap for AEO/GEO | No competitor **website**, services, categories or content is held anywhere. A website URL would need a billed Place Details call (see the feasibility document, §9). |

### 2.3 Google Business Profile

| Item | Verified detail |
|---|---|
| Provider | `backend/app/services/google/provider.py` (`HttpGoogleProvider`): accounts, locations, `get_location_details` (read mask includes profile, categories, hours, `serviceItems`), reviews, posts, media, performance, keyword impressions (`searchkeywords/impressions/monthly`). |
| Snapshot | `GbpSnapshot` (`models/agent.py`): `info`, `posts`, `media`, `performance` JSONB, one row per Google location, latest fetch only. `info` carries `title`, `description`, categories, `services`, `hours`, `special_hours`, `phone`, `website`, `open_status`. |
| Daily history | `gbp_metric_daily` (migration `0035`, `services/gbp_metrics.py`) for per-day Google performance metrics. |
| What GBP does **not** give | Position for a keyword, competitor data, or any AI-search visibility. `docs/LOCAL_SEO_ARCHITECTURE_PROPOSAL.md` §4.1 records this and the code never claims otherwise. |
| Live status | `docs/GOOGLE_API_AUDIT.md` (2026-11-10): every Business Profile API returned 403 `SERVICE_DISABLED`; later `docs/PRODUCTION_EXTERNAL_VALIDATION.md` records on a test profile: connect, profile read, post create/read/delete, photo upload/delete, description change/restore all **PASS** (2026-11-15). Review reply, governed approval path, autonomy and review sync on the test profile **NOT TESTED**. The production OAuth app is in **Testing** mode (listed test users only; refresh tokens expire after 7 days): **BLOCKED** for real customers until Google verifies it. |
| Not editable through FlowQR | Services list ("services can't be edited through FlowQR yet", `optimizer.py`). Q&A API was discontinued by Google (2025-11-03) and is not used. |

### 2.4 Profile checks and knowledge

| Item | Verified detail |
|---|---|
| Checklist | `services/agent/optimizer.py` `checks()`: description, categories, services, hours, special hours, phone, **website (presence only)**, name-stuffing, photos, posts, search visibility, freshness. Deterministic, "unknown" is never guessed as missing. It never suggests keywords in the business name. |
| Health score | `services/agent/health.py`, `HealthSnapshot` daily history. Components with no data are excluded, not zero. |
| Knowledge | `BusinessKnowledge` (`models/agent.py`): `offers` (verified prices), `hours` (text), `faqs` (`[{q, a}]`), `brand_voice`, `approved_claims`, `prohibited_claims`, `audience`, `safety_profile` (`general` or `health`). Description and services live in `tenants.review_context` (JSONB). `services/agent/knowledge.py` `context()` and `render()` build the grounding block placed in every prompt; the rule "if a fact is not listed, do not state it" is in the block. Health businesses get prohibited-claim defaults and patient-confidentiality rules (`services/agent/safety.py`). |
| FAQs already exist | Owners can store up to ~15 FAQs used in prompts (`render()` takes the first 15). They are **not** published anywhere and are not checked against a website. |
| Tests | `test_ai_intelligence.py`, `test_ai_quality.py`, `test_ai_regression.py`. |

### 2.5 AI provider layer, metering, budgets

| Item | Verified detail |
|---|---|
| Providers | `services/ai/base.py` `get_provider()`: `gemini` (`gemini.py`, `generateContent`, JSON mode), `openrouter`, and `openai_compat` (any OpenAI-style `/chat/completions`). Plain text in, text out via `generate(system, user, max_tokens, temperature)`; `services/ai/structured.py` `generate_json` adds tolerant JSON parsing. |
| What it cannot do today | **No web-search tools, no citations, no grounding parameters.** The providers send a system prompt and a user prompt and read the first choice's text. Querying an AI platform *with its search tool* would be a new client, not a configuration change. |
| Default model | `GEMINI_MODEL` default `gemini-3.5-flash` in `core/config.py`; the benchmark (`docs/ai-eval/RESULTS.md`) ran `gemini-3.5-flash-lite` and recommended no model change. Which model production actually runs is **not verified** here. |
| Metering | `services/ai_usage.py` `metered(provider, db, tenant_id, kind)`: every call is checked against the business and platform monthly budgets **before** it is made and written to `ai_call_ledger` (own transaction; tokens, estimated USD, ok/error/blocked, latency). Per-plan counted allowances exist only for review generation and AI replies (`services/plans.py` `quota_field_for`); every other task kind is limited by its plan feature and the USD budgets. |
| Fail-closed pricing | With `AI_PRICE_IN_PER_MTOK`/`AI_PRICE_OUT_PER_MTOK` unset (they default to 0), cost is "unpriced" and the **USD budgets refuse calls** (`docs/COMMERCIAL_LIMITS_AND_COSTS.md` §3). Whether production has these set is **not verified**. |
| Quality | Deterministic validators (`services/ai/quality.py`): stock phrases, wrong language/script, keyword stuffing, repetition, invented numbers. A benchmark harness exists (`app/ai_eval`, `python -m app.cli ai-eval`); no human has rated the outputs yet (`docs/AI_INTELLIGENCE.md` §5). |
| Language | English, Hindi, Hinglish for replies, posts, descriptions (`services/ai/language.py`, `craft.py`). Customer review drafts: English and Hindi only. |

### 2.6 Usage ledger for external APIs

`services/usage.py` and `ApiUsage` (`models/platform.py`): one row per billed external request, `provider`, `operation`, `feature`, `units`, `status` (`ok`/`error`/`refused`), `est_cost_usd` **only when a price is configured** (`API_PRICES`, `settings.api_prices`), idempotency key, append-only for the application, no foreign key to tenants. Currently used for Places and Google Business Profile (`PLACES`, `GBP` constants). The pattern fits a new provider with no schema change other than new `provider` strings.

### 2.7 Background jobs

`backend/app/workers/celery_app.py` beat schedule (all verified present): `sync-due-google-locations`, `billing-housekeeping`, `retry-failed-replies`, `auto-replies`, `publish-due-posts`, `publish-due-media`, `recover-stuck-posts`, `autonomy-execute`/`-housekeeping`/`-followups`/`-retention`/`-scan` (6 h), `daily-agent` (30 min), `purge-deleted-accounts`, `purge-review-sessions`, `check-ranks` (6 h), `check-rank-grids` (6 h), `heartbeat`, `ops-watch` (15 min), `notify-by-email`. Tasks in `workers/tasks.py` (503 lines). Celery config: `task_acks_late`, `worker_prefetch_multiplier=1`, default retry delay 60 s; `sync_location` uses exponential back-off with jitter and `max_retries=3`. Redis is the broker; there is no results backend (`backend=None`).

### 2.8 Plans and entitlements

| Item | Verified detail |
|---|---|
| Features | `services/plans.py`: `CORE` (review sync, AI replies, review generation, QR campaigns, review analytics, GBP connection, GBP info), `GROWTH_ADD` (gbp_posts, gbp_media, gbp_performance, insights, local_seo, keyword_tracking, geo_ranking, autonomy, ai_posts, profile_optimizer, growth_agent), `PRO_ADD` (multi_location). A feature is a string key checked through `entitlements.require_feature`. |
| Plans in this tree | Codes `starter` ₹499, `growth` ₹799, `pro` ₹1,499, seeded from migration `0029`. The names the owner now uses (Launch, Growth, Scale) are applied by migration `0037_cashfree_billing` on the unmerged branch `billing/cashfree-phase1`, which is not in this working tree. This audit and the companion document use **Launch (`starter`), Growth, Scale (`pro`)** and say so where it matters. |
| Locations and seats | Growth: 1 location, 10 seats; Pro: 10 locations, 50 seats (both **provisional**, `docs/COMMERCIAL_LIMITS_AND_COSTS.md`). |
| Geo allowances | `limits.geo` (maps per location, points per map, points per month) is `None` for every plan until an admin sets it; a half-set plan stays off. |
| Adding an AI feature | Needs a new key in `ALL_FEATURES`/`FEATURE_LABELS`, the plan rows in `billing_plans.features` (a data change: new migration or the admin screen), and a counted allowance would need a new column or JSON field in `billing_plans.limits` (the existing `limits` JSONB already carries `geo`). |

### 2.9 Approval workflow

`services/agent/executor.py` (612 lines), `autonomy_policy.py`, `content_exec.py`, `models/autonomy.py` (`AgentAction`, `AgentActionApproval`, append-only hash-chained `AgentInterventionEvent`). Proposals state problem, reason, evidence and a preview; a person approves or an owner-configured policy allows a low-risk change; `AUTONOMY_EMERGENCY_STOP` holds every Google write platform-wide (`docs/PRODUCTION_DEPLOYMENT_REPORT.md` requires it until the write paths are validated; the project's own deployment notes record it as `true` in production, which this audit did not re-check on the server). `services/agent/seo_engine.py` proposes a description change from measured weak search terms and only mentions terms the business verifiably is or does. **This is the template for "owner approval before publishing"**, but every executor target today is a Google Business Profile write.

### 2.10 Tenant isolation

Row-level security on tenant tables: `ENABLE` + `FORCE ROW LEVEL SECURITY`, policy `current_setting('app.bypass_rls', true) = 'on' OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid` (pattern in migration `0036_pinned_competitors.py`, original in `0002`). The API sets the context per request; workers use a bypass session and filter by tenant explicitly. Account export (`services/account.py` `TABLES`) and account deletion (`purge_deleted_accounts`) iterate a fixed model list, so **a new tenant table must be added to the export list or it will be silently missing from a customer's data export** (the retention review already found this once, `docs/DATA_RETENTION.md` finding 1).

### 2.11 Frontend

Navigation: single source `frontend/src/lib/nav.ts`; destinations Home, Reviews, **GBP** (`/seo`: Overview, Rankings, Performance, Profile), Growth, Locations, AI Assistant, Tasks & Approvals, Activity, Settings, Billing; bottom bar on phones (Home, Reviews, GBP, Growth, More). Old URLs stay valid through `frontend/src/lib/legacy-routes.mjs`. Design rules in `docs/DESIGN.md` (orange accent `#EA542E`, 16px data cards, no glass, no glow, status never by colour alone, phone-first). SEO components in `frontend/src/components/seo` and `components/gbp`.

---

## 3. Searched for and absent

| Capability | Search performed | Result |
|---|---|---|
| Website fetching, crawling, HTML parsing | Case-insensitive grep over `backend/app`, `requirements.txt`, `pyproject.toml` for `website_audit`, `audit_website`, `crawl`, `beautifulsoup`, `bs4`, `lxml`, `robots.txt`, `sitemap`, `llms.txt` | No match except a bot user-agent regex in `services/cards.py` (filters scans by crawlers). `requirements.txt` has `httpx` but **no HTML parser**. |
| Structured data | Same grep for `schema.org`, `json-ld`, `jsonld`, `FAQPage`, `LocalBusiness` | No match in the backend. (`frontend/src/app/robots.ts` and `sitemap.ts` belong to FlowQR's own marketing site, not a customer-site tool.) |
| Website field | Grep `website` | Stored: `tenants.website` (nullable string, 300), Google profile `website`, Places `websiteUri` used for onboarding suggestions (`services/places_suggest.py`). **Only presence is checked** (`optimizer.py:103`). The site is never requested. |
| Question database | Grep and model review | `BusinessKnowledge.faqs` (owner-entered Q&A) and `RankKeyword` (tracked search terms) exist; neither is a question bank. |
| AI-platform clients | Provider layer read in full (§2.5) | None. No OpenAI, Perplexity, Bing or Gemini-with-search code. |
| Search Console / Bing Webmaster | Grep over `backend/app/**/*.py` for `searchconsole`, `search_console`, `webmasters`, `bing` | No integration. The only matches are the English word "describing" in review-writing prompts. The Google OAuth scope requested is `business.manage` plus identity (`docs/GOOGLE_API_AUDIT.md`). Search Console would need a **new scope and a new consent**. |
| Publishing to a website | Executor targets read | Only Google Business Profile (profile fields, posts, media, review replies). No CMS, FTP, WordPress or tag-manager integration. |
| SSRF-hardened outbound fetcher | Read `services/ai/openrouter.py`, `rank.py`, `google/provider.py` | Outbound HTTP exists but only to fixed provider hosts. **There is no code that fetches a user-supplied URL**, so no SSRF protection exists yet. This must be designed, not assumed (feasibility §12). |

---

## 4. Data model reference (existing tables relevant to the proposal)

| Table | Model file | Holds | Reuse |
|---|---|---|---|
| `tenants` | `models/tenancy.py` | name, category, website, phone, address, language, `review_context` (description, services, languages), `ai_monthly_budget_usd`, `places_monthly_cap` | Source for business facts |
| `google_locations` | `models/business.py` | Google location, `place_id`, lat/lng, selected | Location anchor for any per-location AEO/GEO data |
| `business_knowledge` | `models/agent.py` | offers, hours, faqs, claims, voice, audience, safety profile | **Extend rather than duplicate** |
| `gbp_snapshots` | `models/agent.py` | Latest Google profile, posts, media, performance | Consistency checks |
| `rank_keywords`, `rank_checks` | `models/rank.py` | Tracked terms; per-check top-10 results | Source of "who appears" and of a seed question list |
| `pinned_competitors`, `competitor_snapshots` | `models/competitors.py` | Up to 5 followed competitors; dated rating/review/position | Competitor roster for GEO comparisons |
| `reviews` | `models/business.py` | Synced Google reviews | Review-theme input (heuristic today) |
| `agent_tasks`, `agent_actions` (+approvals, events) | `models/agent.py`, `models/autonomy.py` | To-do cards; governed changes with approval and tamper-evident history | Recommendations and approvals |
| `ai_call_ledger`, `ai_generation_logs` | `models/platform.py` | Per-call AI cost; generation outcomes | AI cost for new tasks (new `kind`) |
| `api_usage_ledger` (`ApiUsage`) | `models/platform.py` | Billed external requests | Cost of AI-platform queries (new `provider` values) |
| `billing_plans`, `subscriptions` | `models/billing.py` (plans), `models/platform.py` (subscriptions) | Plan features and limits copied per subscription | Entitlements |
| `ai_outputs` | `models/ai_quality.py` | Owner-facing AI text and the owner's decision | Acceptance rate for new content types |

Alembic head in this tree is `0036_pinned_competitors`; the Cashfree branch adds `0037_cashfree_billing`. **Any new migration number depends on merge order** and must be chosen against the real head at that time (the project already hit a renumbering problem, `docs/MIGRATION_RECONCILIATION.md`).

---

## 5. Operational status that is **not** verified here

I did not connect to the VPS, the production database or any Google or AI account. The following are therefore unknown from this audit and must be checked before any plan relies on them:

1. Whether production has a working Places key and `RANK_PROVIDER=google_places` (docs say the original key was exposed and a restricted one was to be created; a later document records one set up on the VPS on 2026-11-16 for onboarding suggestions).
2. Whether production runs Gemini and which model, and whether `AI_PRICE_*` and the USD budgets are set (unset prices make budgets refuse calls).
3. Whether any real customer has a Google connection (the OAuth app is in Testing mode).
4. How many tenants have a `website` value. **This number decides the size of the AEO website audit audience** and is one query away: `SELECT count(*) FILTER (WHERE website IS NOT NULL AND website <> ''), count(*) FROM tenants`. It has not been run.
5. Whether Cashfree billing is live (the project memory records it deployed on 2026-11-16 then switched off; the `billing/cashfree-phase1` branch is unmerged in this tree).

---

## 6. Reusable vs new, in one table

| Need | Reuse as is | Extend | New |
|---|---|---|---|
| Per-tenant, per-location data and RLS | pattern, helpers | | new tables |
| Business facts | `business_knowledge`, `tenants.review_context` | add fields (website pages, credentials, service-area, languages spoken) | |
| Scheduling | Celery beat + worker | new tasks | |
| AI text generation, language, safety | `services/ai/*`, `agent/knowledge.py` | new task kinds (`aeo_*`) in metering | prompts |
| AI cost control | `ai_usage.metered`, `ApiUsage` | new `provider`/`kind` strings, new counted allowance | |
| Approval and audit | `AgentAction`, `executor`, `audit.py` | new action types | publishing target that is **not** Google |
| Competitor roster and history | `competitors.py`, `rank_checks.top_results` | store competitor website URL (needs Place Details) | competitor content snapshots |
| Entitlements | `plans.py`, `entitlements.py` | new feature keys and a counted allowance | |
| UI shell, nav, tokens | `nav.ts`, `DESIGN.md`, `components/seo` | new destination or tab | pages |
| Website fetch, parse, extract | | | **all of it** (including SSRF protection) |
| Schema.org read/generate/validate | | | **all of it** |
| AI-platform query clients | `httpx` usage pattern, error taxonomy in `ai/base.py` | | **all of it** (OpenAI Responses, Perplexity, and so on) |
| Mention and citation extraction | | | **all of it** |
| Question discovery and bank | | | **all of it** |
