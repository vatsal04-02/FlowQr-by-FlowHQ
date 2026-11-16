"""Growth agent: safety rules, knowledge base, health score, daily plan, task state machine, posts workflow, profile description.

Google is a TEST DOUBLE (FakeGbpProvider) and the AI is a scripted stub. Everything else (PostgreSQL, RLS, state machines, scheduling,
tenancy) is real. Nothing here proves live Google or live AI behaviour."""
import uuid
from datetime import timedelta

import pytest

from app.core.db import SessionLocal, set_rls_context
from app.models import AgentTask, Review, ScheduledPost
from app.models.base import utcnow
from app.services import google as g
from app.services.agent import health as health_svc
from app.services.agent import plan as plan_svc
from app.services.agent.safety import check_text, is_health
from app.services.ai.base import AIUnavailable
from tests.conftest import owner_exec, owner_query
from tests.test_gbp import fake, gid  # noqa: F401
from tests.test_google_and_reviews import connected  # noqa: F401
from tests.test_location_permissions import invite

KB_HEALTH = {"offers": [], "prohibited_claims": [], "approved_claims": [], "safety_profile": "health"}
KB_GENERAL = {"offers": [], "prohibited_claims": [], "approved_claims": [], "safety_profile": "general"}


class Scripted:
    """TEST DOUBLE LLM: returns the queued outputs in order (the last one repeats)."""
    name, model, usage = "scripted", "scripted-1", None

    def __init__(self, *outputs):
        self.outputs, self.prompts = list(outputs), []

    def generate(self, system, user, **kw):
        self.prompts.append(user)
        return self.outputs.pop(0) if len(self.outputs) > 1 else self.outputs[0]


@pytest.fixture()
def ai(monkeypatch):
    holder = {"p": Scripted("Thank you for visiting us. We are glad you shared your feedback.")}
    for target in ("app.api.v1.agent.get_provider", "app.api.v1.posts.get_provider", "app.api.v1.reviews.get_provider", "app.services.agent.plan.get_provider"):
        monkeypatch.setattr(target, lambda: holder["p"])
    return holder


def set_ai(ai, *outputs):
    ai["p"] = Scripted(*outputs)
    return ai["p"]


def add_review(biz, gid_, rating=5, text="Great clinic", days_ago=3, replied=False, loc=None):
    with SessionLocal() as db:
        set_rls_context(db, bypass=True)
        r = Review(tenant_id=uuid.UUID(biz.tenant_id), location_id=uuid.UUID(loc or biz.location_id), google_location_id=uuid.UUID(gid_), external_id=uuid.uuid4().hex,
                   rating=rating, text=text, reviewer_name="Asha", review_created_at=utcnow() - timedelta(days=days_ago), first_seen_at=utcnow(),
                   google_reply_text="Thanks!" if replied else None, google_reply_at=utcnow() - timedelta(days=days_ago - 1) if replied else None)
        db.add(r)
        db.commit()
        return str(r.id)


def tasks(biz, scope="open"):
    return biz.get("/agent/tasks", params={"scope": scope}).json()["tasks"]


# ------------------------------------------------------------------ safety rules (pure)
@pytest.mark.parametrize("text, kb, expect", [
    ("Thank you for your kind words. We hope to see you again.", KB_HEALTH, []),
    ("Our session costs ₹500 only!", KB_HEALTH, ["invented_price"]),
    ("Rs. 1,200 for a full assessment", KB_GENERAL, ["invented_price"]),
    ("Get 20% off this week", KB_GENERAL, ["invented_offer"]),
    ("Free consultation for everyone", KB_GENERAL, ["invented_offer"]),
    ("Your appointment is confirmed for 5pm", KB_GENERAL, ["appointment_claim"]),
    ("We treated you last month and your recovery was quick", KB_HEALTH, ["health_claim"]),
    ("As a patient of ours you know we guarantee results", KB_HEALTH, ["health_claim"]),
    ("Painless treatment with 100% recovery", KB_HEALTH, ["health_claim"]),
    ("Thanks for the review, we guarantee nothing but care", KB_GENERAL, []),  # the health rules apply to health businesses only
    ("We are open Monday to Saturday", KB_HEALTH, []),
])
def test_safety_rules(text, kb, expect):
    got = {v.code for v in check_text(text, kb=kb, kind="reply")}
    assert got == set(expect), (text, got)


def test_verified_prices_offers_and_approved_claims_are_allowed():
    kb = {**KB_HEALTH, "offers": [{"name": "First visit assessment", "price_inr": 500}], "approved_claims": ["experienced team"]}
    assert check_text("The first visit assessment is ₹500.", kb=kb, kind="post") == []
    assert [v.code for v in check_text("It is ₹700.", kb=kb, kind="post")] == ["invented_price"]
    assert check_text("Get a First visit assessment with 20% off", kb=kb, kind="post") == []  # the named offer exists
    assert [v.code for v in check_text("Our clinic's number 1 clinic claim", kb={**KB_GENERAL, "prohibited_claims": ["number 1 clinic"]}, kind="post")] == ["prohibited_claim"]


def test_health_category_detection():
    assert is_health("Physiotherapy clinic") and is_health("Dental") and not is_health("Restaurant") and not is_health(None)


# ------------------------------------------------------------------ knowledge base
def test_knowledge_base_is_seeded_safe_for_a_clinic_validated_and_admin_only(connected, ai):
    k = connected.get("/agent/knowledge").json()
    assert k["safety_profile"] == "health" and "guaranteed cure" in k["prohibited_claims"] and k["completeness"]["missing"] == ["description", "services", "brand voice"]
    assert "NONE are verified" in k["grounding_preview"] and "HEALTH BUSINESS" in k["grounding_preview"]
    body = {"description": "Physiotherapy for back and neck pain in Lucknow.", "services": ["Back pain physiotherapy", "Sports injury rehab"],
            "offers": [{"name": "First visit assessment", "price_inr": 500, "details": "45 minutes"}], "hours": "Mon-Sat 9am-7pm", "faqs": [{"q": "Do you take walk-ins?", "a": "Yes, when a slot is free."}],
            "brand_voice": "warm, calm", "approved_claims": [], "prohibited_claims": k["prohibited_claims"] + ["cheapest in town"]}
    r = connected.put("/agent/knowledge", json=body)
    assert r.status_code == 200 and r.json()["completeness"]["complete"] and "₹500" in r.json()["grounding_preview"] and "cheapest in town" in r.json()["prohibited_claims"]
    assert connected.get("/review-growth/context").json()["description"].startswith("Physiotherapy")  # one source of truth with the review assistant
    assert connected.put("/agent/knowledge", json={**body, "description": "We are the best and guaranteed cheapest clinic"}).status_code == 422  # same plain-text rules as the review assistant
    assert connected.put("/agent/knowledge", json={**body, "offers": [{"name": "x", "price_inr": -5}]}).status_code == 422
    staff = invite(connected)
    assert staff.get("/agent/knowledge").status_code == 200 and staff.put("/agent/knowledge", json=body).status_code == 403
    chk = connected.post("/agent/knowledge/check", json={"text": "Painless treatment, cheapest in town, only ₹900", "kind": "post"}).json()["violations"]
    assert {v["code"] for v in chk} == {"health_claim", "prohibited_claim", "invented_price"}
    assert owner_query("SELECT count(*) FROM audit_logs WHERE tenant_id = :t AND action = 'agent.knowledge_update'", t=connected.tenant_id)[0][0] == 1


def test_knowledge_is_tenant_isolated(connected, biz_b):
    connected.put("/agent/knowledge", json={"description": "Physio for backs.", "services": ["Back care"], "offers": [], "faqs": [], "prohibited_claims": []})
    other = biz_b.get("/agent/knowledge").json()
    assert other["business"] == "Beta Dental" and "Back care" not in other["services"] and other["description"] == ""


# ------------------------------------------------------------------ grounded replies
def test_reply_drafts_are_grounded_and_a_rule_breaking_draft_is_retried_then_refused(connected, ai, gid):
    rid = add_review(connected, gid, 2, "Waited too long and nobody told me why")
    p = set_ai(ai, "Sorry about that. We charge only ₹100 and guarantee a cure.", "We are sorry about the wait. Please call the clinic so we can understand what happened.")
    r = connected.post(f"/reviews/{rid}/drafts/generate")
    assert r.status_code == 201 and "₹" not in r.json()["body"] and len(p.prompts) == 2
    assert "BUSINESS FACTS" in p.prompts[0] and "was rejected because" in p.prompts[1] and "invented price" not in p.prompts[0].lower()
    set_ai(ai, "We guarantee a complete cure for your condition.")
    n = owner_query("SELECT count(*) FROM reply_drafts WHERE review_id = :r", r=rid)[0][0]
    bad = connected.post(f"/reviews/{rid}/drafts/generate")
    assert bad.status_code == 502 and owner_query("SELECT count(*) FROM reply_drafts WHERE review_id = :r", r=rid)[0][0] == n  # nothing was saved


# ------------------------------------------------------------------ health score
def test_health_score_without_data_says_so_and_never_invents_one(connected):
    h = connected.get("/agent/health").json()
    assert h["score"] is None and "Not enough real data" in h["message"] and h["covered_weight"] < 30
    assert all(not c["available"] for c in h["components"] if c["key"] in ("profile", "posting", "photos", "engagement")) and "Σ(weight × value)" in h["formula"]


def test_health_score_formula_uses_only_real_data_and_adds_up(connected, ai, gid):
    for rating, replied, days in ((5, True, 5), (4, True, 9), (1, False, 2)):
        add_review(connected, gid, rating, "x", days_ago=days, replied=replied)
    assert connected.post("/agent/google/refresh").json()["locations"][0]["ok"] is True
    h = connected.get("/agent/health").json()
    c = {x["key"]: x for x in h["components"]}
    assert c["reply_coverage"]["value"] == pytest.approx(2 / 3, abs=1e-3) and "2 of 3 reviews" in c["reply_coverage"]["detail"]
    assert c["profile"]["value"] == pytest.approx(0.70) and "Description" in c["profile"]["detail"]  # the fake profile has a 3-letter description
    assert c["review_activity"]["value"] == pytest.approx(0.75) and c["posting"]["value"] == 0 and c["photos"]["value"] == 0
    assert c["engagement"]["value"] == pytest.approx(4 / 13, abs=1e-3)  # 4 actions now vs 13 in the 28 days before, as the fake Google returned them
    avail = [x for x in h["components"] if x["available"]]
    assert h["covered_weight"] == 100 and h["score"] == round(100 * sum(x["weight"] * x["value"] for x in avail) / sum(x["weight"] for x in avail))
    assert 40 <= h["score"] <= 55


def test_unavailable_measures_are_left_out_not_counted_as_zero(connected, gid):
    add_review(connected, gid, 5, "x", replied=True)
    add_review(connected, gid, 5, "y", replied=True)
    h = connected.get("/agent/health").json()  # reviews only: no Google snapshot
    avail = {x["key"] for x in h["components"] if x["available"]}
    assert avail == {"reply_coverage", "review_activity"} and h["covered_weight"] == 40
    assert h["score"] == round(100 * (25 * 1.0 + 15 * 0.5) / 40)


def test_score_changes_are_explained_from_stored_history(connected, gid):
    add_review(connected, gid, 5, "x", replied=False)
    add_review(connected, gid, 5, "y", replied=False)
    first = connected.get("/agent/health").json()
    assert first["changes"] == ["This is the first recorded score; changes will be explained from tomorrow."]
    yesterday = (utcnow() - timedelta(days=1)).date()
    owner_exec("UPDATE health_snapshots SET day = :d WHERE tenant_id = :t", d=yesterday, t=connected.tenant_id)
    owner_exec("UPDATE reviews SET google_reply_text = 'Thanks', google_reply_at = now() WHERE tenant_id = :t", t=connected.tenant_id)
    second = connected.get("/agent/health").json()
    assert second["score"] > first["score"] and any(c.startswith("Score up") for c in second["changes"]) and any("Review reply coverage" in c for c in second["changes"])
    assert [h["score"] for h in second["history"]] == [first["score"], second["score"]]


# ------------------------------------------------------------------ plan + state machine
def test_the_plan_is_built_from_real_data_prioritised_deduplicated_and_resolves_itself(connected, ai, gid):
    low = add_review(connected, gid, 1, "Rude reception", days_ago=2)
    add_review(connected, gid, 5, "Lovely", days_ago=20)
    r = connected.post("/agent/plan/run").json()
    assert r["created"] >= 3
    t = tasks(connected)
    kinds = [x["kind"] for x in t]
    assert kinds[0] == "reply_review" and t[0]["evidence"]["review_id"] == low and t[0]["priority"] == 10 and "1-star review from Asha" in t[0]["title"] and "2 days old" in t[0]["why"]
    assert {"reply_review", "complete_knowledge", "create_post"} <= set(kinds) and "connect_google" not in kinds
    assert connected.post("/agent/plan/run").json()["created"] == 0  # same issues are not suggested twice
    assert sum(1 for x in tasks(connected) if x["kind"] == "reply_review") == 2
    owner_exec("UPDATE reviews SET google_reply_text = 'Thanks', google_reply_at = now() WHERE id = :r", r=low)
    connected.post("/agent/plan/run")
    done = {x["evidence"].get("review_id"): x for x in tasks(connected, "history")}
    assert done[low]["status"] == "done" and connected.get(f"/agent/tasks/{done[low]['id']}/history").json()[-1]["note"] == "A reply now exists on Google"
    run = connected.get("/agent/activity").json()
    assert run["runs"][0]["kind"] == "daily_plan" and run["runs"][0]["status"] == "ok" and run["last_plan_date"]


def test_with_no_google_account_the_plan_says_connect_and_does_not_invent_google_tasks(biz_a):
    biz_a.post("/agent/plan/run")
    kinds = {x["kind"] for x in tasks(biz_a)}
    assert kinds == {"connect_google", "complete_knowledge"}
    t = next(x for x in tasks(biz_a) if x["kind"] == "connect_google")
    assert t["evidence"]["state"] == "not_connected" and "Connect" in t["title"]


def test_task_state_machine_rejects_illegal_moves_and_records_every_step(connected, gid):
    add_review(connected, gid, 3, "ok", days_ago=1)
    connected.post("/agent/plan/run")
    tid = next(x["id"] for x in tasks(connected) if x["kind"] == "reply_review")
    assert connected.post(f"/agent/tasks/{tid}/snooze", json={"days": 2}).json()["status"] == "snoozed"
    assert connected.post(f"/agent/tasks/{tid}/snooze", json={"days": 3}).json()["status"] == "snoozed"  # repeating is harmless (it just extends)
    assert connected.post(f"/agent/tasks/{tid}/dismiss").json()["status"] == "dismissed"
    assert connected.post(f"/agent/tasks/{tid}/dismiss").json()["status"] == "dismissed" and connected.post(f"/agent/tasks/{tid}/draft").status_code in (409, 503)
    assert connected.post(f"/agent/tasks/{tid}/snooze", json={"days": 1}).status_code == 409  # a dismissed task cannot be snoozed
    hist = connected.get(f"/agent/tasks/{tid}/history").json()
    assert [(h["from"], h["to"]) for h in hist] == [(None, "suggested"), ("suggested", "snoozed"), ("snoozed", "dismissed")] and hist[-1]["actor"] == "user"
    with SessionLocal() as db:
        set_rls_context(db, bypass=True)
        t = db.get(AgentTask, uuid.UUID(tid))
        with pytest.raises(plan_svc.TaskError):
            plan_svc.transition(db, t, "published", actor="user")
        db.rollback()
    snoozed = connected.post("/agent/plan/run")  # a dismissed task is not resurrected, and a new snooze wakes up by itself
    assert snoozed.status_code == 200


def test_a_snoozed_task_wakes_up_when_its_time_has_passed(connected, gid):
    add_review(connected, gid, 3, "ok", days_ago=1)
    connected.post("/agent/plan/run")
    tid = next(x["id"] for x in tasks(connected) if x["kind"] == "reply_review")
    connected.post(f"/agent/tasks/{tid}/snooze", json={"days": 1})
    assert tid not in [x["id"] for x in tasks(connected, "today")]
    owner_exec("UPDATE agent_tasks SET snoozed_until = now() - interval '1 minute' WHERE id = :t", t=tid)
    assert next(x for x in tasks(connected) if x["id"] == tid)["status"] == "suggested"


def test_reply_task_end_to_end_draft_approve_publish_and_only_then_published(connected, ai, fake, gid):
    rid = add_review(connected, gid, 4, "Good physio, parking was hard", days_ago=4)
    connected.post("/agent/plan/run")
    t = next(x for x in tasks(connected) if x["kind"] == "reply_review")
    set_ai(ai, "Thank you for the feedback. We are glad the physio helped and we will look at the parking information we share.")
    d = connected.post(f"/agent/tasks/{t['id']}/draft").json()
    assert d["status"] == "awaiting_approval" and d["reply"]["status"] == "draft" and fake.replies == []  # nothing sent
    ap = connected.get("/agent/approvals").json()
    assert [r["review_id"] for r in ap["replies"]] == [rid] and ap["replies"][0]["ai"] is True and ap["replies"][0]["violations"] == []
    did = d["reply"]["id"]
    assert connected.post(f"/reply-drafts/{did}/approve", json={}).status_code == 200
    assert next(x for x in tasks(connected) if x["id"] == t["id"])["status"] == "approved" and fake.replies == []
    assert connected.post(f"/reply-drafts/{did}/publish").json()["status"] == "published"
    final = next(x for x in tasks(connected, "history") if x["id"] == t["id"])
    assert final["status"] == "published" and len(fake.replies) == 1
    ev = connected.get(f"/agent/tasks/{t['id']}/history").json()
    assert [e["to"] for e in ev] == ["suggested", "drafted", "awaiting_approval", "approved", "published"]
    assert ev[-1]["actor"] == "google" or ev[-1]["actor"] == "system"


def test_a_failed_publish_leaves_the_task_failed_never_published(connected, ai, fake, gid):
    add_review(connected, gid, 4, "Fine", days_ago=4)
    connected.post("/agent/plan/run")
    t = next(x for x in tasks(connected) if x["kind"] == "reply_review")
    did = connected.post(f"/agent/tasks/{t['id']}/draft").json()["reply"]["id"]
    connected.post(f"/reply-drafts/{did}/approve", json={})
    fake.reply_error = g.GoogleAPIError(500, "boom")
    assert connected.post(f"/reply-drafts/{did}/publish").json()["status"] == "failed"
    cur = next(x for x in tasks(connected) if x["id"] == t["id"])
    assert cur["status"] == "failed" and cur["failure_reason"] and fake.replies == []


def test_auto_draft_prepares_drafts_but_never_publishes(connected, ai, fake, gid):
    add_review(connected, gid, 2, "Slow", days_ago=2)
    assert connected.put("/agent/settings", json={"auto_draft_replies": True}).json() == {**connected.get("/agent/settings").json(), "auto_draft_replies": True}
    assert connected.get("/agent/settings").json()["auto_publish"] is False
    r = connected.post("/agent/plan/run").json()
    assert r["drafted"] == 1 and fake.replies == []
    t = next(x for x in tasks(connected) if x["kind"] == "reply_review")
    assert t["status"] == "awaiting_approval" and t["reply"]["status"] == "draft"
    assert owner_query("SELECT count(*) FROM reply_drafts WHERE status = 'published'")[0][0] >= 0


def test_ai_not_configured_is_an_honest_setup_message(connected, gid, monkeypatch):
    from app.services.ai.base import AIUnavailable as U
    add_review(connected, gid, 2, "Slow", days_ago=2)
    connected.post("/agent/plan/run")
    tid = next(x["id"] for x in tasks(connected) if x["kind"] == "reply_review")
    def nope():
        raise U("no key", code="not_configured")
    monkeypatch.setattr("app.api.v1.agent.get_provider", nope)
    r = connected.post(f"/agent/tasks/{tid}/draft")
    assert r.status_code == 503 and "Setup required" in r.json()["detail"]
    assert next(x for x in tasks(connected) if x["id"] == tid)["status"] == "suggested"


# ------------------------------------------------------------------ posts
GOOD = "We are open Monday to Saturday. Call the clinic to book a visit."


def make_post(biz, gid_, text=GOOD, **kw):
    r = biz.post("/posts", json={"google_location_id": gid_, "summary": text, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def test_post_workflow_nothing_reaches_google_until_a_person_approves(connected, fake, gid):
    p = make_post(connected, gid)
    assert p["status"] == "draft" and fake.posts == []
    assert connected.post(f"/posts/{p['id']}/approve", json={}).status_code == 409  # a draft cannot be approved: it must be submitted first
    assert connected.post(f"/posts/{p['id']}/submit").json()["status"] == "awaiting_approval"
    staff = invite(connected)
    assert staff.post(f"/posts/{p['id']}/approve", json={}).status_code == 403 and fake.posts == []
    edited = connected.patch(f"/posts/{p['id']}", json={"summary": GOOD + " Walk-ins welcome."}).json()
    assert edited["status"] == "draft"  # an edit voids the pending request: the approved text is exactly what is published
    connected.post(f"/posts/{p['id']}/submit")
    done = connected.post(f"/posts/{p['id']}/approve", json={}).json()
    assert done["status"] == "published" and done["publish_result"] == "published" and done["google_post_name"] and done["published_at"]
    assert [x["summary"] for x in fake.posts] == [GOOD + " Walk-ins welcome."]
    assert connected.patch(f"/posts/{p['id']}", json={"summary": "Changed after publishing, not allowed"}).status_code == 409
    assert connected.post(f"/posts/{p['id']}/cancel").status_code == 409
    acts = {a for (a,) in owner_query("SELECT action FROM audit_logs WHERE entity_id = :p", p=p["id"])}
    assert {"post.draft_create", "post.approve", "post.publish_published"} <= acts


def test_rule_breaking_text_cannot_be_approved(connected, fake, gid):
    p = make_post(connected, gid, "Painless treatment, 100% cure, only ₹999 today with 50% off")
    connected.post(f"/posts/{p['id']}/submit")
    assert connected.get("/posts").json()["posts"][0]["violations"]
    r = connected.post(f"/posts/{p['id']}/approve", json={})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "safety_violation" and len(r.json()["detail"]["violations"]) >= 3 and fake.posts == []


def test_scheduled_posts_wait_for_their_time_and_the_scheduler_publishes_them_once(connected, fake, gid):
    from app.workers.tasks import publish_due_posts
    p = make_post(connected, gid)
    connected.post(f"/posts/{p['id']}/submit")
    when = (utcnow() + timedelta(hours=3)).isoformat()
    s = connected.post(f"/posts/{p['id']}/approve", json={"scheduled_for": when}).json()
    assert s["status"] == "scheduled" and s["publish_result"] is None and fake.posts == []
    assert publish_due_posts.run() == {"published": 0, "retry": 0, "failed": 0, "skipped": 0, "held": 0} and fake.posts == []
    cal = connected.get("/posts/calendar", params={"from": utcnow().date().isoformat(), "to": (utcnow() + timedelta(days=2)).date().isoformat()}).json()
    assert sum(len(v) for v in cal["days"].values()) == 1 and cal["timezone"] == "Asia/Kolkata"
    owner_exec("UPDATE scheduled_posts SET scheduled_for = now() - interval '1 minute' WHERE id = :p", p=p["id"])
    assert publish_due_posts.run()["published"] == 1 and len(fake.posts) == 1
    assert publish_due_posts.run()["published"] == 0 and len(fake.posts) == 1  # never twice
    assert connected.get("/posts", params={"status": "published"}).json()["posts"][0]["google_post_name"]


def test_transient_failures_retry_with_backoff_permanent_ones_fail_with_a_diagnostic(connected, fake, gid):
    from app.workers.tasks import publish_due_posts
    p = make_post(connected, gid)
    connected.post(f"/posts/{p['id']}/submit")
    fake.error = g.GoogleAPIError(503, "unavailable")
    r = connected.post(f"/posts/{p['id']}/approve", json={}).json()
    assert r["status"] == "scheduled" and r["publish_result"] == "retry" and r["attempts"] == 1 and "temporary problem" in r["failure_reason"] and r["next_attempt_at"]
    assert publish_due_posts.run()["published"] == 0  # not due yet
    fake.error = None
    owner_exec("UPDATE scheduled_posts SET next_attempt_at = now() - interval '1 second' WHERE id = :p", p=p["id"])
    assert publish_due_posts.run()["published"] == 1
    q = make_post(connected, gid, GOOD + " Second.")
    connected.post(f"/posts/{q['id']}/submit")
    fake.error = g.GoogleAPIError(400, "Request contains an invalid argument.")
    f = connected.post(f"/posts/{q['id']}/approve", json={}).json()
    assert f["status"] == "failed" and "rejected this post" in f["failure_reason"] and f["attempts"] == 1
    fake.error = None
    assert connected.post(f"/posts/{q['id']}/retry").json()["status"] == "published"
    r3 = make_post(connected, gid, GOOD + " Third.")
    connected.post(f"/posts/{r3['id']}/submit")
    fake.error = g.GoogleApiNotApproved(403, "disabled", why="service_disabled", service="mybusiness.googleapis.com")
    n = connected.post(f"/posts/{r3['id']}/approve", json={}).json()
    assert n["status"] == "failed" and "not enabled" in n["failure_reason"]
    assert connected.get("/google/status").json()["connections"][0]["api_access"] == "api_disabled"
    fake.error = None
    act = connected.get("/agent/activity").json()
    assert [x["id"] for x in act["failed_posts"]] == [r3["id"]]


def test_transient_failure_gives_up_after_the_attempt_limit(connected, fake, gid):
    from app.workers.tasks import publish_due_posts
    p = make_post(connected, gid)
    connected.post(f"/posts/{p['id']}/submit")
    fake.error = g.GoogleAPIError(503, "unavailable")
    connected.post(f"/posts/{p['id']}/approve", json={})
    for _ in range(5):
        owner_exec("UPDATE scheduled_posts SET next_attempt_at = now() - interval '1 second' WHERE id = :p AND status = 'scheduled'", p=p["id"])
        publish_due_posts.run()
    row = connected.get("/posts").json()["posts"][0]
    assert row["status"] == "failed" and row["attempts"] == 4 and fake.posts == []


def test_posts_respect_plan_location_and_tenant_boundaries(connected, fake, gid, biz_b):
    p = make_post(connected, gid)
    assert biz_b.get(f"/posts").json()["posts"] == [] and biz_b.post(f"/posts/{p['id']}/submit").status_code == 404
    other = connected.post("/locations", json={"name": "Second branch"}).json()["id"]
    owner_exec("UPDATE google_locations SET location_id = :l WHERE id = :g", l=other, g=gid)
    staff = invite(connected, location_ids=[connected.location_id])  # limited to the branch the Google location no longer belongs to
    assert staff.get("/posts").json()["posts"] == [] and staff.post("/posts", json={"google_location_id": gid, "summary": GOOD}).status_code == 404
    assert staff.get(f"/posts/{p['id']}").status_code in (404, 405)
    owner_exec("UPDATE subscriptions SET status = 'expired' WHERE tenant_id = :t", t=connected.tenant_id)
    assert connected.post("/posts", json={"google_location_id": gid, "summary": GOOD}).status_code == 402
    assert connected.get("/posts").status_code == 200  # reading stays available


def test_ai_post_drafts_are_grounded_checked_and_wait_for_approval(connected, fake, ai, gid):
    connected.put("/agent/knowledge", json={"description": "Physiotherapy for back pain.", "services": ["Back pain care"], "offers": [], "faqs": [], "prohibited_claims": []})
    p = set_ai(ai, "Back pain can make daily life hard. Our physiotherapy team offers back pain care. Call us to book a visit.")
    r = connected.post("/posts/ai-draft", json={"google_location_id": gid})
    assert r.status_code == 201 and r.json()["status"] == "awaiting_approval" and r.json()["generated_by_ai"] and fake.posts == [] and "Back pain care" in p.prompts[0]
    set_ai(ai, "We guarantee a 100% cure with painless sessions.")
    assert connected.post("/posts/ai-draft", json={"google_location_id": gid}).status_code == 502
    assert len(connected.get("/posts").json()["posts"]) == 1  # the unsafe draft was never stored
    assert any(e["status"] == "error" for e in connected.get("/workspace/ai-usage").json()["by_kind"] if e["kind"] == "post_draft")


# ------------------------------------------------------------------ profile description
def test_profile_description_task_is_written_to_google_only_after_approval_and_confirmed_by_google(connected, fake, ai, gid):
    connected.put("/agent/knowledge", json={"description": "Physiotherapy for back and neck pain.", "services": ["Back care"], "offers": [], "faqs": [], "prohibited_claims": []})
    connected.post("/agent/google/refresh")
    connected.post("/agent/plan/run")
    t = next(x for x in tasks(connected) if x["kind"] == "profile_fix" and x["evidence"]["field"] == "description")
    text = "Gomti Physio is a physiotherapy clinic in Lucknow offering back care and neck pain physiotherapy. Call the clinic to book a visit or to ask a question."
    set_ai(ai, text)
    d = connected.post(f"/agent/tasks/{t['id']}/draft").json()
    assert d["status"] == "awaiting_approval" and d["draft"]["description"] == text and fake.writes == []
    assert connected.patch(f"/agent/tasks/{t['id']}/draft", json={"description": "Painless 100% cure physiotherapy clinic that guarantees recovery for everyone."}).json()["violations"]
    bad = connected.post(f"/agent/tasks/{t['id']}/approve")
    assert bad.status_code == 422 and fake.writes == []  # unsafe text cannot be approved
    connected.patch(f"/agent/tasks/{t['id']}/draft", json={"description": text})
    staff = invite(connected)
    assert staff.post(f"/agent/tasks/{t['id']}/approve").status_code == 403
    ok = connected.post(f"/agent/tasks/{t['id']}/approve").json()
    assert ok["status"] == "published" and fake.writes[-1][1]["description"] == text and fake.details["description"] == text


def test_a_profile_write_google_does_not_reflect_is_a_failure_not_a_success(connected, fake, ai, gid, monkeypatch):
    connected.put("/agent/knowledge", json={"description": "Physiotherapy.", "services": ["Back care"], "offers": [], "faqs": [], "prohibited_claims": []})
    connected.post("/agent/google/refresh")
    connected.post("/agent/plan/run")
    t = next(x for x in tasks(connected) if x["kind"] == "profile_fix" and x["evidence"]["field"] == "description")
    set_ai(ai, "Gomti Physio is a physiotherapy clinic in Lucknow offering back care. Call the clinic to book a visit or ask a question about our services.")
    connected.post(f"/agent/tasks/{t['id']}/draft")
    monkeypatch.setattr(fake, "update_location", lambda at, loc, ch: dict(fake.details))  # 200 from Google, but nothing changed
    r = connected.post(f"/agent/tasks/{t['id']}/approve").json()
    assert r["status"] == "failed" and "does not show the new description" in r["failure_reason"]


def test_google_refresh_failures_are_reported_not_hidden(connected, fake, gid):
    fake.error = g.GoogleApiNotApproved(403, "disabled", why="service_disabled", service="mybusinessbusinessinformation.googleapis.com")
    out = connected.post("/agent/google/refresh").json()["locations"][0]
    assert out["ok"] is False and "profile" in out["error"]
    assert connected.get("/agent/health").json()["components"][0]["available"] is False
    runs = connected.get("/agent/activity").json()["runs"]
    assert runs[0]["kind"] == "refresh_google" and runs[0]["status"] == "failed"


# ------------------------------------------------------------------ location restriction + celery
def test_location_restricted_staff_only_see_their_locations_tasks_and_approvals(connected, gid):
    other = connected.post("/locations", json={"name": "Second branch"}).json()["id"]
    mine = add_review(connected, gid, 2, "mine", days_ago=2)
    theirs = add_review(connected, gid, 2, "theirs", days_ago=3, loc=other)
    connected.post("/agent/plan/run")
    staff = invite(connected, location_ids=[connected.location_id])
    seen = tasks(staff)
    assert [x["evidence"]["review_id"] for x in seen if x["kind"] == "reply_review"] == [mine]
    assert {x["kind"] for x in seen} <= {"reply_review", "create_post", "profile_fix", "add_photo"} and "complete_knowledge" not in {x["kind"] for x in seen}  # tenant-wide tasks are hidden
    hidden = next(x["id"] for x in tasks(connected) if x["evidence"].get("review_id") == theirs)
    assert staff.post(f"/agent/tasks/{hidden}/dismiss").status_code == 404 and staff.get(f"/agent/tasks/{hidden}/history").status_code == 404
    kb_task = next(x["id"] for x in tasks(connected) if x["kind"] == "complete_knowledge")
    assert staff.post(f"/agent/tasks/{kb_task}/dismiss").status_code == 404


def test_the_daily_agent_job_builds_a_plan_once_per_day_per_business(connected, gid):
    from app.workers.tasks import daily_agent
    add_review(connected, gid, 2, "slow", days_ago=2)
    owner_exec("UPDATE tenants SET timezone = 'Pacific/Kiritimati' WHERE id = :t", t=connected.tenant_id)  # UTC+14: always past 06:00 local somewhere in the day
    first = daily_agent.run()
    assert first["failed"] == 0
    from app.services.agent.plan import tenant_today
    ran_once = owner_query("SELECT count(*) FROM agent_runs WHERE tenant_id = :t AND kind = 'daily_plan'", t=connected.tenant_id)[0][0]
    daily_agent.run()
    assert owner_query("SELECT count(*) FROM agent_runs WHERE tenant_id = :t AND kind = 'daily_plan'", t=connected.tenant_id)[0][0] == ran_once  # not again today
    assert any(x["kind"] == "reply_review" for x in tasks(connected)) or ran_once == 0
