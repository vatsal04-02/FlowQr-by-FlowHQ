"""Retention of content taken from Google (services/google_retention.py). Mock Google only. The mechanism is OFF by default in code; these tests switch it on for themselves.

The rule under test: the 30-day clock starts when FlowQR FIRST STORED a record and never moves; a later sync cannot extend it; an expired record is never filled in again.
"""
from contextlib import closing
from datetime import date, datetime, timedelta, timezone

import pytest

from app.core.config import Settings, config_problems, settings
from app.core.db import system_session
from app.models import GoogleConnection, GoogleLocation
from app.models.base import utcnow
from app.services import google_retention as gr
from tests.conftest import make_business, owner_exec, owner_query
from tests.test_google_and_reviews import FakeGoogleProvider, callback, connect, connected, fake, greview  # noqa: F401  (fixtures)
from tests.test_google_and_reviews import sync_select


@pytest.fixture()
def on(monkeypatch):
    monkeypatch.setattr(settings, "google_content_retention_enabled", True)
    monkeypatch.setattr(settings, "google_content_retention_days", 30)
    monkeypatch.setattr(settings, "google_content_retention_action", "redact")


@pytest.fixture(autouse=True)
def _clean_google_content():
    """The tables the job works on are global in the test database, so each test starts and ends with them empty."""
    def wipe():
        for t in ("reply_drafts", "reviews", "gbp_snapshots", "gbp_metric_daily"):
            owner_exec(f"DELETE FROM {t}")
        owner_exec("DELETE FROM agent_tasks WHERE kind = 'reply_review'")
        owner_exec("DELETE FROM ai_outputs")
    wipe()
    yield
    wipe()


def run(**kw):
    with closing(system_session()) as db:
        return gr.run(db, **kw)


def stored(ext, days):
    """Make a review look as if FlowQR first stored it `days` ago."""
    owner_exec("UPDATE reviews SET first_seen_at = now() - make_interval(days => :d) WHERE external_id = :e", d=days, e=ext)


def row(ext):
    return owner_query("SELECT text, reviewer_name, google_reply_text, rating, google_content_expired_at IS NOT NULL FROM reviews WHERE external_id = :e", e=ext)[0]


def n(ext=None):
    """How many review rows (the fake connection selects two locations, so each review is stored once per location)."""
    return owner_query("SELECT count(*) FROM reviews" + (" WHERE external_id = :e" if ext else ""), e=ext)[0][0]


def seeded(connected, fake, count=3):
    fake.reviews = [greview(i, rating=4, text=f"Text {i}", reply="Thanks" if i == 1 else None) for i in range(1, count + 1)]
    sync_select(connected, fake)


# ------------------------------------------------------------------ off by default, report, boundary
def test_the_retention_job_is_off_by_default_and_deletes_nothing(connected, fake):
    assert Settings(_env_file=None).google_content_retention_enabled is False  # the code default
    seeded(connected, fake)
    stored("rev-1", 400)
    assert run() == {"enabled": False, "dry_run": False, "counts": {}, "errors": []}
    assert row("rev-1")[0] == "Text 1"


def test_a_report_only_counts_and_can_look_ahead_without_changing_anything(connected, fake, on):
    seeded(connected, fake)
    stored("rev-1", 31)
    out = run(dry_run=True)
    assert out["dry_run"] is True and out["counts"]["reviews"] == n("rev-1") and out["errors"] == []
    ahead = run(dry_run=True, now=utcnow() + timedelta(days=31))  # a month from now everything stored today is past the period
    assert ahead["counts"]["reviews"] == n()
    assert row("rev-1")[0] == "Text 1" and row("rev-1")[4] is False and row("rev-2")[0] == "Text 2"


def test_redact_clears_text_names_and_reply_copy_after_the_period_and_keeps_the_rest(connected, fake, on):
    seeded(connected, fake)
    day1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    stamps = {"rev-1": day1 - timedelta(seconds=1), "rev-2": day1, "rev-3": day1 + timedelta(days=20)}  # one second past, exactly on, and well inside the period
    for ext, at in stamps.items():
        owner_exec("UPDATE reviews SET first_seen_at = :a WHERE external_id = :e", a=at, e=ext)
    out = run(now=day1 + timedelta(days=30))
    assert out["enabled"] is True and out["counts"]["reviews"] == n("rev-1") and out["errors"] == []
    assert row("rev-1") == (None, None, None, 4, True)  # strictly older: rating kept, content gone
    assert row("rev-2")[0] == "Text 2" and row("rev-2")[4] is False  # exactly `days` old: kept
    assert row("rev-3")[0] == "Text 3"
    assert run(now=day1 + timedelta(days=30))["counts"]["reviews"] == 0  # repeatable: nothing left to do


def test_a_sync_never_moves_the_storage_clock_and_never_fills_expired_content_in_again(connected, fake, on):
    seeded(connected, fake)
    first = owner_query("SELECT first_seen_at FROM reviews WHERE external_id = 'rev-1' ORDER BY id LIMIT 1")[0][0]
    for _ in range(3):
        sync_select(connected, fake)  # Google still returns the same reviews every time
    assert owner_query("SELECT first_seen_at FROM reviews WHERE external_id = 'rev-1' ORDER BY id LIMIT 1")[0][0] == first  # re-fetching did not move it
    stored("rev-1", 40)
    run()
    assert row("rev-1")[0] is None
    updates_before = owner_query("SELECT update_count FROM reviews WHERE external_id = 'rev-1'")[0][0]
    sync_select(connected, fake)  # Google still has the review and returns its text again
    after = row("rev-1")
    assert after[0] is None and after[1] is None and after[2] is None and after[4] is True  # NOT filled in again
    assert owner_query("SELECT update_count FROM reviews WHERE external_id = 'rev-1'")[0][0] == updates_before
    assert n("rev-1") == owner_query("SELECT count(DISTINCT google_location_id) FROM reviews WHERE external_id = 'rev-1'")[0][0]  # and not stored a second time
    stored("rev-2", 5)
    assert run()["counts"]["reviews"] == 0 and row("rev-2")[0] == "Text 2"


def test_new_content_google_returns_later_is_a_new_record_with_its_own_clock(connected, fake, on):
    seeded(connected, fake, count=2)
    stored("rev-1", 40), stored("rev-2", 40)
    run()
    fake.reviews = fake.reviews + [greview(9, rating=5, text="A brand new review")]
    sync_select(connected, fake)
    assert row("rev-9") == ("A brand new review", "Reviewer 9", None, 5, False)
    assert row("rev-1")[0] is None and row("rev-2")[0] is None  # the old ones stay expired
    assert run()["counts"]["reviews"] == 0  # the new one is days old, not expired


# ------------------------------------------------------------------ drafts, snapshots, metrics, AI outputs, tasks
def test_unpublished_drafts_expire_and_published_replies_are_kept(connected, fake, on):
    seeded(connected, fake)
    ids = [r["id"] for r in connected.get("/reviews").json()["items"]]
    for i in ids[:2]:
        assert connected.post(f"/reviews/{i}/drafts", json={"body": "A draft reply of enough length"}).status_code in (200, 201)
    owner_exec("UPDATE reply_drafts SET status = 'published' WHERE id = (SELECT id FROM reply_drafts ORDER BY created_at LIMIT 1)")
    owner_exec("UPDATE reply_drafts SET created_at = now() - interval '45 days'")
    out = run()
    assert out["counts"]["drafts"] == 1
    assert owner_query("SELECT status::text FROM reply_drafts")[0][0] == "published"


def test_snapshots_metrics_ai_text_and_agent_task_evidence_expire_too(connected, fake, on):
    seeded(connected, fake)
    gid, tid = owner_query("SELECT id, tenant_id FROM google_locations WHERE selected")[0]
    owner_exec("INSERT INTO gbp_snapshots (id, tenant_id, google_location_id, info, fetched_at, created_at, updated_at) VALUES (gen_random_uuid(), :t, :g, '{\"title\":\"X\"}'::jsonb, now() - interval '31 days', now(), now())", t=str(tid), g=str(gid))
    owner_exec("INSERT INTO gbp_metric_daily (id, tenant_id, google_location_id, metric, day, value, source, first_fetched_at, fetched_at) VALUES (gen_random_uuid(), :t, :g, 'CALL_CLICKS', current_date - 40, 3, 'performance_api', now() - interval '40 days', now())", t=str(tid), g=str(gid))
    owner_exec("INSERT INTO ai_outputs (id, tenant_id, kind, ref_id, original_text, quality_score, created_at, decision) VALUES (gen_random_uuid(), :t, 'reply', gen_random_uuid(), 'Thank you for the kind words about the clinic', 0.9, now() - interval '40 days', 'approved')", t=str(tid))
    owner_exec("""INSERT INTO agent_tasks (id, tenant_id, plan_date, kind, title, why, evidence, status, priority, dedupe_key, created_at, updated_at)
                  VALUES (gen_random_uuid(), :t, current_date - 40, 'reply_review', 'Reply to a 5-star review from Priya Sharma', 'w', CAST(:ev AS jsonb), 'suggested', 10, 'reply:x', now() - interval '40 days', now())""",
               t=str(tid), ev='{"reviewer": "Priya Sharma", "snippet": "Lovely staff", "rating": 5}')
    out = run()
    assert out["errors"] == [] and out["counts"]["snapshots"] == 1 and out["counts"]["metrics"] == 1 and out["counts"]["ai_outputs"] == 1 and out["counts"]["agent_tasks"] == 1
    assert owner_query("SELECT info IS NULL FROM gbp_snapshots")[0][0] is True
    assert owner_query("SELECT count(*) FROM gbp_metric_daily")[0][0] == 0  # first stored 40 days ago, although it was refreshed today: the refresh did not extend it
    assert owner_query("SELECT original_text, quality_score, decision FROM ai_outputs")[0] == ("", 0.9, "approved")  # text gone, score and decision kept
    title, evidence = owner_query("SELECT title, evidence FROM agent_tasks WHERE kind = 'reply_review'")[0]
    assert "Priya" not in title and "reviewer" not in evidence and "snippet" not in evidence and evidence["rating"] == 5
    assert run()["counts"] == {"reviews": 0, "snapshots": 0, "metrics": 0, "drafts": 0, "ai_outputs": 0, "agent_tasks": 0}


def test_days_older_than_the_period_are_not_stored_while_retention_is_on_and_are_otherwise(connected, fake, monkeypatch):
    from app.services import gbp_metrics

    seeded(connected, fake)
    gloc = owner_query("SELECT id FROM google_locations WHERE selected ORDER BY id LIMIT 1")[0][0]
    series = {"CALL_CLICKS": [{"date": str(datetime.now(timezone.utc).date() - timedelta(days=d)), "value": 2} for d in (3, 29, 31, 200)]}
    from app.models import GoogleLocation as GL

    def record():
        with closing(system_session()) as db:
            gbp_metrics.record(db, db.get(GL, gloc), series)
            db.commit()
        return owner_query("SELECT count(*) FROM gbp_metric_daily")[0][0]

    assert record() == 4  # off: unchanged behaviour
    owner_exec("DELETE FROM gbp_metric_daily")
    monkeypatch.setattr(settings, "google_content_retention_enabled", True)
    assert record() == 2  # on: only the days inside the period are stored; fetching the older ones again does not bring them back


# ------------------------------------------------------------------ tenant isolation, audit, failure handling, scheduler health
def test_the_job_works_on_age_alone_and_never_touches_a_younger_row_of_another_business(connected, fake, on):
    seeded(connected, fake, count=2)
    other = make_business("Second Clinic")
    tid = owner_query("SELECT tenant_id FROM google_locations WHERE selected LIMIT 1")[0][0]
    owner_exec("INSERT INTO google_connections (id, tenant_id, google_sub, status, scopes, created_at, updated_at, auth_mode, api_access) VALUES (gen_random_uuid(), :t, 's2', 'active', '', now(), now(), 'client_token', 'approved')", t=other.tenant_id)
    c2 = owner_query("SELECT id FROM google_connections WHERE tenant_id = :t", t=other.tenant_id)[0][0]
    owner_exec("INSERT INTO google_locations (id, tenant_id, connection_id, google_account_name, google_location_name, title, selected, consecutive_failures, created_at, updated_at) VALUES (gen_random_uuid(), :t, :c, 'accounts/9', 'locations/9', 'B', true, 0, now(), now())", t=other.tenant_id, c=str(c2))
    g2 = owner_query("SELECT id FROM google_locations WHERE connection_id = :c", c=str(c2))[0][0]
    owner_exec("INSERT INTO reviews (id, tenant_id, google_location_id, external_id, rating, text, review_created_at, first_seen_at, update_count, created_at, updated_at) VALUES (gen_random_uuid(), :t, :g, 'young', 5, 'keep me', now(), now() - interval '10 days', 0, now(), now())", t=other.tenant_id, g=str(g2))
    owner_exec("INSERT INTO reviews (id, tenant_id, google_location_id, external_id, rating, text, review_created_at, first_seen_at, update_count, created_at, updated_at) VALUES (gen_random_uuid(), :t, :g, 'old', 5, 'expire me', now(), now() - interval '31 days', 0, now(), now())", t=other.tenant_id, g=str(g2))
    stored("rev-1", 31), stored("rev-2", 2)
    run()
    assert row("young")[0] == "keep me" and row("old")[0] is None and row("rev-1")[0] is None and row("rev-2")[0] == "Text 2"
    assert str(tid) != str(other.tenant_id)


def test_every_run_writes_a_counts_only_audit_entry_even_when_nothing_expired(connected, fake, on):
    seeded(connected, fake)
    stored("rev-1", 31)
    run()
    meta = owner_query("SELECT metadata FROM audit_logs WHERE action = 'retention.google_content_run' ORDER BY created_at DESC LIMIT 1")[0][0]
    assert set(meta) == {"counts", "errors", "days", "action"} and meta["counts"]["reviews"] >= 1
    assert "Text 1" not in str(meta) and "Reviewer" not in str(meta)
    before = owner_query("SELECT count(*) FROM audit_logs WHERE action = 'retention.google_content_run'")[0][0]
    run()  # nothing left to expire: still a heartbeat entry
    assert owner_query("SELECT count(*) FROM audit_logs WHERE action = 'retention.google_content_run'")[0][0] == before + 1
    with closing(system_session()) as db:
        assert gr.last_run_at(db) is not None


def test_one_failing_step_is_reported_and_the_others_still_run(connected, fake, on, monkeypatch):
    seeded(connected, fake)
    stored("rev-1", 31)

    def boom(db, now, dry_run):
        raise RuntimeError("x")

    monkeypatch.setattr(gr, "STEPS", (("snapshots", boom),) + tuple(s for s in gr.STEPS if s[0] != "snapshots"))
    out = run()
    assert out["errors"] == ["snapshots"] and out["counts"]["reviews"] == n("rev-1") and row("rev-1")[0] is None


def test_the_scheduled_task_retries_a_failed_step_and_alerts_the_administrators_when_it_still_fails(monkeypatch):
    from celery.exceptions import Retry

    from app.workers import tasks

    alerts = []
    monkeypatch.setattr(gr, "run", lambda db: {"enabled": True, "dry_run": False, "counts": {}, "errors": ["metrics"]})
    monkeypatch.setattr("app.services.google.agency.alert_internal", lambda subject, lines: alerts.append((subject, lines)))

    class Req:
        retries = 0

    task = tasks.google_content_retention
    monkeypatch.setattr(type(task), "request", Req, raising=False)
    with pytest.raises(Retry):
        task.run()
    assert alerts == []  # first failure: retried later, nobody emailed yet
    monkeypatch.setattr(task, "max_retries", 0)  # as if every retry had been used
    out = task.run()  # retries exhausted: alert
    assert out["errors"] == ["metrics"] and len(alerts) == 1 and "metrics" in alerts[0][1][0] and "Google content" in alerts[0][0]
    monkeypatch.setattr(gr, "run", lambda db: {"enabled": False, "dry_run": False, "counts": {}, "errors": []})
    assert task.run()["enabled"] is False and len(alerts) == 1  # off: nothing to retry or report


def test_the_operations_check_notices_a_scheduler_that_stopped_or_a_failing_step(connected, fake, on, monkeypatch):
    from app.services import ops

    with closing(system_session()) as db:
        assert ops.check_google_retention(db)["status"] == "critical"  # enabled, but it has never run
    run()
    with closing(system_session()) as db:
        assert ops.check_google_retention(db)["status"] == "ok"
    monkeypatch.setattr(ops, "utcnow", lambda: utcnow() + timedelta(hours=40))  # (the audit table is append-only, so the clock moves instead of the entry)
    with closing(system_session()) as db:
        assert ops.check_google_retention(db)["status"] == "critical"  # the daily entry stopped
    monkeypatch.undo()
    monkeypatch.setattr(settings, "google_content_retention_enabled", False)
    with closing(system_session()) as db:
        assert ops.check_google_retention(db) is None  # off: nothing to check


def test_an_unreadable_backup_folder_is_reported_not_raised(monkeypatch, tmp_path):
    from app.services import ops

    monkeypatch.setattr(settings, "backup_status_file", str(tmp_path / "status.json"))
    monkeypatch.setattr("app.services.ops.Path.is_file", lambda self: (_ for _ in ()).throw(PermissionError(13, "denied")))
    out = ops.check_backup()
    assert out["status"] == "warn" and "permissions" in out["detail"]


# ------------------------------------------------------------------ disconnect, configuration, classification
def test_disconnect_keeps_history_by_default_and_removes_everything_taken_from_google_when_asked(connected, fake, monkeypatch):
    seeded(connected, fake)
    total = n()
    assert connected.delete(f"/google/connections/{connected.conn_id}").status_code == 204
    assert n() == total  # today's behaviour is unchanged by default
    monkeypatch.setattr(settings, "google_content_delete_on_disconnect", True)
    with closing(system_session()) as db:
        out = gr.purge_connection(db, connected.conn_id, tenant_id=None)
        db.commit()
    assert out["reviews"] == total and n() == 0


def test_the_start_up_guard_keeps_the_period_inside_googles_stated_limit_and_allows_only_redact():
    def prod(**over):
        from cryptography.fernet import Fernet

        base = dict(app_env="production", secret_key="s" * 48, token_encryption_key=Fernet.generate_key().decode(), cookie_secure=True, public_card_base_url="https://go.flowqr.co.in",
                    frontend_url="https://app.flowqr.co.in", cors_origins="https://app.flowqr.co.in", database_url="postgresql+psycopg://flowqr_app:Xk29sLmQ8vNa@db:5432/flowqr",
                    platform_admin_emails="ops@flowhq.in", smtp_host="smtp.sendgrid.net", razorpay_key_id="rzp_live_abcdefghij", razorpay_key_secret="x" * 20, razorpay_webhook_secret="w" * 20,
                    card_price_paise=19900, google_redirect_uri="https://app.flowqr.co.in/api/v1/google/callback", google_client_id="id", google_client_secret="secret")
        base.update(over)
        return Settings(_env_file=None, **base)

    assert config_problems(prod()) == []
    assert config_problems(prod(google_content_retention_enabled=True, google_content_retention_days=30)) == []
    assert any("between 1 and 30" in p for p in config_problems(prod(google_content_retention_enabled=True, google_content_retention_days=90)))
    assert any("must be redact" in p for p in config_problems(prod(google_content_retention_action="delete")))  # delete would let the next sync store the review again with a fresh clock


def test_every_store_of_google_content_is_classified():
    text = " ".join(gr.CLASSIFICATION)
    for needle in ("reviews.text", "gbp_snapshots", "gbp_metric_daily", "reply_drafts", "ai_outputs", "agent_tasks", "notifications", "audit_logs"):
        assert needle in text
