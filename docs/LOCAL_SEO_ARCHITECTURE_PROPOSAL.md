# FlowQR: Local SEO, Reputation and Performance redesign. Phase 1: audit and architecture proposal

Status: **proposal, awaiting approval.** No application code, migration, deployment or production setting was changed to produce this document.
Audit date: 2026-11-16. Audited from the working tree on branch `phase-2/commercial-readiness` (`0138e15` plus uncommitted dashboard chart work).

Evidence labels used throughout:

| Label | Meaning |
|---|---|
| **Google, official** | A Google API the code already calls (or documents calling) with the owner's own OAuth token. |
| **Google Places, measured** | Google Places API (New), called with FlowHQ's server key. A repeatable measurement, not what every person sees in Maps. |
| **FlowQR, counted** | Rows FlowQR itself recorded (card scans, landing visits, clicks to Google, review sessions). |
| **FlowQR, calculated** | Derived from the above by a stated formula (health score, sentiment heuristic). Shown with the formula. |
| **Third party** | A paid external data provider. None is in use today. |
| **Unavailable** | No verified source. The UI says so; nothing is estimated. |

Two honesty caveats that apply to the whole proposal:

1. **No Business Profile call has ever succeeded against live Google from this code** (`docs/GOOGLE_API_AUDIT.md`, 2026-11-10: all four APIs returned 403 `SERVICE_DISABLED`; the OAuth token refresh is the only live-verified call). The production Business Profile OAuth client was configured later in this project, but the Business Profile API access application and a verified location are still the owner's to complete. Every "Google, official" metric below is therefore *coded and tested against a mock transport, not confirmed live*. Until that changes, those cards must render "Google isn't sharing this yet", never zeros.
2. Of the Google APIs, only the **Places API** has a working key: it was set up on the VPS on 2026-11-16 for onboarding suggestions and exercised locally. Rank tracking uses the same key, but this audit did not run a live rank check, so treat rank numbers as "coded and tested, not yet observed in production".

---

## 1. What exists today (inventory)

### 1.1 Frontend: 55 customer pages, 12 admin pages

Navigation is defined in one file, [`frontend/src/lib/nav.ts`](../frontend/src/lib/nav.ts): four sections (top pill nav) with a left rail per section, a command palette, per-item sub-tabs, role hiding (`only`), and a permanent-redirect table [`legacy-routes.mjs`](../frontend/src/lib/legacy-routes.mjs) that already keeps ~35 old URLs alive. **That redirect layer is what makes the restructure low-risk**: moving a page means adding one line, not breaking bookmarks.

| Section | Pages (route, what it really does) | State |
|---|---|---|
| **Overview** | `/overview` Summary (rating, key tiles, review trend, goal, funnel, growth chart, topics, attention list, health strip) · `/overview/reviews` (ratings, volume, reply speed) · `/overview/performance` ("Search & Maps": Google views/actions, monthly trend, keyword impressions, compare locations + CSV) · `/overview/funnel` + `/overview/campaigns` (card scans → landing → Google click) · `/overview/locations` (branch comparison) · `/overview/reports` (PDF + CSV) | Built. Google parts mocked-only. |
| **GBP Manager** | `/gbp` hub · `/gbp/reviews` (+`[id]`) inbox, drafts, approve, publish · `/gbp/info` + `/gbp/hours` profile editor · `/gbp/posts` (draft → approval → scheduled → publish) · `/gbp/photos` (URL add, scheduler) · `/gbp/rank` **Local ranking + Geo-grid (already built)** · `/gbp/locations` connection/sync · `/gbp/cards` (+`[id]`, `designs`) · `/gbp/campaigns` (+`[id]`, `landing`, `guide`) · `/gbp/inbox/*` (5 pages) | Built, except **Inbox: 5 pages are 12-line "Setup required" placeholders (WhatsApp)**. |
| **AI** | `/ai` Reply assistant · `/ai/today` · `/ai/tasks` · `/ai/approvals` · `/ai/activity` · `/ai/automations` · `/ai/autonomy` (owner/admin) · `/ai/voice` · `/ai/assistant` (+`settings`: the *customer-facing* review-writing assistant) · `/ai/insights` · `/ai/studio` (AI Creator works) + `calendar`, `brand`, `assets`, `social` · `/ai/brain` · `/ai/usage` | Mostly built. **Studio calendar/brand/assets/social are 12-line placeholders** (Meta). |
| **Settings** | Business, Team, Plan & billing (+payments), Account, Connections, Appearance, Notifications, Audit log | Built. |

Placeholders hidden behind honest "Setup required" screens (not fake data): `gbp/inbox` ×5 (WhatsApp), `ai/studio/{calendar,brand,assets,social}` (Meta).

### 1.2 Backend: FastAPI modular monolith

Routers (`backend/app/api/v1`): `analytics` (overview, insights) · `reports` (summary, PDF, CSV) · `gbp` (info, categories, posts, media, **keywords**, **performance**) · `rank` + `rank_grid` · `reviews` · `review_growth` / `review_public` · `agent` + `autonomy_actions` · `locations` · `cards` / `qr` · `billing` · `tenants` · `places` · admin/ops/auth/etc.
Models: `GbpSnapshot`, `HealthSnapshot`, `RankKeyword`, `RankCheck`, `RankGrid`/`RankGridScan`/`RankGridPoint`, `Review`, `ReplyDraft`, `AgentTask`, `ScanEvent`, `ReviewSession`/`ReviewEvent`, and the multi-tenant base (RLS on every tenant table; `ctx.scope(...)` enforces location-level staff access).
Celery beat (every task already exists): review sync, `check-ranks` (6 h), `check-rank-grids` (6 h), `daily-agent`, `publish-due-posts/media`, `notify-by-email`, autonomy jobs, ops watch.

### 1.3 Findings that change the plan

The brief asks for modules that are largely **already built**. The proposal therefore re-organises and completes; it does not rebuild.

| Brief item | What the audit found |
|---|---|
| Local Rank Tracking, keyword management, geo-grid, history | **Built**: `services/rank.py`, `rank_grid.py`, `components/gbp/{LocalRank,GeoGrid}.tsx`. Official Places API (New), never scraped. Plan allowance gating (fail closed), monthly caps, scan cost estimate, heatmap, history, SoLV/ARP comparison thresholds. |
| Competitor profiles, ratings, review counts | **Partly present, no UI.** Every `RankCheck` stores the top 10 Places results with `name`, `rating`, `userRatingCount`, `is_you` (`RankCheck.top_results`). Rating and review-count *growth* for a competitor can be derived from repeated checks at **zero extra API cost**. No page shows it. |
| Search terms that showed the profile | **Built in the backend and Performance page**: `GET /gbp/{id}/keywords` (monthly search-keyword impressions, Google official). Not a rank. |
| Google Profile Health | **Built as a score**: `services/agent/health.py` (7 weighted components, visible formula, components with no data are excluded, never counted as zero) + `HealthSnapshot` daily history + `profile_completeness()` (description, hours, phone, website, category). Displayed only as a strip on Overview and in the AI daily plan. No dedicated page. Service-item and secondary-category checks are not yet scored although `serviceItems` and `additionalCategories` are already fetched. |
| Review sentiment / themes / complaint categories | **Built, but a heuristic**: `services/insights.py` is a transparent keyword + rating rule set (EN/Hinglish/Hindi), 10 topic buckets, computed on the fly (not stored). It is a signal, not AI classification. Page: `/ai/insights`. |
| Response time | Built (`avg_response_hours`, reply rate, previous-period comparison). |
| Performance metrics history | **Gap.** `GbpSnapshot.performance` holds only the *latest* fetch (56 days). There is no per-day table, so history beyond what Google returns on request cannot be kept or shown if Google is unreachable. |
| Exportable reports | PDF + CSV exist for reviews/posts/tasks/AI; Performance has a CSV for location comparison only. No rank/SEO export. |
| Location filter | `LocationScope` provider exists; Overview uses it; Performance uses its own `GbpFrame` selector. Inconsistent. |
| Conversion events | Measurable and already separated: scans, landing views, clicks to Google, synced reviews. A click or session is never counted as a review (enforced and tested). |

---

## 2. Proposed information architecture

The brief's six groups map cleanly onto what exists. Recommendation: **keep the existing top pill + left-rail mechanism** and grow it from four sections to six (Workspace, Reputation, Local SEO, Analytics, AI, Settings). Six pills fit on desktop; on phones the section row already scrolls.

```
WORKSPACE            Overview                      /overview             (redesigned, §3)
                     Locations                     /gbp/locations  + /overview/locations merged (§2.2)
REPUTATION           Reviews & Inbox               /gbp/reviews          (+ "Reply assistant" /ai as the "Drafts" tab)
                     Review Collection             /gbp/cards, /gbp/cards/designs, /ai/assistant (customer-facing writer)
                     Campaigns                     /gbp/campaigns (+landing, guide)
                     Review insights   (new tab)   /ai/insights moves here
LOCAL SEO            SEO Overview      (NEW)       /seo
                     Local Rank Tracking           /gbp/rank → /seo/rank  (existing components)
                     Google Profile Health (NEW)   /seo/profile    (+ links to Business info, Hours, Posts, Photos editors)
                     Competitor Analysis (NEW)     /seo/competitors
ANALYTICS            Performance                   /overview/performance → /analytics/performance
                     Reports                       /overview/reports → /analytics/reports
                     (Customer funnel)             /overview/funnel → /analytics/funnel   (kept: it is the card-to-Google funnel)
AI WORKSPACE         AI Growth Assistant           /ai/today  (tabs: Today · Tasks & Approvals · Activity)
                     Content Studio                /ai/studio (AI Creator only; rest hidden, §5)
SETTINGS             Account · Team · Billing · Connections · Notifications · Audit    (existing)
                     + "Business", "AI & automation" (Brand voice, Business brain, Autonomy, Usage)
```

### 2.1 Mapping every existing page

Nothing is deleted. "Redirect" means the old URL keeps working through `legacy-routes.mjs`.

| Today | Proposed home | Action |
|---|---|---|
| `/overview` | Workspace › Overview | Redesign |
| `/overview/reviews` | Analytics › Performance (Reviews tab) | Merge as a tab; redirect |
| `/overview/performance` | Analytics › Performance | Keep, extend, relabel "Search & Maps" tab |
| `/overview/funnel`, `/overview/campaigns` | Analytics › Performance › Cards & campaigns tab | Keep content; redirect |
| `/overview/locations` | Workspace › Locations (comparison tab) | Merge with `/gbp/locations` |
| `/overview/reports` | Analytics › Reports | Move |
| `/gbp` hub | removed from nav; replaced by Overview + SEO Overview | Redirect to `/overview`. **Needs approval** (it is a working summary page) |
| `/gbp/reviews` (+`[id]`) | Reputation › Reviews & Inbox | Rename |
| `/ai` Reply assistant | Reviews & Inbox › "Drafts" tab | Merge (same data, second entry point today) |
| `/gbp/info`, `/gbp/hours`, `/gbp/posts`, `/gbp/photos` | Local SEO › Google Profile Health (linked editors) | Keep pages; reach them from Profile Health |
| `/gbp/rank` | Local SEO › Local Rank Tracking | Move; components unchanged |
| `/gbp/locations` | Workspace › Locations | Move |
| `/gbp/cards`, `/gbp/cards/designs` | Reputation › Review Collection | Move |
| `/gbp/campaigns/*` | Reputation › Campaigns | Move |
| `/gbp/inbox/*` (5, WhatsApp) | **Hidden** | Remove from nav until WhatsApp exists; keep routes (§5) |
| `/ai/today`, `/ai/tasks`, `/ai/approvals`, `/ai/activity`, `/ai/automations` | AI Growth Assistant tabs | Merge into 3 tabs |
| `/ai/autonomy`, `/ai/voice`, `/ai/brain`, `/ai/usage` | Settings › AI & automation | Move (configuration, not daily work) |
| `/ai/assistant` (+settings) | Reputation › Review Collection | Move (it is what customers see on a card) |
| `/ai/insights` | Reputation › Review insights | Move |
| `/ai/studio` AI Creator | AI Workspace › Content Studio | Keep |
| `/ai/studio/{calendar,brand,assets,social}` | **Hidden** | Placeholders (§5) |
| `/settings/*` | Settings | Add "AI & automation"; otherwise unchanged |

Duplicate destinations this removes: Reviews (3 places: Overview › Reviews, GBP › Reviews, AI › Reply assistant), Locations (2), "Overview" (2 meanings), Insights vs Overview topics, Campaigns (Overview + GBP).

### 2.2 Decisions I need from you (also repeated in §8)

1. Merge `/gbp` hub into Overview and drop it from navigation?
2. Move Brand voice / Business brain / Autonomy / Usage into Settings?
3. Hide the 9 placeholder pages (WhatsApp ×5, Studio ×4) from navigation?
4. Fold `/overview/reviews` into Performance as a tab?

---

## 3. Overview: every metric with its real source

Design: compact (14–18px radius cards), one date filter (7/30/90/custom) and one location filter shared across the page, previous-period delta on each number, one status line per card ("Google · updated 3 h ago" / "Not shared by Google yet").

| Metric | Source (label) | Endpoint / table | Permission | Refresh | If unavailable |
|---|---|---|---|---|---|
| Overall Google rating | Google, official (synced reviews) | `GET /analytics/overview` → `reviews.average_rating_all_time` (table `reviews`) | any member; staff see only their locations (`ctx.scope`) | review sync every `review_sync_interval_minutes` | "Connect Google" empty state |
| Total reviews | same | `reviews.total_synced` | same | same | same |
| New reviews this month | same | `reviews.new_in_range` | same | same | same |
| Search views, Maps views | Google, official | `GET /gbp/{id}/performance` (`BUSINESS_IMPRESSIONS_*`), proposed daily store §7 | `gbp_performance` feature | daily job (proposed) | "Google isn't sharing this yet" + reason (API disabled / awaiting approval / reconnect) |
| Website clicks, calls, direction requests | Google, official | same (`WEBSITE_CLICKS`, `CALL_CLICKS`, `BUSINESS_DIRECTION_REQUESTS`) | same | same | same |
| Review growth trend | FlowQR, counted from synced reviews | `reviews.series` | any | with sync | empty state |
| Local ranking summary | Google Places, measured | `GET /gbp/{id}/rank` (`rank_keywords`, `rank_checks`) | any; check requires admin | every 6 h (`check-ranks`) when `rank_provider` configured | "Local ranking isn't set up" (existing state) |
| Pending review replies | FlowQR, counted | `reviews.awaiting_reply` | any | live | n/a |
| Important profile-health issues | FlowQR, calculated from Google profile | `HealthSnapshot` + `profile_completeness()` | any | daily | "Connect Google to check your profile" |
| Growth recommendations | FlowQR, calculated (existing agent plan) | `GET /agent/today`, `agent_tasks` | any | daily agent | omitted, not invented |

Removed from Overview to cut repetition: the separate rating card plus four key tiles plus growth chart overlap (rating appears three times); they collapse into one KPI band and one trend. Overview must show nothing that is not in this table.

---

## 4. Local SEO module

### 4.1 Data-source research (what Google does and does not provide)

| Capability | Provided by Google Business Profile APIs? | Verified | Use |
|---|---|---|---|
| Daily impressions (Search/Maps × desktop/mobile), calls, website clicks, directions, bookings, messages | **Yes**: Performance API `fetchMultiDailyMetricsTimeSeries` | Documented and mock-tested; not live ([sources](#sources)) | Overview, Performance |
| **Search terms that showed the profile (monthly impressions per term)** | **Yes**: `…/searchkeywords/impressions/monthly` (Google reports small counts as "fewer than N") | Documented and mock-tested; **already implemented** | SEO Overview "Top-performing keywords" |
| **Ranking position for a keyword** | **No.** Google gives impressions per term, not position. | n/a | Must not be implied. Position comes only from Places measurements below. |
| **Competitor ratings / review counts** | **No** from Business Profile (own locations only). | n/a | Places API returns *public* rating and `userRatingCount` for any place. |
| **Competitor keyword visibility** | **No.** | n/a | Derived from Places search results (who appears for the same query). |
| Profile fields (categories, services, hours, description, phone, website) | Yes: Business Information API (`serviceItems`, `categories`, `regularHours`, `profile` already in the read mask) | mock-tested | Profile Health |

### 4.2 Geo-grid: provider decision

A geo-grid is *already built* on the official **Google Places API (New) Text Search**, one billed search per grid point with a location bias circle, rank = position among the first 20 results, "not found" is a real answer and an API error is never read as a rank (`services/rank_grid.py`). This is a first-party, terms-compliant measurement and the code, caps, allowance gating and cost estimator exist. Options:

| Option | Terms / reliability | Cost (verify before budgeting) | Recommendation |
|---|---|---|---|
| **A. Stay on Places API (New)** (current) | Official, supported, no scraping. Caveat in the UI already: Maps' own ordering varies by device, spot and person. | Billed per request by SKU. Google's global list (search result, 2026-11-16): Text Search Pro $32 / 1,000 (5,000 free/month), Enterprise $35 / 1,000 (1,000 free); India has its own price list. **Whether `rating`/`userRatingCount` in the field mask moves the call to Enterprise is not confirmed**: check Google's field-to-SKU table and your own billing page. A 5×5 grid = 25 requests per keyword per scan. The repo deliberately requires you to enter the price (`API_PRICES`) rather than hard-code it. | **Recommended. Keep.** |
| B. DataForSEO Google Maps SERP API | Commercial provider that returns Maps results per coordinate; you build the grid yourself (a 7×7 grid is 49 billed tasks per keyword). Terms and the legality of how it gathers data are the provider's responsibility; FlowQR becomes dependent on it. | Sources disagree on price (≈$0.0006 per SERP standard mode on its own page vs. higher third-party figures; $50 minimum deposit). | Do not adopt without your approval and a terms review. |
| C. Local Falcon (or similar) API | Packaged grid product; credits per map pin; its own terms restrict reuse of its content. | Subscription plus credits; figures unverified. | Not recommended: duplicates what is built, adds a competitor's branding/terms. |
| D. Scraping Google Maps | Violates Google's terms and is unreliable. | n/a | **Rejected.** |

**No new provider purchase or terms acceptance is needed for the proposed modules.** What *is* needed (already listed as MISSING DECISIONS in `docs/COMMERCIAL_LIMITS_AND_COSTS.md`): the per-plan geo-grid allowance (maps, points per map, points per month), the Places price in `API_PRICES`, and a platform-wide cap (`RANK_PLATFORM_MONTHLY_CAP`, currently 0 = no cap, the one control that fails open). Until the allowance is set, maps stay OFF by design. Competitor review-growth needs no extra provider (derived from the Places result rows already stored).

### 4.3 Page-by-page

**SEO Overview** (`/seo`, new). One screen answering "how visible am I?":
- Local visibility summary: share of tracked keywords where you are in top 3 / top 10 / not in top 20 (*Places, measured*), with the date of the last check.
- Tracked keyword positions + change since previous check (existing `compare` logic and significance thresholds).
- Visibility trend: share-in-top-10 over time from `rank_checks`.
- Top-performing keywords: highest-impression search terms from Google (*Google, official*), kept visually separate from rank so the two are never confused.
- Keywords needing attention: tracked keywords that dropped, or are "not in top 20", or have impressions but no tracking.
- Unavailable states: provider not configured; Google not connected; no keywords yet (with a "add your first keyword" action).

**Local Rank Tracking** (`/seo/rank`). The existing keyword list, history and geo-grid, unchanged in behaviour, plus: a competitor strip per keyword (top 3 names, ratings) from the stored top results, and SoLV/ARP summary already computed for grids.

**Google Profile Health** (`/seo/profile`). Reuse `health.py` and `profile_completeness()`, shown as a checklist (not just a score): description length, hours, phone, website, main category, **secondary categories and service items** (need new checks; data is already fetched), photo count/freshness, posting recency, unanswered reviews, with the formula visible. Each failed check links to the existing editor. Recommendations come from the existing plan engine; none are invented. No "SEO score" invented beyond the existing formula.

**Competitor Analysis** (`/seo/competitors`). Phase A (no new cost, no new tables beyond a view): competitors = places that appear alongside you in your stored Places results. Shows name, rating, review count, change in review count between checks, and how often they outrank you across your tracked keywords (*Places, measured*; labelled as derived from your own checks). Phase B (optional, needs your approval): let the owner *pin* up to N competitors and snapshot their rating and review count on a schedule via Place Details (new table, extra billed calls). Review growth is then a real difference of two dated measurements, never an estimate. "Opportunities" are rule-based and shown with the evidence ("3 competitors in the top 3 have 4× your reviews").

---

## 5. Consolidating the AI features

| Feature | Recommendation | Reason |
|---|---|---|
| Reply assistant (`/ai`) | **Merge** into Reviews & Inbox as a Drafts tab | Same drafts as the reviews inbox; two entry points today. |
| Today, Tasks, Approvals, Activity | **Merge** into one **AI Growth Assistant** with tabs (Today · Tasks & Approvals · Activity) | One daily workflow; four near-identical list pages today. |
| Automations | **Merge** into AI Growth Assistant (a card at the top) or Settings › AI & automation | It only sets what the assistant may do. |
| Autonomy | **Move to Settings › AI & automation** (owner/admin) | Control centre, not a daily page; keep exactly as is (`AUTONOMY_EMERGENCY_STOP=true` in production stays). |
| Brand voice, Business brain | **Move to Settings › AI & automation** | Configuration. Business brain also feeds the Profile Health "services" check. |
| Usage & limits | **Move to Settings › Billing/AI usage** | Plan limits. |
| Insights | **Move to Reputation › Review insights** | It is review analysis, not AI. Note it is a transparent heuristic, not an AI model; label it that way. |
| Review-writing assistant (`/ai/assistant`) | **Move to Review Collection** | It is what customers see on the card page. |
| Content Studio: AI Creator | **Keep** | Works (drafts need approval). |
| Studio: Calendar, Brand Kit, Asset Library, Social publishing | **Hide until implemented** | 12-line "Setup required" placeholders, Meta integration does not exist. |
| Inbox & Leads (WhatsApp ×5) | **Hide until implemented** | Placeholders, no WhatsApp integration. |

No working feature is removed; hidden pages keep their routes and redirects. **Rules preserved:** replies always need a human, `auto_publish` stays false, no rating gating, "published" only after Google confirms.

---

## 6. Performance module (`/analytics/performance`)

Tabs: **Search & Maps** (Google) · **Reviews** (counted) · **Cards & campaigns** (counted). Shared date filter (7/30/90/custom), shared location filter, previous-period comparison, a table beneath every chart, CSV/PDF export.

| Metric | Source (label) | Notes |
|---|---|---|
| Search impressions, Maps impressions (split desktop/mobile) | Google, official | Reported a few days late; the last days of a range are excluded in both periods so comparisons are like-for-like (already how the dashboard behaves). |
| Website clicks, calls, direction requests, bookings, messages | Google, official | `BUSINESS_CONVERSATIONS` was removed by Google; `MESSAGING_CLICKS` added (audit doc). |
| Review growth, average-rating trend, reply time | FlowQR, from synced Google reviews | |
| Card QR/NFC scans, review-page visits, clicks to Google | FlowQR, counted (bots and rapid repeats excluded) | Shown as separate steps, never summed into "reviews". |
| Conversion | **Only** scan → landing visit → click to Google (each measured). **No scan-to-review conversion**; the UI states FlowQR cannot tell which scan produced a review. | |
| Location breakdown | per location table (existing Compare) | Staff see only permitted locations. |
| Exports | CSV per table; the existing PDF summary extended with Search & Maps and rank sections | Formula-injection-safe writer already exists. |

---

## 7. Data requirements per feature

Existing storage is reused wherever possible. **One new table is proposed** for history; competitor Phase B would add one more only if approved.

| Feature | Data source | Endpoint | Permission | Storage | Refresh | Retention | Tenant isolation | Failure / unavailable |
|---|---|---|---|---|---|---|---|---|
| Review metrics | Google reviews via sync | `/analytics/overview`, `/analytics/insights` | member; location-scoped | `reviews` | sync interval | until account deletion (existing) | RLS + `ctx.scope` | Connect-Google state |
| Search/Maps/actions | Performance API | `/gbp/{id}/performance` | `gbp_performance` | **NEW `gbp_metric_daily`** (tenant_id, google_location_id, day, metric, value, fetched_at; unique per location/day/metric; RLS) plus latest `GbpSnapshot.performance` | daily job re-fetches a trailing 14-day window (Google revises recent days) | proposed: keep while subscribed; **Google's own history limit is not verified here, check the Performance API docs before promising a length** | RLS policy identical to other tenant tables; added to the data-export/deletion paths | per-reason card state; stored history still shown with "last updated" |
| Search keywords | Performance API monthly | `/gbp/{id}/keywords` | `gbp_performance` | on demand (optional monthly store) | monthly | optional | RLS | same |
| Rank + grid | Places API (New) | `/gbp/{id}/rank`, `/rank/grids` | admin to run; member to view | `rank_keywords`, `rank_checks`, `rank_grids*` (exist) | 6 h job + manual; allowance-gated | existing | RLS | provider-not-configured, allowance-off, error rows kept as errors |
| Competitors (Phase A) | stored `rank_checks.top_results` | new read-only `/gbp/{id}/competitors` | member | none new | with rank checks | existing | RLS | "No rank checks yet" |
| Competitors (Phase B, optional) | Places Place Details | new | admin | new `competitors`, `competitor_snapshots` | scheduled, capped | proposed 12 months | RLS | per-competitor error |
| Profile health | Business Information API + `GbpSnapshot` | `/agent/health` (exists) | member | `HealthSnapshot` (exists) | daily | existing | RLS | "Connect Google" |
| Sentiment/themes | reviews text | `/analytics/insights` | `insights` feature | computed per request (consider caching) | request | n/a | RLS | no written reviews |
| Cards funnel | FlowQR events | `/analytics/overview` | member | `scan_events`, `review_events` | live | existing | RLS | no-card state |

Migrations: one additive Alembic revision (0034) for `gbp_metric_daily` with RLS and grants (the repo's existing pattern in `0002`). No existing column is altered.

---

## 8. Execution plan and approvals

### Phase 2: UX (no new integrations)
1. New `nav.ts` structure + legacy redirects for every moved URL (tests: every old URL still 308s to a valid page).
2. Overview rebuilt to the §3 table; one shared date + location filter component.
3. `/analytics/performance` tabbed page assembled from existing components (no new API).
4. `/seo` shell + SEO Overview, Profile Health and Competitors (Phase A) using existing endpoints plus a read-only competitors endpoint.
5. Tighten visual density to 14–18px data cards; reuse the chart components already upgraded this session (`LineChart`, `ColumnChart`, `Sparkline`).

### Phase 3: backend
1. Alembic 0034 + daily Performance job + backfill; tests for tenant isolation, staff location scoping, unavailable states, and data correctness against a mock Google transport.
2. Competitors read endpoint; profile-health checks for services and secondary categories.
3. Export additions.

### Phase 4: validation
Backend tests, `tsc`, production build, responsive + dark-mode checks, reduced-motion check, and each metric compared with its raw source (mock transport; live comparison only where Google actually returns data).

### Approvals needed before Phase 2

| # | Decision | My recommendation |
|---|---|---|
| 1 | Six top-level sections instead of four | Yes |
| 2 | Merge `/gbp` hub and `/overview/reviews` into other pages | Yes (redirects keep the URLs) |
| 3 | Move Brand voice, Business brain, Autonomy, Usage to Settings › AI & automation | Yes |
| 4 | Hide the 9 placeholder pages from navigation | Yes |
| 5 | Stay on Places API (New) for rank and geo-grid; no third-party rank vendor | Yes |
| 6 | Add `gbp_metric_daily` for Google metric history | Yes |
| 7 | Competitors: Phase A only now, pinned-competitor snapshots (Phase B) later | Yes |
| 8 | You set the geo-grid per-plan allowance, the Places price (`API_PRICES`) and `RANK_PLATFORM_MONTHLY_CAP` | Needed before maps can run for customers |

### Risks and open items
- Google Business Profile access is not approved or live-verified; all Google cards will show "unavailable" until it is. Building the UI first is safe because it renders unavailable states honestly.
- Places pricing and whether `rating`/`userRatingCount` raise the SKU must be read from your own Google Cloud billing page before the allowance numbers are set.
- The same Places key currently serves the laptop and the VPS (recommend a separate, IP-restricted key).
- Google Performance API retention length is unverified; do not promise a history window until checked.
- The sentiment/theme feature is a keyword heuristic. It should be labelled as such and not marketed as AI analysis.
- `docs/ART_DIRECTION_AND_UI_AUDIT.md` still describes an older visual direction and `DESIGN.md` does not exist in the repo; the redesign should write one.

---

## Sources

- Business Profile Performance API reference (searchkeywords and fetchMultiDailyMetricsTimeSeries): <https://developers.google.com/my-business/reference/performance/rest>
- Google Maps Platform pricing (Places Text Search SKUs): <https://developers.google.com/maps/billing-and-pricing/pricing>
- DataForSEO Google Maps SERP API pricing: <https://dataforseo.com/pricing/serp/google-maps-serp-api> · grid-tracker note: <https://dataforseo.com/help-center/build-grid-rank-tracker-maps>
- Local Falcon terms of use: <https://www.localfalcon.com/terms-of-use>
- In-repo: `docs/GOOGLE_API_AUDIT.md`, `docs/FEATURE_MATRIX.md`, `docs/COMMERCIAL_LIMITS_AND_COSTS.md`
