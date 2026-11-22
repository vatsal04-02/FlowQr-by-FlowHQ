"""deploy/backup-redact.sql must do to a backup copy exactly what services/google_retention.py does to the live data (so a backup never holds Google content past its limit)."""
import pathlib
import re

import pytest

from app.services import google_retention as gr
from tests.conftest import owner_exec, owner_query
from tests.test_google_and_reviews import FakeGoogleProvider, callback, connect, connected, fake, greview, sync_select  # noqa: F401  (fixtures)

SQL = pathlib.Path(__file__).resolve().parents[2] / "deploy" / "backup-redact.sql"
pytestmark = pytest.mark.skipif(not SQL.exists(), reason="the deploy folder is not mounted in this run")


@pytest.fixture(autouse=True)
def _clean():
    def wipe():
        for t in ("reply_drafts", "reviews", "gbp_snapshots", "gbp_metric_daily"):
            owner_exec(f"DELETE FROM {t}")
        owner_exec("DELETE FROM agent_tasks WHERE kind = 'reply_review'")
        owner_exec("DELETE FROM ai_outputs")
    wipe()
    yield
    wipe()


def statements():
    text = "\n".join(line for line in SQL.read_text(encoding="utf-8").split("\n") if not line.lstrip().startswith("--"))
    return [s.strip() for s in text.split(";") if s.strip()]


def run_sql(days):
    for st in statements():
        owner_exec(st, days=days)


def seed(connected, fake):
    fake.reviews = [greview(i, rating=4, text=f"Text {i}", reply="Thanks" if i == 1 else None) for i in range(1, 4)]
    sync_select(connected, fake)
    gid, tid = owner_query("SELECT id, tenant_id FROM google_locations WHERE selected")[0]
    owner_exec("UPDATE reviews SET first_seen_at = now() - interval '20 days' WHERE external_id = 'rev-1'")
    owner_exec("UPDATE reviews SET first_seen_at = now() - interval '5 days' WHERE external_id = 'rev-2'")
    owner_exec("INSERT INTO gbp_snapshots (id, tenant_id, google_location_id, info, fetched_at, created_at, updated_at) VALUES (gen_random_uuid(), :t, :g, CAST(:j AS jsonb), now() - interval '20 days', now(), now())", t=str(tid), g=str(gid), j='{"title": "X"}')
    owner_exec("INSERT INTO gbp_metric_daily (id, tenant_id, google_location_id, metric, day, value, source, first_fetched_at, fetched_at) VALUES (gen_random_uuid(), :t, :g, 'CALL_CLICKS', current_date - 20, 3, 'performance_api', now() - interval '20 days', now())", t=str(tid), g=str(gid))
    owner_exec("INSERT INTO ai_outputs (id, tenant_id, kind, ref_id, original_text, created_at) VALUES (gen_random_uuid(), :t, 'reply', gen_random_uuid(), 'a reply the AI wrote', now() - interval '20 days')", t=str(tid))
    owner_exec("""INSERT INTO agent_tasks (id, tenant_id, plan_date, kind, title, why, evidence, status, priority, dedupe_key, created_at, updated_at)
                  VALUES (gen_random_uuid(), :t, current_date - 20, 'reply_review', 'Reply to a 5-star review from Priya Sharma', 'w', CAST(:ev AS jsonb), 'suggested', 10, 'reply:x', now() - interval '20 days', now())""",
               t=str(tid), ev='{"reviewer": "Priya Sharma", "snippet": "Lovely staff", "rating": 5}')


def snapshot():
    return {
        "review_text": sorted(r[0] or "-" for r in owner_query("SELECT external_id || ':' || coalesce(text, '-') || ':' || coalesce(reviewer_name, '-') || ':' || coalesce(google_reply_text, '-') FROM reviews")),
        "snapshot_info_null": owner_query("SELECT info IS NULL FROM gbp_snapshots")[0][0],
        "metrics": owner_query("SELECT count(*) FROM gbp_metric_daily")[0][0],
        "ai_text": owner_query("SELECT original_text FROM ai_outputs")[0][0],
        "task": owner_query("SELECT title, evidence::text FROM agent_tasks WHERE kind = 'reply_review'")[0],
    }


def test_the_sql_has_one_statement_per_retention_step():
    assert len(statements()) == len(gr.STEPS) == 6
    body = SQL.read_text(encoding="utf-8")
    for needle in ("UPDATE reviews", "UPDATE gbp_snapshots", "DELETE FROM gbp_metric_daily", "DELETE FROM reply_drafts", "UPDATE ai_outputs", "UPDATE agent_tasks"):
        assert needle in body


def wipe_all():
    for t in ("reply_drafts", "reviews", "gbp_snapshots", "gbp_metric_daily"):
        owner_exec(f"DELETE FROM {t}")
    owner_exec("DELETE FROM agent_tasks WHERE kind = 'reply_review'")
    owner_exec("DELETE FROM ai_outputs")


def test_the_redaction_sql_and_the_retention_job_leave_the_same_result(connected, fake, monkeypatch):
    from contextlib import closing
    from datetime import timedelta

    from app.core.config import settings
    from app.core.db import system_session
    from app.models.base import utcnow

    monkeypatch.setattr(settings, "google_content_retention_enabled", True)
    monkeypatch.setattr(settings, "google_content_retention_days", 30)
    seed(connected, fake)
    with closing(system_session()) as db:
        gr.run(db, now=utcnow() + timedelta(days=15))  # the job, as if every record were 15 days older: the same cut as a 15-day redaction of a 30-day rule
    by_job = snapshot()
    wipe_all()
    seed(connected, fake)
    run_sql(15)
    by_sql = snapshot()
    assert by_sql == by_job
    assert by_sql["metrics"] == 0 and by_sql["snapshot_info_null"] is True and by_sql["ai_text"] == ""
    assert not any("Text 1" in r for r in by_sql["review_text"]) and any("Text 2" in r for r in by_sql["review_text"]) and "Priya" not in by_sql["task"][0]


def test_a_longer_window_leaves_younger_content_alone(connected, fake):
    seed(connected, fake)
    run_sql(25)  # everything seeded is 20 days old or younger
    s = snapshot()
    assert any("Text 1" in r for r in s["review_text"]) and s["metrics"] == 1 and s["snapshot_info_null"] is False and s["ai_text"] == "a reply the AI wrote" and "Priya" in s["task"][0]


def test_the_scripts_are_consistent_about_the_arithmetic():
    backup = (SQL.parent / "backup.sh").read_text(encoding="utf-8")
    assert "REDACT_DAYS=$((30 - KEEP - 1))" in backup and "redacted-dump.sh" in backup and "pg_dump -U flowqr -d flowqr --no-owner | gzip" not in backup
    assert re.search(r'-le 28', backup)  # KEEP + REDACT_DAYS + 1 == 30 for every allowed KEEP
