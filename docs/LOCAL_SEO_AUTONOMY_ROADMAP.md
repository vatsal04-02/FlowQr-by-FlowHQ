# Local SEO autonomy roadmap: from Milestone 2 to Level 4

Status: **planning only. Nothing here is built or activated.** Worker and beat stay stopped, the emergency stop stays on, autonomy stays off, the two clinic connections stay isolated, no clinic profile is touched, nothing is pushed or deployed. Written 2026-11-17 on top of `LOCAL_SEO_ENGINE_AUDIT_AND_ROADMAP.md`, `GOOGLE_READINESS_M2.md` and `GOOGLE_DATA_RETENTION_FINDINGS.md`. This document **absorbs and replaces the Milestone 3 to 6 plan** in the audit (it keeps their content and re-orders it around autonomy).

Evidence labels: **Code** (read in this repository), **Dev DB / Tests** (observed locally), **Google docs** (read 2026-11-17), **Market** (competitor pages read 2026-11-17: marketing claims, not verified behaviour), **Assumption**.

---

## 1. Two scales that must not be confused

The code already uses "Level 1/2/3" for **how risky one action is** (`autonomy_policy.py`). Your brief uses "Level 4" for **how autonomous the product is**. To avoid collision this roadmap calls them:

| Name | Meaning | Where it lives |
|---|---|---|
| **Risk class R1 / R2 / R3** (today's "Level 1/2/3") | R1 low-risk wording of the description; R2 hours, services, contact, secondary categories; R3 name, primary category, address, attributes, service area, primary contact, removals, sensitive claims | `autonomy_policy.SPECS` (unchanged; UI should say "risk class" to stop the clash) |
| **Autonomy level A0 to A4** (product maturity, per location) | below | new (this roadmap) |

| Autonomy level | What FlowQR does | State today |
|---|---|---|
| **A0 Observe** | reads Google, scores, measures; sends nothing | the default (everything off) |
| **A1 Suggest** | proposes, with evidence and a preview; the owner decides each | built (tasks, optimizer, `agent_actions`) |
| **A2 Execute on approval** | the owner approves one change; FlowQR writes, reads back, verifies, records | built, mock-tested; live proof only for description, post, photo on the test profile |
| **A3 Delegated** | for **R1/R2, reversible, explicitly consented, within budgets**, FlowQR executes without asking each time and reports afterwards | plumbing built in Milestone 2 (consent, executor re-check); **no budgets, no rollback, no per-location policy, no owner screen** |
| **A4 Closed loop** | A3 plus continuous planning from measured outcomes, automatic rollback of its own failed changes, drift detection, weekly reporting, spending and quota discipline; **R3 and irreversible actions stay human** | not built |

**A4 never means** unattended name/address/primary-category changes, publishing anything without a person where policy requires one, ignoring quotas, or acting where consent is absent or revoked.

---

## 2. What the market does (and what Grexa actually shows)

Marketing pages read 2026-11-17. They describe claims, not proven behaviour.

| Product | Autonomous GBP actions it claims | Approval / consent as published | Google connection published | Price published |
|---|---|---|---|---|
| **Grexa** (Navi Mumbai) | "Profile rewrite", "More reviews", "Review replies: respond to all reviews", "Daily posts", "Photo scheduler", "Performance" | **No page says whether changes publish without approval.** Home page: "You review their work in the Grexa App" (before or after is not stated). Terms: "you are responsible for reviewing and approving such content before using or publishing it." No consent mechanism described | **Not found** (the free booster starts from a business name or public Google link; it warns never to share a Google password on WhatsApp) | INR per term: Discovery (GBP only) ₹6,999 / 6 months, ₹9,999 / year; Growth (GBP + two WhatsApp agents) ₹15,000 / 3 months to ₹60,000 / year. No plan limits stated. Terms: auto-renewal; "No refund ... under any circumstances" |
| Merchynt Paige | description, services, attributes, social links, weekly posts, review replies, scheduled photos | "approval-first for posts and review replies, or use autopilot" | "Connect the Google account that manages your Business Profile" | $99 per profile per month |
| Semrush GBP AI Agent | posts every 7 days, replies within 24 hours, a photo every 10 days; description generated in the audit | no approval gate; per-skill on/off; 100 recent actions listed; no undo | not published | in a Local plan |
| Local Falcon "Falcon Agent" | hours, services, **categories**, posts, photos, replies, scheduled | autonomous mode with per-location toggles; "Full Action History"; reverts only *unauthorised* changes made by others | "connected directly to your Google Business Profile" | in its Basic plan and up |
| Localo AI agent | none: "never changes your GBP" | suggestions only | via Localo | not stated |
| Search Atlas (generic guide) | audits, posts, replies | five categories need approval by default (negative replies, category changes, mass content, paid promotions, legal flags); starts at low autonomy | OAuth, generic | $199/month unverified |

What this means:
* **Does Grexa do the same thing?** It *markets* the same capability set minus ranking and competitors: rewrite, reviews, replies, daily posts, photos, performance (plus WhatsApp lead and chat agents, which FlowQR does not have). It does **not** publish geo-grid, competitor monitoring, categories, hours or reports as features. Whether it is *autonomous* in practice cannot be established from its public pages: no approval model, no Google connection method, no Google API policy or consent statement, and the results claims (for example calls "90 → 355", "₹900k+") are unnamed case studies with no method.
* **Nobody publishes how they satisfy Google's "prior specific and express consent" rule**, nobody publishes an undo for their own changes, and only Search Atlas (generic) and Merchynt describe approval tiers. FlowQR already has per-location, per-action consent with the wording stored, immediate revocation, a read-back check and a tamper-evident history. That is a real differentiator **if** it becomes visible to owners (control centre) and is not weakened.
* **What competitors do that we do not yet:** weekly summaries (Merchynt, Falcon), recurring autopilot posts/photos (Semrush, Merchynt, Falcon), AI replies to positive reviews on autopilot (Semrush, Merchynt), services/attributes optimisation (Merchynt). **Caution:** Falcon Agent changing categories unattended, and Semrush/Merchynt posting unattended, sit on the wrong side of FlowQR's rules (R3 and public content). Matching them is a product decision, not a default (see D-A, D-B).
* **Price context:** Paige $99 per profile per month is about ₹8,900; Grexa's cheapest GBP plan is ₹9,999 a year (about ₹833 a month) with no limits published; FlowQR Growth is ₹799 a month with Google-posts, ranking and the engine. FlowQR's unit costs for autonomy are small (AI text at fractions of a rupee per draft; Places searches about ₹3 each when used), so the pressure is on trust and proof, not on cost.

---

## 3. What stays exactly as it is

Propose → classify → approve → execute → read-back → verify; `AgentAction` as the single record; idempotency keys and the one-write-in-flight index; claim-before-write; stuck work resolved by reading Google, never writing again; retry limits (`autonomy_max_attempts`); per-location **consent grants** (append-only, wording stored, revoked at once, re-checked at write time); the emergency stop (env and runtime); hash-chained history; RLS on every table (and every new table in the export and deletion lists); Level/risk classification that can only escalate; person approval for R3 and for public content; "do not revert changes Google made".

---

## 4. New cross-cutting components (the foundation for A3 and A4)

These are shared by every capability in section 5, so they come first. Each is **built disabled** and tested with the Google test double.

| # | Component | What it adds | Backend | Frontend | Effort |
|---|---|---|---|---|---|
| F1 | **Risk and reversibility metadata** | each `ActionSpec` gains `reversible` (true/false), `undo_method` (restore value, delete post, delete reply, none), `blast_radius` (field, location, public), `cooldown_days` (minimum days between changes to the same field). Risk class stays; **autonomy ceiling per action = f(risk class, reversibility)**: R1/R2 and reversible may reach A3; irreversible or R3 are capped at A2 | `autonomy_policy.py`, tests that every spec declares them and that nothing irreversible is grantable | none (shown in control centre) | 1 wk |
| F2 | **Per-location execution policy** | table `location_autonomy_policy` (RLS): level A0 to A3 per location, allowed scopes (must each have an active consent), daily and weekly change budgets, quiet hours in the business's time zone, per-field cooldown, "pause after N failures". The executor reads it with consent: both must allow | migration, `services/autonomy_exec_policy.py`, executor and content_exec hooks, API | policy panel | 2 wks |
| F3 | **Execution budgets and rate limits** | per location, per business and platform: changes per day/week (today only one per-business daily limit of 3), Google edits per minute per profile (today 10 per minute in-process), Places/AI budgets reused; a budget refusal is recorded and visible, never silent | `executor`, `usage.py`, ops check, admin view | budget meters | 1.5 wks |
| F4 | **Undo engine** | an `undo` action that restores `current_value` **only if Google still holds exactly what FlowQR wrote** (otherwise refuses: never revert Google's or the owner's own later change); posts by delete, replies by `deleteReply` (exists in the provider, used only by tests), photos by delete; undo is itself audited, read back, and consent-neutral because it only restores the owner's prior state | `executor.undo`, provider (post/media/reply delete via governed path), history events | "Undo" button with preview and reason | 2.5 wks |
| F5 | **Outcome measurement** | before/after windows around a *verified* action: same-length windows, Google reporting lag excluded, the metric's own Google definition shown, "moved / did not move / not enough data", **never "caused by"**; reuses `agent_rank_followups` for rank and `gbp_metric_daily` for views and actions; counters stored as FlowQR-owned numbers so raw Google content can expire | `services/outcomes.py`, `learning.py`, jobs | outcome cards | 2 wks |
| F6 | **Drift and Google-change detection** | `getGoogleUpdated` (diffMask) and read-back drift: show "Google or someone else changed X after FlowQR set it", **offer** accept or restore, never auto-revert (Google policy) | provider (live-validated read exists), `services/drift.py`, job | "Google changed this" panel | 1.5 wks |
| F7 | **Autonomy control centre** | one screen per location: level, what FlowQR may do (each scope with its exact consent wording, one switch), what it did this week, what waits for you, budget meters, Undo, "Withdraw everything" (revoke-all exists) and "Disconnect FlowQR" | consent API exists; add policy, budgets, activity feeds | new pages inside the existing GBP and Settings areas; phone first | 4 wks |
| F8 | **Job reliability and observability** | per-job success and failure counts, a circuit breaker per external provider (Google, Places, AI) that stops work after repeated failures, a dead-letter list of items that exhausted retries, an `ops_watch` check for each new job | `workers/*`, `ops.py` | admin and owner status | 1.5 wks |
| | **Foundation total** | | | | **about 16 weeks** |

---

## 5. Capability by capability

Format per capability: **Now** (verified), **Missing**, **Google dependency**, **Consent**, **Retention**, **Failure and recovery**, **Tests and acceptance**, **Effort**, **Status**. "Foundation" means F1 to F8 above.

### C1. Google Business Profile monitoring and optimisation
* **Now:** daily profile snapshot (profile, categories, hours, services, special hours, open status, phone, website), 56 days of performance; deterministic optimizer checks; `seo_engine` proposes description and missing website/phone; executor writes description, regular hours, categories, phone, website with read-back. Live proof: description only (2026-11-15). Validation-only proof (2026-11-17, test profile): description, categories, services (including adding one), regular hours, special hours with regular hours, phone, website.
* **Missing backend:** write paths for services and special hours (new `ActionSpec`s, read-back verification, undo); attributes (read works, 31 attributes for the category; write request shape unverified); the six-part recommendation text with an *expected benefit stated as a hypothesis*; `next_audit_at` per location; reading `getGoogleUpdated`. **Frontend:** per-recommendation Explain, Preview, Approve, Execute, Verify, Undo; services and hours editors with preview.
* **Google dependency:** Business Information API (`locations.patch`, `getGoogleUpdated`, attributes), 10 edits per minute per profile, 300 QPM. Prod project needs approval and the verified OAuth app.
* **Consent:** per location and per type (exists). New scopes only for R1/R2 reversible writes proven live: services (R2), special hours (R2). Attributes remain R3.
* **Retention:** snapshots are overwritten on refresh (plausibly within 30 days); stored before/after values in `agent_actions` are FlowQR's own record (D3 question).
* **Failure and recovery:** unchanged engine (claim, retry limit, read-back mismatch means failed, recovery by reading); add undo and cooldown.
* **Tests and acceptance:** contract tests from recorded real shapes; executor tests for each new type including mismatch and "Google changed since proposal"; **live write proof on the test profile for each new type before it is grantable**; acceptance: no type is offered for consent until a recorded live round trip (write, read back, restore) exists.
* **Effort:** 3 wks after F1/F4. **Status:** build now (against the double); *live proof blocked on D5 approval*.

### C2. Review monitoring, sentiment analysis, authorised replies
* **Now:** sync every 30 minutes (polling), Google's reply state honoured, a keyword/rating sentiment heuristic (EN/Hinglish/Hindi, labelled a signal), AI reply drafts needing a person, **template replies to new 4 and 5 star reviews with per-location consent**, risk check for health, legal and abuse content.
* **Missing:** reply undo (`deleteReply` is in the provider; wire through governed path); response-quality checks (deterministic: length, placeholders, prohibited claims); unanswered-review reminders with a rate limit; optional **AI replies to positive reviews under consent** (competitors do this; our policy keeps AI-drafted replies person-only, an owner decision: D-A); Pub/Sub notifications instead of polling (API not enabled on the project). **Frontend:** reply queue with per-review explain and undo; consent switch in the control centre.
* **Google dependency:** v4 reviews API (no sunset notice found); `updateReply` valid only on verified locations; Notifications API (Pub/Sub) not enabled; review-solicitation rules (no incentives, no gating) already enforced.
* **Consent:** `reply_template` (built). AI-written replies: **no standing grant until D-A**; Google: "if you respond to reviews on behalf of your end-client, you must receive their authorization first" and verbal consent is not enough (recorded wording satisfies this).
* **Retention:** **launch blocker D3**: raw review text stored indefinitely. Design reply logic to need only the review being answered plus FlowQR-owned counters.
* **Failure and recovery:** governed path exists (hold on emergency stop, retry transient, never second reply). Add: a reply rejected by Google is shown as rejected (exists); undo.
* **Tests and acceptance:** existing 20+ template-reply tests plus undo, consent per location, no reply to sensitive content, no reply older than 3 days; acceptance for any AI-reply extension: measured acceptance rate over real approvals (`ai_outputs`) before any standing grant.
* **Effort:** 2 wks (undo, reminders, quality checks), +2 wks for the optional AI-reply grant. **Status:** build now; *AI-reply grant blocked on D-A and acceptance data; live reply test needs a real review from a second Google account*.

### C3. Profile completeness and information accuracy
* **Now:** `profile_completeness` (5 fields), 12 optimizer checks, health score with visible formula, tenant-record vs Google for missing phone/website.
* **Missing:** **inconsistency detection** across Google profile, business record and Business Brain (phone, hours, address, services, categories, name rules), including holiday hours; verification status (`getVoiceOfMerchantState` read works: `hasVoiceOfMerchant`, `hasBusinessAuthority`); Google-suggested changes (F6); attributes completeness; services list vs knowledge base. A **conflict queue**: both values shown with source and date, the owner picks, FlowQR drafts the fix. **Frontend:** conflict list and resolution.
* **Google dependency:** Business Information reads, Verifications API (works on the dev project), attributes list.
* **Consent:** detection needs none; fixes reuse C1 scopes.
* **Retention:** compare and store only a hash and the field name plus the owner's decision, not copies of Google content.
* **Failure and recovery:** unknown never becomes "missing" (existing rule); a failed read leaves the previous state.
* **Tests and acceptance:** normalisation tests (phone to canonical digits, hours canonical week, address tokens); fixtures for each conflict type; acceptance: every conflict shows both values, both sources and dates; nothing is written without the owner's choice.
* **Effort:** 2 wks. **Status:** build now (website comparison excluded; website audit is the separate AEO track).

### C4. Local keyword and ranking intelligence
* **Now:** tracked terms (10 per location), Places Text Search rank (first 20), weekly checks inside a 300-per-month cap, Google's own search-term report, 7/14/28-day follow-ups, geo-grid built and **disabled** (six guards).
* **Missing:** **opportunity discovery** (deterministic: category plus each verified service plus place, filtered by Google's search terms; suggested for the owner to accept; no tracking added without consent); category-gap hints from the Google category list; `languageCode` is fixed to English; per-plan keyword numbers; a platform-wide cap that fails closed (today 0 means no cap).
* **Google dependency and cost (India list, Google pricing pages, USD):** Text Search **Pro $9.60 per 1,000** (free cap 35,000 a month); **Enterprise $10.50 per 1,000** (free cap 7,000). **A request whose field mask contains `rating` or `userRatingCount` is billed as Enterprise**; FlowQR's mask has both. Whether you need ratings in every rank check or only in competitor snapshots is a cost decision.
* **Consent:** none for reading and ranking (it spends FlowQR's budget, not Google profile changes). Keyword changes the owner did not choose are not made.
* **Retention:** place ids may be kept; coordinates 30 days; other Places content depends on terms not yet read (D3 item).
* **Failure and recovery:** an error is never a rank (existing); budget refusal visible (F3).
* **Tests and acceptance:** suggestions only from verified services and place; no term the business has no basis for (existing rule); cost per check recorded in the ledger; acceptance: geo-grid stays refused until the allowance, price, platform caps and a restricted key exist.
* **Effort:** 2.5 wks. **Status:** discovery build now; **geo-grid blocked** (commercial approval); Place Details cost see C5.

### C5. Competitor monitoring within approved quotas
* **Now:** top 10 per check, pin up to 5, dated snapshots (rating, reviews, position) from stored rank checks at **no extra Google call**; display only, not used by any recommendation.
* **Missing:** use in the planner (review-count gap, rating gap, how often they outrank you, review growth between two real observations); optional profile facts (category, website, photo recency) need **Place Details**, which is **deferred (D6)**.
* **Cost prerequisite for D6 (preliminary, India list, USD):** Place Details **Pro $5.10 per 1,000** (free cap 35,000), **Enterprise $6.00 per 1,000** (free cap 7,000; includes rating, review count, website, phone, hours). Five pinned competitors checked weekly is about 22 lookups per location per month, about **$0.13 (about ₹12)**; at 1,000 locations about $130 a month, inside the 7,000 free lookups only up to about 320 locations. These are list prices read from Google's pages, not your invoice; **no lookup will be added without your commercial approval.**
* **Consent:** none (read-only, our budget).
* **Retention:** competitor data is Places content: depends on the Service Specific Terms (not retrieved).
* **Failure and recovery:** absence is "did not appear", never a rank (existing).
* **Tests and acceptance:** a difference is reported only between two dated observations; observed and estimated clearly labelled.
* **Effort:** 1.5 wks (planner use of existing data); +2 wks Place Details. **Status:** planner use buildable now; **Place Details blocked on D6**.

### C6. Google Posts and photo management
* **Now:** AI post drafts (one per location per day if enabled), approval per post, scheduler with retries and stuck-publish recovery, photo scheduler, read-back (post id, live URL), approval-required by policy (`person_only`). Live proof: post create/read/delete and photo upload/delete on the test profile.
* **Missing:** a content calendar with owner-approved themes and facts; **batch approval** ("approve this week's plan") that still records one decision per item; undo (delete); post types beyond STANDARD (event, offer need dates and verified offers); photo categories and Google's size rule (min 250 px short edge, at least 10,240 bytes, except profile/cover) checked before scheduling.
* **Google dependency:** v4 localPosts and media; posts: STANDARD, EVENT, OFFER (ALERT not creatable); photos: `sourceUrl`; no sunset notice found.
* **Consent:** per-item approval stays (D4). A *standing* grant to publish FlowQR-drafted posts on a schedule would be a **separate, specifically authorised permission**: not built, needs D-B and Google's "listing creations ... prior specific and express consent" read as satisfied by a recorded standing grant (legal view needed).
* **Retention:** post text and photo URLs are Google Content once read back; keep FlowQR's own scheduled record only as long as needed.
* **Failure and recovery:** existing; add dedupe across retries by content hash and one publish in flight (exists).
* **Tests and acceptance:** no post without a person's approval; duplicate content refused; every number or offer traces to the Business Brain; acceptance for a standing grant: a limited scope (themes and facts the owner approved, fixed cadence, weekly cap, undo).
* **Effort:** 3 wks (calendar, batch approval, undo, event/offer types). **Status:** build now; **standing publish grant blocked on D-B plus legal view**.

### C7. Google performance analysis
* **Now:** daily metrics stored (`gbp_metric_daily`: impressions by Search and Maps and device, calls, website clicks, directions, bookings, messages), 3-day lag handled, "not returned" distinct from zero, search-term report; metric definitions from Google (for example impressions are counted once per user per day).
* **Missing:** the action-anchored before/after (F5), metric-deprecation handling (`BUSINESS_CONVERSATIONS` and `BUSINESS_FOOD_ORDERS` are deprecated and one invalid enum fails the whole request), history limits (Google's page states none; **Unknown**), reporting cards that say what moved without attributing a cause.
* **Google dependency:** Performance API; 300 QPM.
* **Consent:** none. **Retention:** daily rows and review-derived numbers are the D3 core: store as counters with an expiry class once the answer is known.
* **Failure and recovery:** a failed fetch keeps previous data with its "last updated" stamp.
* **Tests and acceptance:** same-length windows, lag excluded, a missing metric never zero; acceptance: no sentence says an action *caused* a change.
* **Effort:** 1 wk beyond F5. **Status:** build now; storage design **blocked on D3 answer** for how long raw rows may live.

### C8. Automated growth planning and prioritisation
* **Now:** `agent/plan.py` builds a daily task list (reply, post, profile fix, photo, connect, complete knowledge) with a dedupe key and a priority number; health score; optimizer checks; learning suppression of repeated failures.
* **Missing:** a **planner** that ranks work by evidence strength, effort, risk class and measured past outcomes (F5), respects budgets (F3) and consent (what could run on its own vs what needs the owner), writes the weekly plan and `next_audit_at`; proposal cap per business (today none); no recommendation without evidence, and every one carries "expected benefit" as a hypothesis and "approval needed".
* **Google dependency:** none new. **Consent:** the planner only *marks* which items may run on their own; it never grants.
* **Retention:** plans and priorities are FlowQR's own data.
* **Failure and recovery:** a planner failure leaves the previous plan; a repeated recommendation is suppressed by the dedupe and cool-down.
* **Tests and acceptance:** deterministic ranking tests; every item has evidence, risk class and approval requirement; acceptance: an owner sees at most N items a week per location; nothing repeats within its cool-down.
* **Effort:** 2.5 wks. **Status:** build now.

### C9. Execution verification, retries and failure recovery
* **Now:** claim before write, per-field in-flight lock, retry limits and back-off, read-back verification, mismatch means failed, suspension after repeated failures, recovery by reading Google, emergency stop, hash-chained history (`verify_history`).
* **Missing:** undo (F4); circuit breaker per provider and dead-letter list (F8); drift detection after success (F6); per-job observability; chaos-style tests (worker killed mid-write, duplicate delivery, two workers); alerting when a business's failure streak suspends it.
* **Google dependency:** 429 and `Retry-After` handling exists; add jittered back-off consistent with Google's guidance.
* **Consent:** a revoked consent stops queued work (built).
* **Retention:** history 730 days (D3 question for stored values).
* **Tests and acceptance:** property tests: never two writes for one idempotency key; never a write after revoke, stop or budget exhaustion; acceptance: a killed worker never produces a double publish.
* **Effort:** 2 wks beyond F4, F6, F8. **Status:** build now.

### C10. Automated weekly business reports
* **Now:** on-demand PDF and CSV (`/reports`), hourly digest email of items waiting; no weekly scheduled report.
* **Missing:** a weekly job per business (local time, once, idempotent per ISO week) that sends one email and keeps one in-app copy: what FlowQR did (actions executed and verified, undone, refused and why), what is waiting, rating and review changes, Google views and actions with the lag note, rank movement, budget used, **next steps**, all with the same observed-versus-estimated labels; plain language including Hindi/Hinglish labels; an unsubscribe and an owner's choice of recipients.
* **Google dependency:** none new. **Consent:** the owner's notification preferences exist; add a weekly-report preference (opt-out).
* **Retention:** the report stores **numbers and FlowQR's own action log**, not Google review text or photos.
* **Failure and recovery:** a failed send is retried once and recorded; never sent twice for the same week.
* **Tests and acceptance:** idempotent per week; no number without its source; empty weeks say so; acceptance: every figure traces to a stored row.
* **Effort:** 2 wks. **Status:** build now.

---

## 6. What can be built now, and what cannot

### Buildable now (no Google approval, policy answer or legal review needed; built disabled, tested with the Google double)
F1 risk and reversibility metadata; F2 per-location policy; F3 budgets; F4 undo engine (against the double); F5 outcome measurement (from existing stored data); F6 drift detection (read-only call already live-validated); F8 reliability; control-centre screens (consent grant and revoke, policy, budgets, activity, undo); C3 inconsistency detection; C4 opportunity discovery; C5 planner use of existing competitor data; C6 calendar and batch approval (per-item approval kept); C7 reporting; C8 planner; C9 hardening; C10 weekly report.
**Design rule while D3 is open:** do not add new stores of raw Google content; compute and keep FlowQR-owned counters so raw rows can expire without breaking screens.

### Blocked, and by what
| Blocker | Type | Blocks | Owner action |
|---|---|---|---|
| **D3 retention** (30-day wording; Limited Use scope; Places caching terms) | policy clarification + legal | onboarding any real customer to Google sync; final storage design for reviews, daily metrics, coordinates, competitor data; the "keep reviews as history" disconnect behaviour | ask Google in writing; legal opinion; read the Maps Service Specific Terms in a browser |
| **Production OAuth verification, consent screen out of Testing, production APIs and 300 QPM quota** | Google approval | any production Google sync; reliable refresh tokens (7-day expiry in Testing) | Cloud Console checks (D7) and Google's review |
| **Live write proof** for services, special hours, hours, phone, website, categories, replies | owner approval (D5) | making any of those grantable | approve the sequence in `GOOGLE_READINESS_M2.md` section 6 |
| **Notifications (Pub/Sub) and Place Actions APIs** not enabled; Place Actions needs access | Google configuration and approval | review push notifications; booking-link management | enable in Cloud Console; request access |
| **D6 paid Place Details** | commercial approval | competitor profile facts | approve cost model |
| **Geo-grid** | commercial approval | any grid scan | Places price, plan allowances, platform caps, restricted key |
| **D-A: AI-written replies to positive reviews on a standing grant** | owner product decision + acceptance data | closing the gap with Semrush/Merchynt | decide after measuring owners' acceptance of AI drafts |
| **D-B: a standing grant to publish drafted posts or photos** | owner decision + legal view of Google's "express consent" for listing creations | unattended posting | decide; keep per-item approval until then (D4) |
| **R3 fields, attributes, name, address, primary category** | policy (never automatic) | stays human | none |
| **Clinic connections** (real customers' data) | your approval | revoking their tokens; any reuse | approve revocation or keep isolated |
| **Consent wording, DPDP, disclosure ("Working with a third party" notice)** | legal review | launch | counsel |

---

## 7. Sequencing, effort and gates

| Phase | Content | Effort (engineer-weeks) | Exit gate |
|---|---|---|---|
| **P1 Foundation** | F1, F2, F3, F8 | 6 | every action type declares reversibility; budgets and policy refuse correctly in tests; nothing active |
| **P2 Safety net** | F4 undo, F6 drift, C9 hardening | 6 | undo refuses when Google changed; killed-worker tests pass; drift never auto-reverts |
| **P3 Intelligence** | F5, C3, C4 discovery, C5 planner use, C7 | 9 | every number labelled observed or estimated; no causal wording; counters-not-content storage |
| **P4 Owner control** | F7 control centre (phone first), consent screens, C8 planner, C10 weekly report | 8.5 | an owner can grant, see, budget, undo and revoke everything without developer help; report is idempotent |
| **P5 Content and review autonomy** | C1 new write types (after live proof), C2 undo and reminders, C6 calendar | 8 | each grantable type has a recorded live round trip on the test profile |
| **Total** | | **about 38 (range 26 to 52)** | |

Optional, outside the total: AI positive replies (+2), Place Details (+2), standing post grant (+2), geo-grid enablement (config and verification, not engineering). The estimate **includes** the Milestone 3 to 6 scope from the audit (about 13 weeks) and is one engineer; two engineers do not halve it because P1 to P2 is a dependency chain.

**Gates before any activation (none of which is part of this plan):** D3 answered; production OAuth verified and approved; live round trips recorded per grantable type on the test profile; control centre shipped; budgets and undo tested; separate written approval from you. Activation order if approved: one internal test location at A2, then A3 for R1 description and missing-contact changes only, then widen scope by scope.

---

## 8. Acceptance criteria for "Level 4" (all must hold)

1. Every autonomous action traces to an active consent for that location and type, a budget with headroom, an unrevoked policy, no emergency stop, and evidence from verified facts.
2. Every executed change is read back from Google; a mismatch is a failure; every change is undoable or marked irreversible and therefore never autonomous.
3. Undo refuses if Google or the owner changed the value since; FlowQR never reverts Google's changes.
4. Revoking consent, switching autonomy off, or the emergency stop halts execution within one job cycle and returns queued work to the owner.
5. Re-running or killing any job never produces a second write, post or reply.
6. Outcomes are reported as observed movement with the metric's Google definition, lag and sample size; nothing claims causation or a guaranteed ranking.
7. Weekly reports are sent once per week per business and every number traces to a stored row.
8. All new tables are tenant-isolated, in the data export, and covered by the retention decision.
9. R3 changes, public content without a person, and anything blocked in section 6 remain unavailable.

## 9. Decisions requested
| # | Decision | Recommendation |
|---|---|---|
| D-A | Allow a standing grant for AI-written replies to positive reviews? | Not yet: measure acceptance of AI drafts first; keep template replies |
| D-B | Allow a standing grant to publish drafted posts or photos on a schedule? | Not yet; keep per-item approval (D4); revisit after legal view |
| D-C | Rename "Level 1/2/3" to "risk class" in screens to avoid clashing with autonomy levels | Yes |
| D-D | Pursue retention route: Google written answer, legal advice, redesign (which first) | Google's written answer and legal advice in parallel; design for counters meanwhile |
| D-E | Approve the live-write test sequence on the FlowHQ test profile (D5) | Yes, after D-D is under way |
| D-F | Begin P1 (foundation) now, disabled | Yes |
