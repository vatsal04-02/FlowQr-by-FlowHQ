"""Phase 2: the platform-admin work queue (failed Google actions, waiting approvals, deletion and export requests). Real database; Google is the Phase 1 test double.
The queue is read-only and built from real records: nothing is estimated, and an empty queue says so."""
import uuid
from datetime import timedelta

from app.models.agent import ScheduledPost
from app.models.base import utcnow
from tests.conftest import owner_exec
from tests.test_google_and_reviews import connected  # noqa: F401
from tests.test_phase1_executor import desc, env, fake, gid  # noqa: F401


def test_the_queue_shows_failed_pending_and_account_requests_from_real_records(env, admin):  # noqa: F811
    a_fail, a_wait = desc(env), desc(env, "A fuller and more useful description of this business, written only from the verified facts we hold.")
    owner_exec("UPDATE agent_actions SET status = 'failed', attempts = 3, last_error = 'Google said no: 403 permission denied' WHERE id = :a", a=a_fail.id)
    owner_exec("UPDATE agent_actions SET created_at = now() - interval '30 hours' WHERE id = :a", a=a_wait.id)
    post = ScheduledPost(tenant_id=env.tenant.id, google_location_id=env.gloc.id, summary="Weekend offer", status="failed", attempts=4,
                         failure_reason="Google refused: the post link is not allowed", scheduled_for=utcnow() - timedelta(hours=2))
    env.db.add(post)
    env.db.commit()
    assert env.biz.get("/account/export").status_code == 200
    owner_exec("UPDATE tenants SET deletion_requested_at = now() - interval '5 days', deletion_scheduled_for = now() - interval '1 hour' WHERE id = :t", t=env.tenant.id)

    q = admin.get("/admin/work-queue").json()
    mine = [x for x in q["failed"]["actions"] if x["id"] == str(a_fail.id)]
    assert mine and mine[0]["status"] == "failed" and mine[0]["attempts"] == 3 and "permission denied" in mine[0]["error"] and mine[0]["business"] == env.tenant.name
    assert q["failed"]["counts"]["failed"] >= 1
    assert any(p["id"] == str(post.id) and "not allowed" in p["error"] for p in q["failed"]["posts"])
    waiting = [x for x in q["pending"]["actions"] if x["id"] == str(a_wait.id)]
    assert waiting and waiting[0]["waiting_hours"] >= 29 and waiting[0]["level"] == 1
    assert q["pending"]["actions_total"] >= 1
    ours = [d for d in q["account_requests"]["deletions_scheduled"] if d["tenant_id"] == str(env.tenant.id)]
    assert ours and ours[0]["overdue"] is True, "a deletion whose time has passed must be flagged: the daily job is not running or is failing"
    assert any(e["tenant_id"] == str(env.tenant.id) and e["files"] for e in q["account_requests"]["exports_recent"])
    assert q["window_days"] == 30
    owner_exec("UPDATE tenants SET deletion_requested_at = NULL, deletion_scheduled_for = NULL WHERE id = :t", t=env.tenant.id)  # the test database is shared: leave nothing for the daily job


def test_an_old_failure_drops_out_of_the_window_and_a_quiet_platform_reports_nothing(env, admin):  # noqa: F811
    a = desc(env)
    owner_exec("UPDATE agent_actions SET status = 'failed', last_error = 'old' , updated_at = now() - interval '45 days' WHERE id = :a", a=a.id)
    q = admin.get("/admin/work-queue").json()
    assert str(a.id) not in [x["id"] for x in q["failed"]["actions"]]
    assert set(q) == {"generated_at", "window_days", "failed", "pending", "account_requests"}


def test_only_a_platform_admin_can_read_the_queue(biz_a):
    assert biz_a.get("/admin/work-queue").status_code == 403


def test_the_queue_never_discloses_secrets_or_the_content_of_a_proposed_change(env, admin):  # noqa: F811
    a = desc(env)
    owner_exec("UPDATE agent_actions SET status = 'failed', last_error = 'x' WHERE id = :a", a=a.id)
    body = admin.get("/admin/work-queue").text.lower()
    for needle in ("proposed_value", "current_value", "refresh_token", "access_token", "password"):
        assert needle not in body, needle
