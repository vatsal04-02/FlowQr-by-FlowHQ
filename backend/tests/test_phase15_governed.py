"""Phase 1.5: posts, photos, replies and the owner's own profile edits all go through the centralised action engine (policy, approval evidence, emergency stop,
claim, read-back, tamper-evident history). MOCKED: Google is a TEST DOUBLE (GovGoogle) that can hide what it was sent, fail, or answer 200 without storing.
The database, the state machines and the policy are real. Nothing here shows what the real Google API does."""
import uuid
from datetime import timedelta

import pytest

from app.core.config import settings
from app.models.base import utcnow
from app.services import google as g
from app.services.agent import autonomy_policy as pol
from app.services.agent import content_exec, history
from app.core.db import SessionLocal, set_rls_context
from tests.conftest import owner_exec, owner_query
from tests.test_agent import GOOD, make_post
from tests.test_google_and_reviews import StubReplyAI, connected, greview, sync_select  # noqa: F401
from tests.test_google_business_agent import FakeAgentGoogle, jpeg, upload
from tests.test_location_permissions import invite


class GovGoogle(FakeAgentGoogle):
    """TEST DOUBLE. `hide_posts` = Google accepts a post but never lists it; `ghost_reply` = answers a reply 200 but stores nothing."""

    def __init__(self):
        super().__init__()
        self.hide_posts, self.ghost_reply, self.list_post_calls = False, False, 0

    def update_location(self, at, loc, changes):
        self._maybe(); self.writes.append(("update", dict(changes)))
        for k, v in changes.items():
            if k in ("description", "hours", "phone", "website"):
                self.details[k] = v
        return dict(self.details)

    def list_posts(self, at, acct, loc):
        self.list_post_calls += 1
        return [] if self.hide_posts else super().list_posts(at, acct, loc)

    def reply_to_review(self, at, acct, loc, review_id, comment):
        if self.reply_error:
            raise self.reply_error
        self.replies.append((review_id, comment))
        if not self.ghost_reply:
            for rv in self.reviews:
                if rv.external_id == review_id:
                    rv.reply_text, rv.reply_state = comment, "APPROVED"
        return {"comment": comment, "state": "APPROVED", "updated_at": None, "policy_violation": None}


@pytest.fixture()
def fake(monkeypatch):
    f = GovGoogle()
    monkeypatch.setattr(g, "get_google_provider", lambda: f)
    return f


@pytest.fixture()
def gid(connected, fake):  # noqa: F811
    sync_select(connected, fake)
    return connected.glocs[0]["id"]


def scheduled_post(biz, gid_, text=GOOD):
    p = make_post(biz, gid_, text)
    biz.post(f"/posts/{p['id']}/submit")
    assert biz.post(f"/posts/{p['id']}/approve", json={"scheduled_for": (utcnow() + timedelta(hours=3)).isoformat()}).status_code == 200
    owner_exec("UPDATE scheduled_posts SET scheduled_for = now() - interval '1 minute' WHERE id = :p", p=p["id"])
    return p["id"]


def acts(sid):
    return owner_query("SELECT status, attempts, action_type, subject_type, \"authorization\", policy_level, verification->>'matched', last_error, id FROM agent_actions WHERE subject_id = :s ORDER BY created_at", s=sid)


def events(action_id):
    return [e for (e,) in owner_query("SELECT event_type FROM agent_intervention_events WHERE action_id = :a ORDER BY seq", a=action_id)]


def clean():
    owner_exec("UPDATE agent_actions SET status = 'canceled' WHERE status IN ('pending_approval', 'approved', 'executing')")
    owner_exec("UPDATE scheduled_posts SET status = 'canceled' WHERE status IN ('scheduled', 'publishing')")
    owner_exec("UPDATE scheduled_media SET status = 'canceled' WHERE status IN ('scheduled', 'publishing')")


@pytest.fixture(autouse=True)
def _quiet():
    clean()
    yield


# ============================================================================ policy: public content is person-only

def test_posts_photos_and_replies_are_level_2_and_can_never_run_on_their_own():
    for t in ("publish_content", "upload_photo", "reply_publish", "content_edit", "content_delete"):
        spec = pol.SPECS[t]
        d = pol.classify(t)
        assert spec.level == 2 and spec.person_only and d.level == 2
        # standing policy cannot authorise them, even with autonomy on and the type set to "auto" in the raw data
        assert pol.authorization_for(d, autonomy_enabled=True, suspended=False, permissions={t: "auto"}) == "owner"
        assert pol.validate_permissions({t: "auto"}) and "public content" in pol.validate_permissions({t: "auto"})[0]
    assert pol.validate_permissions({"publish_content": "ask", "upload_photo": "off"}) == []


def test_the_policy_endpoint_and_settings_say_a_person_approves_every_post_photo_and_reply(connected):
    p = {a["type"]: a for a in connected.get("/agent/policy").json()["actions"]}
    for t in ("publish_content", "upload_photo", "reply_publish"):
        assert p[t]["can_be_preauthorised"] is False and p[t]["needs_person_every_time"] is True
    assert p["hours_update"]["can_be_preauthorised"] is True
    r = connected.put("/agent/autonomy-settings", json={"permissions": {"publish_content": "auto"}})
    assert r.status_code == 422 and "public content" in r.json()["detail"]["problems"][0]
    perms = {x["type"]: x for x in connected.get("/agent/autonomy-settings").json()["permissions"]}
    assert perms["publish_content"]["can_be_auto"] is False and perms["hours_update"]["can_be_auto"] is True


# ============================================================================ Google Posts

def test_a_scheduled_post_is_published_through_a_governed_action_and_read_back(connected, fake, gid):
    from app.workers.tasks import publish_due_posts
    sid = scheduled_post(connected, gid)
    assert publish_due_posts.run()["published"] == 1 and len(fake.posts) == 1
    (st, attempts, atype, subj, authz, level, matched, err, aid), = acts(sid)
    assert (st, attempts, atype, subj, authz, level, matched, err) == ("executed", 1, "publish_content", "post", "owner", 2, "true", None)
    ev = events(aid)
    assert ev[:3] == ["proposed", "policy_classified", "approved"] and ev[-4:] == ["executing", "google_write", "read_back", "verified"]
    approval = owner_query("SELECT decision, basis, authorized_by IS NOT NULL FROM agent_action_approvals WHERE action_id = :a", a=aid)[0]
    assert approval == ("approved", "person", True)  # the person's own approval, carried over from the post (the job does not know their role)
    db = SessionLocal(); set_rls_context(db, bypass=True)
    assert history.verify(db, aid)["ok"] is True
    db.close()
    assert owner_query("SELECT status FROM scheduled_posts WHERE id = :p", p=sid)[0][0] == "published"  # the owner-facing state is unchanged


def test_the_same_post_is_never_sent_twice_however_often_it_is_run(connected, fake, gid):
    from app.workers.tasks import publish_due_posts
    sid = scheduled_post(connected, gid)
    assert publish_due_posts.run()["published"] == 1
    assert publish_due_posts.run()["published"] == 0 and len(fake.posts) == 1 and len(acts(sid)) == 1
    db = SessionLocal(); set_rls_context(db, bypass=True)
    from app.models import ScheduledPost
    p = db.get(ScheduledPost, uuid.UUID(sid))
    again = content_exec.run(db, "post", p)  # asking again returns what already happened; nothing is sent
    assert again["outcome"] == "done" and again["reason"] == "already_executed" and len(fake.posts) == 1
    db.close()


def test_a_post_nobody_approved_is_never_sent(connected, fake, gid):
    from app.workers.tasks import publish_due_posts
    sid = scheduled_post(connected, gid)
    owner_exec("UPDATE scheduled_posts SET approved_by = NULL WHERE id = :p", p=sid)
    assert publish_due_posts.run()["held"] == 1 and fake.posts == [] and acts(sid) == []
    assert owner_query("SELECT status FROM scheduled_posts WHERE id = :p", p=sid)[0][0] == "scheduled"


def test_the_emergency_stop_holds_posts_and_the_approve_now_button_without_losing_them(connected, fake, gid, monkeypatch):
    from app.workers.tasks import publish_due_posts
    monkeypatch.setattr(settings, "autonomy_emergency_stop", True)
    p = make_post(connected, gid)
    connected.post(f"/posts/{p['id']}/submit")
    r = connected.post(f"/posts/{p['id']}/approve", json={}).json()
    assert r["publish_result"] == "held" and r["status"] == "scheduled" and fake.posts == [] and acts(p["id"]) == []
    assert publish_due_posts.run()["stopped"] is True and fake.posts == []
    monkeypatch.setattr(settings, "autonomy_emergency_stop", False)
    assert publish_due_posts.run()["published"] == 1 and len(fake.posts) == 1 and acts(p["id"])[0][0] == "executed"


def test_google_accepting_a_post_it_does_not_list_is_not_confirmed(connected, fake, gid):
    from app.workers.tasks import publish_due_posts
    fake.hide_posts = True
    sid = scheduled_post(connected, gid)
    assert publish_due_posts.run()["published"] == 1
    (st, _, _, _, _, _, matched, err, aid), = acts(sid)
    assert st == "failed" and matched == "false" and "not confirmed" in err and "does not show it yet" in err
    assert events(aid)[-3:] == ["google_write", "read_back", "failed"]
    # the action is not counted toward autonomy's automatic suspension: nothing here is autonomous
    assert owner_query("SELECT coalesce(max(autonomy_failure_streak), 0) FROM agent_settings WHERE tenant_id = :t", t=connected.tenant_id)[0][0] == 0


def test_a_temporary_google_error_retries_the_same_action_and_sends_once(connected, fake, gid):
    from app.workers.tasks import publish_due_posts
    sid = scheduled_post(connected, gid)
    fake.error = g.GoogleAPIError(503, "Google is busy")
    assert publish_due_posts.run()["retry"] == 1 and fake.posts == []
    (st, attempts, *_rest), = acts(sid)
    assert st == "approved" and attempts == 1
    fake.error = None
    owner_exec("UPDATE scheduled_posts SET next_attempt_at = now() - interval '1 minute' WHERE id = :p", p=sid)
    assert publish_due_posts.run()["published"] == 1 and len(fake.posts) == 1
    (st, attempts, *_rest), = acts(sid)
    assert (st, attempts) == ("executed", 2)  # one action, two attempts, one post


def test_a_refused_post_fails_its_action_and_an_owner_retry_is_a_new_one_that_still_sends_once(connected, fake, gid):
    from app.workers.tasks import publish_due_posts
    sid = scheduled_post(connected, gid)
    fake.error = g.GoogleAPIError(403, "denied")
    assert publish_due_posts.run()["failed"] == 1
    assert [a[0] for a in acts(sid)] == ["failed"] and "denied" in acts(sid)[0][7].lower()
    fake.error = None
    r = connected.post(f"/posts/{sid}/retry")
    assert r.status_code == 200 and r.json()["publish_result"] == "published" and len(fake.posts) == 1
    assert [a[0] for a in acts(sid)] == ["failed", "executed"]


def test_a_plan_without_posts_holds_the_post_and_creates_no_action(connected, fake, gid):
    from app.workers.tasks import publish_due_posts
    from tests.test_billing import db_sub
    sid = scheduled_post(connected, gid)
    db, sub = db_sub(connected.tenant_id); sub.features = ["review_sync", "ai_replies", "gbp_info"]; db.commit(); db.close()
    assert publish_due_posts.run()["held"] == 1 and fake.posts == [] and acts(sid) == []
    db, sub = db_sub(connected.tenant_id); sub.features = ["review_sync", "ai_replies", "gbp_info", "gbp_posts", "gbp_media", "gbp_performance", "insights"]; db.commit(); db.close()


def test_two_workers_cannot_publish_one_post_at_once(connected, fake, gid):
    import threading
    from app.models import ScheduledPost
    sid = scheduled_post(connected, gid)
    fake.hold, fake.entered = threading.Event(), threading.Event()
    orig = fake.create_post

    def slow(at, acct, loc, post):
        fake.entered.set()
        fake.hold.wait(10)
        return orig(at, acct, loc, post)
    fake.create_post = slow
    out: dict = {}

    def worker(name):
        db = SessionLocal(); set_rls_context(db, bypass=True)
        try:
            out[name] = content_exec.run(db, "post", db.get(ScheduledPost, uuid.UUID(sid)))
        finally:
            db.close()
    t = threading.Thread(target=worker, args=("first",)); t.start()
    assert fake.entered.wait(10)
    worker("second")  # the first is inside Google, with its claim committed
    fake.hold.set(); t.join(15)
    assert out["first"]["outcome"] == "done" and out["second"]["outcome"] == "skipped" and out["second"]["reason"] in ("busy", "not_approved")
    assert len(fake.posts) == 1 and len(acts(sid)) == 1


# ============================================================================ crash recovery

def test_a_post_published_when_the_process_died_is_verified_not_sent_again(connected, fake, gid):
    from app.workers.tasks import publish_due_posts
    sid = scheduled_post(connected, gid)
    publish_due_posts.run()
    aid = acts(sid)[0][8]
    owner_exec("UPDATE agent_actions SET status = 'executing', executed_at = NULL, verified_at = NULL, verification = NULL, claimed_at = now() - interval '30 minutes' WHERE id = :a", a=aid)
    db = SessionLocal(); set_rls_context(db, bypass=True)
    assert content_exec.recover_stuck(db) == {"verified": 1, "requeued": 0, "failed": 0, "deferred": 0}
    db.close()
    assert acts(sid)[0][0] == "executed" and len(fake.posts) == 1 and "verified" in events(aid)


def test_an_interrupted_action_for_a_post_that_never_left_goes_back_to_waiting_to_be_sent(connected, fake, gid):
    sid = scheduled_post(connected, gid)
    from app.workers.tasks import publish_due_posts
    fake.error = g.GoogleAPIError(503, "busy")
    publish_due_posts.run()
    aid = acts(sid)[0][8]
    owner_exec("UPDATE agent_actions SET status = 'executing', claimed_at = now() - interval '30 minutes' WHERE id = :a", a=aid)
    db = SessionLocal(); set_rls_context(db, bypass=True)
    assert content_exec.recover_stuck(db)["requeued"] == 1
    db.close()
    fake.error = None
    owner_exec("UPDATE scheduled_posts SET next_attempt_at = NULL WHERE id = :p", p=sid)
    assert publish_due_posts.run()["published"] == 1 and len(fake.posts) == 1 and [a[0] for a in acts(sid)] == ["executed"]


# ============================================================================ photos

def test_a_scheduled_photo_is_published_through_a_governed_action_and_confirmed_with_google(connected, fake, gid):
    from app.workers.tasks import publish_due_media
    m = upload(connected, gid, jpeg()).json()
    connected.post(f"/gbp/{gid}/library/{m['id']}/approve", json={"scheduled_for": (utcnow() + timedelta(hours=2)).isoformat()})
    owner_exec("UPDATE scheduled_media SET scheduled_for = now() - interval '1 minute' WHERE id = :m", m=m["id"])
    assert publish_due_media.run()["published"] == 1 and len(fake.uploads) == 1
    (st, _, atype, subj, authz, level, matched, _err, aid), = acts(m["id"])
    assert (st, atype, subj, authz, level, matched) == ("executed", "upload_photo", "photo", "owner", 2, "true")
    assert owner_query("SELECT verification->>'processing' FROM agent_actions WHERE id = :a", a=aid)[0][0] == "true"  # Google has it and is still processing: said so
    assert publish_due_media.run()["published"] == 0 and len(fake.uploads) == 1


def test_a_photo_left_uploading_by_a_crash_is_never_re_sent_without_a_person_checking(connected, fake, gid):
    from app.workers.tasks import publish_due_media
    m = upload(connected, gid, jpeg()).json()
    connected.post(f"/gbp/{gid}/library/{m['id']}/approve", json={})
    fake.upload_error = g.GoogleAPIError(503, "busy")
    publish_due_media.run()
    aid = acts(m["id"])[0][8]
    owner_exec("UPDATE agent_actions SET status = 'executing', claimed_at = now() - interval '30 minutes' WHERE id = :a", a=aid)
    db = SessionLocal(); set_rls_context(db, bypass=True)
    assert content_exec.recover_stuck(db)["failed"] == 1
    db.close()
    row = owner_query("SELECT status, failure_reason FROM scheduled_media WHERE id = :m", m=m["id"])[0]
    assert row[0] == "failed" and "Check your Google photos" in row[1]
    fake.upload_error = None
    assert publish_due_media.run()["published"] == 0 and fake.uploads == []  # nothing is sent until a person retries


def test_a_photo_nobody_approved_is_never_uploaded(connected, fake, gid):
    from app.workers.tasks import publish_due_media
    m = upload(connected, gid, jpeg()).json()
    connected.post(f"/gbp/{gid}/library/{m['id']}/approve", json={})
    owner_exec("UPDATE scheduled_media SET approved_by = NULL WHERE id = :m", m=m["id"])
    assert publish_due_media.run()["published"] == 0 and fake.uploads == [] and acts(m["id"]) == []


# ============================================================================ review replies

def reply_ready(connected, fake, monkeypatch, n=2):
    monkeypatch.setattr("app.api.v1.reviews.get_provider", lambda: StubReplyAI())
    fake.reviews = [greview(n, 5, "Great")]
    connected.post("/google/sync")
    rid = connected.get("/reviews").json()["items"][0]["id"]
    d = connected.post(f"/reviews/{rid}/drafts/generate").json()
    assert connected.post(f"/reply-drafts/{d['id']}/approve", json={}).status_code == 200
    return d["id"]


def test_a_reply_is_published_through_a_governed_action_and_the_review_is_read_back(connected, fake, gid, monkeypatch):
    did = reply_ready(connected, fake, monkeypatch)
    r = connected.post(f"/reply-drafts/{did}/publish")
    assert r.status_code == 200 and r.json()["status"] == "published"
    (st, _, atype, subj, authz, level, matched, _err, aid), = acts(did)
    assert (st, atype, subj, authz, level, matched) == ("executed", "reply_publish", "reply", "owner", 2, "true")
    assert len(fake.replies) == 1 and "verified" in events(aid)


def test_a_reply_google_says_yes_to_but_does_not_store_is_not_confirmed(connected, fake, gid, monkeypatch):
    fake.ghost_reply = True
    did = reply_ready(connected, fake, monkeypatch)
    r = connected.post(f"/reply-drafts/{did}/publish")
    assert r.status_code == 200
    (st, _, _, _, _, _, matched, err, aid), = acts(did)
    assert st == "failed" and matched == "false" and "no reply" in err.lower()


def test_the_emergency_stop_holds_a_reply_with_a_clear_message(connected, fake, gid, monkeypatch):
    did = reply_ready(connected, fake, monkeypatch)
    monkeypatch.setattr(settings, "autonomy_emergency_stop", True)
    r = connected.post(f"/reply-drafts/{did}/publish")
    assert r.status_code == 503 and "AUTONOMY_EMERGENCY_STOP" in r.json()["detail"] and fake.replies == []
    monkeypatch.setattr(settings, "autonomy_emergency_stop", False)
    assert connected.post(f"/reply-drafts/{did}/publish").status_code == 200 and len(fake.replies) == 1


def test_a_failed_reply_is_retried_by_the_job_without_a_second_reply(connected, fake, gid, monkeypatch):
    from app.workers.tasks import retry_failed_replies
    did = reply_ready(connected, fake, monkeypatch)
    fake.reply_error = g.GoogleAPIError(503, "busy")
    assert connected.post(f"/reply-drafts/{did}/publish").json()["status"] == "failed"
    fake.reply_error = None
    owner_exec("UPDATE reply_logs SET http_status = 503 WHERE draft_id = :d", d=did)
    assert retry_failed_replies.run()["retried"] == 1
    assert owner_query("SELECT status FROM reply_drafts WHERE id = :d", d=did)[0][0] == "published" and len(fake.replies) == 1
    assert [a[0] for a in acts(did)] == ["failed", "executed"]


# ============================================================================ the owner's own edits (profile editor and direct post/photo tools)

def test_a_profile_edit_goes_through_the_policy_with_a_read_back_and_history(connected, fake, gid):
    r = connected.patch(f"/gbp/{gid}/info", json={"description": "A friendly clinic in Gomti Nagar for back and neck pain."})
    assert r.status_code == 200 and r.json()["description"] == "A friendly clinic in Gomti Nagar for back and neck pain."
    row = owner_query("SELECT status, action_type, policy_level, \"authorization\", proposed_by, verification->>'matched', id FROM agent_actions WHERE field_key = 'description' AND tenant_id = :t ORDER BY created_at DESC LIMIT 1", t=connected.tenant_id)[0]
    assert row[:6] == ("executed", "description_improve", 1, "owner", "user", "true")
    ev = events(row[6])
    assert ev[:3] == ["proposed", "policy_classified", "approved"] and [e for e in ev if e in ("google_write", "read_back", "verified")] == ["google_write", "read_back", "verified"]
    assert owner_query("SELECT basis FROM agent_action_approvals WHERE action_id = :a", a=row[6])[0][0] == "owner"  # authorised by the person, not by standing autonomy


def test_replacing_an_existing_phone_number_is_level_3_and_the_owner_can_do_it_but_an_admin_cannot(connected, fake, gid):
    admin = invite(connected, "admin")
    r = admin.patch(f"/gbp/{gid}/info", json={"phone": "+91 99999 11111"})
    assert r.status_code == 403 and "owner" in r.json()["detail"].lower() and fake.details["phone"] == "+91 98765 43210"
    ok = connected.patch(f"/gbp/{gid}/info", json={"phone": "+91 99999 11111"})
    assert ok.status_code == 200 and fake.details["phone"] == "+91 99999 11111"
    row = owner_query("SELECT effective_type, policy_level FROM agent_actions WHERE tenant_id = :t AND field_key = 'phone' AND status = 'executed'", t=connected.tenant_id)
    assert row == [("primary_contact_change", 3)]


def test_an_admin_may_make_a_level_1_or_2_edit(connected, fake, gid):
    admin = invite(connected, "admin")
    assert admin.patch(f"/gbp/{gid}/info", json={"description": "Gomti Nagar physiotherapy clinic for back and neck pain."}).status_code == 200
    assert admin.patch(f"/gbp/{gid}/info", json={"hours": [{"day": "MONDAY", "open": "08:00", "close": "17:00"}, {"day": "TUESDAY", "open": "08:00", "close": "17:00"}]}).status_code == 200


def test_a_profile_edit_google_does_not_apply_is_an_error_not_a_success(connected, fake, gid):
    orig = fake.update_location
    fake.update_location = lambda at, loc, changes: dict(fake.details)  # a 200 that stores nothing
    r = connected.patch(f"/gbp/{gid}/info", json={"description": "A friendly clinic in Gomti Nagar for back and neck pain."})
    fake.update_location = orig
    assert r.status_code == 502 and "does not show the new description" in r.json()["detail"]
    assert owner_query("SELECT status FROM agent_actions WHERE tenant_id = :t AND field_key = 'description' ORDER BY created_at DESC LIMIT 1", t=connected.tenant_id)[0][0] == "failed"


def test_the_emergency_stop_blocks_the_profile_editor_too(connected, fake, gid, monkeypatch):
    monkeypatch.setattr(settings, "autonomy_emergency_stop", True)
    r = connected.patch(f"/gbp/{gid}/info", json={"description": "A friendly clinic in Gomti Nagar for back and neck pain."})
    assert r.status_code == 503 and "paused" in r.json()["detail"] and fake.writes == []


def test_a_direct_post_is_governed_confirmed_and_a_double_click_sends_once(connected, fake, gid):
    body = {"summary": "Winter back-care workshop on Saturday."}
    a = connected.post(f"/gbp/{gid}/posts", json=body)
    assert a.status_code == 201 and len(fake.posts) == 1
    again = connected.post(f"/gbp/{gid}/posts", json=body)  # the same content from the same person within the minute: the same action
    assert again.status_code in (201, 409) and len(fake.posts) == 1
    row = owner_query("SELECT status, action_type, subject_type, verification->>'matched' FROM agent_actions WHERE tenant_id = :t AND subject_type = 'dpost'", t=connected.tenant_id)
    assert row == [("executed", "publish_content", "dpost", "true")]


def test_a_direct_post_edit_delete_and_photo_are_governed_and_verified(connected, fake, gid):
    p = connected.post(f"/gbp/{gid}/posts", json={"summary": "Winter back-care workshop on Saturday."}).json()
    r = connected.http.patch(f"/api/v1/gbp/{gid}/posts", params={"name": p["name"]}, json={"summary": "Workshop moved to Sunday 10am."}, headers={"X-CSRF-Token": connected.csrf})
    assert r.status_code == 200
    assert connected.delete(f"/gbp/{gid}/posts", params={"name": p["name"]}).status_code == 204 and fake.posts == []
    m = connected.post(f"/gbp/{gid}/media", json={"source_url": "https://cdn.example.com/front.jpg", "category": "EXTERIOR"})
    assert m.status_code == 201
    assert connected.delete(f"/gbp/{gid}/media", params={"name": m.json()["name"]}).status_code == 204
    kinds = owner_query("SELECT subject_type, action_type, status, verification->>'matched' FROM agent_actions WHERE tenant_id = :t AND subject_type LIKE 'd%' ORDER BY created_at", t=connected.tenant_id)
    assert kinds == [("dpost", "publish_content", "executed", "true"), ("dpostedit", "content_edit", "executed", "true"), ("dpostdel", "content_delete", "executed", "true"),
                     ("dphoto", "upload_photo", "executed", "true"), ("dphotodel", "content_delete", "executed", "true")]


def test_the_emergency_stop_blocks_direct_posts(connected, fake, gid, monkeypatch):
    monkeypatch.setattr(settings, "autonomy_emergency_stop", True)
    r = connected.post(f"/gbp/{gid}/posts", json={"summary": "Winter back-care workshop on Saturday."})
    assert r.status_code == 503 and fake.posts == []


# ============================================================================ the control centre

def test_the_control_centre_reads_waiting_done_failed_and_usage_in_one_call(connected, fake, gid):
    from app.workers.tasks import publish_due_posts
    fake.hide_posts = True
    scheduled_post(connected, gid)
    publish_due_posts.run()
    cc = connected.get("/agent/control-centre").json()
    assert cc["is_owner"] is True and cc["can_decide"] is True and cc["settings"]["enabled"] is False  # OFF by default since migration 0038 (decision D2: automation is opt-in)
    assert [a["label"] for a in cc["problems"]] == ["Publish an approved Google Post"] and "not confirmed" in cc["problems"][0]["last_error"]
    u = cc["usage"]
    assert u["ai"]["generations_cap"] > 0 and "places" in u and u["autonomy"]["daily_limit"] == 3 and u["places"]["grid_enabled"] in (True, False)


def test_the_control_centre_shows_only_what_the_person_may_see_and_decide(connected, fake, gid):
    staff = invite(connected, "staff")
    cc = staff.get("/agent/control-centre").json()
    assert cc["is_owner"] is False and cc["can_decide"] is False


def test_the_owners_emergency_stop_switches_autonomy_off_and_returns_policy_authorised_work_to_a_person(connected, fake, gid):
    from app.services.agent import executor
    assert connected.put("/agent/knowledge", json={"description": "Physiotherapy for back and neck pain in Lucknow.", "services": ["Back care", "Neck pain physiotherapy"], "offers": [], "faqs": [], "prohibited_claims": []}).status_code == 200
    assert connected.post("/agent/google/refresh").json()["locations"][0]["ok"] is True
    connected.put("/agent/autonomy-settings", json={"enabled": True})
    from app.services import consent as consent_svc
    assert connected.post("/agent/consents", json={"location_id": gid, "scope": "description_improve", "wording_version": consent_svc.WORDING_VERSION}).status_code == 201  # D2: express consent
    db = SessionLocal(); set_rls_context(db, bypass=True)
    from app.models import GoogleLocation, Tenant
    a = executor.propose(db, db.get(Tenant, uuid.UUID(connected.tenant_id)), db.get(GoogleLocation, uuid.UUID(gid)), "description_improve",
                         proposed="Gomti Physio is a physiotherapy clinic in Lucknow for back care and neck pain physiotherapy. Call us to book a visit or ask a question about our services.",
                         source={"kind": "business_knowledge", "refs": ["description"]}, trigger="t", problem="p", reason="r")
    db.commit()
    db.close()
    assert a.status == "approved", a.last_error  # Level 1, autonomy on, evidence present: authorised by policy
    admin = invite(connected, "admin")
    assert admin.post("/agent/autonomy-settings/stop").status_code == 403  # only the owner has this button
    r = connected.post("/agent/autonomy-settings/stop")
    assert r.status_code == 200 and r.json()["withdrawn"] == 1 and r.json()["enabled"] is False and r.json()["suspended"] is True
    assert owner_query("SELECT status FROM agent_actions WHERE id = :a", a=a.id)[0][0] == "pending_approval"
    assert "autonomy_withdrawn" in events(a.id)
    assert connected.post("/agent/autonomy-settings/resume").json()["suspended"] is False
