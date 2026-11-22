# Google content retention: architecture (migration 0064, revised 2026-11-22)

**What this is.** The mechanism that removes content taken from the Google Business Profile APIs 30 days after FlowQR first stored it. It applies the strictest reading of Google's text that keeps the product working. Whether that reading is exactly what Google requires of FlowQR's service is still a question for Google (`GOOGLE_QUESTIONS_TO_SUBMIT.md`); nothing here is a statement that Google has approved anything.

## The rule

Google's text (read 2026-11-21): content provided through the Business Profile APIs may not be pre-fetched, cached, indexed or stored beyond limited amounts for performance; stored content "must be stored temporarily for no more than 30 calendar days", stored securely and "cannot be manipulated or aggregated". It names no exception and does not distinguish an owner's token from the agency login, so the mechanism treats both the same.

**The clock starts when FlowQR first stored a record and never moves.**

* A sync that returns the same review again does **not** extend its life (`reviews.first_seen_at` is set once).
* An expired review is **never filled in again**: sync skips a review whose content was expired (`google_content_expired_at`), so fetching the same content again cannot restart an obligation. (A `delete` action was removed for the same reason: a deleted row would be stored again by the next sync with a fresh clock.)
* **New** content that Google returns later is a new record with its own 30 days.
* A **snapshot** is replaced by each refresh, never accumulated, so it is at most as old as the last refresh; it is cleared if a refresh did not happen within the period.
* **Daily metrics** are deleted 30 days after first stored (`first_fetched_at`; a later revision of the day's value does not move it), and while retention is on days older than the period are **not stored at all**, so they cannot be fetched back in.

## Classification (every store audited)

| Store | What it holds | Class | What happens |
|---|---|---|---|
| `reviews.text`, `reviewer_name`, `google_reply_text` | review words, the reviewer's name, Google's copy of the owner reply | Google content | cleared when older than the period |
| `reviews.rating`, dates, ids, reply state | operational metadata | metadata | **kept** (counts over time, sync de-duplication). Whether ratings and dates must also go is question 4/5 for Google |
| `gbp_snapshots.info/posts/media/performance` | last profile, posts, media, performance Google returned | Google content | cleared (SQL NULL) when the last refresh is older than the period |
| `gbp_metric_daily` | daily performance numbers | Google content | deleted when first stored longer ago than the period; old days not stored. The application role holds `DELETE` for this since migration 0064 (0035 had given none) |
| `reply_drafts` (unpublished) | AI drafts written from review text | derived | deleted after the period; a **published** reply is the business's own public words and is kept |
| `ai_outputs` (kind `reply`) | the AI's original reply text | derived | text cleared after the period; score, decision and edit ratio (no Google content) kept |
| `agent_tasks` (reply_review) | title and evidence carry the reviewer's name and a snippet | derived | name and snippet removed after the period |
| notifications | built from reviews on request, nothing stored | none | follow the reviews |
| data export | generated and streamed on request, never stored on disk | none | contains only what is stored at that moment |
| Redis | no review or Google content is cached there (verified by reading the code that writes to it) | none | n/a |
| `audit_logs` | counts, ids, codes; never Google content | none | not expired by this job |
| `google_locations`, `google_connections` | resource names, titles, encrypted tokens, status | identifiers and credentials | not expired by this job: needed to operate; removed by the account-deletion lifecycle |
| Places / competitor / rank tables | Google Maps Platform data, a different API with its own terms | out of scope | unchanged |
| **Database backups** | nightly encrypted dumps and manual pre-release dumps | copies | written from a redacted copy (see Backups) |

`services/google_retention.CLASSIFICATION` mirrors this table and a test fails if a store is dropped from it.

## The job

`flowqr.google_content_retention`, daily on the existing beat, `services/google_retention.run`.

* **Idempotent**: a second run finds nothing. **Boundary**: a record exactly `days` old is kept, only strictly older goes. **Tenant-neutral**: it works on age alone and never on who owns a row; a younger row of any business is never touched. **Independent steps**: one failing leaves the others to run and is reported.
* **Retries and alerts**: a run with a failed step is retried 10, 20 and 40 minutes later; if it still fails the administrators are emailed the step names (never content). A run writes **one counts-only audit entry every day it runs** (`retention.google_content_run`: counts, errors, days, action; no review text, no names), so a missing entry is how the operations check notices a stopped scheduler.
* **Operations check** (Admin > Operations): when retention is on, the job must have run within 36 hours without a failed step, otherwise the check is critical.
* **Report**: `python -m app.cli google-retention-report [--days-ahead N]` counts what a run would expire (now, or N days ahead) and changes nothing.

Settings: `GOOGLE_CONTENT_RETENTION_ENABLED` (code default false), `GOOGLE_CONTENT_RETENTION_DAYS` (30; the start-up guard requires 1 to 30 while enabled), `GOOGLE_CONTENT_RETENTION_ACTION` (only `redact`), `GOOGLE_CONTENT_DELETE_ON_DISCONNECT` (false: disconnecting keeps history today; true removes everything taken from Google for that connection at once).

## Backups (a copy of the data is a store too)

**Rule:** a backup kept K days must hold no Google content older than 30 - K days at the moment it is written, so that content never outlives 30 days anywhere.

* **Nightly backups** (`deploy/backup.sh`, kept `BACKUP_KEEP_DAYS` = 14, allowed 1 to 28) are written from a **redacted copy**: `deploy/redacted-dump.sh` dumps the live database, restores that stream into a scratch database inside the same Postgres container, runs `deploy/backup-redact.sql` there with `REDACT_DAYS = 30 - KEEP - 1` (15 days for 14), checks that nothing older than that survived (the backup fails instead), dumps the scratch database, and drops it (also on failure). The live database is never changed. Everything that is not Google content is dumped exactly as it is, so recovery of the rest is unchanged, and the existing encryption, off-site copy and status file are untouched. A review is therefore in a backup for at most 15 days of its life plus 14 days of the backup's, 29 days in total. The unredacted stream exists only in a pipe and in the scratch database; no unredacted backup file is ever written.
* **The SQL is the retention job, repeated:** `tests/test_backup_redaction.py` seeds the same data, runs the job and the SQL, and requires identical results (reviews, snapshots, metrics, drafts, AI text, task evidence), plus one statement per retention step, so the two cannot drift apart silently.
* **Manual dumps** (`/opt/flowqr/backups/pre-*.dump`, made before releases) are not redacted unless made with `deploy/redacted-dump.sh`; they are removed after 14 days by `deploy/prune-manual-dumps.sh`, which `backup.sh` now runs after every nightly backup (no separate cron entry). Make new manual dumps with `redacted-dump.sh`.
* **Transition:** nightly backups written before this change hold content at most 8 days old when written and are deleted within 14 days, so none outlives about 22 days of content life.
* **Restoring:** a restored database contains content as old as the backup allows (at most 15 days) plus the days since. **After any restore, run the retention job before the application serves traffic**: `python -m app.cli google-retention-report` to see what it will do, then let the daily job (or `google_retention.run`) apply it. Content already redacted in a backup is not brought back by the sync.
* **What this is not:** key-expiry encryption of individual rows, or excluding tables from backups. They were considered: expiring keys would make a backup unreadable for the whole table, not for the old content only, and excluding the content tables would break foreign keys and lose ratings. Redacting the copy keeps full recovery of everything that is not Google content.

## AI providers

Review text reaches an AI provider only through `services/ai/privacy.py`: `AI_REVIEW_DATA_KILL_SWITCH` stops it for every provider at once, and review data does not go to Gemini unless `GEMINI_DATA_TERMS_VERIFIED=true`. Google's page says nothing about AI use of the content (question 7). The AI's derived text is covered by the draft, `ai_outputs` and task expiry above.

## Customer disclosure and controls

Existing: the agency consent text and separate notice, the stop button and removal within seven business days, the privacy notice and Google data-use page drafts, the account-deletion flow. **Not decided:** the wording of a retention disclosure ("FlowQR keeps your Google reviews' text for 30 days"). It depends on Google's answer and legal review, so none was invented.

## Tests

`tests/test_google_retention.py` (17): off by default; report and look-ahead; redact with the exact boundary; a sync never moves the clock and never refills; new content gets its own clock; drafts versus published replies; snapshots, metrics, AI text and task evidence; the metrics write floor; tenant neutrality; the counts-only audit heartbeat; a failing step; retry and alert; the operations check; the unreadable-backup-folder fix; disconnect; the start-up guard; classification completeness.

## What activation does to a live business (read before switching on)

Reviews first stored more than 30 days ago lose their text, names and reply copy; ratings, dates and ids stay. Unpublished reply drafts older than 30 days disappear. The SEO page's history shrinks to the last 30 days as old metric rows reach their 30th day. New reviews keep their text for 30 days. A review's text cannot come back from Google once expired.
