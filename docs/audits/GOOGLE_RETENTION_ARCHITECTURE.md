# Google content retention: architecture (migration 0064)

Written 2026-11-21. **Mechanism only.** Whether and how Google's storage text applies to FlowQR is not answered in writing (`GOOGLE_AGENCY_POLICY_STATUS.md`, R-1; the questions to send are in `GOOGLE_QUESTIONS_TO_SUBMIT.md`). Nothing here decides compliance. The job is **off** and deletes nothing until a person sets `GOOGLE_CONTENT_RETENTION_ENABLED=true`.

## What Google's text says (as read 2026-11-21, not Google's answer)

Content provided through the Business Profile APIs may not be pre-fetched, cached, indexed or stored beyond limited amounts for performance; stored content "must be stored temporarily for no more than 30 calendar days", stored securely and "cannot be manipulated or aggregated". The page names no exception for reviews, ids or operational data, says nothing about AI, and does not say whether it differs for an owner who signs in themselves versus an agency login. It applies to the content, not to which login fetched it, so the mechanism below treats owner-OAuth and agency connections identically.

## Data classification (every store audited by reading the code that writes Google content)

| Store | What it holds | Class | Expiry (when enabled) |
|---|---|---|---|
| `reviews.text`, `reviewer_name`, `google_reply_text` | review words, the reviewer's name, Google's copy of the owner reply | Google content | cleared (`redact`) or row removed (`delete`) when `google_fetched_at` is older than the period |
| `reviews.rating`, dates, ids, `google_reply_state` | operational metadata | metadata | kept on `redact` (so counts over time still work); gone with the row on `delete` |
| `gbp_snapshots.info/posts/media/performance` | the last profile, posts, media and performance Google returned | Google content | cleared (SQL NULL) when `fetched_at` is older than the period |
| `gbp_metric_daily` | daily performance numbers | Google content | rows removed when `fetched_at` is older than the period (the app role was given DELETE for this in 0064; 0035 had deliberately given none) |
| `reply_drafts` (not published) | AI drafts derived from review text | derived | removed after the period; a **published** reply is the business's own words, already public, and is kept |
| `agent_tasks` (reply_review) | title and evidence carry the reviewer's name and a text snippet | derived | name and snippet removed after the period |
| notifications | built from reviews on request, nothing stored | none | follow the reviews |
| `audit_logs` | counts, ids and codes only (no review text, no names, no tokens) | none | not subject to expiry here |
| `google_locations`, `google_connections` | resource names, titles, tokens (encrypted), status | identifiers and credentials | not expired by this job: needed to operate; removed on account deletion (existing lifecycle) |
| Places / competitor / rank tables | Google Maps Platform (Places API), a different API with its own terms | out of scope | not changed |

`services/google_retention.CLASSIFICATION` mirrors this table and a test fails if a store is dropped from it.

## How the clock works

* **Age is the last re-fetch from Google**, not the review's own date: `reviews.google_fetched_at` is set to now every time Google returns the review. Existing rows were set to the migration time by 0064, so turning the job on never expires a review merely because the column is new.
* **Refresh:** with retention on, review sync reads the **whole** list again once per half the period (`locations.last_full_synced_at`), so every review Google still has is re-fetched well inside the period. A review whose text was cleared and that Google still has is filled in again by the next sync (not counted as a customer edit). Content that Google removed, that stopped syncing, or that belongs to a disconnected location ages out.
* A row exactly `days` old is kept; strictly older goes. All times UTC.

## The job

`flowqr.google_content_retention`, daily on the existing beat, `services/google_retention.run`. Independent steps (reviews, snapshots, metrics, drafts, agent tasks): one failing is reported and the others run; repeatable; writes one audit entry with **counts and settings only**. `python -m app.cli google-retention-report` counts what a run would do and changes nothing.

Settings (all default to today's behaviour): `GOOGLE_CONTENT_RETENTION_ENABLED=false`, `GOOGLE_CONTENT_RETENTION_DAYS=30` (the start-up guard requires 1 to 30 while enabled), `GOOGLE_CONTENT_RETENTION_ACTION=redact|delete`, `GOOGLE_CONTENT_DELETE_ON_DISCONNECT=false`. None of them is in `deploy/vps/docker-compose.vps.yml`, so none can reach the application until a person adds it there on purpose.

## Disconnection and deletion

* **Disconnect** keeps synced reviews as history today (unchanged by default). With `GOOGLE_CONTENT_DELETE_ON_DISCONNECT=true` it removes everything taken from Google for that connection's locations at once (`purge_connection`), keeping the connection and location rows, and writes a counts-only audit entry.
* **Account deletion** uses the existing privacy lifecycle (cooling-off, then purge of the tenant's rows).

## Backups and recovery

Database dumps are rotated by `deploy/backup.sh` (`KEEP` days) and the VPS keeps dated pre-release dumps in `/opt/flowqr/backups` by hand. **A dump taken before an expiry contains the content that expiry removed.** Treatment if retention is switched on: (1) keep dumps no longer than the retention period (set `KEEP` accordingly, and delete the manual pre-release dumps after the rollback window), (2) after any restore, run the retention job (`google_retention.run`) before the application serves traffic, which re-applies every expiry. This is a procedure, not an automatic guarantee: a restore is a person's action.

## AI providers

Review text is sent to an AI provider only through `services/ai/privacy.py`: `AI_REVIEW_DATA_KILL_SWITCH` stops it for every provider at once, and review data does not go to Gemini unless `GEMINI_DATA_TERMS_VERIFIED=true` (owner-set, only with evidence). Google's page says nothing about AI use of Business Profile content, so this stays an open question (question 7). AI outputs derived from reviews are covered by the draft and task expiry above; the provider's own retention is governed by the provider's terms and is not controlled here.

## Customer disclosure, consent and deletion controls

Existing: the agency consent text and separate notice (48 hours), the stop button and removal within seven business days, the privacy notice and Google data-use page drafts, and the account deletion flow. **Not decided:** the wording of a retention disclosure ("FlowQR keeps your Google reviews for N days"). That wording depends on Google's answer and on legal review, so none was invented.

## Tests

`tests/test_google_retention.py` (15): off by default; report-only; redact (including the exact-boundary row); refill by sync; full-list refresh cadence; delete with drafts; unpublished drafts versus published replies; snapshots, metrics and agent-task scrubbing; counts-only audit; one failing step; disconnect default versus purge; purge isolation between businesses; start-up guard; classification completeness.

## To switch it on (after Google's answer and a person's decision)

1. Decide the action and period from Google's written answer. 2. Run `google-retention-report` and read the counts. 3. Add the variables to `.env.production` **and** to the overlay `docker-compose.vps.yml`. 4. Recreate api, worker and beat with both compose files. 5. Check the next daily audit entry. 6. Align backup rotation.
