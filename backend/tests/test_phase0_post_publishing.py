"""Phase 0: Google Posts publishing is crash-safe and never duplicates.

MOCKED: every Google call goes to a TEST DOUBLE (RecordingGoogle). It models the one property that matters here: Google's localPosts.create is NOT
idempotent, so sending twice creates two posts. These tests prove FlowQR's own state handling; they say nothing about the real Google API
(live verification is the separate `google-write-test` command, see docs/AGENT_AUDIT.md).

A "crash" is a BaseException raised from inside the Google call: it is not caught by publish()'s `except Exception`, so the code behaves as if the
process died at exactly that point, and the database is then inspected from a different session."""
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.db import SessionLocal, set_rls_context
from app.models import ScheduledPost
from app.models.base import utcnow
from app.services import google as g
from app.services.agent import posts as posts_svc
from tests.conftest import owner_exec, owner_query
from tests.test_google_business_agent import FakeAgentGoogle
from tests.test_google_and_reviews import connected, sync_select  # noqa: F401


class SimulatedCrash(BaseException):
    """The worker or API process died here."""


class RecordingGoogle(FakeAgentGoogle):
    """TEST DOUBLE. Counts creates, stamps createTime like Google does, and can fail or die at a chosen point."""

    def __init__(self):
        super().__init__()
        self.creates = 0
        self.crash = None  # "before" | "after": die before Google has the post / after Google created it
        self.raise_after_create = None  # an exception raised AFTER Google created the post (an ambiguous failure: a lost response)
        self.list_error = None
        self.seen_status_at_call = None
        self.watch_row = None

    def create_post(self, at, acct, loc, post):
        self._maybe()  # FakeGbpProvider's injected error (self.error), e.g. a 400 from Google
        if self.watch_row:  # what does a DIFFERENT session see while Google is being called?
            self.seen_status_at_call = owner_query("SELECT status, attempts, publishing_started_at IS NOT NULL FROM scheduled_posts WHERE id = :i", i=self.watch_row)[0]
        if self.crash == "before":
            raise SimulatedCrash()
        self.creates += 1
        p = {"name": f"{acct}/{loc}/localPosts/{self.creates}", "summary": post["summary"], "state": "LIVE", "created_at": utcnow().isoformat()}
        self.posts.append(p)
        if self.crash == "after":
            raise SimulatedCrash()
        if self.raise_after_create:
            raise self.raise_after_create
        return p

    def list_posts(self, at, acct, loc):
        if self.list_error:
            raise self.list_error
        return list(self.posts)


@pytest.fixture()
def fake(monkeypatch):  # the name `connected` (tests/test_google_and_reviews.py) expects
    f = RecordingGoogle()
    monkeypatch.setattr(g, "get_google_provider", lambda: f)
    return f


@pytest.fixture(autouse=True)
def _no_leftover_posts():
    """The test database is shared across tests: park any posts earlier tests left due or in flight, so the scheduled jobs here only see this test's."""
    owner_exec("UPDATE scheduled_posts SET status = 'canceled' WHERE status IN ('scheduled', 'publishing', 'approved')")
    yield


@pytest.fixture()
def rg(fake):
    return fake


@pytest.fixture()
def gid(connected, fake):  # noqa: F811
    sync_select(connected, fake)
    return connected.glocs[0]["id"]


def make_post(gid_, text="Winter check-up slots are open this week. Call to book.", **over) -> uuid.UUID:
    tenant = owner_query("SELECT tenant_id FROM google_locations WHERE id = :g", g=gid_)[0][0]
    db = SessionLocal(); set_rls_context(db, bypass=True)
    uid = owner_query("SELECT user_id FROM memberships WHERE tenant_id = :t LIMIT 1", t=tenant)[0][0]  # a post only reaches Google with a person's approval on it
    p = ScheduledPost(tenant_id=tenant, google_location_id=uuid.UUID(gid_), summary=text, status="scheduled", scheduled_for=utcnow() - timedelta(minutes=1), approved_by=uid, approved_at=utcnow(), **over)
    db.add(p); db.commit(); pid = p.id; db.close()
    return pid


def row(pid):
    r = owner_query("SELECT status, attempts, google_post_name, first_attempt_at IS NOT NULL, publishing_started_at, failure_reason FROM scheduled_posts WHERE id = :i", i=pid)[0]
    return {"status": r[0], "attempts": r[1], "name": r[2], "first": r[3], "started": r[4], "reason": r[5]}


def publish(pid, rg, now=None):
    db = SessionLocal(); set_rls_context(db, bypass=True)
    try:
        p = db.get(ScheduledPost, pid)
        out = posts_svc.publish(db, p, provider=rg, now=now)
        db.commit()
        return out
    finally:
        db.close()


def recover(rg, now=None):
    db = SessionLocal(); set_rls_context(db, bypass=True)
    try:
        return posts_svc.recover_stuck(db, provider=rg, now=now)
    finally:
        db.close()


def age_claim(pid, minutes=30):
    owner_exec("UPDATE scheduled_posts SET publishing_started_at = now() - make_interval(mins => :m) WHERE id = :i", i=pid, m=minutes)


# ============================================================================ 1. the atomic claim

def test_the_publishing_state_is_committed_before_google_is_called(gid, rg):
    pid = make_post(gid)
    rg.watch_row = pid
    assert publish(pid, rg) == "published"
    status, attempts, started = rg.seen_status_at_call  # read by another session, DURING the Google call
    assert status == "publishing" and attempts == 1 and started is True
    assert row(pid)["status"] == "published" and row(pid)["name"] and rg.creates == 1


def test_a_post_that_is_publishing_cannot_be_claimed_or_published_again(gid, rg):
    pid = make_post(gid)
    owner_exec("UPDATE scheduled_posts SET status = 'publishing', publishing_started_at = now() WHERE id = :i", i=pid)
    db = SessionLocal(); set_rls_context(db, bypass=True)
    try:
        assert pid not in [p.id for p in posts_svc.due(db)]  # the scheduler only takes `scheduled`
        with pytest.raises(posts_svc.PostError):  # and a second direct publish of the same row is refused before Google is touched
            posts_svc.publish(db, db.get(ScheduledPost, pid), provider=rg)
    finally:
        db.close()
    assert rg.creates == 0


# ============================================================================ 2. crashes

def test_crash_after_google_created_the_post_is_adopted_not_sent_again(gid, rg):
    pid = make_post(gid)
    rg.crash = "after"
    with pytest.raises(SimulatedCrash):
        publish(pid, rg)
    assert row(pid)["status"] == "publishing" and rg.creates == 1  # the claim survived the crash; Google already has the post
    rg.crash = None

    assert recover(rg)["adopted"] == 0  # too recent: a slow but live publish is never interrupted
    age_claim(pid)
    out = recover(rg)
    assert out == {"adopted": 1, "requeued": 0, "failed": 0, "deferred": 0}
    r = row(pid)
    assert r["status"] == "published" and r["name"] == rg.posts[0]["name"]  # confirmed by what Google lists, not assumed
    assert rg.creates == 1
    assert recover(rg) == {"adopted": 0, "requeued": 0, "failed": 0, "deferred": 0}
    assert [a for (a,) in owner_query("SELECT action FROM audit_logs WHERE entity_id = :i ORDER BY created_at", i=str(pid))] == ["post.recover_adopted"]


def test_crash_before_google_got_the_post_sends_it_exactly_once_after_recovery(gid, rg):
    pid = make_post(gid)
    rg.crash = "before"
    with pytest.raises(SimulatedCrash):
        publish(pid, rg)
    rg.crash = None
    assert row(pid)["status"] == "publishing" and rg.creates == 0
    age_claim(pid)
    assert recover(rg)["requeued"] == 1
    assert row(pid)["status"] == "scheduled"
    assert publish(pid, rg) == "published"
    assert rg.creates == 1 and len(rg.posts) == 1  # one post on Google, not two


def test_recovery_never_resends_when_google_cannot_be_asked(gid, rg):
    pid = make_post(gid)
    rg.crash = "after"
    with pytest.raises(SimulatedCrash):
        publish(pid, rg)
    rg.crash = None
    age_claim(pid)
    rg.list_error = g.GoogleAPIError(503, "Google is down")
    assert recover(rg) == {"adopted": 0, "requeued": 0, "failed": 0, "deferred": 1}
    assert row(pid)["status"] == "publishing" and rg.creates == 1  # left alone, not re-sent on a guess
    rg.list_error = None
    assert recover(rg)["adopted"] == 1 and rg.creates == 1


def test_recovery_gives_up_after_the_attempt_limit_instead_of_looping(gid, rg):
    pid = make_post(gid, attempts=posts_svc.MAX_ATTEMPTS - 1)
    rg.crash = "before"
    with pytest.raises(SimulatedCrash):
        publish(pid, rg)
    rg.crash = None
    age_claim(pid)
    assert recover(rg)["failed"] == 1
    r = row(pid)
    assert r["status"] == "failed" and "not found on Google" in r["reason"] and rg.creates == 0


def test_recovery_marks_a_post_failed_when_its_location_was_disconnected(gid, rg):
    pid = make_post(gid)
    owner_exec("UPDATE scheduled_posts SET status = 'publishing', publishing_started_at = now() - interval '1 hour', first_attempt_at = now() - interval '1 hour', attempts = 1 WHERE id = :i", i=pid)
    owner_exec("UPDATE google_connections SET status = 'disconnected' WHERE id = (SELECT connection_id FROM google_locations WHERE id = :g)", g=gid)
    assert recover(rg)["failed"] == 1 and row(pid)["status"] == "failed"


# ============================================================================ 3. retries

def test_an_ambiguous_failure_then_retry_does_not_duplicate(gid, rg):
    """Google created the post, then the response was lost (a 503/timeout). The retry must look first and adopt it."""
    pid = make_post(gid)
    rg.raise_after_create = g.GoogleAPIError(503, "response lost")
    assert publish(pid, rg) == "retry"
    assert row(pid)["status"] == "scheduled" and rg.creates == 1
    rg.raise_after_create = None
    owner_exec("UPDATE scheduled_posts SET next_attempt_at = now() - interval '1 minute' WHERE id = :i", i=pid)
    assert publish(pid, rg) == "published"
    assert rg.creates == 1 and row(pid)["name"] == rg.posts[0]["name"]


def test_an_owner_retry_after_a_final_failure_still_looks_before_creating(gid, rg):
    pid = make_post(gid, attempts=posts_svc.MAX_ATTEMPTS - 1)
    rg.raise_after_create = g.GoogleAPIError(503, "response lost")
    assert publish(pid, rg) == "failed"  # out of attempts, so it is shown as failed...
    assert rg.creates == 1
    rg.raise_after_create = None
    db = SessionLocal(); set_rls_context(db, bypass=True)
    p = db.get(ScheduledPost, pid)
    posts_svc.retry(p)  # ...and the owner clicks Retry (attempts reset, first_attempt_at kept)
    db.commit(); db.close()
    assert publish(pid, rg) == "published"
    assert rg.creates == 1  # adopted, not created again


def test_a_definite_google_rejection_does_not_look_for_a_post_and_creates_nothing(gid, rg):
    pid = make_post(gid)
    rg.error = g.GoogleAPIError(400, "invalid summary")  # FakeGbpProvider raises this from create_post via _maybe()
    assert publish(pid, rg) == "failed"
    assert rg.creates == 0 and "rejected" in row(pid)["reason"]


def test_two_flowqr_posts_with_the_same_text_never_adopt_each_others_google_post(gid, rg):
    a, b = make_post(gid, text="Same words in two posts, on purpose."), make_post(gid, text="Same words in two posts, on purpose.")
    assert publish(a, rg) == "published"
    owner_exec("UPDATE scheduled_posts SET first_attempt_at = now() - interval '1 minute', attempts = 1 WHERE id = :i", i=b)  # b "may have been tried before"
    assert publish(b, rg) == "published"
    assert rg.creates == 2 and row(a)["name"] != row(b)["name"]  # a's post is claimed by a, so b created its own


def test_a_rejected_google_post_is_never_adopted_as_published(gid, rg):
    pid = make_post(gid)
    owner_exec("UPDATE scheduled_posts SET first_attempt_at = now() - interval '1 minute', attempts = 1 WHERE id = :i", i=pid)
    rg.posts.append({"name": "accounts/1/locations/2/localPosts/rejected", "summary": "Winter check-up slots are open this week. Call to book.", "state": "REJECTED",
                     "created_at": utcnow().isoformat()})
    assert publish(pid, rg) == "published"
    assert rg.creates == 1 and row(pid)["name"] != "accounts/1/locations/2/localPosts/rejected"


def test_an_old_google_post_with_the_same_text_is_not_adopted(gid, rg):
    pid = make_post(gid)
    owner_exec("UPDATE scheduled_posts SET first_attempt_at = now(), attempts = 1 WHERE id = :i", i=pid)
    rg.posts.append({"name": "accounts/1/locations/2/localPosts/old", "summary": "Winter check-up slots are open this week. Call to book.", "state": "LIVE",
                     "created_at": (utcnow() - timedelta(days=30)).isoformat()})  # a genuine earlier post, long before this attempt
    assert publish(pid, rg) == "published"
    assert rg.creates == 1


# ============================================================================ 4. bookkeeping and wiring

def test_a_fresh_approval_resets_the_publish_lifecycle(gid, rg):
    pid = make_post(gid)
    owner_exec("UPDATE scheduled_posts SET status = 'awaiting_approval', first_attempt_at = now(), publish_token = gen_random_uuid(), publishing_started_at = now() WHERE id = :i", i=pid)
    db = SessionLocal(); set_rls_context(db, bypass=True)
    p = db.get(ScheduledPost, pid)
    posts_svc.approve(p, user_id=uuid.uuid4(), when=None)
    assert (p.first_attempt_at, p.publishing_started_at, p.publish_token, p.attempts) == (None, None, None, 0)
    db.close()


def test_one_google_post_name_cannot_belong_to_two_flowqr_posts_at_a_location(gid, rg):
    a, b = make_post(gid), make_post(gid)
    owner_exec("UPDATE scheduled_posts SET google_post_name = 'accounts/1/locations/2/localPosts/9' WHERE id = :i", i=a)
    with pytest.raises(Exception) as exc:
        owner_exec("UPDATE scheduled_posts SET google_post_name = 'accounts/1/locations/2/localPosts/9' WHERE id = :i", i=b)
    assert "uq_scheduled_posts_google_name" in str(exc.value) or "duplicate" in str(exc.value).lower()


def test_the_recovery_job_is_registered_and_scheduled(gid, rg, monkeypatch):
    from app.workers import tasks
    from app.workers.celery_app import celery_app

    assert celery_app.conf.beat_schedule["recover-stuck-posts"]["task"] == "flowqr.recover_stuck_posts"
    assert celery_app.conf.beat_schedule["recover-stuck-posts"]["schedule"] <= 600
    pid = make_post(gid)
    rg.crash = "after"
    with pytest.raises(SimulatedCrash):
        publish(pid, rg)
    rg.crash = None
    age_claim(pid)
    assert tasks.recover_stuck_posts.run() == {"adopted": 1, "requeued": 0, "failed": 0, "deferred": 0}  # the real task, through the real Google factory (patched to the double)
    assert row(pid)["status"] == "published" and rg.creates == 1


def test_the_scheduled_job_publishes_once_even_if_it_runs_twice(gid, rg):
    from app.workers.tasks import publish_due_posts

    pid = make_post(gid)
    first = publish_due_posts.run()
    second = publish_due_posts.run()
    assert first["published"] == 1 and second["published"] == 0
    assert rg.creates == 1 and row(pid)["status"] == "published"
