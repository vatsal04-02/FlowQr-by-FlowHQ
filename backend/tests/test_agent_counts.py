"""GET /agent/counts: the two numbers behind the sidebar badges (tasks to do, approvals waiting).

The point of the endpoint is that it is safe to call on every page: it must never plan, write or commit (unlike GET /agent/tasks), it is scoped to the business, and a browser may
keep the answer for about a minute. Google and the AI are test doubles, as in test_agent.py."""
import uuid

from sqlalchemy import func, select

from app.core.db import SessionLocal, set_rls_context
from app.models import AgentTask, ReplyDraft, ReplyStatus
from tests.test_agent import add_review, ai  # noqa: F401
from tests.test_gbp import fake, gid  # noqa: F401
from tests.test_google_and_reviews import connected  # noqa: F401

TODO = {"suggested", "drafted", "failed"}


def task_rows(tenant_id: str) -> int:
    with SessionLocal() as db:
        set_rls_context(db, bypass=True)
        return db.scalar(select(func.count()).select_from(AgentTask).where(AgentTask.tenant_id == uuid.UUID(tenant_id))) or 0


def add_draft(review_id: str, tenant_id: str, status=ReplyStatus.draft):
    with SessionLocal() as db:
        set_rls_context(db, bypass=True)
        d = ReplyDraft(tenant_id=uuid.UUID(tenant_id), review_id=uuid.UUID(review_id), body="Thank you for your review.", status=status)
        db.add(d)
        db.commit()
        return str(d.id)


def test_a_new_business_has_nothing_waiting_and_the_answer_may_be_cached_for_a_minute(connected, ai):
    r = connected.get("/agent/counts")
    assert r.status_code == 200 and r.json() == {"tasks": 0, "approvals": 0}
    assert r.headers["cache-control"] == "private, max-age=60" and "Cookie" in r.headers["vary"]  # the cached answer belongs to this session, not to whoever asks next


def test_counting_never_plans_or_writes(connected, ai, gid):
    add_review(connected, gid, rating=1, text="Waited far too long", days_ago=2)  # a review the daily plan would suggest a reply for
    before = task_rows(connected.tenant_id)
    for _ in range(3):
        assert connected.get("/agent/counts").json() == {"tasks": 0, "approvals": 0}
    assert task_rows(connected.tenant_id) == before == 0  # only the planner (POST /agent/plan/run, or the daily job) creates tasks; counting never does


def test_tasks_counts_what_needs_the_owner_and_agrees_with_the_task_list(connected, ai, gid):
    add_review(connected, gid, rating=1, text="Waited far too long", days_ago=2)
    assert connected.post("/agent/plan/run").json()["created"] >= 1
    listed = connected.get("/agent/tasks", params={"scope": "open"}).json()["tasks"]
    todo = [t for t in listed if t["status"] in TODO]
    assert todo, "the planner should have suggested something for an unanswered 1-star review"
    assert connected.get("/agent/counts").json()["tasks"] == len(todo)
    # snoozing a task quiets its badge
    connected.post(f"/agent/tasks/{todo[0]['id']}/snooze", json={"days": 2})
    assert connected.get("/agent/counts").json()["tasks"] == len(todo) - 1


def test_approvals_counts_reply_drafts_waiting_and_is_tenant_scoped(connected, ai, gid, biz_b):
    review = add_review(connected, gid, rating=4, text="Good service", days_ago=1)
    draft = add_draft(review, connected.tenant_id)
    assert connected.get("/agent/counts").json()["approvals"] == 1
    assert connected.get("/agent/approvals").json()["replies"].__len__() == 1  # the Approvals page lists the same item
    assert biz_b.get("/agent/counts").json() == {"tasks": 0, "approvals": 0}  # another business sees none of it
    with SessionLocal() as db:
        set_rls_context(db, bypass=True)
        db.get(ReplyDraft, uuid.UUID(draft)).status = ReplyStatus.published
        db.commit()
    assert connected.get("/agent/counts").json()["approvals"] == 0


def test_counts_needs_a_session(connected):
    from fastapi.testclient import TestClient

    from app.main import app
    assert TestClient(app).get("/api/v1/agent/counts").status_code == 401
