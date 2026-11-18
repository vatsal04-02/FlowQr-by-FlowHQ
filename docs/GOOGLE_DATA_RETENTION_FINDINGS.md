# Google data retention: what the policies say, what FlowQR stores, what is unresolved

Status: **LAUNCH BLOCKER (decision D3, 2026-11-17). No retention job was written, because the governing wording is unresolved for most data types and the instruction is to escalate rather than guess.** Read on 2026-11-17 from Google's own pages (quotes are short and verbatim; Google can change them at any time). Not legal advice.

## 1. What Google's documents actually say

| Source | Verbatim fragment | Applies to |
|---|---|---|
| Business Profile API Policies, "Content storage" (`developers.google.com/my-business/content/policies`) | "You cannot pre-fetch, cache, index, or store any content provided through the Business Profile APIs ("Content") for use outside of your Business Profile project except for limited amounts of Content." | "Content" is defined as any content provided through the Business Profile APIs. **The page lists no exception or separate rule for reviews, profile data, performance data or search keywords.** |
| same | "You can store limited amounts of Content only to improve the performance of your project." | purpose limit |
| same | "It must be stored temporarily for no more than 30 calendar days." "It must be stored securely." "It cannot be manipulated or aggregated in any way." | the three conditions on stored Content |
| same | "At no time may you store Content in order to prevent Google from tracking usage of your" project | |
| same, "Automated use" | "you must not automate or trigger review replies, Q&As, listing creations, listing edits, or other actions without the user's prior specific and express consent." and "You may not use the Business Profile APIs to automatically revert changes made by Google." | consent (implemented: Milestone 2) |
| same, "Termination of end-client relationship" | "you have seven business days to provide them the ability to disassociate" ... "you must also relinquish and remove those permissions" | disconnect |
| Business Profile API Terms (`.../content/terms`) | precedence only: Business Profile Terms, then API Policies, then Google APIs Terms of Service | no retention clause |
| Business Profile Terms of Service (`support.google.com/business/answer/9292476`) | no API retention, caching or deletion clause found | |
| Google APIs Terms of Service (`developers.google.com/terms`), 5.e and 8.b | "Scrape, build databases, or otherwise create permanent copies of such content" and "or keep cached copies longer than permitted by the cache header" are prohibited; on termination "delete any cached or stored content that was permitted by the cache header" | general |
| API Services User Data Policy | Limited Use rules "apply to the raw data obtained from the scopes and data aggregated, anonymized, or derived from them"; "The data (including derivations) is aggregated and used for internal operations" | **Applies to "Sensitive and Restricted Scopes". The pages read do not say whether `business.manage` is one.** Unresolved. |
| Review rules (`support.google.com/business/answer/7400114`) | no incentives for reviews, no discouraging negative reviews or selectively soliciting positive ones, no fake engagement | conduct, not retention |
| Places API policies (`developers.google.com/maps/documentation/places/web-service/policies`) | "The place ID ... You can therefore store place ID values indefinitely."; latitude and longitude may be cached "for up to 30 consecutive calendar days"; other content only "as expressly permitted under the Google Maps Platform Service Specific Terms" | Places data. **The Service Specific Terms page returned no content when fetched, so field-by-field caching periods for ratings, review counts and names are not verified.** |

## 2. What FlowQR stores today (read from the code and the development database)

| Data | Table | Source | How long it is kept today | Fit with the wording above |
|---|---|---|---|---|
| Reviews: text, rating, reviewer name, Google's reply | `reviews` | Business Profile API | indefinitely (the disconnect route keeps "synced reviews as history") | **Conflicts on a plain reading** (a review is "Content", stored for far longer than 30 days). Unresolved: whether Google treats review sync as the "limited amounts ... to improve performance" case. |
| Daily performance metrics | `gbp_metric_daily` | Performance API | indefinitely (months of rows) | **Conflicts on a plain reading**; also "cannot be ... aggregated" collides with the charts, which sum days. |
| Profile, posts, media, 56-day performance snapshot | `gbp_snapshots` | Business Information / v4 APIs | replaced on each refresh (daily) | Plausibly "temporary" (overwritten within a day or so); the 30-day ceiling is met. |
| Google location rows: title, place id, **latitude and longitude** | `google_locations` | Business Profile API and Places | indefinitely | Place id is exempt. **Latitude and longitude obtained from Places are kept past 30 days** (`services/rank.py` `_ensure_center`). Conflicts with the Places rule. |
| Search-term impressions | inside `gbp_snapshots.performance` | Performance API | replaced on refresh | as snapshots |
| Competitor names, ratings, review counts, positions | `rank_checks.top_results`, `competitor_snapshots` | Places API | rank checks and competitor snapshots indefinitely; map scans 400 days | **Unresolved**: depends on the Service Specific Terms (not retrieved). The product's value (review growth between two dated observations) needs retention. |
| What Google held before and after each change | `agent_actions.current_value/proposed_value`, `verification` | Business Information API | 730 days (retention job) | **Unresolved**: audit evidence of FlowQR's own actions vs "Content". |
| OAuth refresh and access tokens | `google_connections` | OAuth | until disconnect, then wiped (tested) | Tokens are not "Content"; wiped on disconnect. No deletion-on-request rule was found in the pages read. |
| Owner-entered business facts | `business_knowledge`, `tenants` | the owner | until deletion | Not Google Content. |

## 3. Interpretation questions that must be answered before launch (escalated, not guessed)

1. **Does "Content storage" apply to reviews and metrics for a product whose purpose is syncing and analysing them?** The page names no exception. Options: (a) ask Google in writing (the API contact channel used for the access request), (b) legal advice, (c) redesign. FlowQR must not rely on a favourable reading it has not confirmed.
2. **Is `business.manage` a sensitive or restricted scope for the Limited Use rules, and do those rules (which cover "derived" and "aggregated" data) apply?** Check the project's OAuth verification outcome, which names the scope category.
3. **Which Places content may be cached, for how long?** Read the Maps Platform Service Specific Terms in a browser (the fetch returned an empty page) and record the periods for rating, userRatingCount, displayName.
4. **Does anything require deleting stored Content when a merchant disconnects?** None found in the pages read, but FlowQR's own promise (and DPDP) may.
5. **The Business Profile Terms and the "Working with a third party" notice** (support policy for third-party managers) must be checked against the website.

## 4. Design implications (so that either answer is cheap to implement)

These are recorded so that the product can follow whichever interpretation is confirmed. **None is built yet.**
* Every table that holds Google Content gets an explicit `retention_class` (for example `google_content_30d`, `places_cache`, `own_record`) in a single registry, and **one** retention job expires by class, with counts only in the audit log (the existing `agent/retention.py` pattern: whole records, flag-guarded).
* Screens should be derivable from a short window plus FlowQR-owned counters (for example "reviews answered this month" stored as a number, not as the review text), so that expiring raw text does not blank the dashboard. Whether a stored aggregate is itself prohibited ("cannot be ... aggregated") is question 1.
* The disconnect route currently keeps reviews "as history". If the answer to question 4 is "delete", disconnect becomes: revoke tokens, deselect locations, and queue deletion of that connection's Google Content after a grace period the owner can see.
* Latitude and longitude from Places: store the place id only and re-fetch the coordinates when a check runs (one Place Details call, which has a price: see the paid-lookup decision D6, so this needs the cost review first), or keep them under the 30-day rule.

## 5. Decision needed

Which of (a) written clarification from Google, (b) legal review, (c) redesign to short-lived raw content plus FlowQR-owned counters, to pursue first. **Until one of them has produced an answer, FlowQR should not onboard real customers to Google sync.** Today it syncs only the owner's own test profile and two clinic profiles that are now isolated (see `GOOGLE_READINESS_M2.md`).

## 6. Update 2026-11-18

Still **unresolved**. No answer from Google, no legal advice, and no retention job for Google content has been written. The inventory of every Google-derived data type, where it is stored, how long it is kept, which services read it, and the possible options per type (none chosen) is in `PRIVACY_COMPLIANCE_AUDIT.md` §10. The separate, interim safeguard for sending review data to an AI provider is in §9 of the same document.
