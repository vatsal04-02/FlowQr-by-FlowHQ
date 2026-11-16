"""Business intelligence layer, post ideas endpoint and the AI Output Acceptance Rate, against real PostgreSQL (row-level security included).
Google is a test double and the AI a scripted stub."""
import json

import pytest

from app.services.ai import outcomes
from tests.conftest import owner_query
from tests.test_agent import add_review, ai, set_ai, tasks  # noqa: F401
from tests.test_gbp import fake, gid  # noqa: F401
from tests.test_google_and_reviews import connected  # noqa: F401
from tests.test_location_permissions import invite

REPLY_A = ("Waiting that long without a word from us is not what we want for anyone, and we are sorry it happened. Please call the clinic so we can understand what went wrong that day "
           "and make it right.")
REPLY_A_EDITED = REPLY_A.replace("Please call the clinic", "Please do call the clinic")
REPLY_REWRITE = "Sorry about the delay. Phone us on the clinic number and ask for the manager; we will look into the timing together and fix our process."
POST_TEXT = ("Do you really need a doctor's referral to see a physiotherapist? For a first assessment, no. Call the clinic, tell us where it hurts, and we will find a time that fits "
             "your work day.")


def review_id(biz, gid_, **kw):
    return add_review(biz, gid_, kw.pop("rating", 2), kw.pop("text", "Waited too long and nobody told me why, appointment was rushed"), **kw)


# ------------------------------------------------------------------ intelligence layer
def test_intelligence_reads_this_business_only_and_asks_for_what_is_missing(connected, fake, gid, biz_b):  # noqa: F811
    for _ in range(3):
        add_review(connected, gid, 5, "Very clean clinic and the staff are polite and helpful", days_ago=5)
    add_review(connected, gid, 2, "Waited an hour, nobody told me why", days_ago=2)
    r = connected.get("/agent/intelligence", params={"google_location_id": gid})
    assert r.status_code == 200
    d = r.json()
    assert d["reviews"]["n"] == 4 and dict(d["reviews"]["praise"])["cleanliness"] == 3 and dict(d["reviews"]["concerns"])["waiting time"] == 1 and d["reviews"]["unanswered"] == 4
    assert {q["key"] for q in d["missing"]} >= {"brand_voice", "audience", "faqs"}
    assert "from 4 real reviews" in d["rendered"].lower() or "4 real reviews" in d["rendered"]
    assert "Waited an hour" not in json.dumps(d)  # themes only: review text is never echoed into the observation block
    other = biz_b.get("/agent/intelligence").json()
    assert other["reviews"]["n"] == 0 and other["reviews"]["praise"] == [] and "recent_replies" not in other


def test_audience_is_saved_without_disturbing_the_rest_and_reaches_the_prompt(connected, fake, gid):  # noqa: F811
    connected.put("/agent/knowledge", json={"description": "Physiotherapy for back pain.", "services": ["Back care"], "offers": [], "faqs": [], "prohibited_claims": [],
                                            "audience": "office workers within 3 km"})
    k = connected.get("/agent/knowledge").json()
    assert k["audience"] == "office workers within 3 km" and "office workers within 3 km" in k["grounding_preview"]
    connected.put("/agent/knowledge", json={"description": "Physiotherapy for back pain.", "services": ["Back care"], "offers": [], "faqs": [], "prohibited_claims": []})  # audience omitted
    assert connected.get("/agent/knowledge").json()["audience"] == "office workers within 3 km"
    connected.put("/agent/knowledge", json={"description": "Physiotherapy for back pain.", "services": ["Back care"], "offers": [], "faqs": [], "prohibited_claims": [], "audience": ""})
    assert connected.get("/agent/knowledge").json()["audience"] == ""
    assert "audience" in {q["key"] for q in connected.get("/agent/intelligence").json()["missing"]}  # cleared, so it is asked for again


def test_intelligence_knows_recent_posts_so_new_ones_can_differ(connected, fake, gid):  # noqa: F811
    p = connected.post("/posts", json={"google_location_id": gid, "summary": POST_TEXT}).json()
    d = connected.get("/agent/intelligence", params={"google_location_id": gid}).json()
    assert POST_TEXT in d["recent_posts"] and d["recent_post_types"]
    assert p["status"] == "draft"


# ------------------------------------------------------------------ post ideas endpoint
IDEAS = [
    {"type": "educational", "title": "Referral myth", "text": POST_TEXT, "image": "The reception desk with the appointment book", "why": "Removes a common reason people delay calling"},
    {"type": "service", "title": "First visit", "text": "A first physiotherapy visit lasts about 45 minutes. We listen first, then examine, then explain what we found before agreeing a plan with you. "
                                                       "Ask the clinic for the next free time.", "image": "A treatment room as it really looks", "why": "Shows what to expect"},
]


def test_post_ideas_endpoint_returns_distinct_ideas_and_saves_nothing(connected, fake, gid, ai):  # noqa: F811
    set_ai(ai, json.dumps(IDEAS))
    before = len(connected.get("/posts").json()["posts"]) if isinstance(connected.get("/posts").json(), dict) else len(connected.get("/posts").json())
    r = connected.post("/posts/ideas", json={"google_location_id": gid, "count": 2})
    assert r.status_code == 200, r.text
    ideas = r.json()["ideas"]
    assert [i["title"] for i in ideas] == ["Referral myth", "First visit"] and all(i["image"] and i["why"] for i in ideas)
    after = len(connected.get("/posts").json()["posts"]) if isinstance(connected.get("/posts").json(), dict) else len(connected.get("/posts").json())
    assert before == after and fake.posts == []
    assert connected.post("/posts/ideas", json={"google_location_id": gid, "count": 9}).status_code == 422


def test_post_ideas_when_everything_is_refused_is_an_honest_error(connected, fake, gid, ai):  # noqa: F811
    set_ai(ai, json.dumps([{"type": "offer", "title": "x", "text": "We guarantee a 100% cure in 5 days for everyone who visits, call now!", "image": "x", "why": "x"}]))
    assert connected.post("/posts/ideas", json={"google_location_id": gid}).status_code == 502


def test_post_ideas_are_for_signed_in_owners_of_that_location_only(connected, fake, gid, ai, biz_b):  # noqa: F811
    set_ai(ai, json.dumps(IDEAS))
    assert biz_b.post("/posts/ideas", json={"google_location_id": gid}).status_code in (403, 404)


# ------------------------------------------------------------------ acceptance rate
def kinds(biz):
    return biz.get("/agent/ai-quality").json()["kinds"]


def test_reply_acceptance_counts_an_untouched_approval_as_accepted_and_a_rewrite_as_not(connected, fake, gid, ai):  # noqa: F811
    set_ai(ai, REPLY_A)
    r1, r2, r3 = review_id(connected, gid), review_id(connected, gid), review_id(connected, gid)
    d1 = connected.post(f"/reviews/{r1}/drafts/generate", json={}).json()
    d2 = connected.post(f"/reviews/{r2}/drafts/generate", json={}).json()
    d3 = connected.post(f"/reviews/{r3}/drafts/generate", json={}).json()
    assert kinds(connected)["reply"]["generated"] == 3 and kinds(connected)["reply"]["acceptance_rate"] is None  # nothing decided yet: no rate, not 0%
    assert connected.post(f"/reply-drafts/{d1['id']}/approve", json={"acknowledge_flags": True}).status_code == 200  # approved as written
    connected.patch(f"/reply-drafts/{d2['id']}", json={"body": REPLY_REWRITE})
    assert connected.post(f"/reply-drafts/{d2['id']}/approve", json={"acknowledge_flags": True}).status_code == 200  # rewritten, then approved
    assert connected.delete(f"/reply-drafts/{d3['id']}").status_code == 204  # thrown away
    k = kinds(connected)["reply"]
    assert (k["generated"], k["decided"], k["approved"], k["accepted"], k["rejected"]) == (3, 3, 2, 1, 1)
    assert k["acceptance_rate"] == round(1 / 3, 3) and k["median_edit_ratio"] is not None and k["top_reject_reasons"][0][0] == "owner_rejected"


def test_a_light_edit_is_still_an_acceptance_and_the_edit_ratio_is_recorded(connected, fake, gid, ai):  # noqa: F811
    set_ai(ai, REPLY_A)
    d = connected.post(f"/reviews/{review_id(connected, gid)}/drafts/generate", json={}).json()
    connected.patch(f"/reply-drafts/{d['id']}", json={"body": REPLY_A_EDITED})
    connected.post(f"/reply-drafts/{d['id']}/approve", json={"acknowledge_flags": True})
    k = kinds(connected)["reply"]
    assert k["accepted"] == 1 and 0 < k["median_edit_ratio"] <= outcomes.ACCEPT_EDIT_RATIO


def test_regenerating_marks_the_earlier_draft_as_replaced(connected, fake, gid, ai):  # noqa: F811
    set_ai(ai, REPLY_A)
    rid = review_id(connected, gid)
    connected.post(f"/reviews/{rid}/drafts/generate", json={})
    connected.post(f"/reviews/{rid}/drafts/generate", json={})
    k = kinds(connected)["reply"]
    assert k["generated"] == 2 and k["regenerated"] == 1 and k["decided"] == 1  # the first was superseded; the second is still open


def test_post_and_description_acceptance(connected, fake, gid, ai):  # noqa: F811
    set_ai(ai, POST_TEXT)
    p = connected.post("/posts/ai-draft", json={"google_location_id": gid}).json()
    assert connected.post(f"/posts/{p['id']}/approve", json={}).status_code == 200
    q = connected.post("/posts/ai-draft", json={"google_location_id": gid}).json()
    assert connected.post(f"/posts/{q['id']}/cancel").status_code == 200
    k = kinds(connected)["post"]
    assert (k["generated"], k["approved"], k["accepted"], k["rejected"]) == (2, 1, 1, 1) and k["avg_quality"] is not None

    connected.put("/agent/knowledge", json={"description": "Physiotherapy for back and neck pain.", "services": ["Back care"], "offers": [], "faqs": [], "prohibited_claims": []})
    connected.post("/agent/google/refresh")
    connected.post("/agent/plan/run")
    t = next(x for x in tasks(connected) if x["kind"] == "profile_fix" and x["evidence"]["field"] == "description")
    text = "Gomti Physio is a physiotherapy clinic in Lucknow offering back care and neck pain physiotherapy. Call the clinic to book a visit or to ask a question."
    set_ai(ai, text)
    connected.post(f"/agent/tasks/{t['id']}/draft")
    connected.patch(f"/agent/tasks/{t['id']}/draft", json={"description": text + " We are open six days a week, so ask the clinic about the first available time."})
    assert connected.post(f"/agent/tasks/{t['id']}/approve").json()["status"] == "published"
    d = kinds(connected)["description"]
    assert d["generated"] == 1 and d["approved"] == 1 and d["median_edit_ratio"] is not None


def test_acceptance_is_per_business_and_the_platform_view_has_counts_only(connected, fake, gid, ai, biz_b, admin):  # noqa: F811
    set_ai(ai, REPLY_A)
    d = connected.post(f"/reviews/{review_id(connected, gid)}/drafts/generate", json={}).json()
    connected.post(f"/reply-drafts/{d['id']}/approve", json={"acknowledge_flags": True})
    assert kinds(biz_b)["reply"]["generated"] == 0
    assert invite(connected).get("/agent/ai-quality").status_code == 200  # staff can read it
    assert biz_b.get("/admin/ai-quality").status_code == 403
    r = admin.get("/admin/ai-quality")
    assert r.status_code == 200 and r.json()["kinds"]["reply"]["generated"] >= 1
    assert REPLY_A not in r.text and "original_text" not in r.text  # platform admins get numbers, never the businesses' text
    assert owner_query("select count(*) from ai_outputs where tenant_id = :t", t=biz_b.tenant_id)[0][0] == 0


def test_recording_never_breaks_the_owners_action(connected, fake, gid, ai, monkeypatch):  # noqa: F811
    set_ai(ai, REPLY_A)
    d = connected.post(f"/reviews/{review_id(connected, gid)}/drafts/generate", json={}).json()

    def boom(*a, **k):
        raise RuntimeError("db hiccup")
    monkeypatch.setattr(outcomes.AIOutput, "__init__", boom)  # make the insert path explode
    d2 = connected.post(f"/reviews/{review_id(connected, gid)}/drafts/generate", json={})
    assert d2.status_code == 201  # the draft is still created
    assert connected.post(f"/reply-drafts/{d['id']}/approve", json={"acknowledge_flags": True}).status_code == 200


def test_edit_ratio_is_word_level():
    assert outcomes.edit_ratio("a b c d", "a b c d") == 0.0
    assert outcomes.edit_ratio("a b c d", "a b c x") == 0.25
    assert outcomes.edit_ratio("a b c d", "w x y z") == 1.0
    assert outcomes.edit_ratio("", "") == 0.0


# ------------------------------------------------------------------ agent opportunities from real data
def _series(prev_value, cur_value):
    from datetime import date, timedelta
    end = date.today() - timedelta(days=3)
    days = [(end - timedelta(days=i)) for i in range(0, 56)]
    return {"CALL_CLICKS": [{"date": d.isoformat(), "value": cur_value if i < 28 else prev_value} for i, d in enumerate(days)]}


def test_agent_notices_posts_that_say_the_same_thing_and_asks_for_a_different_angle(connected, fake, gid):  # noqa: F811
    same = "Back pain from long hours at a desk is common. Our physiotherapists can assess your posture and show you simple exercises. Call the clinic to book a visit."
    fake.posts = [{"name": f"p{i}", "summary": same.replace("common", "common today" if i else "common"), "state": "LIVE", "cta_type": None} for i in range(4)]
    connected.post("/agent/google/refresh")
    connected.post("/agent/plan/run")
    t = next(x for x in tasks(connected) if "too alike" in x["title"])
    assert t["kind"] == "create_post" and t["evidence"]["avg_overlap_pct"] >= 25 and "different" in t["suggested_action"].lower()
    fake.posts = [{"name": "a", "summary": "Do you need a referral to see a physiotherapist? No, a first assessment needs none.", "state": "LIVE", "cta_type": None},
                  {"name": "b", "summary": "Winter stiffness in the knees is common; here is a simple warm-up before you walk in the morning.", "state": "LIVE", "cta_type": None},
                  {"name": "c", "summary": "Our clinic is open Monday to Saturday, and the first visit lasts about forty-five minutes.", "state": "LIVE", "cta_type": None}]


def test_agent_reports_a_drop_in_customer_actions_as_a_comparison_never_a_cause(connected, fake, gid, monkeypatch):  # noqa: F811
    monkeypatch.setattr(fake, "fetch_performance", lambda at, loc, s, e, m: _series(3, 1))
    connected.post("/agent/google/refresh")
    connected.post("/agent/plan/run")
    t = next(x for x in tasks(connected) if "fell by" in x["title"])
    assert t["evidence"]["change_pct"] <= -20 and t["evidence"]["current"] < t["evidence"]["previous"]
    assert "not a diagnosis" in t["why"] and "will not claim" in t["suggested_action"]


def test_no_alert_when_performance_is_steady_or_too_small_to_judge(connected, fake, gid, monkeypatch):  # noqa: F811
    monkeypatch.setattr(fake, "fetch_performance", lambda at, loc, s, e, m: _series(3, 3))
    connected.post("/agent/google/refresh")
    connected.post("/agent/plan/run")
    assert not [x for x in tasks(connected) if "fell by" in x["title"]]


# ------------------------------------------------------------------ optimizer: the six parts of every recommendation
def test_every_optimizer_check_explains_current_problem_fix_reason_evidence_and_preview(connected, fake, gid, ai):  # noqa: F811
    connected.put("/agent/knowledge", json={"description": "Physiotherapy for back pain.", "services": ["Back care", "Sports rehab"], "offers": [], "faqs": [], "prohibited_claims": []})
    connected.post("/agent/google/refresh")
    r = connected.get(f"/agent/profile/{gid}/optimize").json()
    assert r["checks"]
    for c in r["checks"]:
        assert {"current", "problem", "recommendation", "reason", "evidence", "preview"} <= set(c), c["key"]
        assert c["reason"] and c["evidence"]["read_from_google_at"]
        if c["state"] != "ok":
            assert c["problem"] and c["recommendation"] is not None or c["key"] in ("services", "name", "special_hours")
    desc = next(c for c in r["checks"] if c["key"] == "description")
    assert desc["current"] == "Old" and desc["preview"] is None  # the fake profile says "Old"; no draft yet
    assert "ranking" not in " ".join(c["reason"] for c in r["checks"]).lower().replace("never", "")  # no ranking promises in any reason
    t = next(x for x in connected.post("/agent/plan/run").json() and tasks(connected) if x["kind"] == "profile_fix" and x["evidence"].get("field") == "description")
    text = "Gomti Physio is a physiotherapy clinic in Lucknow offering back care and sports rehab. Call the clinic to book a visit or to ask a question about a first assessment."
    set_ai(ai, text)
    connected.post(f"/agent/tasks/{t['id']}/draft")
    after = next(c for c in connected.get(f"/agent/profile/{gid}/optimize").json()["checks"] if c["key"] == "description")
    assert after["preview"] == {"kind": "description", "text": text}  # the proposed change is shown next to the current text
