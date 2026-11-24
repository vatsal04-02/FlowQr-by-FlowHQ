"""Operations monitoring: the admin Operations checks, worker/scheduler heartbeat, failed-job tracking, AI budget, backup freshness,
critical-alert emails and the browser crash relay. Checks run against the real database; Redis is replaced by a tiny in-memory fake
so the tests do not depend on a running Redis."""
import json
import time
import uuid
from datetime import timedelta
from pathlib import Path

import pytest

from app.core.config import settings
from app.core.db import system_session
from app.models import AIGenerationLog
from app.models.base import utcnow
from app.services import mailer, ops
from tests.conftest import make_business, owner_exec, owner_query


class FakeRedis:
    def __init__(self):
        self.kv, self.h = {}, {}

    def ping(self):
        return True

    def set(self, k, v, ex=None):
        self.kv[k] = v.encode() if isinstance(v, str) else v

    def get(self, k):
        return self.kv.get(k)

    def hget(self, name, k):
        return self.h.get(name, {}).get(k)

    def hset(self, name, k, v):
        self.h.setdefault(name, {})[k] = v.encode() if isinstance(v, str) else v

    def hgetall(self, name):
        return {k.encode(): v for k, v in self.h.get(name, {}).items()}

    def hdel(self, name, k):
        self.h.get(name, {}).pop(k, None)

    def expire(self, *a):
        pass


@pytest.fixture()
def redis(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr(ops, "_redis", lambda: r)
    return r


def by_id(result):
    return {c["id"]: c for c in result["checks"]}


# ------------------------------------------------------------------ access
def test_only_platform_admins_see_operations(biz_a, client, admin):
    assert client.get("/api/v1/admin/ops").status_code == 401
    assert biz_a.get("/admin/ops").status_code == 403
    r = admin.get("/admin/ops")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ops.RANK and {"database", "migrations", "worker", "backup", "sentry", "smtp", "ai_budget"} <= set(by_id(body))
    assert all({"id", "label", "status", "detail", "action"} <= set(c) for c in body["checks"])


def test_the_page_never_contains_a_secret(admin, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "AIza-gemini-secret-xyz")
    monkeypatch.setattr(settings, "smtp_password", "smtp-secret-xyz")
    monkeypatch.setattr(settings, "sentry_dsn", "https://publickey@o1.ingest.sentry.io/123")
    monkeypatch.setattr(settings, "razorpay_key_secret", "rzp-secret-xyz")
    text = admin.get("/admin/ops").text
    assert not any(s in text for s in ("AIza-gemini-secret-xyz", "smtp-secret-xyz", "publickey@", "rzp-secret-xyz", settings.secret_key))


# ------------------------------------------------------------------ database, migrations
def test_database_and_migrations_are_checked_for_real():
    db = system_session()
    try:
        assert ops.check_database(db)["status"] == "ok"
        m = ops.check_migrations(db)
        assert m["status"] == "ok" and "At head" in m["detail"], m
    finally:
        db.close()
    real = owner_query("select version_num from alembic_version")[0][0]
    owner_exec("update alembic_version set version_num = '0001_fake'")
    try:
        db = system_session()
        try:
            bad = ops.check_migrations(db)
        finally:
            db.close()
        assert bad["status"] == "critical" and "0001_fake" in bad["detail"]
    finally:
        owner_exec("update alembic_version set version_num = :v", v=real)


def test_the_app_role_can_read_but_not_change_the_migration_version():
    db = system_session()
    try:
        assert db.execute(ops.text("select count(*) from alembic_version")).scalar() == 1
        with pytest.raises(Exception):
            db.execute(ops.text("update alembic_version set version_num = 'x'"))
    finally:
        db.rollback()
        db.close()


# ------------------------------------------------------------------ worker + scheduler
def test_heartbeat_states(redis):
    assert ops.check_heartbeat()["status"] == "critical"  # never seen
    ops.record_heartbeat()
    assert ops.check_heartbeat()["status"] == "ok"
    redis.set(ops.HEARTBEAT_KEY, str(time.time() - 400))
    assert ops.check_heartbeat()["status"] == "warn"
    redis.set(ops.HEARTBEAT_KEY, str(time.time() - 4000))
    assert ops.check_heartbeat()["status"] == "critical"


def test_heartbeat_is_unknown_not_healthy_when_redis_is_down(monkeypatch):
    monkeypatch.setattr(ops, "_redis", lambda: None)
    assert ops.check_heartbeat()["status"] == "unknown" and ops.check_redis()["status"] == "critical"


def test_failed_jobs_show_until_they_succeed_again(redis):
    ops.record_task("flowqr.publish_due_posts", True)
    assert ops.check_task_failures()[0]["status"] == "ok"
    time.sleep(0.05)  # Windows' clock ticks every ~15 ms: a failure in the same tick as the success would not count as "after" it
    ops.record_task("flowqr.publish_due_posts", False, "GoogleRateLimited")
    c = ops.check_task_failures()[0]
    assert c["status"] == "warn" and "publish_due_posts" in c["detail"] and "GoogleRateLimited" in c["detail"]
    time.sleep(0.05)
    ops.record_task("flowqr.publish_due_posts", True)
    assert ops.check_task_failures()[0]["status"] == "ok"


def test_celery_signals_record_outcomes_and_heartbeat_task_works(redis):
    from app.workers import monitor
    monitor.heartbeat()
    assert ops.check_heartbeat()["status"] == "ok"

    class T:
        name = "flowqr.sync_due_locations"
    monitor._fail(sender=T, exception=ValueError("customer text must not be stored"))
    assert "customer text" not in json.dumps({k: v.decode() for k, v in redis.h[ops.TASKS_KEY].items()})  # class name only
    assert ops.check_task_failures()[0]["status"] == "warn"
    monitor._ok(sender=T)
    assert ops.check_task_failures()[0]["status"] == "ok"


# ------------------------------------------------------------------ AI budget
def _log(db, tenant_id, cost):
    db.add(AIGenerationLog(tenant_id=tenant_id, kind="reply", provider="gemini", model="m", language="en", input_chars=1, output_chars=1, status="ok",
                           cost_usd=cost, latency_ms=1, created_at=utcnow()))
    db.commit()


def test_ai_budget_warns_at_80_and_flags_at_100(biz_a, monkeypatch):
    db = system_session()
    try:
        base = ops.ai_spend(db)["usd"]
        monkeypatch.setattr(settings, "ai_monthly_budget_usd", base + 10.0)
        assert next(c for c in ops.check_ai(db) if c["id"] == "ai_budget")["status"] == "ok"
        _log(db, uuid.UUID(biz_a.tenant_id), 8.5)
        c = next(c for c in ops.check_ai(db) if c["id"] == "ai_budget")
        assert c["status"] == "warn" and "%" in c["detail"]
        _log(db, uuid.UUID(biz_a.tenant_id), 2.0)
        assert next(c for c in ops.check_ai(db) if c["id"] == "ai_budget")["status"] == "critical"
        monkeypatch.setattr(settings, "ai_monthly_budget_usd", 0.0)
        assert next(c for c in ops.check_ai(db) if c["id"] == "ai_budget")["status"] == "warn"  # no budget set is a warning, not "fine"
    finally:
        db.close()


def test_ai_cost_is_estimated_from_tokens_only_when_prices_are_configured(biz_a, monkeypatch):
    db = system_session()
    try:
        monkeypatch.setattr(settings, "ai_price_in_per_mtok", 0.0), monkeypatch.setattr(settings, "ai_price_out_per_mtok", 0.0)
        before = ops.ai_spend(db)
        db.add(AIGenerationLog(tenant_id=uuid.UUID(biz_a.tenant_id), kind="reply", provider="gemini", model="m", language="en", input_chars=1, output_chars=1, status="ok",
                               prompt_tokens=2_000_000, completion_tokens=1_000_000, latency_ms=1, created_at=utcnow()))
        db.commit()
        unpriced = ops.ai_spend(db)
        assert unpriced["usd"] == before["usd"] and unpriced["unpriced_calls"] == before["unpriced_calls"] + 1  # honestly unknown, not zero cost
        monkeypatch.setattr(settings, "ai_price_in_per_mtok", 0.5), monkeypatch.setattr(settings, "ai_price_out_per_mtok", 3.0)
        priced = ops.ai_spend(db)
        assert round(priced["usd"] - before["usd"], 4) >= 4.0  # 2M*0.5/1M + 1M*3/1M
    finally:
        db.close()


# ------------------------------------------------------------------ backups
def test_backup_status_file_states(tmp_path, monkeypatch):
    f = tmp_path / "status.json"
    monkeypatch.setattr(settings, "backup_status_file", str(f))
    assert ops.check_backup()["status"] in ("warn", "critical")  # missing

    def write(**kw):
        d = {"ok": True, "finished_at": utcnow().isoformat(), "encrypted": True, "offsite": True, "size_mb": 3.2, "restore_verified_at": utcnow().isoformat()}
        d.update(kw)
        f.write_text(json.dumps(d))
        return ops.check_backup()

    assert write()["status"] == "ok"
    assert write(offsite=False)["status"] == "warn" and "not copied off the server" in ops.check_backup()["detail"]
    assert write(encrypted=False)["status"] == "warn"
    assert write(finished_at=(utcnow() - timedelta(hours=60)).isoformat())["status"] == "critical"
    assert write(ok=False, error="pg_dump failed")["status"] == "critical"
    assert write(restore_verified_at=None)["status"] == "warn"  # a backup nobody has restored is not proven
    f.write_text("{not json")
    assert ops.check_backup()["status"] == "warn"


# ------------------------------------------------------------------ alerts
def test_new_critical_checks_email_admins_once_per_day(redis, monkeypatch):
    monkeypatch.setattr(settings, "platform_admin_emails", "ops-a@example.com,ops-b@example.com")
    mailer.OUTBOX.clear()
    result = {"checks": [{"id": "worker", "label": "Worker and scheduler", "status": "critical", "detail": "No heartbeat", "action": "Start the worker"},
                         {"id": "redis", "label": "Redis", "status": "ok", "detail": "fine", "action": ""}]}
    assert ops.alert_on_new_critical(result) == ["worker"]
    assert sorted(m["to"] for m in mailer.OUTBOX) == ["ops-a@example.com", "ops-b@example.com"]
    assert "Start the worker" in mailer.OUTBOX[0]["body"] and "Redis" not in mailer.OUTBOX[0]["body"]
    mailer.OUTBOX.clear()
    assert ops.alert_on_new_critical(result) == [] and mailer.OUTBOX == []  # no repeat while it stays critical
    result["checks"][0]["status"] = "ok"
    ops.alert_on_new_critical(result)  # recovered: forgotten
    result["checks"][0]["status"] = "critical"
    assert ops.alert_on_new_critical(result) == ["worker"]  # breaks again: alert again


def test_ops_watch_task_runs_and_reports_status(redis):
    from app.workers import monitor
    out = monitor.ops_watch()
    assert out["status"] in ops.RANK and isinstance(out["alerted"], list)


# ------------------------------------------------------------------ browser crash relay
def test_browser_crash_reports_need_a_session_and_csrf_and_are_limited(client, monkeypatch):
    assert client.post("/api/v1/monitoring/client-error", json={"message": "boom"}).status_code in (401, 403)
    s = make_business("Crash Biz")
    assert s.post("/monitoring/client-error", json={"message": "x" * 301}).status_code == 422
    seen = []
    from app.api.v1 import ops as ops_api
    monkeypatch.setattr(ops_api.monitoring, "capture_message", lambda *a, **k: seen.append((a, k)))
    assert s.post("/monitoring/client-error", json={"message": "TypeError: x is undefined", "digest": "123", "path": "/ai/today"}).status_code == 204
    assert len(seen) == 1 and "TypeError" in seen[0][0][0]
    s.http.headers.pop("X-CSRF-Token", None)
    r = s.http.post("/api/v1/monitoring/client-error", json={"message": "no csrf"})
    assert r.status_code == 403


# ------------------------------------------------------------------ error reporting scrubbing
def test_error_reports_drop_request_bodies_cookies_and_local_variables():
    from app.core import monitoring
    ev = {"request": {"url": "https://x/api/v1/reviews", "data": {"text": "customer review"}, "cookies": {"flowqr_session": "tok"}, "headers": {"Cookie": "a"}},
          "user": {"email": "a@b.c"}, "exception": {"values": [{"stacktrace": {"frames": [{"function": "f", "vars": {"token": "secret"}}]}}]}}
    out = monitoring.scrub(ev)
    flat = json.dumps(out)
    assert "customer review" not in flat and "flowqr_session" not in flat and "secret" not in flat and "a@b.c" not in flat and out["request"]["url"].endswith("/reviews")


def test_monitoring_is_a_noop_without_a_dsn(monkeypatch):
    from app.core import monitoring
    monkeypatch.setattr(settings, "sentry_dsn", "")
    monkeypatch.setattr(monitoring, "_on", False)
    assert monitoring.init("api") is False
    monitoring.capture_message("nothing happens")  # must not raise
