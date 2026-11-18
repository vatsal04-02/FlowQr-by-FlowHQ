# AI Search Visibility (AEO and GEO): feasibility study and implementation plan

Status: **research and planning only. Nothing was built, migrated, installed, configured or deployed.** Written 2026-11-17 from the working tree on `phase-2/commercial-readiness`. The code inventory is in the companion [AI_SEARCH_VISIBILITY_TECHNICAL_AUDIT.md](AI_SEARCH_VISIBILITY_TECHNICAL_AUDIT.md); read its §1 first if you want to know what exists.

Evidence labels used throughout:

| Label | Meaning |
|---|---|
| **Verified (official)** | Read on the vendor's own documentation or terms page on 2026-11-17 (by fetching the page, not from a search snippet). |
| **Verified (repo)** | Read in this repository. |
| **Third-party** | A blog or news report. Used only to point at something to verify; never as a basis for a claim. |
| **Assumption** | A number or fact I chose to make a calculation possible. Listed in §10.2 and §16. |
| **Unknown** | Could not be established. A named step in the roadmap resolves it. |

Vendor documentation changes quickly (model names and prices below changed several times in 2026 alone). Every external figure here is dated 2026-11-17 and must be re-read on the day a budget or contract depends on it.

---

## 1. Executive summary

**AEO (Answer Engine Optimization) is feasible, cheap to run, and mostly new code.** FlowQR can build a Business Knowledge Profile, a website "answer readiness" audit, a structured-data audit, a question bank and owner-approved content suggestions for about ₹2 of AI cost per business per month. The reusable parts (knowledge base, AI layer, metering, approvals, scheduling, UI shell) are solid. The website fetching, parsing and structured-data work does not exist at all today and needs a new, security-hardened component.

**The honest limit on AEO's value.** Google's own documentation says there are "no additional requirements to appear in AI Overviews or AI Mode, nor other special optimizations necessary" and "no special schema.org structured data that you need to add" (**Verified (official)**). FAQ rich results stopped appearing in Google Search on 7 May 2026 (**Verified (official)**, Search Central changelog). So AEO for FlowQR customers must be sold as what it truthfully is: *making your business facts complete, consistent and easy for any system, human or machine, to understand*. It cannot be sold as "get recommended by AI".

**GEO (Generative Engine Optimization) measurement is only partly feasible, and only through proxies.**

| Platform | Can FlowQR measure the real product? | What is actually possible |
|---|---|---|
| ChatGPT Search | **No.** No API for the ChatGPT product. | The OpenAI API `web_search` tool queries *an OpenAI model with web search*. OpenAI's pages do not say it equals what ChatGPT shows. A proxy, labelled as one. |
| Google AI Overviews / AI Mode | **No.** No API returns them. | Search Console folds AI features into the "Web" totals; the API's `type` has no AI value. Gemini "grounding" is a different product and its terms forbid the analysis monitoring needs. |
| Microsoft Copilot | **No** public answer API found. | Bing Webmaster Tools "AI Performance" (public preview since 10 Feb 2026) shows citations of a verified site, owner-operated, no API found. Bing Search APIs were retired 11 Aug 2025; Grounding with Bing has terms that restrict storing and AI-evaluation use. |
| Perplexity | **Partly.** An official API returns a cited answer and supports city/lat-long location. | Closest to a real measurement, but it is the *API's* answer. Terms read so far are permissive about monitoring; two further terms documents were not read. |

**Whether a proxy measurement is informative for tier-2 Indian cities is unknown and is the single biggest technical risk.** AI web-search answers to "best physiotherapist in Gomti Nagar" may rarely name small local businesses at all, in which case a visibility metric would read near zero for almost everyone and be useless. That has to be measured before anything is built (Phase 0).

**Cost.** AEO costs rupees per business per month. GEO costs roughly **₹3.4 to ₹6.7 per query sample** across two platforms (base ₹4.7), so weekly monitoring of ten questions with two samples each is about ₹400 a month per business: half of a ₹799 plan. GEO therefore cannot be an unbounded feature on any current plan. With hard caps (§11) the blended cost across a plausible customer mix is about ₹40 to ₹120 per business per month (4.7% to 14.8% of revenue).

**Recommendation (detail in §16).**
- **Go** on AEO, as a Growth and Scale feature with a reduced version for Launch, after a short Phase 0.
- **Conditional go** on GEO, as a capped allowance (Growth small, Scale larger) plus a paid add-on, **only if** Phase 0 shows the proxy metric is informative and a legal read of the vendor terms passes.
- **No-go** on: scraping any AI product or search page; browser automation against ChatGPT, Google or Copilot; using Gemini grounding or Grounding with Bing for monitoring (terms); any claim that FlowQR "ranks" a business in AI answers or can make AI recommend it; auto-generated review/rating markup.

---

## 2. What is technically possible

1. **Business Knowledge Profile**: assemble and reconcile business facts FlowQR already holds (tenant record, Google profile snapshot, owner-entered knowledge base: services, hours, FAQs, verified offers, claims) plus facts extracted from the business's own website.
2. **Website answer-readiness audit**: fetch the owner's own website (a few pages), extract text and JSON-LD, and check whether it answers a set of local customer questions and agrees with the Google profile. Deterministic checks first, an AI read second.
3. **Crawler-access check**: read the site's `robots.txt` and report whether the crawlers behind ChatGPT search (`OAI-SearchBot`), Google and Bing are allowed in. OpenAI documents that a site that opts out of `OAI-SearchBot` "will not be shown in ChatGPT search answers" (**Verified (official)**). This is concrete, cheap and actionable.
4. **Structured-data audit and generation** of schema.org JSON-LD for facts the owner has verified (LocalBusiness sub-types, Organization, Service, Product/Offer, optionally FAQPage), with strict rules on what must not be generated (§5).
5. **Question discovery**: generate local customer questions from category, services and place; seed from the business's existing tracked search terms and Google's own search-term report (both exist today).
6. **Owner-approved content help**: FAQ drafts, description and service-page suggestions written only from verified facts, using the existing metered, safety-checked AI layer.
7. **Proxy GEO measurement** with OpenAI (`web_search`) and Perplexity (Agent API `web_search`), repeated N times per question, producing "appeared in k of n checks", cited domains and competitor names.
8. **First-party analytics where the owner already has them**: Bing Webmaster Tools AI Performance (owner views it; no API found) and Search Console (aggregate only). Both require the owner to have verified their site; many small businesses will not have.
9. **Competitor view** built on data FlowQR already stores (top-10 Places results, pinned competitors with rating/review history) plus competitor names found in AI answers.

## 3. What is not currently possible or not reliable

| Claim a customer might want | Why FlowQR cannot honestly deliver it |
|---|---|
| "Your rank in ChatGPT / AI Overviews" | AI answers have no ranked list. Position in an answer is not an organic rank and varies run to run. No API exposes the real ChatGPT or AI Overviews output. |
| "Track your AI Overviews / AI Mode appearances" | Not available programmatically. Search Console includes them inside the "Web" totals, and the Search Analytics API `type` values are `web`, `webMultimodal`, `image`, `video`, `news`, `discover`, `googleNews` (**Verified (official)**). Third-party reports mention a separate "generative AI" report in Search Console; the official pages I read do not show it. **Unknown** until checked in a live Search Console property. |
| "Copilot visibility" for any business | No public API for Copilot answers was found. Only the owner-operated Bing Webmaster report exists, and only for sites they verified. |
| Using Gemini grounding or Grounding with Bing to monitor | Their terms prohibit it in practice (§6). |
| "Do this and AI will recommend you" | Google states no special optimization exists; other vendors publish no such rule. Anything promising this is unsupportable. |
| Historical AI visibility from before the customer joined | No platform provides it. History starts on the day FlowQR starts sampling. |
| Review/star markup generated from Google reviews | Google's policy makes self-served reviews on LocalBusiness/Organization pages ineligible, and markup must match visible content (**Verified (official)**). |
| Location-exact results like a person standing in the neighbourhood | OpenAI accepts only approximate country/city/region/timezone; Perplexity's Agent API accepts country/region/city and latitude/longitude; Bing grounding takes a `market` (language-country) only. No platform guarantees neighbourhood-level behaviour. |

---

## 4. Existing FlowQR functionality that can be reused

Full detail and paths in the technical audit. In short:

| Reuse | From | For |
|---|---|---|
| Business facts and "only state what is listed" grounding | `business_knowledge`, `tenants.review_context`, `services/agent/knowledge.py` | The Business Knowledge Profile and every generated suggestion |
| Safety rules for health businesses | `services/agent/safety.py`, `safety_profile` | Credentials, outcomes, patient confidentiality |
| AI provider, JSON output, language support (English, Hindi, Hinglish) | `services/ai/*` | Question generation, audit synthesis, FAQ drafts |
| Metering and budgets (check before every call, ledger after) | `services/ai_usage.py` | New task kinds `aeo_*`, `geo_extract` |
| External-API ledger with "unpriced is never free" | `services/usage.py` | OpenAI and Perplexity query costs |
| Scheduler, retries, tenant-by-tenant job pattern | `workers/celery_app.py`, `tasks.py` | Weekly audits, monitoring runs |
| Competitor roster and dated history | `pinned_competitors`, `competitor_snapshots`, `rank_checks.top_results` | Competitor comparison with no new Google call |
| Tracked keywords and Google's search-term report | `rank_keywords`, `GbpSnapshot.performance.keywords` | Seed questions |
| Approval workflow, evidence, tamper-evident history | `AgentAction`, `executor`, `audit.py` | Owner approval before anything is published |
| Plans, features, counted allowances | `services/plans.py`, `entitlements.py` | Gating and caps |
| Navigation, design tokens, empty-state patterns | `nav.ts`, `docs/DESIGN.md`, `components/seo` | UI |
| RLS pattern and the export/deletion lists | migration `0036`, `services/account.py` | Isolation and offboarding |

**Not reusable, because it does not exist:** anything that fetches a website, parses HTML or JSON-LD, queries an AI platform, extracts mentions/citations, or publishes outside Google Business Profile (audit §3).

---

## 5. Feature-by-feature feasibility matrix

Legend for **Build**: S small (days), M medium (1 to 3 weeks), L large (3+ weeks). **Reliability**: how far the output can be trusted. **Ongoing cost** is per business per month at base assumptions.

| # | Feature | Feasible | Reliability | Build | Ongoing cost | Depends on | Notes |
|---|---|---|---|---|---|---|---|
| A1 | Question generation (category, services, place, intent) | Yes | Medium (needs human edit; model can invent unrealistic questions) | S | under ₹1 | AI layer | Seed from tracked keywords + Google search terms |
| A2 | Reusable question bank (per tenant, plus category templates) | Yes | High | S to M | none | new table | Category templates curated by FlowQR, localised |
| A3 | Customer-intent categorisation (service / location / urgency / price / trust) | Yes | Medium | S | under ₹1 | AI layer | Deterministic rules first |
| B1 | Fetch owner's own website (home + a few linked pages) | Yes | High for static sites; weak for JavaScript-only sites | M | compute only | new fetcher with SSRF defence | No browser rendering in v1 |
| B2 | Answer-readiness audit (are services, hours, address, phone, pricing, credentials, FAQs present and consistent) | Yes | Medium to high for presence checks; medium for "answers the question" (AI read) | M | about ₹1 to ₹2 | B1, knowledge profile | Findings carry the exact snippet as evidence |
| B3 | Crawler-access check (`robots.txt` vs OAI-SearchBot, Googlebot, Bingbot, others) | Yes | High | S | none | B1 | Verify each bot's official name first |
| C1 | Structured-data **read** (existing JSON-LD, Microdata) and validity checks | Yes | High | M | none | B1 | Use Google's published required properties |
| C2 | Structured-data **generate** (LocalBusiness subtype, Organization, Service, Product/Offer) | Yes, restricted | High for syntax; value uncertain | M | under ₹1 | verified facts only | Copy-paste snippet; FlowQR cannot publish to a site |
| C3 | FAQPage markup | Yes, discouraged | Low value | S | none | visible FAQ on page | Google no longer shows FAQ rich results |
| C4 | AggregateRating / Review markup | **Not generated by default** | n/a | n/a | n/a | | See §5.1 |
| D1 | AI FAQ drafts | Yes | Medium; needs owner edit | S | under ₹1 | knowledge profile | Source-tagged; owner approves |
| D2 | Service-page and description suggestions | Yes | Medium | M | about ₹1 | B2 | GBP description via existing executor; website copy by copy-paste |
| D3 | Missing-information detection | Yes | High | S | none | B2 | "You have no hours on your website" |
| D4 | Content freshness reminders | Yes | High | S | none | page last-modified is unreliable; use owner-confirmed dates | |
| E1 | Business Knowledge Profile + consistency check (GBP vs website vs owner facts) | Yes | High for exact fields (phone, hours, address); medium for free text | M | none | B1 | Needs the source-of-truth rules in §8 |
| G1 | OpenAI `web_search` sampling (proxy for ChatGPT) | Yes | Low to medium, **proxy** | M | ₹3.7 per sample | API key, legal read | Approximate location only |
| G2 | Perplexity Agent API sampling | Yes | Low to medium, **closest to real** | M | ₹1.0 per sample | API key, legal read | Location incl. lat/long |
| G3 | Gemini grounding / Google AI Overviews / AI Mode sampling | **No** | n/a | n/a | n/a | | Terms forbid analysis and caching; no AI Overviews API |
| G4 | Grounding with Bing sampling | **No** | n/a | n/a | n/a | | Terms; Azure-only; no raw content |
| G5 | Bing Webmaster AI Performance (owner's own data) | Manual only | Medium; sample, preview | S (guide + manual entry) | none | owner verified site | No API found |
| G6 | Search Console (aggregate clicks/impressions incl. AI features) | Possible later | Medium; no AI breakout | M | none | new OAuth scope | Many SMBs lack it |
| G7 | Mention detection (business named in the answer) | Yes | Medium; needs disambiguation (§13) | M | about ₹0.1 per sample | G1/G2 | Match by name + domain + phone/area |
| G8 | Citation extraction (URL, domain) | Yes | High where the API returns annotations | S | none | G1/G2 | OpenAI `url_citation`; Perplexity `search_results` |
| G9 | Competitor mention extraction | Yes | Medium | S to M | about ₹0.1 per sample | G7 | Link to Places competitors by name + place |
| G10 | Trend over time | Yes | Only meaningful with many samples | S | none | stored runs | Show "k of n" never a rank |
| H1 | Competitor website/content comparison | Possible | Medium | M | Place Details calls (**price unverified**) | website URL of competitors | Fetch public pages respecting robots.txt; legal read |

### 5.1 Structured data: what is appropriate and what must not be generated

(All from Google Search Central pages read 2026-11-17 unless stated; schema.org types are used as published by schema.org, which I know but did not re-fetch.)

| Schema | Generate? | Condition |
|---|---|---|
| LocalBusiness, using the **most specific sub-type** (Google: "Use the most specific LocalBusiness sub-type possible") | Yes | Only `name` and `address` are required; add `telephone`, `openingHoursSpecification`, `geo`, `url`, `priceRange` only when the owner has confirmed them. |
| Organization | Yes, optional | Same rule. |
| MedicalBusiness / a medical sub-type | Yes, where genuinely a clinic | **Never** generate conditions, treatments, outcomes or credentials the owner has not confirmed in the knowledge base; health businesses use the existing `safety_profile = health` rules. |
| Service | Yes | Name and description from verified services. |
| Product / Offer with `price` | Only for prices in `business_knowledge.offers` | Never invented, never rounded. |
| FAQPage | Only where the **same questions and answers are visible on the page** | Google: markup must be "a true representation of the page content" and must not mark up content "not visible to readers". FAQ rich results are no longer shown, so expected benefit is unknown. |
| AggregateRating / Review for the business itself | **No** | Google: if the entity being reviewed "controls the reviews about itself", LocalBusiness/Organization pages "are ineligible for star review feature"; ratings must be "sourced directly from users"; do not "aggregate reviews or ratings from other websites". Copying the Google rating into the site's markup is the pattern this prohibits. A site that itself collects and shows genuine reviews is the only exception, and FlowQR cannot know that. |
| Anything hidden, or describing a different business, or "fake reviews" | **Never** | Spam policy; Google also lists "attempting to manipulate generative AI responses" as spam (**Verified (official)**). |

llms.txt and similar AI-specific files: Google says none are needed. **Not recommended** until a vendor documents that it reads them.

---

## 6. Platform comparison (GEO)

All rows **Verified (official)** unless noted, read 2026-11-17. Model names and prices were taken from the pages as served that day; both have changed repeatedly this year and **must be rechecked before any budget is signed**.

| | OpenAI (ChatGPT Search / API) | Google (AI Overviews, AI Mode, Gemini API) | Microsoft (Copilot, Bing) | Perplexity |
|---|---|---|---|---|
| Official API that returns a searched, cited answer? | **Yes, but a different surface:** Responses API `web_search` tool (Chat Completions in some cases). Not the ChatGPT product; the docs do not state equivalence. | **AI Overviews/AI Mode: no.** Gemini API "Grounding with Google Search" returns a model answer with `url_citation` annotations; it is not AI Overviews. | **Copilot: none found.** Grounding with Bing Search exists inside Azure AI Foundry Agent Service; Bing Search APIs retired 11 Aug 2025. | **Yes.** Agent API (current), Search API (ranked results only). Sonar chat-completions support ended 27 Sep 2026 and is being served as Agent API requests. |
| Detect business mentions? | In answer text (we parse) | In answer text | In answer text | In answer text |
| Cited URLs? | Yes: `url_citation` (url, title, positions) and a full `sources` list on request | Yes: `url_citation` (url, title); titles may be bare domains | Yes: citations and a Bing query link, but "Developers and end users don't have access to raw content" | Yes: `search_results` (url, title, snippet, date) |
| Competitor mentions? | Parse text | Parse text | Parse text | Parse text |
| Location support | `user_location`: country (ISO), city, region, timezone, type "approximate" | **No location parameter found** on the grounding page | `market` = `<language>-<country>` (for example en-IN); no city | `user_location`: country, region, city, latitude, longitude (lat/long must come with country). Search API: country only |
| Commercial monitoring / reporting permitted? | OpenAI terms and usage policy **not read**; output ownership not checked. **Unknown, legal read needed.** | **No in practice.** Grounding terms: may not "cache, frame, syndicate, resell, analyze, train on, or otherwise learn from Grounded Results"; display only to the end user who submitted the prompt; no "database"; results may not be "accessed or collected by automated or programmatic means". | **Doubtful.** Enterprise terms: use limited to "internet search experiences"; may not use output "to train, evaluate or improve any AI Model"; caching limited, "creating a database of Bing Services Output" is a listed prohibition; no SLA. | API terms (read): customer owns Output; no ban on storing found; Perplexity may terminate an application it finds "competitive with Perplexity". **Not read:** Acceptable Use Policy, Search Service terms, third-party model terms. |
| Cost (list) | `web_search` **$10 / 1,000 calls** plus search content tokens at model rates (a call may run more than once); `gpt-5-search-api` $1.25 in / $10 out per 1M tokens; the recommended newer model's price **not captured** | Gemini 3-series grounding: 5,000 free search requests a month (paid tier, shared), then **$14 / 1,000 search queries**, billed per query the model runs; Flash-Lite $0.30 in / $2.50 out per 1M | Grounding with Bing **$14 / 1,000 transactions** (a transaction = a tool call), 150 TPS, 1M/day; Azure subscription required; currency not stated on the page | Agent API `web_search` **$2.50 / 1,000** (or $1.00 with `fast` search type); `perplexity/sonar` $0.25 in / $2.50 out per 1M; Search API $5.00 / 1,000 requests; Sonar Pro price **not found** |
| Rate limits | The underlying model's tiered limits | Default 1,500 requests/day/project (paid tier, Gemini 3+), raisable | 150 TPS / 1M a day | Agent API QPS 1 to 33 by spend tier ($0 to $5,000+); Search API 50 query units/s |
| Historical data | None | None | None via API; Bing report shows selected date ranges | None |
| First-party analytics for owners | none | Search Console (Web totals include AI features; no AI breakout in the docs read) | Bing Webmaster **AI Performance**: public preview (10 Feb 2026), Total Citations, Average Cited Pages, grounding queries (a "sample"), page-level activity; covers Copilot, Bing AI summaries "and select partner integrations"; **no API found**; later additions (Topics, Intents, Citation Share) seen only on the blog listing | none |
| Crawler that decides whether a site can appear | `OAI-SearchBot` (search), `GPTBot` (training), `ChatGPT-User` (user-initiated fetches, "robots.txt rules may not apply") | Googlebot; "indexed and eligible to be shown in Google Search with a snippet" | Bingbot (not re-checked here) | PerplexityBot (**not verified**) |
| Classification | Official API, **proxy** | AI Overviews: **unsupported**. Gemini grounding: official API, **use prohibited for this purpose** | Copilot: **unsupported**. Bing grounding: official, **use doubtful**. Bing Webmaster: **first-party, manual** | Official API, **closest to measurement**, terms partly unread |

**Other categories requested:**
- *Manual research*: the owner (or a FlowQR staff member) typing a question into ChatGPT, Google, Copilot and noting the result. Always allowed; not scalable; can seed Phase 0 and a "check it yourself" guide.
- *Browser automation*: driving ChatGPT, Google AI Mode or Copilot through a headless browser to read their answers. **Not proposed.** It breaks the products' terms in general, is brittle, is exactly the anti-bot circumvention this study was told to avoid, and would make FlowQR's measurement indefensible. Same for any third-party tool whose data comes from such automation: its terms and provenance would need review and FlowQR would carry the reputational risk.
- *Third-party AI-visibility vendors*: exist (**Third-party, not verified here**). Not evaluated. If the proxy approach fails Phase 0, buying data from a vendor whose collection method is documented and lawful is the fallback to examine, with its own terms review.

**Cross-platform caveats the dashboard must state.** API answers are generated by models and search backends that can differ from the consumer products; answers vary between identical runs; the same question asked from another city can differ; the business appearing today says little about tomorrow.

---

## 7. Proposed architecture

Extend the modular monolith. No new service, no new datastore.

```
backend/app/
  models/aeo.py                 # new tables (section 8)
  schemas/aeo.py
  api/v1/aeo.py                 # /ai-visibility/* routes (tenant-scoped, role-checked, feature-gated)
  services/aeo/
    profile.py                  # Business Knowledge Profile builder + consistency checks
    fetcher.py                  # SSRF-safe fetch of a single URL (sections 12)
    extract.py                  # HTML -> visible text, headings, JSON-LD, microdata, contact facts
    audit.py                    # readiness + structured-data findings (deterministic first)
    questions.py                # generation, categorisation, bank
    schema_gen.py               # JSON-LD generation from verified facts only
    content.py                  # FAQ/service/description drafts -> approval
  services/geo/
    runner.py                   # builds a run: questions x platforms x samples, budget checks
    clients/openai_search.py    # Responses API web_search client
    clients/perplexity.py       # Agent API client
    extract.py                  # mentions, citations, competitors from one answer
    matching.py                 # business/competitor entity resolution
  workers/tasks.py              # + aeo_audit_due, geo_run_due, geo_retention
```

### 7.1 Service boundaries
- **AEO** reads facts and a website and writes findings and drafts. It never calls an AI-search platform.
- **GEO** queries platforms and writes observations. It never writes to the business's profile or website.
- **Recommendations** are produced by a thin layer that turns audit findings and GEO observations into `AgentTask` cards ("what to improve next") and, where the change is a Google Business Profile edit, into governed `AgentAction`s through the existing executor. Website changes remain advice and copy-ready text.
- Tenant-scoped API only; the workers use the existing bypass session but filter by tenant explicitly and set the context for per-tenant writes.

### 7.2 Background processing and scheduling
- Beat tasks follow the existing pattern (`check_ranks` is the model): pick due items oldest first, cap work per run, per-tenant isolation, one failing tenant does not stop others.
- **AEO audit**: on demand (owner presses "Check my website"), after a profile or knowledge change, and monthly. Fetch with hard limits (§12).
- **GEO runs**: a run = one question x one platform x one sample. Sampled on the plan's schedule. A run is idempotent per (question, platform, sample slot, period) so a retry cannot be billed twice (the ledger already supports idempotency keys).
- Spread runs across the week to avoid bursts and to respect Perplexity's QPS tiers (1 to 33 per second) and OpenAI's tiered limits. Scale check: 10,000 businesses on the capped design is about 80,000 (expected) to 180,000 (worst case) query-samples a month, each two platform calls, so roughly 0.06 to 0.14 calls per second on average. Throughput is not the constraint; cost and vendor rate tier are.

### 7.3 Error handling, retries, rate limiting
- Reuse the AI error taxonomy (`AIUnavailable` codes: auth, credits, rate_limited, timeout, quota_exhausted, bad_response). A **provider-level circuit breaker** (as `ai/health.py` does) pauses a platform on auth/credit errors so it does not burn retries.
- Retry only transient errors (429 with `Retry-After`, 5xx, timeouts), maximum two retries with jitter, never retry a billed success.
- A failed sample is stored as failed and is **never counted as "not mentioned"**. This is the same rule the rank tracker uses for errors vs rank (`rank_checks.status`).
- Per-platform concurrency caps in config; per-tenant daily ceiling in addition to the monthly allowance.

### 7.4 AI model selection
- **Inference tasks** (question generation, audit synthesis, FAQ drafts, mention extraction): the existing provider layer. The benchmark in this repo found `gemini-3.5-flash-lite` equal or better than the cheaper alternative on its tasks and cost about $0.0004 to $0.0007 per output; the same model is a reasonable default. **No evidence exists that it performs well on audit or extraction tasks**: they need their own small benchmark (Phase 1) using the repo's `ai-eval` approach.
- **Search tasks** (GEO sampling): not the existing provider; a separate client per platform (§6). Keep the *answering* model separate from the *extraction* model: extract mentions with deterministic matching first and a cheap model only for ambiguous cases.
- **Prompt versioning**: every prompt and sampling configuration gets a version string stored on each run; a regression test pins the prompt hashes, as `test_ai_regression.py` does today. Changing a prompt changes the series, so a trend chart must break the line at a version change.

### 7.5 Evidence storage
- Store, per sample: platform, model identifier as returned, prompt version, the question text, approximate location sent, time, the **answer text** (needed to audit a false-positive mention), citations (URL, title), extracted mentions with the matched span, and status.
- Retention: 90 days for answer text, 13 months for derived rows (mention flags, citations). **Proposed**; DPDP and contract review pending (§12). Answers contain no customer personal data by design (questions are generic, never include a name), so the exposure is low.
- Website snapshots: store extracted facts and a content hash, and keep the raw text of the page for 30 days only so findings can show their evidence; do not retain full HTML.

### 7.6 Audit logging
Reuse `services/audit.py` for: audit started/finished, content draft created/approved/rejected, schema snippet generated/copied, GEO enabled/disabled, question bank edits, allowance changes. Changes proposed to Google go through `AgentAction`, which already keeps the tamper-evident history.

### 7.7 Usage metering
- AI inference: `metered(provider, db, tenant_id, kind)` with kinds `aeo_questions`, `aeo_audit`, `aeo_content`, `geo_extract`.
- Search calls: `usage.record(provider="openai_search"|"perplexity", operation=..., feature="geo_sample", units=1)`; prices in `API_PRICES` so a missing price is shown unpriced, never zero; a **counted monthly allowance** ("AI checks") enforced before each sample, in the same fail-closed style as maps (`limits.geo`). Add a platform-wide daily and monthly ceiling for GEO spend equivalent to `RANK_PLATFORM_*` caps, because the one existing control that fails *open* (`RANK_PLATFORM_MONTHLY_CAP = 0`) is a known weakness (`docs/COMMERCIAL_LIMITS_AND_COSTS.md` §4.3). New spending controls must **fail closed**.

### 7.8 Tenant isolation and RLS
Every new tenant table gets `ENABLE` and `FORCE ROW LEVEL SECURITY` with the standard policy and minimal grants; per-location tables carry `google_location_id` and are filtered through `ctx.can_access_location` exactly as `api/v1/seo.py` does. Add every new table to `services/account.py` `TABLES` and to deletion and retention jobs (the export omission has happened before). Category-level shared data (question templates, and the optional cross-tenant answer cache in §10.4) must contain no tenant identifiers and be readable but not writable by tenants.

---

## 8. Database design proposal

Proposal only; **no migration was created**. The migration number depends on merge order (`0036` is head here; `0037_cashfree_billing` is on an unmerged branch).

Mapping of the candidate entities you listed to the recommendation:

| Candidate entity | Recommendation | Reason |
|---|---|---|
| `business_knowledge_profiles` | **Do not create.** Extend `business_knowledge` (+ a small `knowledge_sources` table below). | `business_knowledge` already is the tenant's verified facts. A second table would create two sources of truth. |
| `ai_search_queries` | Create as `ai_questions` | New |
| `ai_visibility_runs` | Create | New |
| `ai_visibility_results` | Create as `ai_visibility_answers` | New |
| `ai_citations` | Create | New |
| `ai_competitor_mentions` | Create as `ai_entity_mentions` (self and competitors in one table, `is_self` flag) | One extraction, one table |
| `aeo_content_audits` | Create as `aeo_audits` + `aeo_findings` | A run and its findings are different cardinalities |
| `aeo_recommendations` | **Do not create.** Use existing `agent_tasks` (advice) and `agent_actions` (governed changes) | Already has state, approval, history, UI |

### 8.1 Extensions to existing tables
- `business_knowledge`: add `service_area` (text, for example "Gomti Nagar, Lucknow"), `languages_spoken` (text[]), `credentials` (JSONB `[{text, evidence_note, confirmed_at}]`, only owner-confirmed, used for schema and drafts), `website_pages` (JSONB list of up to 10 owner-approved URLs to audit). `faqs` already exists; add `source` and `confirmed_at` per item inside the JSON.
- `tenants.website` stays the primary URL.
- `billing_plans.features` and `limits`: new keys `aeo_audit`, `aeo_content`, `ai_visibility`, and `limits.ai_visibility = {questions, samples_per_month, platforms}`.

### 8.2 New tables (all tenant-scoped with RLS; `tenant_id` uuid FK to `tenants` ON DELETE CASCADE)

| Table | Key columns | Notes |
|---|---|---|
| `ai_questions` | `id`, `tenant_id`, `google_location_id`, `text` (<=200), `intent` (service/location/hours/price/trust/comparison), `service_ref`, `origin` (generated/owner/seeded_keyword/template), `language`, `tracked` bool, `approved_by`, timestamps; unique (`google_location_id`, normalised text) | The bank. Only `tracked = true` questions are sampled. |
| `question_templates` (no tenant) | `category_key`, `intent`, `pattern`, `language` | Curated by FlowQR; no tenant data |
| `knowledge_sources` | `tenant_id`, `field` (phone/hours/address/services/...), `source` (owner/gbp/website/schema), `value_hash`, `value_excerpt`, `observed_at`, `status` (agrees/conflicts/missing) | Output of the consistency check; drives §9's conflict list |
| `website_snapshots` | `tenant_id`, `url`, `fetched_at`, `status`, `http_status`, `content_hash`, `text_excerpt` (30-day), `facts` JSONB, `jsonld` JSONB, `robots` JSONB | No raw HTML retained |
| `aeo_audits` | `tenant_id`, `google_location_id`, `started_at`, `finished_at`, `status`, `score_inputs` JSONB, `prompt_version`, `triggered_by` | Visible formula, like `health.py`: components with no data are excluded, never zero |
| `aeo_findings` | `audit_id`, `key`, `severity`, `state` (ok/improve/missing/unknown), `evidence` JSONB (snippet, URL), `suggestion_ref` | Deterministic findings carry their evidence |
| `ai_visibility_runs` | `tenant_id`, `google_location_id`, `period` (date), `platform`, `status`, `planned_samples`, `done_samples`, `cost_usd_est`, `prompt_version` | One row per platform per scheduled run |
| `ai_visibility_answers` | `run_id`, `question_id`, `sample_no`, `platform`, `model`, `location_sent` JSONB, `answered_at`, `status`, `answer_text` (90-day), `latency_ms`, `usage_ref` | A failed sample stays a failed sample |
| `ai_citations` | `answer_id`, `url`, `domain`, `title`, `is_own_domain` bool, `is_competitor_domain` bool | Source-domain analysis |
| `ai_entity_mentions` | `answer_id`, `entity_name`, `is_self`, `place_id` (nullable, resolved match), `competitor_id` (nullable), `match_method` (place_id/domain/phone/name), `match_confidence`, `span` | False-positive control lives here |

Indexes: (`tenant_id`, `created_at`) on all; (`question_id`, `answered_at`) on answers; unique (`run_id`, `question_id`, `sample_no`) for idempotency.

---

## 9. Business Knowledge Profile, source of truth and conflicts

### 9.1 What it consolidates
Google profile (`gbp_snapshots.info`), website extraction (`website_snapshots`), categories, services (`review_context.services`), locations (`google_locations`), hours, owner-verified offers/prices, owner-confirmed credentials, FAQs, review themes (the existing keyword heuristic, labelled as such), contact details. Customer review themes are a **soft** signal only (a word-list count, `docs/AI_INTELLIGENCE.md` §5) and must never be turned into a claim ("customers say you are the best") in generated content.

### 9.2 Source-of-truth hierarchy
1. **Owner-confirmed fact in the Business Knowledge Profile.** The owner is the only party who can say what is true. A fact becomes "confirmed" by an explicit owner action with a date.
2. **Google Business Profile** for the operational fields customers see in Search and Maps (address, phone, hours, categories, services). It is the default *proposed* truth for these because FlowQR can already read it, and the owner already maintains it.
3. **The business's website**, owner-controlled but not editable by FlowQR.
4. **Structured data on the website**, which must be a mirror of (3).
5. **Third-party listings and AI answers**, observed only; never a source of truth (an AI answer that is wrong is a *finding*, not an input).

### 9.3 Conflict resolution (never automatic)
Detect (normalised comparison; phone to E.164, hours to a canonical week, address token match) → classify (**agree / conflict / only-in-one / unknown**) → show both values with where they came from and when → the owner picks the winner → FlowQR drafts the fix for the losing side (GBP edit through the existing approval executor; website text as copy-ready; schema regenerated from the winner). The result is written back with a date. A value FlowQR could not read is "unknown", never "missing".

### 9.4 Checks specified by exact field
Phone, address, opening hours (including holiday hours), primary and additional categories vs services listed, business name (exact; **never suggest adding keywords**, Google's guideline already enforced by `optimizer.py`), website URL, languages, price list vs `offers`, and "claims on the website that are not in `approved_claims`" (the last one is a flag for the owner, not a judgement).

---

## 10. AI provider and API cost analysis

### 10.1 What each task needs

| Task | Provider | Why | Cost driver |
|---|---|---|---|
| Question generation, audit synthesis, FAQ/content drafts | Existing LLM layer (Gemini Flash-Lite class) | Reuse, benchmarked, metered | Tokens |
| Website parsing, JSON-LD extraction, robots check | None (code) | Deterministic | Compute |
| Structured-data audit | None, Google's published property rules in code | Deterministic | Compute |
| AI answer sampling | OpenAI `web_search`, Perplexity Agent API | The only two with official, location-aware, cited-answer APIs whose use for this purpose is not clearly prohibited by terms read so far | Tool calls + tokens |
| Citation extraction | None; API fields | Structured annotations | none |
| Mention / competitor extraction | Deterministic matching first; Flash-Lite for ambiguous | Cost and false-positive control | Tokens |
| Competitor content analysis | Place Details (Google) for the website URL, then the same fetcher | **Place Details SKU/price for `websiteUri` unverified** | Google billing |

Rejected: Gemini grounding and Grounding with Bing for monitoring (terms, §6); any scraping or browser automation.

### 10.2 Unit costs and the assumptions that produce them

Inputs verified in §6. Derived estimates are **Assumptions** and shown with ranges.

| Unit | Low | Base | High | How |
|---|---|---|---|---|
| OpenAI sample (1 to 3 search calls at $0.01 each + about 8k search tokens + 600 output) | $0.03 | **$0.04** | $0.06 | The model actually recommended for web search has no captured price; `gpt-5-search-api` ($1.25 / $10 per 1M) is used as the stand-in. **Unknown until priced on the day.** |
| Perplexity sample (1 to 3 searches at $0.0025 + `sonar` tokens) | $0.006 | **$0.010** | $0.012 | Agent API tool price + `perplexity/sonar` price |
| Extraction per sample (Flash-Lite, about 2k in / 300 out) | | **$0.001** each platform | | $0.30 / $2.50 per 1M |
| Exchange rate | | **₹90 per USD** | | **Assumption.** `USD_INR_RATE` is unset in this repo. |
| **Both platforms, one question, one sample** | **₹3.4** | **₹4.7** | **₹6.7** | OpenAI-only ₹3.7, Perplexity-only ₹1.0 |
| AEO full audit cycle (questions + audit + FAQ drafts, +30% for retries as measured in `ai-eval`) | | **about $0.02, ₹1.8** | | Flash-Lite tokens |

Not included (not priced because not decided): hosting for the fetcher and extra worker, monitoring tools, support, payment fees, GST treatment, the Google Place Details calls for competitor sites, and engineering.

### 10.3 Cost by usage pattern, per business per month (base)

| Pattern | Query-samples a month | Cost ₹ | Share of ₹499 / ₹799 / ₹1,499 |
|---|---|---|---|
| Monthly, 5 questions, 3 samples | 15 | **70** | 14% / 9% / 5% |
| Every 2 weeks, 5 questions, 2 samples | 22 | 101 | 20% / 13% / 7% |
| Monthly, 10 questions, 3 samples | 30 | 140 | 28% / 18% / 9% |
| Weekly, 10 questions, 2 samples | 87 | 406 | 81% / 51% / 27% |
| Weekly, 20 questions, 3 samples | 260 | 1,217 | 244% / 152% / 81% |

The last two show why GEO cannot be left uncapped.

### 10.4 Fleet estimates, 100 / 1,000 / 10,000 businesses

Customer mix (**Assumption**): 40% Launch, 40% Growth, 20% Scale, revenue ₹499 / ₹799 / ₹1,499 before GST and payment fees. Allowances (proposal, §11): Growth 15 query-samples a month, Scale 60, Launch none. Launch gets a half-weight AEO audit.

| Scenario | Businesses | Monthly revenue ₹ | Monthly AI-search cost ₹ | Per business per month ₹ | % of revenue |
|---|---|---|---|---|---|
| **AEO only** (no GEO) | 100 | 81,900 | 141 | 1.4 | 0.2% |
| | 1,000 | 8,19,000 | 1,411 | 1.4 | 0.2% |
| | 10,000 | 81,90,000 | 14,112 | 1.4 | 0.2% |
| **Expected GEO** (50% of Growth and 70% of Scale enable it, using 70% of the allowance), base cost | 100 | 81,900 | 3,876 | 38.8 | 4.7% |
| | 1,000 | 8,19,000 | 38,758 | 38.8 | 4.7% |
| | 10,000 | 81,90,000 | 3,87,576 | 38.8 | 4.7% |
| Expected GEO, **high** unit cost | 100 / 1,000 / 10,000 | | 5,456 / 54,558 / 5,45,580 | 54.6 | 6.7% |
| **Worst case** (everyone enables and exhausts the allowance), base | 100 / 1,000 / 10,000 | | 8,565 / 85,651 / 8,56,512 | 85.7 | 10.5% |
| Worst case, **high** unit cost | 100 / 1,000 / 10,000 | | 12,129 / 1,21,291 / 12,12,913 | 121.3 | 14.8% |

The cost is linear: **10,000 businesses cost 100 times 100 businesses.** There is no volume discount assumed (none was found). Possible reductions, each unproven: sharing one sample across businesses that ask the same question about the same place (low overlap expected for long-tail local queries; requires platform terms to allow cross-customer reuse); cheaper `fast` search type on Perplexity ($1.00 vs $2.50 per 1,000); dropping the OpenAI proxy if Phase 0 shows it adds nothing over Perplexity (then ₹1.0 a sample).

For context, existing spend per business is not small: the repo's own Places figure (Google's global list price $32 per 1,000 text searches, **to be confirmed for India**, `docs/LOCAL_SEO_ARCHITECTURE_PROPOSAL.md` §4.2) makes ten tracked keywords checked weekly about 43 calls, roughly ₹125 a month, before AI reply and post costs. New GEO cost stacks on that.

### 10.5 Unknowns that need verification before any price is set
1. OpenAI price of the model to use for `web_search`, and OpenAI's current terms for monitoring-type use (terms not read).
2. Perplexity Acceptable Use Policy, Search Service terms and third-party-model terms (not read), and Sonar Pro / current model prices.
3. Google Place Details price for the `websiteUri` field in India.
4. Whether answers for local queries from these APIs name small Indian businesses at all (Phase 0).
5. Rate-limit tier needed for the volume (Perplexity tiers by cumulative spend).
6. GST and payment fee treatment of the margin.

---

## 11. Commercial model

Prices are **not** changed. Everything below is entitlement design plus an add-on hypothesis to test.

### 11.1 Entitlement proposal

| | Launch (₹499) | Growth (₹799) | Scale (₹1,499) |
|---|---|---|---|
| Business Knowledge Profile + consistency check | Yes | Yes | Yes |
| Website answer-readiness audit | Monthly, own site, home page + 2 | Monthly, up to 10 pages, on demand once a week | Same plus all locations |
| Crawler-access and structured-data checks | Yes | Yes | Yes |
| Schema snippets (verified facts only) | Basic LocalBusiness | + Service, Offer | Same |
| Question bank | 10 questions | 50 | 150 across locations |
| AI FAQ and content drafts | Within existing AI allowances (new `kind`, no counted quota in the confirmed terms) | Same | Same |
| **AI answer checks (GEO samples) a month** | **0 (read-only guide, "check it yourself")** | **15** | **60** |
| Platforms | | Perplexity first; OpenAI proxy if Phase 0 shows value | Both |
| Competitors in AI answers | | Top 3 names | Up to the 5 pinned |
| Extra checks | | **Paid add-on** | **Paid add-on** |

Which capabilities carry recurring vendor cost: only the GEO sampling (₹1 to ₹4.7 a sample). Everything else costs a few rupees a month or nothing.

### 11.2 Add-on or included?
GEO monitoring should be an **allowance with a visible meter plus a paid pack**, because usage is the cost. A pack of 60 samples costs ₹281 at base cost (₹400 high). To keep cost at or below 35% of its price: **₹800 at base, about ₹1,150 at high cost**. At 50% margin, ₹560 to ₹800. These are formula results, not a recommended price: the right price depends on what Phase 0 shows customers value and on the unpriced items in §10.5. Charge **by checks (question-samples)** rather than by location or tracked question alone, because cost scales with checks; a location or question cap still keeps the interface simple. Offer first to Scale customers and measure use before widening.

### 11.3 Frequency
- Questions that matter: weekly sampling is needed only for trend charts; most local businesses will not change their AI footprint week to week. Default **monthly with 3 samples**, **every 2 weeks** on Scale. More frequent runs add cost without adding information, given sampling noise.
- AEO website audit: monthly plus on demand (rate-limited).
- Crawler-access check: with every audit.

### 11.4 Gross margin sense-check
Expected incremental AI-search cost is 4.7% to 6.7% of revenue; worst case 10.5% to 14.8% (§10.4), before the unpriced items and existing costs. That is sustainable *only* with hard caps, fail-closed spending ceilings and a meter the customer can see. Without caps, a single enthusiastic Growth customer can cost more than they pay (weekly, 20 questions, 3 samples: ₹1,217 against ₹799).

### 11.5 Customer expectations
Sell *"understand and improve how clearly your business shows up"* and *"see where AI answers mention you"*. Never sell rankings, guarantees or "AI ranking". Every screen carries the disclaimer in §13.

---

## 12. Security and compliance considerations

1. **SSRF is the main new attack surface.** FlowQR would, for the first time, fetch a URL a user typed. Required: allow `http`/`https` only; resolve DNS and **block private, loopback, link-local, metadata and reserved ranges, including after every redirect and on every DNS rebinding retry**; cap redirects, response size (for example 1 to 2 MB), time and total pages; do not send credentials or cookies; fixed identifying User-Agent with a contact URL; fetch from a worker with no access to internal services; per-tenant and global rate limits. Add adversarial tests (`127.0.0.1`, `169.254.169.254`, decimal/octal IPs, redirects to internal hosts, huge bodies, slow-loris). Building this *before* any other AEO code is a Phase 1 gate.
2. **Respect `robots.txt`** for any site that is not the customer's own. For the customer's own site, fetch with their consent (they supply the URL) but still honour reasonable rate limits; still report if `robots.txt` blocks our own audit.
3. **Competitor websites**: fetching public pages is lawful in most analyses, but robots, terms of those sites and Indian law have not been reviewed here. **Treat competitor content analysis (H1) as needing legal sign-off**, and start with names, ratings and cited URLs only.
4. **Prompt-injection from fetched pages and AI answers.** Page text and answers are untrusted. Never place raw page text in an instruction position; pass it as quoted data, ask for structured output only, and never let model output trigger actions without the existing approval step. The existing review pipeline already keeps review text out of other prompts for this reason (`docs/AI_INTELLIGENCE.md` §2); the same discipline applies.
5. **Content truthfulness.** Generated text is built only from `business_knowledge` and verified website facts (same "if it is not listed, do not state it" rule), carries per-sentence source tags, and requires owner approval. Health businesses keep the existing prohibitions (no outcomes, no patient confirmation, no "best", no invented credentials). **Owner approval is a hard gate**: nothing is published, nothing is shown as FlowQR's claim.
6. **Vendor terms.** Read and record: OpenAI service terms and usage policies; Perplexity AUP and Search Service terms; confirm that automated, scheduled, multi-tenant querying and storing outputs for 13 months is permitted; confirm customers' business names and questions as inputs are acceptable. Do not start Phase 2 before this is on file.
7. **Data protection.** The data is business information, not personal data, but owners' names and phone numbers appear in business facts; questions must not contain personal data; no review text is sent to a search platform. Update the privacy notice for "we send generic questions about your business type and area to AI search providers". Retention proposals in §7.5 need the same lawyer review already pending for other retention decisions (`docs/DATA_RETENTION.md` §6).
8. **Secrets.** New API keys server-side only, in `.env.production`, never logged, never returned; per-provider restricted keys; separate keys for development and production. (The project's history shows keys pasted into chat; the plan should include creating dedicated keys, not reusing existing ones.)
9. **Abuse.** A user must not be able to point the fetcher at arbitrary sites for reconnaissance: restrict the audit to the tenant's own registered domain plus owner-approved pages on that domain (and up to N pinned competitor domains), not any URL.
10. **Spam policy.** Google lists attempts to manipulate generative AI responses as spam. Do not build hidden text, doorway pages, auto-generated reviews or mass low-value pages. Every recommendation must be something that helps a human reader.

---

## 13. Risks and limitations, with safeguards

| Risk | Detail | Safeguard |
|---|---|---|
| **AI response variability** | Identical prompts return different answers and different named businesses | Always sample N≥3; report "appeared in k of n"; show the range, never a single "position"; store the answers for audit |
| **Location and language dependence** | `user_location` is approximate (OpenAI) or absent (Gemini); Hindi/Hinglish questions may behave differently | State the location sent on every result; test English and Hinglish separately in Phase 0 |
| **Personalisation** | A person's history changes what they see; API calls are neutral | Disclaimer: "an example check, not what everyone sees" |
| **Platform access restrictions** | Terms and prices change (several vendor models and prices changed in 2026) | Provider abstraction, per-platform kill switch, prices in config, monthly review of the vendor changelogs |
| **Unavailable APIs** | No Copilot or AI Overviews API | Say so on the screen: "AI Overviews and Copilot can't be measured by any tool we can use. Here is how to look yourself." |
| **Inconsistent citation data** | Citations may be absent, bare domains, or redirect links | Store as returned; normalise domain; never infer a citation that was not returned |
| **False-positive mentions** | A competitor with a similar name, a chain, a business with a common name | Resolve by `place_id`, domain, phone, then name+area; keep `match_method` and confidence; low-confidence matches shown as "possible", excluded from counts; show the span |
| **Hallucinated information about the business in answers** | An answer may state wrong hours or services | Compare facts in the answer with the confirmed profile; surface as "AI is saying something incorrect about you" with the evidence; **never** auto-correct anything |
| **Competitor data accuracy** | Places ratings change; names ambiguous | Date every observation; only claim differences between two real dated observations (the existing competitor service already does this) |
| **Provider price changes** | Prices doubled or changed on dated schedules this year (for example Gemini 3.8 Flash input $0.75 to $1.50 per 1M from 1 Jan 2027) | `API_PRICES` in config; budget alerts; allowance units are "checks", not dollars, so a price change moves margin not entitlement |
| **Customer expectations** | "Rank", "guarantee", "make ChatGPT recommend us" | Language rules in §14; no scoring that implies rank; sales copy review |
| **Unreliable metric (the big one)** | Proxy results may rarely name small local businesses at all | Phase 0 gate (§15); if it fails, ship AEO only |
| **Measuring noise as progress** | Weekly dips and rises are noise | Do not draw trend arrows before enough samples; require a minimum of 4 periods before showing "up" or "down" |
| **Legal exposure of generated claims** | A generated service-page sentence turns out false | Source tags; owner approval; audit log; prohibited-claim lists |
| **Cost overrun** | Uncapped runs | Fail-closed allowance, platform daily and monthly ceiling, per-run budget pre-check, alerts like `ops-watch` |

**Reporting disclaimer (proposed wording, shown wherever AI results appear).** *"This shows what an AI search tool answered when we asked it a question like your customers might, at the time shown and for the place shown. AI answers change from one moment and one person to the next. This is not a ranking and not a guarantee that AI will, or won't, mention your business. Changes to your website and profile can help AI tools understand your business, but nobody can promise what an AI tool will say."*

---

## 14. UI and UX proposal

### 14.1 Placement
**A new destination, "AI Search", not a subsection of GBP.**
- The existing GBP destination (`/seo`: Overview, Rankings, Performance, Profile) is about Google Business Profile. AEO's centre of gravity is the **website** and the **facts that must agree across places**, and GEO is about **AI tools**, neither of which belongs under a label that says "Google Business Profile".
- The phone bottom bar is already full (Home, Reviews, GBP, Growth + More). The new destination appears in the sidebar and in More on phones. Do not add a fifth bottom tab.
- Cross-links keep the products joined: the GBP checklist links "Make sure your website says the same" into AI Search; AI Search links "fix on Google" back to GBP editors.

Sidebar entry: **AI Search** ("Is your business easy for AI to understand?"). Second-row tabs (at most four, per the nav rule): **Overview · Questions · Website · Competitors**. The six-page structure in the brief maps like this:

| Brief | Where it lives |
|---|---|
| Overview | Overview |
| AEO Audit | Website |
| AI Mentions | Overview (summary) and Questions (per question) |
| Citations | Overview ("Websites AI references") and Competitors |
| Competitors | Competitors |
| Recommendations | Overview ("What to improve next") and the existing Tasks & Approvals |

### 14.2 Plain-language names (no jargon on screens)
| Concept | On screen |
|---|---|
| AEO / GEO | not shown; the section is "AI Search" |
| Mentions | "AI named your business" |
| Citations | "Websites AI references" |
| Visibility | "Where AI finds your business" |
| Question bank | "Questions your business can answer" |
| Audit | "Is your website ready?" |
| Competitor mentions | "Competitors appearing instead" |
| Recommendations | "What you should improve next" |

### 14.3 Screens (wireframes in words; follow `docs/DESIGN.md`: 16px cards, orange only as the single highlight, no gradients, no glass, no decorative charts, status always with words)

**Overview**
1. One sentence of state: *"We last checked on 12 Nov. Not enough checks yet to show a trend."* or *"Your website hasn't been checked yet."*
2. **Where AI finds your business**: a plain table of the questions checked: question, platform, **"named you in 2 of 3 checks"**, date, link. If no data: "No checks yet." Never a percentage without its denominator.
3. **Websites AI references**: list of domains cited, with count, own site flagged.
4. **Competitors appearing instead**: top names with counts.
5. **What you should improve next**: up to 3 items, each with the evidence ("Your website doesn't show opening hours; your Google profile does"), a button to fix it.
6. Footer: disclaimer text from §13.

**Questions**: list grouped by intent with a tracked toggle; "add your own"; each row expands to the stored answers with the matched span highlighted. The AI-suggested questions are drafts the owner accepts.

**Website**: readiness checklist with states ok / improve / missing / unknown (the same visual pattern as `/seo/profile`), crawler-access result (*"ChatGPT's search crawler is allowed / blocked"*), "Facts that don't match" list (§9.3), generated schema snippet with a copy button and the plain explanation of what it does and does not do (*"This helps computers read your page. It doesn't guarantee anything."*).

**Competitors**: the pinned competitors already shown in GBP > Rankings, with how often each was named in AI answers and which sites were cited next to them.

### 14.4 Rules
- Nothing is shown that was not measured. An unmeasured state is "Not checked yet", not 0.
- No composite "AI score". If a score is wanted later it must be the visible-formula pattern from `health.py`, not an invented index.
- Show the date, the place and the platform on every result.
- Hinglish and Hindi labels follow the app's existing language switching.

---

## 15. Implementation roadmap

Effort is engineer-weeks for one full-stack engineer familiar with the codebase, including tests; **estimates with a plausible error of ±40%**, not commitments. External costs exclude engineering.

### Phase 0: feasibility and dependencies (1 to 2 weeks)

**Deliverables:** a short written result with go/no-go on GEO.
1. Run the website-share query (`tenants.website`), and count how many have a working URL (script fetching nothing but their own home page with the SSRF-safe fetcher prototype).
2. **Measurement spike** (throwaway script, not product code): about 40 questions (English and Hinglish) across 5 pilot businesses in Lucknow/other cities (including the owner-authorised test profile), 3 samples each, on OpenAI `web_search` and Perplexity. Record: how often a pilot business is named; agreement between repeated samples; how often the named businesses match the Places top 3 for the same query; citation quality.
3. Legal read of OpenAI and Perplexity terms for scheduled, multi-tenant monitoring and output storage.
4. Confirm Place Details price for the website field; confirm Bing Webmaster has no API; check a real Search Console property for a separate AI report.
5. Confirm bot names (Bingbot, PerplexityBot) in each vendor's docs.

**Files/modules:** none in the application (scripts under `scratchpad` or `backend/scripts` outside the app).
**Database:** none. **API dependencies:** OpenAI and Perplexity keys (dedicated, spend-capped). **External cost:** about 40 questions x 3 samples x 2 platforms = 240 samples at ₹3.4 to ₹6.7 = **₹800 to ₹1,600**; budget cap ₹5,000.
**Testing:** none beyond recording raw outputs.
**Acceptance criteria (proposed thresholds, my judgment; set them before running):** (a) at least one platform names a pilot business that is in the Places top 3 for the same query in **at least 30% of questions in at least one of three samples**; (b) the same business is named in **at least 2 of 3 repeats** in at least half of the cases where it was named once; (c) citations are present on at least 80% of answers; (d) the legal read does not forbid the use. **If (a) or (b) fails, drop GEO monitoring and ship AEO only** (or evaluate a documented third-party data vendor).
**Risks:** pilot sample is small and biased towards businesses we know; a pass is permission to build Phase 2, not proof of customer value.

### Phase 1: AEO foundation (7 to 9 weeks)

**Deliverables:** Business Knowledge Profile + consistency checks; SSRF-safe fetcher; website readiness audit; crawler-access check; structured-data read and generation; question generation and bank; first UI (Overview/Questions/Website tabs without GEO).
**Files/modules likely to change:** new `backend/app/services/aeo/*`, `models/aeo.py`, `schemas/aeo.py`, `api/v1/aeo.py`; `models/agent.py` (knowledge fields), `services/plans.py` (new features), `services/account.py` (`TABLES`), `workers/{celery_app,tasks}.py`, `api/v1/seo.py` (cross-link data), `core/config.py` (fetcher limits), `requirements.txt` (an HTML parser: **a choice to make then, nothing installed now**), frontend `app/(app)/ai-search/*`, `components/ai-search/*`, `lib/nav.ts`, `lib/types.ts`, onboarding Business Brain page for new fields.
**Database changes:** new tables `ai_questions`, `question_templates`, `knowledge_sources`, `website_snapshots`, `aeo_audits`, `aeo_findings`; additive columns on `business_knowledge`; plan feature keys via the plans table. One additive migration; RLS and grants like `0036`.
**API dependencies:** none external except the existing LLM provider. **External cost:** about ₹1.4 per business per month (AI) plus hosting for fetcher traffic; negligible.
**Estimated effort:** about 8 weeks (fetcher + SSRF tests 1.5, extraction + structured data 2, audit and consistency 2, questions 1, UI 2.5, tests/hardening 1).
**Testing requirements:** SSRF adversarial suite; extraction fixtures from at least 25 real small-business sites (static, WordPress, Wix, JS-only, no site, blocked by robots, huge, slow); tenant-isolation tests for every new table and endpoint; export/delete coverage; deterministic findings snapshot tests; AI benchmark for question generation and audit synthesis on the repo's `ai-eval` pattern with invented businesses and a human rating sheet; Playwright for the pages; health-business safety tests (no invented credentials/outcomes); schema validity tests against Google's published required properties.
**Acceptance criteria:** an owner with a website gets, within 60 seconds, a findings list where every finding shows its evidence; a business with no website gets a useful "no website" path rather than an empty page; no fetch can reach a private address in any test; no generated sentence appears that is absent from verified facts (checked by the existing fact-check approach); AggregateRating/Review markup never generated; every generated item requires owner approval; the cost per audit is recorded in the ledger.
**Risks:** JS-rendered sites look empty (state this, do not guess); extraction brittleness; the audience (businesses with a site) may be smaller than hoped (Phase 0 number); effort underestimated for the fetcher.

### Phase 2: GEO monitoring (5 to 7 weeks) *(only if Phase 0 passed)*

**Deliverables:** OpenAI and Perplexity clients; scheduled sampling; mention, citation and competitor extraction; allowance and spending controls; Overview "Where AI finds your business"; per-question answers view.
**Files/modules:** new `services/geo/*`; `models/aeo.py` additions; `services/usage.py` (new provider constants); `services/ai_usage.py` (new kinds); `services/plans.py` and `billing_plans.limits.ai_visibility`; `workers/*`; `ops` admin pages for GEO spend (like "Geo-grid maps" in Admin > Operations); frontend Overview/Questions.
**Database:** `ai_visibility_runs`, `ai_visibility_answers`, `ai_citations`, `ai_entity_mentions`; retention job.
**API dependencies:** OpenAI Responses API; Perplexity Agent API. Dedicated, restricted, spend-capped keys.
**External cost:** per §10, about ₹1 to ₹4.7 per sample; platform ceilings from day one.
**Estimated effort:** about 6 weeks (clients 1.5, extraction and matching 2, scheduling and controls 1.5, UI 1.5, hardening included).
**Testing requirements:** clients against recorded responses and a mock transport (the repo's pattern), including every error class and 429 `Retry-After`; **budget never exceeded** property tests (concurrent runs, retries, idempotency); entity-matching test set with look-alike names and chains; prompt-version hash regression test; kill-switch test; tenant isolation; a live validation stage in the style of `docs/LIVE_VALIDATION_RUNBOOK.md` with a spend cap.
**Acceptance criteria:** no sample without a reservation in the allowance and the platform ceiling (fails closed when either is unset); a failed sample never reads as "not mentioned"; every mention shows its answer text and matched span; no rank or percentage without its denominator; documented per-platform disclaimers; cost per sample recorded and reconciled with the vendor invoice within 10% after the first month.
**Risks:** unstable APIs and prices; terms change; mention precision lower than assumed; customers expect rankings.

### Phase 3: competitor intelligence (3 to 4 weeks)

**Deliverables:** competitor names found in AI answers linked to pinned/Places competitors; cited-domain comparison; historical comparison; (optional, legal sign-off) competitor website facts.
**Files:** `services/geo/matching.py`, `services/competitors.py` (link table), `api/v1/seo.py`, frontend Competitors tab.
**Database:** a join table `competitor_ai_links` (or `competitor_id` on mentions, already in §8); optional `competitor_site_snapshots` if H1 approved.
**API dependencies:** Place Details (billed) for competitor website URLs only if H1 goes ahead.
**External cost:** unknown until the Place Details price is verified.
**Estimated effort:** 3 to 4 weeks. **Testing:** matching accuracy set; "absence is not zero" tests carried over from `test_competitors_pinned.py`.
**Acceptance criteria:** a difference is reported only between two real dated observations; unmatched names are shown as unmatched, never forced onto a competitor.
**Risks:** low match rates; legal limits on competitor content.

### Phase 4: AI Growth integration (4 to 5 weeks)

**Deliverables:** recommendations as `AgentTask`/`AgentAction`; owner-approved content (FAQ, descriptions, service text, schema); Google Business Profile description updates through the existing executor; "what to improve next" ranking by evidence; reminders for freshness.
**Files:** `services/agent/plan.py`, `executor.py`, `autonomy_policy.py` (new action types and their policy), `services/aeo/content.py`, frontend Tasks & Approvals.
**Database:** new `action_type` values; `ai_outputs` rows for acceptance-rate measurement of the new content types.
**Testing:** approval-required tests for every new action type; autonomy policy tests (new action types default to approval, never auto); no-publish-without-approval tests; the emergency stop holds them.
**Acceptance criteria:** no new action type is allowed to execute without approval until validated live on a test profile; content acceptance rate is measured (`ai_outputs`) and reviewed before widening.
**Risks:** the only automated publishing channel is Google Business Profile; for the website the product is advice and copy-paste, which limits perceived value.

### Effort summary

| Phase | Engineer-weeks | Likely range |
|---|---|---|
| 0 Feasibility | 1.5 | 1 to 2 |
| 1 AEO foundation | 8 | 6 to 11 |
| 2 GEO monitoring | 6 | 4 to 9 |
| 3 Competitors | 3.5 | 2 to 5 |
| 4 AI Growth integration | 4.5 | 3 to 6 |
| **Total** | **about 23.5** | **about 16 to 33** |

Not included: legal review time, design iteration, support readiness, the Google Business Profile approvals that block live validation of anything touching Google writes, and the project's existing unfinished launch items.

---

## 16. Final recommendation

**Is this genuinely feasible to build as a commercially viable FlowQR feature?** In two halves, with different answers.

### AEO: yes, feasible and worth building, with modest claims
- **It is cheap**: about ₹2 per business per month in AI cost. The reusable foundation is strong (knowledge base, AI safety, metering, approvals, scheduling, UI).
- **It is real work**: the website fetcher, parser, SSRF defence, structured-data tooling and consistency engine do not exist. Budget about 8 engineer-weeks for Phase 1, not a few days.
- **Its value is clarity, not ranking.** Google says no special AEO exists for AI Overviews, FAQ rich results are gone, and the review markup that would be the most tempting is prohibited. The defensible product is "your facts are complete, consistent and readable, and ChatGPT's and Google's crawlers can reach your site". For a small local business that is genuinely useful, and the consistency check across Google profile, website and owner facts is the part nobody else shows them.
- **The audience may be smaller than it looks**: it applies only to businesses with a working website. That number is one query away and has not been run. Do not commit until it is.

### GEO: conditional, and the weaker half
- **Reliable measurement of the four named platforms is not possible.** Two (Google AI Overviews/AI Mode and Copilot) cannot be measured with any lawful tool I could verify; one (ChatGPT) can only be approximated by a different API product; one (Perplexity) can be queried officially and is the closest thing to real. Gemini-grounding and Bing-grounding APIs exist but their terms prohibit the use. Anyone who sells "AI Overviews rank tracking" is using methods this study was told not to propose.
- **It is expensive per unit and does not shrink with scale**: ₹1 to ₹4.7 a sample, linear to 10,000 businesses. Weekly, multi-sample monitoring of ten questions would eat half a Growth plan. Only a capped allowance plus a paid add-on is sustainable.
- **It may not be informative.** Whether these tools name small tier-2 Indian businesses for local queries is untested. If they rarely do, a visibility metric of "named in 0 of 3 checks" for nearly everyone is noise and would damage trust.
- **It risks over-promise.** Customers already expect rankings. A dashboard that shows variable, sampled, proxy data needs strong wording or it generates support load and refunds.

### Decision
| Item | Decision |
|---|---|
| Phase 0 (1 to 2 weeks, about ₹800 to ₹1,600 of API spend) | **Do it first.** It resolves the two questions that decide everything: audience size and metric informativeness |
| Phase 1 AEO | **Go**, after Phase 0 confirms enough businesses have a website. Ship as Growth and Scale, reduced Launch |
| Phase 2 GEO | **Conditional go**: only if the Phase 0 gate passes and the vendor terms are cleared in writing. Ship as capped allowance + paid pack, Scale first |
| Phase 3 competitors | After Phase 2; names and cited domains only until competitor-content fetching is legally reviewed |
| Phase 4 growth integration | Proceed with Phase 1 content; extend to GEO findings after Phase 2 |
| Gemini grounding, Bing grounding, Copilot, AI Overviews tracking | **No-go** |
| Scraping, browser automation of AI products, anti-bot evasion | **No-go** |
| Rank/guarantee language, auto-generated review or rating markup | **No-go** |

If Phase 0 shows the proxy metric is uninformative, **the right outcome is to ship AEO alone**, which is still a coherent, low-cost feature, and say plainly that AI-answer measurement is not yet reliable enough to sell.

---

## Appendix A. Assumptions made in this document

| # | Assumption | Effect if wrong |
|---|---|---|
| 1 | ₹90 per USD (repo has no rate set) | Costs scale proportionally |
| 2 | OpenAI sample $0.03 to $0.06, base $0.04; the actual web-search model's price was not captured | Could move GEO unit cost up or down by half |
| 3 | Perplexity sample $0.006 to $0.012 | Small |
| 4 | Customer mix 40/40/20 Launch/Growth/Scale | Revenue and cost shares change |
| 5 | 50% of Growth and 70% of Scale enable GEO and use 70% of allowance (expected case) | Expected cost scales |
| 6 | Prices before GST and payment fees | Real margin lower |
| 7 | Retention 90 days (answers) and 13 months (derived) | Needs legal review |
| 8 | Effort figures ±40% | Planning range only |
| 9 | Phase 0 acceptance thresholds (30%, 2-of-3, 80%) are judgment, set before the run | Adjust before, never after |
| 10 | Plans named Launch/Growth/Scale = codes `starter`/`growth`/`pro` | Names are applied by an unmerged migration |

## Appendix B. Sources read on 2026-11-17

**Official (fetched):**
- OpenAI web search guide, pricing and crawler pages (`developers.openai.com/api/docs/guides/tools-web-search`, `/pricing`, `/bots`; the `platform.openai.com` URLs redirect there).
- Gemini API grounding guide, pricing and terms (`ai.google.dev/gemini-api/docs/google-search`, `/pricing`, `/terms`; redirect to `aistudio.google.com/docs/...`).
- Perplexity docs: overview, pricing, Search API, Agent API, migration from Sonar, rate limits, changelog; Consumer Terms and API Terms of Service (`docs.perplexity.ai`, `perplexity.ai/hub/legal/...`).
- Microsoft: Grounding with Bing Search (Foundry docs, pricing, grounding legal and enterprise terms), Bing Search APIs retirement notice (`learn.microsoft.com/en-us/lifecycle/announcements/bing-search-api-retirement`), "Introducing AI Performance in Bing Webmaster Tools Public Preview" (10 Feb 2026, `blogs.bing.com/webmaster`).
- Google Search Central: AI features and your website; structured data general guidelines; LocalBusiness; review snippet; spam policies; Search Console Search Analytics `query` reference; Search Console help for performance data; documentation updates changelog (FAQ rich result removal).

**Third-party (used only to know what to verify; no claim in this document rests on them alone):** news and blog coverage of Bing Search API retirement, Search Console AI Mode reporting, Bing AI Performance additions, and OpenAI/Perplexity/Gemini pricing.

**Not read, and needed before building:** OpenAI service terms and usage policies; Perplexity Acceptable Use Policy and Search Service terms; the PerplexityBot and Bingbot crawler documentation; Google Place Details pricing for India; Microsoft Copilot developer documentation beyond one page that returned 404.

**In-repo sources:** the technical audit's §2 lists every file.
