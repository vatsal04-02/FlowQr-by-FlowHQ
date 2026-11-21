"""Retention of content taken from Google (services/google_retention.py). Mock Google only. The mechanism is OFF by default; these tests switch it on for themselves."""
from contextlib import closing
from datetime import timedelta

import pytest

from app.core.config import Settings, config_problems, settings
from app.core.db import system_session
from app.models import GoogleConnection, GoogleLocation, Review
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
    wipe()
    yield
    wipe()


def run(**kw):
    with closing(system_session()) as db:
        return gr.run(db, **kw)


def age(review_ext, days):
    owner_exec("UPDATE reviews SET google_fetched_at = now() - make_interval(days => :d) WHERE external_id = :e", d=days, e=review_ext)


def row(ext):
    return owner_query("SELECT text, reviewer_name, google_reply_text, rating, google_content_expired_at IS NOT NULL FROM reviews WHERE external_id = :e", e=ext)[0]


def n(ext=None):
    """How many review rows (the fake connection selects two locations, so each review is stored once per location)."""
    return owner_query("SELECT count(*) FROM reviews" + (" WHERE external_id = :e" if ext else ""), e=ext)[0][0]


def seeded(connected, fake, n=3):
    fake.reviews = [greview(i, rating=4, text=f"Text {i}", reply="Thanks" if i == 1 else None) for i in range(1, n + 1)]
    sync_select(connected, fake)


# ------------------------------------------------------------------ off by default, and the migration
def test_the_retention_job_is_off_by_default_and_deletes_nothing(connected, fake):
    assert settings.google_content_retention_enabled is False
    seeded(connected, fake)
    age("rev-1", 400)
    assert run() == {"enabled": False, "dry_run": False, "counts": {}, "errors": []}
    assert row("rev-1")[0] == "Text 1"


def test_a_report_only_counts_and_changes_nothing(connected, fake, on):
    seeded(connected, fake)
    age("rev-1", 31)
    out = run(dry_run=True)
    assert out["dry_run"] is True and out["counts"]["reviews"] == n("rev-1") and out["errors"] == []
    assert row("rev-1")[0] == "Text 1" and row("rev-1")[4] is False


def test_sync_stamps_every_review_it_receives_and_the_migration_columns_exist(connected, fake):
    seeded(connected, fake)
    stamps = owner_query("SELECT google_fetched_at FROM reviews WHERE external_id IN ('rev-1','rev-2','rev-3')")
    assert len(stamps) == 3 and all(s[0] is not None for s in stamps)
    cols = {r[0] for r in owner_query("SELECT column_name FROM information_schema.columns WHERE table_name IN ('reviews','google_locations')")}
    assert {"google_fetched_at", "google_content_expired_at", "last_full_synced_at"} <= cols


# ------------------------------------------------------------------ redact
def test_redact_clears_text_names_and_reply_copy_after_the_period_and_keeps_the_rest(connected, fake, on):
    from datetime import datetime, timezone

    seeded(connected, fake)
    day1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    stamps = {"rev-1": day1 - timedelta(seconds=1), "rev-2": day1, "rev-3": day1 + timedelta(days=20)}  # one second past, exactly on, and well inside the period
    for ext, at in stamps.items():
        owner_exec("UPDATE reviews SET google_fetched_at = :a WHERE external_id = :e", a=at, e=ext)
    out = run(now=day1 + timedelta(days=30))
    assert out["enabled"] is True and out["counts"]["reviews"] == n("rev-1") and out["errors"] == []
    assert row("rev-1") == (None, None, None, 4, True)  # strictly older: rating kept, content gone
    assert row("rev-2")[0] == "Text 2" and row("rev-2")[4] is False  # exactly `days` old: kept
    assert row("rev-3")[0] == "Text 3"
    assert run(now=day1 + timedelta(days=30))["counts"]["reviews"] == 0  # repeatable: nothing left to do


def test_a_review_google_still_has_is_filled_in_again_by_the_next_sync_without_counting_as_an_edit(connected, fake, on):
    seeded(connected, fake)
    age("rev-1", 40)
    run()
    assert row("rev-1")[0] is None
    before = owner_query("SELECT update_count FROM reviews WHERE external_id = 'rev-1'")[0][0]
    sync_select(connected, fake)  # the fake still returns it
    after = owner_query("SELECT update_count, google_content_expired_at, google_fetched_at FROM reviews WHERE external_id = 'rev-1'")[0]
    assert row("rev-1")[0] == "Text 1" and after[0] == before and after[1] is None and after[2] is not None


def test_while_retention_is_on_the_sync_reads_the_whole_list_often_enough(connected, fake, on):
    seeded(connected, fake)
    gl = owner_query("SELECT last_full_synced_at FROM google_locations WHERE selected")[0][0]
    assert gl is not None  # the first sync read everything
    owner_exec("UPDATE google_locations SET last_full_synced_at = now() - interval '20 days' WHERE selected")
    before = fake.list_calls
    from app.services.google.sync import sync_google_location

    with closing(system_session()) as db:
        g1 = db.query(GoogleLocation).filter(GoogleLocation.selected.is_(True)).first()
        sync_google_location(db, g1, fake, sleep=lambda s: None)
    assert fake.list_calls > before
    assert owner_query("SELECT last_full_synced_at > now() - interval '1 minute' FROM google_locations WHERE selected")[0][0] is True


# ------------------------------------------------------------------ delete, drafts, snapshots, metrics, tasks
def test_the_delete_action_removes_the_rows_and_their_drafts(connected, fake, on, monkeypatch):
    monkeypatch.setattr(settings, "google_content_retention_action", "delete")
    seeded(connected, fake)
    rid = connected.get("/reviews").json()["items"][0]["id"]
    assert connected.post(f"/reviews/{rid}/drafts", json={"body": "A draft reply to keep until it expires"}).status_code in (200, 201)
    age("rev-1", 31), age("rev-2", 31), age("rev-3", 31)
    total = n()
    assert run()["counts"]["reviews"] == total
    assert owner_query("SELECT count(*) FROM reviews")[0][0] == 0 and owner_query("SELECT count(*) FROM reply_drafts")[0][0] == 0


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


def test_snapshots_metrics_and_agent_task_evidence_expire_too(connected, fake, on):
    seeded(connected, fake)
    gid, tid = owner_query("SELECT id, tenant_id FROM google_locations WHERE selected")[0]
    owner_exec("INSERT INTO gbp_snapshots (id, tenant_id, google_location_id, info, fetched_at, created_at, updated_at) VALUES (gen_random_uuid(), :t, :g, '{\"title\":\"X\"}'::jsonb, now() - interval '31 days', now(), now())", t=str(tid), g=str(gid))
    owner_exec("INSERT INTO gbp_metric_daily (id, tenant_id, google_location_id, metric, day, value, source, first_fetched_at, fetched_at) VALUES (gen_random_uuid(), :t, :g, 'CALL_CLICKS', current_date - 40, 3, 'performance_api', now() - interval '40 days', now() - interval '40 days')", t=str(tid), g=str(gid))
    owner_exec("""INSERT INTO agent_tasks (id, tenant_id, plan_date, kind, title, why, evidence, status, priority, dedupe_key, created_at, updated_at)
                  VALUES (gen_random_uuid(), :t, current_date - 40, 'reply_review', 'Reply to a 5-star review from Priya Sharma', 'w', CAST(:ev AS jsonb), 'suggested', 10, 'reply:x', now() - interval '40 days', now())""",
               t=str(tid), ev='{"reviewer": "Priya Sharma", "snippet": "Lovely staff", "rating": 5}')
    out = run()
    assert out["errors"] == [] and out["counts"]["snapshots"] == 1 and out["counts"]["metrics"] == 1 and out["counts"]["agent_tasks"] == 1
    assert owner_query("SELECT info IS NULL FROM gbp_snapshots")[0][0] is True and owner_query("SELECT count(*) FROM gbp_metric_daily")[0][0] == 0
    title, evidence = owner_query("SELECT title, evidence FROM agent_tasks WHERE kind = 'reply_review'")[0]
    assert "Priya" not in title and "reviewer" not in evidence and "snippet" not in evidence and evidence["rating"] == 5
    assert run()["counts"] == {"reviews": 0, "snapshots": 0, "metrics": 0, "drafts": 0, "agent_tasks": 0}


def test_the_audit_entry_holds_counts_and_settings_only_never_content(connected, fake, on):
    seeded(connected, fake)
    age("rev-1", 31)
    run()
    meta = owner_query("SELECT metadata FROM audit_logs WHERE action = 'retention.google_content_run' ORDER BY created_at DESC LIMIT 1")[0][0]
    assert set(meta) == {"counts", "errors", "days", "action"}
    assert "Text 1" not in str(meta) and "Reviewer" not in str(meta)


def test_one_failing_step_is_reported_and_the_others_still_run(connected, fake, on, monkeypatch):
    seeded(connected, fake)
    age("rev-1", 31)

    def boom(db, now, dry_run):
        raise RuntimeError("x")

    monkeypatch.setattr(gr, "STEPS", (("snapshots", boom),) + tuple(s for s in gr.STEPS if s[0] != "snapshots"))
    out = run()
    assert out["errors"] == ["snapshots"] and out["counts"]["reviews"] == n("rev-1") and row("rev-1")[0] is None


# ------------------------------------------------------------------ disconnect, isolation, configuration
def test_disconnect_keeps_history_by_default_and_removes_everything_taken_from_google_when_asked(connected, fake, monkeypatch):
    seeded(connected, fake)
    total = n()
    assert connected.delete(f"/google/connections/{connected.conn_id}").status_code == 204
    assert n() == total  # today's behaviour is unchanged by default
    other = make_business("Other Clinic")
    assert other is not None
    monkeypatch.setattr(settings, "google_content_delete_on_disconnect", True)
    with closing(system_session()) as db:
        out = gr.purge_connection(db, connected.conn_id, tenant_id=None)
        db.commit()
    assert out["reviews"] == total and n() == 0


def test_purge_connection_only_touches_that_connection(connected, fake):
    seeded(connected, fake)
    gid, tid = owner_query("SELECT id, tenant_id FROM google_locations WHERE selected")[0]
    # a second business with its own review row
    biz = make_business("Second Clinic")
    owner_exec("INSERT INTO google_connections (id, tenant_id, google_sub, status, scopes, created_at, updated_at, auth_mode, api_access) VALUES (gen_random_uuid(), :t, 's2', 'active', '', now(), now(), 'client_token', 'approved')", t=biz.tenant_id)
    c2 = owner_query("SELECT id FROM google_connections WHERE tenant_id = :t", t=biz.tenant_id)[0][0]
    owner_exec("INSERT INTO google_locations (id, tenant_id, connection_id, google_account_name, google_location_name, title, selected, consecutive_failures, created_at, updated_at) VALUES (gen_random_uuid(), :t, :c, 'accounts/9', 'locations/9', 'B', true, 0, now(), now())", t=biz.tenant_id, c=str(c2))
    g2 = owner_query("SELECT id FROM google_locations WHERE connection_id = :c", c=str(c2))[0][0]
    owner_exec("INSERT INTO reviews (id, tenant_id, google_location_id, external_id, rating, text, review_created_at, first_seen_at, update_count, created_at, updated_at) VALUES (gen_random_uuid(), :t, :g, 'other-1', 5, 'keep me', now(), now(), 0, now(), now())", t=biz.tenant_id, g=str(g2))
    with closing(system_session()) as db:
        gr.purge_connection(db, connected.conn_id)
        db.commit()
    assert owner_query("SELECT count(*) FROM reviews WHERE external_id = 'other-1'")[0][0] == 1
    assert owner_query("SELECT count(*) FROM reviews WHERE tenant_id = :t", t=str(tid))[0][0] == 0


def test_the_start_up_guard_keeps_the_period_inside_googles_stated_limit():
    def prod(**over):
        from cryptography.fernet import Fernet

        base = dict(app_env="production", secret_key="s" * 48, token_encryption_key=Fernet.generate_key().decode(), cookie_secure=True, public_card_base_url="https://go.flowqr.co.in",
                    frontend_url="https://app.flowqr.co.in", cors_origins="https://app.flowqr.co.in", database_url="postgresql+psycopg://flowqr_app:Xk29sLmQ8vNa@db:5432/flowqr",
                    platform_admin_emails="ops@flowhq.in", smtp_host="smtp.sendgrid.net", razorpay_key_id="rzp_live_abcdefghij", razorpay_key_secret="x" * 20, razorpay_webhook_secret="w" * 20,
                    card_price_paise=19900, google_redirect_uri="https://app.flowqr.co.in/api/v1/google/callback", google_client_id="id", google_client_secret="secret")
        base.update(over)
        return Settings(_env_file=None, **base)

    assert config_problems(prod()) == []  # off by default: nothing to say
    assert config_problems(prod(google_content_retention_enabled=True, google_content_retention_days=30)) == []
    assert any("between 1 and 30" in p for p in config_problems(prod(google_content_retention_enabled=True, google_content_retention_days=90)))
    assert any("redact or delete" in p for p in config_problems(prod(google_content_retention_action="keep")))


def test_every_store_of_google_content_is_classified():
    text = " ".join(gr.CLASSIFICATION)
    for needle in ("reviews.text", "gbp_snapshots", "gbp_metric_daily", "reply_drafts", "agent_tasks", "notifications", "audit_logs"):
        assert needle in text
