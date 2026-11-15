"""Template-based automatic replies to positive reviews (owner decision 2026-11-15; services/auto_reply.py).
MOCKED: Google is the GovGoogle test double of the Phase 1.5 tests; the database, the policy, the governed publisher and the jobs are real. NOTHING here proves what real Google does with an
automatic reply: that is a live test on the owner's test profile (docs/LIVE_VALIDATION_RUNBOOK.md)."""
import uuid
from datetime import timedelta

import pytest

from app.models.base import utcnow
from app.services import auto_reply as ar
from app.services.agent import controls
from app.services.google.provider import GReview
from tests.conftest import owner_exec, owner_query
from tests.test_google_and_reviews import connected  # noqa: F401
from tests.test_location_permissions import invite
from tests.test_phase15_governed import events, fake, gid  # noqa: F401  (GovGoogle: a reply is stored and read back)


def fresh(i, rating=5, text="Lovely clinic, very friendly staff.", name="priya sharma", age_minutes=30):
    when = (utcnow() - timedelta(minutes=age_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return GReview(external_id=f"auto-{i}-{uuid.uuid4().hex[:6]}", rating=rating, text=text, reviewer_name=name, created_at=when, updated_at=when, reply_text=None)


@pytest.fixture()
def on(connected, fake, gid):  # noqa: F811
    """A connected business with the defaults: autonomy and automatic replies ON, switched on before any review below arrived."""
    assert connected.get("/agent/auto-reply").status_code == 200  # creates the settings row (it is created lazily)
    owner_exec("UPDATE agent_settings SET auto_reply_since = now() - interval '1 hour', autonomy_enabled = true, auto_reply_enabled = true, autonomy_suspended_at = NULL WHERE tenant_id = :t", t=connected.tenant_id)
    owner_exec("DELETE FROM platform_controls")
    # the test database is shared by the whole session and the job covers every business: leave other tests' businesses out of this one's counts
    owner_exec("UPDATE agent_settings SET auto_reply_enabled = false WHERE tenant_id <> :t", t=connected.tenant_id)
    return connected


def run_job():
    from app.workers.tasks import auto_replies
    return auto_replies.run()


def sync(biz, fake, *reviews):
    fake.reviews = list(reviews)
    assert biz.post("/google/sync").status_code in (200, 202)


def my_drafts(biz):
    return owner_query("SELECT d.body, d.status::text, d.auto_published, d.approved_by, d.id, r.rating FROM reply_drafts d JOIN reviews r ON r.id = d.review_id WHERE d.tenant_id = :t ORDER BY d.created_at", t=uuid.UUID(biz.tenant_id))


# ----------------------------------------------------------------------------------------------------------------------------- the rule itself (pure)
def test_names_are_cleaned_before_they_reach_a_public_reply():
    assert ar.clean_first_name("priya sharma") == "Priya"
    assert ar.clean_first_name("  RAVI ") == "Ravi"
    assert ar.clean_first_name("राहुल कुमार") == "राहुल"
    for bad in (None, "", "A Google user", "x", "john123", "<script>", "a@b.com", "Anonymous", "😀😀", "A" * 40):
        assert ar.clean_first_name(bad) is None, bad


def test_the_rendered_reply_has_a_greeting_the_business_name_and_nothing_else():
    body = ar.render(ar.DEFAULT_TEMPLATES["en"][0], "priya sharma", "Gomti Physio", "en")
    assert body.startswith("Dear Priya,") and "Gomti Physio" in body and "{" not in body
    assert ar.render(ar.DEFAULT_TEMPLATES["en"][0], "A Google user", "Gomti Physio", "en").startswith("Hello,")
    assert ar.render(ar.DEFAULT_TEMPLATES["hi"][0], "राहुल", "क्लिनिक", "hi").startswith("प्रिय राहुल,")
    for lang, items in ar.DEFAULT_TEMPLATES.items():  # the built-in templates pass the same rules owners' templates must pass
        for t in items:
            assert ar.validate_template(t) == [], (lang, t)


@pytest.mark.parametrize("bad", [
    "Thank you {greeting}! Visit https://example.com for 20% off your next visit at {business}.",
    "Thank you {greeting}, call us on 9876543210 any time about {business}.",
    "Thank you {greeting}, we guarantee a full cure for everyone at {business}.",
    "Thank you {greeting} for visiting {business}, here is a free session and a discount coupon.",
    "Thank you {greeting}. Your appointment is confirmed at {business} for tomorrow morning.",
    "Hello {name}, thanks a lot for the review of {business} and your time.",
    "Too short",
    "x" * 700,
])
def test_a_template_that_promises_links_numbers_offers_or_unknown_fields_is_refused(bad):
    assert ar.validate_template(bad), bad


@pytest.mark.parametrize("rating,text,ok", [
    (5, "Lovely clinic, very friendly staff.", True), (5, "", True), (5, None, True), (4, "Good experience, clean place.", True),
    (4, "Good doctor but the wait was long.", False), (4, "Nice, however it was expensive.", False), (3, "Okay visit.", False), (2, "Not good.", False), (1, "Terrible", False),
    (5, "FANTASTIC!!!! AMAZING!!!!", False), (5, "I will take this to the consumer court and my lawyer", False), (5, "Dr Sharma treated my knee pain wonderfully, the nurse called me on 9876543210", False),
])
def test_only_clearly_positive_reviews_qualify_for_an_automatic_reply(rating, text, ok):
    assert ar.text_is_clearly_positive(rating, text, 4)[0] is ok, (rating, text)


def test_five_star_only_when_the_owner_chooses_it():
    assert ar.text_is_clearly_positive(4, "Good place.", 5)[0] is False and ar.text_is_clearly_positive(5, "Good place.", 5)[0] is True


def test_the_same_review_always_gets_the_same_template_and_wording_is_not_repeated_back_to_back():
    t = ar.DEFAULT_TEMPLATES["en"]
    a, i = ar.choose(t, "rev-1", [], "Asha", "Clinic", "en")
    assert ar.choose(t, "rev-1", [], "Asha", "Clinic", "en") == (a, i)
    b, j = ar.choose(t, "rev-1", [i], "Asha", "Clinic", "en")
    assert b != a and j != i
    used = []
    for n in range(len(t)):  # with every template but one recently used, the unused one is chosen
        _, k = ar.choose(t, f"rev-{n}", used[-(len(t) - 1):][::-1], "Asha", "Clinic", "en")
        assert k not in used[-(len(t) - 1):]
        used.append(k)


def test_hindi_reviews_get_a_hindi_reply():
    assert ar.language_for("बहुत अच्छा क्लिनिक है, धन्यवाद") == "hi" and ar.language_for("great clinic") == "en"


# ----------------------------------------------------------------------------------------------------------------------------- defaults and the off switch
def test_automatic_replies_and_autonomy_are_on_by_default_for_a_new_business_and_can_be_switched_off(connected):
    s = connected.get("/agent/auto-reply").json()
    assert s["enabled"] is True and s["running"] is True and s["min_rating"] == 4 and s["using_built_in"] is True
    assert connected.get("/agent/autonomy-settings").json()["enabled"] is True
    off = connected.put("/agent/auto-reply", json={"enabled": False}).json()
    assert off["enabled"] is False and off["running"] is False and "switched off" in off["not_running_because"]


def test_switching_it_back_on_does_not_answer_reviews_that_arrived_while_it_was_off(on, fake):
    assert on.put("/agent/auto-reply", json={"enabled": False}).status_code == 200
    sync(on, fake, fresh(1))
    assert on.put("/agent/auto-reply", json={"enabled": True}).status_code == 200
    assert run_job()["sent"] == 0 and fake.replies == []


# ----------------------------------------------------------------------------------------------------------------------------- sending
def test_a_new_positive_review_is_answered_from_the_template_through_the_governed_publisher(on, fake):
    sync(on, fake, fresh(1))
    assert run_job()["sent"] == 1
    assert len(fake.replies) == 1
    body = fake.replies[0][1]
    assert body.startswith("Dear Priya,") and "Dear Priya" in body and "{" not in body
    (d,) = my_drafts(on)
    assert d[1] == "published" and d[2] is True and d[3] is None  # approved by the rule, not by a person
    (st, attempts, atype, subj, authz, level, matched, err, aid), = owner_query(
        "SELECT status, attempts, action_type, subject_type, \"authorization\", policy_level, verification->>'matched', last_error, id FROM agent_actions WHERE subject_id = :s", s=d[4])
    assert (st, atype, subj, authz, level, matched, err) == ("executed", "reply_publish", "reply", "policy", 2, "true", None)
    assert events(aid) == ["proposed", "policy_classified", "auto_authorized", "executing", "google_write", "read_back", "verified"]
    ap = owner_query("SELECT decision, basis, authorized_by FROM agent_action_approvals WHERE action_id = :a", a=aid)
    assert ap == [("auto_authorized", "template_reply_rule", None)]
    assert owner_query("SELECT count(*) FROM audit_logs WHERE action = 'reply.auto_template' AND tenant_id = :t", t=uuid.UUID(on.tenant_id))[0][0] == 1


def test_running_the_job_again_never_sends_a_second_reply(on, fake):
    sync(on, fake, fresh(1))
    run_job(); run_job(); run_job()
    assert len(fake.replies) == 1 and len(my_drafts(on)) == 1


def test_mixed_and_low_reviews_are_left_for_a_person_and_nothing_is_drafted(on, fake):
    sync(on, fake, fresh(1, 3, "It was okay."), fresh(2, 1, "Terrible service."), fresh(3, 4, "Good but we waited an hour."), fresh(4, 5, "Great. My lawyer will contact you about the bill."))
    assert run_job()["sent"] == 0 and fake.replies == [] and my_drafts(on) == []


def test_reviews_older_than_the_window_or_than_the_switch_are_never_answered(on, fake):
    sync(on, fake, fresh(1, age_minutes=60 * 24 * 5))  # five days old when first seen
    assert run_job()["sent"] == 0
    owner_exec("UPDATE agent_settings SET auto_reply_since = now() + interval '1 hour' WHERE tenant_id = :t", t=on.tenant_id)
    sync(on, fake, fresh(2))
    assert run_job()["sent"] == 0 and fake.replies == []


def test_a_person_s_draft_or_an_existing_google_reply_is_never_overridden(on, fake):
    r = fresh(1)
    sync(on, fake, r)
    rid = on.get("/reviews").json()["items"][0]["id"]
    owner_exec("INSERT INTO reply_drafts (id, tenant_id, review_id, body, status, language, generated_by_ai, requires_human_handling, flag_reasons, attempts, auto_published, created_at, updated_at) "
               "VALUES (gen_random_uuid(), :t, :r, 'my own words', 'draft', 'en', false, false, '[]'::jsonb, 0, false, now(), now())", t=uuid.UUID(on.tenant_id), r=uuid.UUID(rid))
    assert run_job()["sent"] == 0 and fake.replies == []
    r2 = fresh(2); r2.reply_text = "Thanks, from the owner"
    sync(on, fake, r2)
    assert run_job()["sent"] == 0 and fake.replies == []


def test_wording_rotates_across_replies(on, fake):
    sync(on, fake, *[fresh(i, name=f"asha{chr(97 + i)}") for i in range(4)])
    assert run_job()["sent"] == 4
    used = [r[0] for r in owner_query("SELECT template_index FROM reply_drafts WHERE tenant_id = :t AND auto_published ORDER BY created_at", t=uuid.UUID(on.tenant_id))]
    assert len(used) == 4 and len(set(used)) == 4, used  # five templates, four replies: none repeats


def test_a_hindi_review_gets_a_hindi_reply(on, fake):
    sync(on, fake, fresh(1, text="बहुत अच्छा अनुभव रहा, धन्यवाद", name="राहुल कुमार"))
    run_job()
    assert fake.replies and fake.replies[0][1].startswith("प्रिय राहुल")


def test_the_owner_s_own_templates_replace_the_built_in_set_and_an_empty_list_restores_it(on, fake):
    own = "{greeting}, we are grateful for your review of {business}. It really helps our small team, and we will be glad to see you again."
    r = on.put("/agent/auto-reply", json={"templates": [own]})
    assert r.status_code == 200 and r.json()["using_built_in"] is False
    sync(on, fake, fresh(1))
    run_job()
    assert "grateful for your review" in fake.replies[0][1]
    assert on.put("/agent/auto-reply", json={"templates": []}).json()["using_built_in"] is True


def test_templates_that_break_the_rules_are_refused_with_the_reason(on):
    r = on.put("/agent/auto-reply", json={"templates": ["Thank you {greeting}, claim a free session at https://x.example now for {business}."]})
    assert r.status_code == 422 and "Template 1" in r.json()["detail"]
    assert on.get("/agent/auto-reply").json()["using_built_in"] is True


def test_only_an_owner_or_admin_can_change_the_settings(on):
    staff = invite(on)
    assert staff.put("/agent/auto-reply", json={"enabled": False}).status_code == 403
    assert staff.get("/agent/auto-reply").status_code == 200  # staff can see what is running


# ----------------------------------------------------------------------------------------------------------------------------- the stops and the caps
def test_the_platform_emergency_stop_holds_automatic_replies(on, fake):
    sync(on, fake, fresh(1))
    from app.core.db import system_session
    db = system_session(); controls.set_emergency_stop(db, on=True, user_id=None, reason="test"); db.commit(); db.close()
    try:
        assert run_job().get("stopped") is True and fake.replies == []
    finally:
        owner_exec("DELETE FROM platform_controls")
    assert run_job()["sent"] == 1  # lifted: the held review is answered, nothing was lost


def test_the_business_own_stop_or_a_suspension_of_autonomy_holds_them(on, fake):
    sync(on, fake, fresh(1))
    owner_exec("UPDATE agent_settings SET autonomy_suspended_at = now() WHERE tenant_id = :t", t=on.tenant_id)
    assert run_job()["sent"] == 0
    owner_exec("UPDATE agent_settings SET autonomy_suspended_at = NULL, autonomy_enabled = false WHERE tenant_id = :t", t=on.tenant_id)
    assert run_job()["sent"] == 0 and fake.replies == []


def test_a_suspended_business_gets_no_automatic_replies(on, fake):
    sync(on, fake, fresh(1))
    owner_exec("UPDATE tenants SET suspended_at = now() WHERE id = :t", t=on.tenant_id)
    try:
        assert run_job()["sent"] == 0 and fake.replies == []
    finally:
        owner_exec("UPDATE tenants SET suspended_at = NULL WHERE id = :t", t=on.tenant_id)


def test_the_plan_s_monthly_reply_allowance_caps_automatic_replies(on, fake):
    owner_exec("UPDATE subscriptions SET review_replies = 2 WHERE tenant_id = :t", t=on.tenant_id)
    sync(on, fake, *[fresh(i, name=f"neha{chr(97 + i)}") for i in range(4)])
    assert run_job()["sent"] == 2 and len(fake.replies) == 2
    s = on.get("/agent/auto-reply").json()
    assert s["allowance"]["cap"] == 2 and s["allowance"]["used"] == 2 and s["allowance"]["remaining"] == 0
    assert run_job()["sent"] == 0 and len(fake.replies) == 2


def test_the_daily_limit_caps_automatic_replies(on, fake):
    assert on.put("/agent/auto-reply", json={"daily_limit": 1}).status_code == 200
    sync(on, fake, fresh(1, name="asha"), fresh(2, name="ravi"))
    assert run_job()["sent"] == 1 and len(fake.replies) == 1


def test_a_transient_google_failure_is_retried_by_the_job_without_a_person_and_without_a_second_reply(on, fake):
    from app.services.google import GoogleAPIError
    sync(on, fake, fresh(1))
    fake.reply_error = GoogleAPIError(503, "Google is busy")
    run_job()
    assert my_drafts(on)[0][1] == "failed" and fake.replies == []
    fake.reply_error = None
    from app.workers.tasks import retry_failed_replies
    assert retry_failed_replies.run()["retried"] == 1
    assert len(fake.replies) == 1 and my_drafts(on)[0][1] == "published"
    retry_failed_replies.run()
    assert len(fake.replies) == 1


def test_a_retry_is_not_made_after_the_owner_switches_the_rule_off(on, fake):
    from app.services.google import GoogleAPIError
    sync(on, fake, fresh(1))
    fake.reply_error = GoogleAPIError(503, "Google is busy")
    run_job()
    fake.reply_error = None
    on.put("/agent/auto-reply", json={"enabled": False})
    from app.workers.tasks import retry_failed_replies
    retry_failed_replies.run()
    assert fake.replies == []


def test_nothing_else_can_use_the_rule_to_skip_a_person(on):
    from app.models import ReplyDraft
    from app.services.agent import content_exec
    from app.core.db import system_session
    db = system_session()
    try:
        d = db.scalars(__import__("sqlalchemy").select(ReplyDraft).limit(1)).first()
        sub = content_exec.Subject(kind="post", action_type="publish_content", tenant_id=uuid.UUID(on.tenant_id), google_location_id=uuid.uuid4(), subject_id=None, feature="gbp_posts",
                                   content={}, approved_by=None, approved_at=None, label="post", send=lambda: ("done", {}), verify=lambda *a: {"matched": True}, policy_rule="template_reply_v1")
        assert content_exec.govern(db, sub)["reason"] == "bad_rule"  # the rule only exists for replies
        sub2 = content_exec.Subject(kind="reply", action_type="reply_publish", tenant_id=uuid.UUID(on.tenant_id), google_location_id=uuid.uuid4(), subject_id=None, feature="ai_replies",
                                    content={}, approved_by=None, approved_at=None, label="r", send=lambda: ("done", {}), verify=lambda *a: {"matched": True}, policy_rule="anything_else")
        assert content_exec.govern(db, sub2)["reason"] == "bad_rule"
        sub3 = content_exec.Subject(kind="reply", action_type="reply_publish", tenant_id=uuid.UUID(on.tenant_id), google_location_id=uuid.uuid4(), subject_id=None, feature="ai_replies",
                                    content={}, approved_by=None, approved_at=None, label="r", send=lambda: ("done", {}), verify=lambda *a: {"matched": True})
        assert content_exec.govern(db, sub3)["reason"] == "no_person_approval"  # no rule and no person: still refused
    finally:
        db.close()
