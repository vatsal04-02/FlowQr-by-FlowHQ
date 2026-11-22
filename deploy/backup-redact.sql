-- Redact Google Business Profile content older than :days days, in a COPY of the database that is about to be dumped (deploy/redacted-dump.sh).
-- Run with:  psql -v ON_ERROR_STOP=1 -v days=15 -f backup-redact.sql
-- It mirrors backend/app/services/google_retention.py step for step (the same columns, the same rule: age counts from when FlowQR first stored the record), so that a backup
-- kept K days holds nothing older than (days + K) <= 30 days. tests/test_backup_redaction.py proves the two agree. Never run it against the live database.

UPDATE reviews SET text = NULL, reviewer_name = NULL, google_reply_text = NULL, google_content_expired_at = now()
 WHERE first_seen_at < now() - make_interval(days => :days) AND google_content_expired_at IS NULL;

UPDATE gbp_snapshots SET info = NULL, posts = NULL, media = NULL, performance = NULL, error = 'Expired under the Google content retention period'
 WHERE fetched_at < now() - make_interval(days => :days) AND (info IS NOT NULL OR posts IS NOT NULL OR media IS NOT NULL OR performance IS NOT NULL);

DELETE FROM gbp_metric_daily WHERE first_fetched_at < now() - make_interval(days => :days);

DELETE FROM reply_drafts WHERE created_at < now() - make_interval(days => :days) AND status IN ('draft', 'approved', 'failed', 'rejected');

UPDATE ai_outputs SET original_text = '' WHERE kind = 'reply' AND created_at < now() - make_interval(days => :days) AND original_text <> '';

UPDATE agent_tasks SET evidence = (evidence - 'reviewer') - 'snippet', title = regexp_replace(title, ' from .*$', '')
 WHERE kind = 'reply_review' AND created_at < now() - make_interval(days => :days) AND (evidence ? 'reviewer' OR evidence ? 'snippet' OR title LIKE '% from %');
